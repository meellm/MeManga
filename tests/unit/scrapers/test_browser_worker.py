"""BrowserWorker: the single thread that owns a scraper's browser.

A timed-out browser call used to raise an empty ``TimeoutError`` while
its task kept running, and every later call queued behind it, timing
out in turn and then running long after its caller had given up.
These tests drive the worker with events and sub-second budgets; no
browser is started. Every blocked task is released and every worker
shut down when a test ends.
"""

from __future__ import annotations

import threading
import time

import pytest

from memanga.scrapers.playwright_base import (
    STEP_RESERVE_S,
    BrowserTimeoutError,
    BrowserWorker,
    PlaywrightScraper,
    _operation_name,
    browser_recycle_due,
    step_timeout_ms,
    task_seconds_left,
)

SHORT = 0.2   # a budget the blocked tasks below always overrun
LONG = 10.0   # a budget no test is meant to reach


class _Gates:
    """Events that blocked tasks wait on; ``release_all`` frees them."""

    def __init__(self):
        self._made = []

    def __call__(self):
        event = threading.Event()
        self._made.append(event)
        return event

    def release_all(self):
        for event in self._made:
            event.set()


@pytest.fixture
def gates():
    g = _Gates()
    yield g
    g.release_all()


@pytest.fixture
def worker(gates):
    w = BrowserWorker(thread_name_prefix="test-worker")
    yield w
    # Free any blocked task first so the worker thread can be joined.
    gates.release_all()
    w.shutdown(wait=True)


def _blocking(gate, ran=None):
    """A task named like the real ones that waits for ``gate``."""
    def _get_chapters_in_thread():
        if ran is not None:
            ran.append("stale")
        assert gate.wait(LONG), "test never released the task"
        return "stale done"
    return _get_chapters_in_thread


def _abandon_one(worker, gate, ran=None):
    """Time one call out so the worker holds an abandoned task."""
    with pytest.raises(BrowserTimeoutError) as exc:
        worker.call("weebcentral", SHORT, _blocking(gate, ran))
    return exc.value


class TestResults:
    def test_returns_result_and_passes_args(self, worker):
        assert worker.call("src", LONG, lambda a, b=0: a + b, 2, b=3) == 5

    def test_task_exceptions_pass_through_unchanged(self, worker):
        error = RuntimeError("navigation failed")

        def boom():
            raise error

        with pytest.raises(RuntimeError) as exc:
            worker.call("src", LONG, boom)
        assert exc.value is error

    @pytest.mark.parametrize("error", [
        TimeoutError("socket read timed out"),
        BrowserTimeoutError(
            "weebcentral get_pages: 5.5s budget used up before the next "
            "browser step"),
    ], ids=["builtin", "browser"])
    def test_task_raised_timeout_is_not_mistaken_for_expiry(
            self, worker, error):
        """A TimeoutError raised *by the task* is its result, not a sign
        the caller's budget ran out: same object, text and cause, and the
        worker is not left thinking a task is still running."""
        cause = OSError("connection reset")

        def _get_pages_in_thread():
            raise error from cause

        with pytest.raises(TimeoutError) as exc:
            worker.call("weebcentral", LONG, _get_pages_in_thread)

        assert exc.value is error
        assert exc.value.__cause__ is cause
        assert "still running" not in str(exc.value)
        # An immediate sub-second call is not refused as "waiting for an
        # earlier get_pages".
        assert worker.call("weebcentral", SHORT, lambda: "ok") == "ok"


class TestTimeout:
    def test_message_names_source_operation_and_budget(self, worker, gates):
        began = time.monotonic()
        error = _abandon_one(worker, gates())

        # The caller is released at its budget, not when the task ends.
        assert time.monotonic() - began < SHORT + 1.0
        message = str(error)
        assert message.startswith(
            "weebcentral get_chapters timed out after 0.2s")
        assert "still running" in message
        assert isinstance(error, TimeoutError)
        assert not isinstance(error, ValueError)
        # Expiry is detected without an exception of its own, so there is
        # no empty TimeoutError to chain.
        assert error.__cause__ is None

    def test_next_call_waits_for_abandoned_task_then_runs(self, worker, gates):
        gate = gates()
        order = []
        _abandon_one(worker, gate, order)

        def follow_up():
            order.append("next")
            return "next done"

        result = {}
        caller = threading.Thread(
            target=lambda: result.update(
                value=worker.call("weebcentral", LONG, follow_up)))
        caller.start()
        gate.set()
        caller.join(LONG)

        assert not caller.is_alive()
        assert result == {"value": "next done"}
        assert order == ["stale", "next"]

    def test_busy_worker_fails_fast_without_queueing(self, worker, gates):
        """While the abandoned task runs, a later call must give up within
        its own budget and must never run afterwards."""
        gate = gates()
        _abandon_one(worker, gate)
        never = []

        def _search_in_thread():
            never.append(True)

        with pytest.raises(BrowserTimeoutError) as exc:
            worker.call("weebcentral", SHORT, _search_in_thread)

        assert str(exc.value).startswith(
            "weebcentral search timed out after 0.2s: the browser is still "
            "busy with an earlier get_chapters")
        gate.set()
        # Once the stale task drains the worker serves normally again,
        # and the refused call did not sneak in behind it.
        assert worker.call("weebcentral", LONG, lambda: "ok") == "ok"
        assert never == []

    def test_repeated_timeouts_keep_at_most_one_abandoned_task(
            self, worker, gates):
        first, second = gates(), gates()
        _abandon_one(worker, first)
        with pytest.raises(BrowserTimeoutError):
            worker.call("weebcentral", SHORT, _blocking(second))
        first.set()
        # The second blocked task was never submitted, so the worker is
        # free as soon as the first one returns.
        assert worker.call("weebcentral", LONG, lambda: "ok") == "ok"

    def test_lock_wait_for_live_callers_is_outside_the_budget(
            self, worker, gates):
        """A call queued behind another live call still gets its whole
        budget for its own task."""
        gate = gates()
        started = threading.Event()

        def holder():
            started.set()
            assert gate.wait(LONG)
            return "held"

        results = {}
        first = threading.Thread(
            target=lambda: results.update(
                first=worker.call("src", LONG, holder)))
        first.start()
        assert started.wait(LONG)
        second = threading.Thread(
            target=lambda: results.update(
                second=worker.call("src", SHORT, lambda: "quick")))
        second.start()
        # Hold the worker past the second call's budget.
        time.sleep(SHORT * 2)
        gate.set()
        first.join(LONG)
        second.join(LONG)

        assert results == {"first": "held", "second": "quick"}


class TestConcurrency:
    def test_calls_never_overlap_on_the_worker(self, worker, gates):
        gate = gates()
        active, peak = [0], [0]
        lock = threading.Lock()

        def task(hold):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            if hold:
                assert gate.wait(LONG)
            with lock:
                active[0] -= 1
            return threading.current_thread().name

        names = []
        threads = [
            threading.Thread(target=lambda h=h: names.append(
                worker.call("src", LONG, task, h)))
            for h in (True, False, False)
        ]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join(LONG)

        assert peak[0] == 1
        assert len(names) == 3 and len(set(names)) == 1

    def test_each_scraper_class_has_its_own_worker(self, gates):
        class _Stuck(PlaywrightScraper):
            name = "stuck-test"

        class _Free(PlaywrightScraper):
            name = "free-test"

        gate = gates()
        try:
            with pytest.raises(BrowserTimeoutError, match="^stuck-test "):
                _Stuck._run_serialized(_blocking(gate), timeout=SHORT)
            # A wedged source must not hold up another one.
            assert _Free._run_serialized(lambda: "free", timeout=LONG) == "free"
        finally:
            gate.set()
            _Stuck._worker.shutdown(wait=True)
            _Free._worker.shutdown(wait=True)


class TestTaskDeadline:
    def test_task_sees_its_callers_deadline(self, worker):
        left = worker.call("src", 30, task_seconds_left)
        assert 25 < left <= 30
        assert task_seconds_left() is None

    def test_step_timeout_is_cut_to_the_remaining_budget(self, worker):
        capped = worker.call("src", 30, step_timeout_ms, 60000)
        assert capped <= (30 - STEP_RESERVE_S) * 1000
        assert capped > 20000
        # Short steps keep their own limit.
        assert worker.call("src", 30, step_timeout_ms, 500) == 500

    def test_step_timeout_outside_a_task_is_unchanged(self):
        assert step_timeout_ms(60000) == 60000

    def test_used_up_budget_raises_instead_of_starting_a_step(self, worker):
        def _get_pages_in_thread():
            return step_timeout_ms(45000)

        with pytest.raises(BrowserTimeoutError) as exc:
            worker.call("weebcentral", STEP_RESERVE_S + 0.5,
                        _get_pages_in_thread)
        assert str(exc.value) == (
            f"weebcentral get_pages: {STEP_RESERVE_S + 0.5:g}s budget used "
            "up before the next browser step")


class TestCleanup:
    def test_busy_worker_is_skipped_then_cleaned_on_its_own_thread(
            self, gates, monkeypatch):
        """cleanup() must not close a browser under a task that is still
        running: it gives up on that worker after the cleanup budget,
        and cleans it on its own thread once the task has ended."""
        from memanga.scrapers import playwright_base as pb

        class _Family(PlaywrightScraper):
            name = "family-test"

        class _Busy(_Family):
            name = "busy-test"

        cleaned = []
        monkeypatch.setattr(
            pb, "cleanup_browsers",
            lambda: cleaned.append(threading.current_thread().name))
        monkeypatch.setattr(PlaywrightScraper, "_CLEANUP_TIMEOUT_S", SHORT)
        gate = gates()
        try:
            with pytest.raises(BrowserTimeoutError):
                _Busy._run_serialized(_blocking(gate), timeout=SHORT)

            began = time.monotonic()
            _Family.cleanup()
            assert time.monotonic() - began < SHORT + 1.0
            assert cleaned == []

            gate.set()
            # A normal budget: room to let the ended task drain first.
            monkeypatch.setattr(PlaywrightScraper, "_CLEANUP_TIMEOUT_S", LONG)
            _Family.cleanup()
            assert len(cleaned) == 1
            assert cleaned[0].startswith("pw-_Busy")
        finally:
            gate.set()
            _Family._worker.shutdown(wait=True)
            _Busy._worker.shutdown(wait=True)


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def new_context(self, **kwargs):
        return _FakeContext()

    def close(self):
        self.closed = True


class _FakeContext:
    def close(self):
        pass


class _FakePlaywright:
    """``sync_playwright().start()`` result whose Firefox never starts."""

    def __init__(self):
        self.launched = []
        self.firefox = self

    def launch(self, **kwargs):
        self.launched.append(_FakeBrowser())
        return self.launched[-1]

    def stop(self):
        pass


class TestBrowserRecycling:
    """#402: a browser that served many tasks is replaced at the start
    of the next one, so long runs don't need ``--safe`` to stay bounded."""

    @pytest.fixture
    def source(self, monkeypatch):
        import playwright.sync_api as pwapi
        from memanga.scrapers import playwright_base as pb
        from memanga.scrapers.weebcentral import WeebCentralScraper

        pw = _FakePlaywright()
        monkeypatch.setattr(pwapi, "sync_playwright", lambda: type(
            "_S", (), {"start": staticmethod(lambda: pw)})())

        class _Recycled(WeebCentralScraper):
            name = "recycle-test"
            browser_recycle_after = 2

        scraper = _Recycled()
        yield scraper, pw
        _Recycled._run_serialized(pb.cleanup_browsers, timeout=LONG)
        _Recycled._worker.shutdown(wait=True)

    @staticmethod
    def _task(scraper, uses=1):
        """One worker task that asks for the browser ``uses`` times."""
        def _get_pages_in_thread():
            for _ in range(uses):
                browser, _ = scraper._get_browser_in_thread()
            return browser
        return type(scraper)._run_serialized(_get_pages_in_thread,
                                             timeout=LONG)

    def test_browser_is_replaced_after_its_task_limit(self, source):
        scraper, pw = source
        used = [self._task(scraper) for _ in range(5)]
        assert len(pw.launched) == 3
        assert used == [pw.launched[0]] * 2 + [pw.launched[1]] * 2 \
            + [pw.launched[2]]
        assert pw.launched[0].closed and pw.launched[1].closed
        assert not pw.launched[2].closed

    def test_repeat_uses_within_one_task_count_once(self, source):
        """A recycle only happens between tasks, never under a page a
        running task still holds."""
        scraper, pw = source
        self._task(scraper, uses=5)
        self._task(scraper, uses=5)
        assert len(pw.launched) == 1
        self._task(scraper, uses=5)
        assert len(pw.launched) == 2

    def test_zero_limit_keeps_the_browser(self, source):
        scraper, pw = source
        scraper.browser_recycle_after = 0
        for _ in range(5):
            self._task(scraper)
        assert len(pw.launched) == 1

    def test_a_restart_inside_a_task_starts_a_new_count(self, source):
        """WeebCentral drops its browser after a hard failure; the fresh
        one must get its full limit, not inherit the old count."""
        from memanga.scrapers import playwright_base as pb

        scraper, pw = source
        self._task(scraper)

        def _get_chapters_in_thread():
            scraper._get_browser_in_thread()
            pb.cleanup_browsers()
            return scraper._get_browser_in_thread()

        type(scraper)._run_serialized(_get_chapters_in_thread, timeout=LONG)
        self._task(scraper)
        assert len(pw.launched) == 2
        self._task(scraper)
        assert len(pw.launched) == 3


def test_recycle_is_never_due_outside_a_task():
    import types

    local = types.SimpleNamespace(tasks_served=99)
    assert browser_recycle_due(local, 1) is False
    assert local.tasks_served == 99


def test_operation_names_drop_private_prefix_and_thread_suffix():
    def _get_chapters_in_thread():
        pass

    def cleanup_browsers():
        pass

    assert _operation_name(_get_chapters_in_thread) == "get_chapters"
    assert _operation_name(cleanup_browsers) == "cleanup_browsers"
