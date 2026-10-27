"""
Base class for Playwright-based scrapers with stealth mode.

Uses ThreadPoolExecutor to run Playwright sync API in a separate thread,
avoiding conflicts with asyncio event loops (e.g., from rich library).
"""

import time
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, wait
import threading
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Thread-local storage for browser instances
_thread_local = threading.local()

# The running browser task's caller deadline, set on the worker thread.
_task_local = threading.local()

# A browser step ends this long before the caller's deadline, leaving
# time to close the page and hand the result back.
STEP_RESERVE_S = 5.0
# Below this much usable time a browser step is not worth starting.
_MIN_STEP_S = 1.0


class BrowserTimeoutError(TimeoutError):
    """A browser task did not finish within its caller's time budget."""


def task_seconds_left() -> Optional[float]:
    """Seconds until the caller of the running browser task gives up,
    or None when not called from inside a ``BrowserWorker`` task."""
    task = getattr(_task_local, "task", None)
    if task is None:
        return None
    return task["deadline"] - time.monotonic()


def task_budget_spent() -> bool:
    """True inside a ``BrowserWorker`` task once too little of the
    caller's budget is left to start another browser step, i.e. when a
    step that just failed most likely failed because it was cut short."""
    left = task_seconds_left()
    return left is not None and left - STEP_RESERVE_S < _MIN_STEP_S


def step_timeout_ms(cap_ms: float) -> float:
    """Playwright timeout for one step of the running browser task.

    ``cap_ms`` is the step's own limit. Inside a ``BrowserWorker`` task
    it is shortened so the step ends ``STEP_RESERVE_S`` before the
    caller's deadline; outside one it is returned unchanged. Raises
    ``BrowserTimeoutError`` when too little time is left to start.
    """
    task = getattr(_task_local, "task", None)
    if task is None:
        return cap_ms
    usable_s = task["deadline"] - time.monotonic() - STEP_RESERVE_S
    if usable_s < _MIN_STEP_S:
        raise BrowserTimeoutError(
            f"{task['source']} {task['operation']}: {task['timeout']:g}s "
            f"budget used up before the next browser step"
        )
    return min(cap_ms, usable_s * 1000)


def _operation_name(fn) -> str:
    """``_get_chapters_in_thread`` -> ``get_chapters``."""
    name = (getattr(fn, "__name__", None) or type(fn).__name__).strip("_")
    if name.endswith("_in_thread"):
        name = name[:-len("_in_thread")]
    return name


class BrowserWorker:
    """The one thread that owns a browser, and the rules for giving it work.

    Playwright's sync objects belong to the thread that created them, so
    every browser call for one owner runs on this worker, one task at a
    time; cleanup goes through it too, so a browser is never touched
    from another thread.

    A caller's ``timeout`` starts once it holds the lock and covers both
    waiting for earlier abandoned work and its own task. Waiting for the
    lock itself means waiting for other live callers, each bounded by
    its own budget, so a queued call does not burn its budget there.

    Python cannot stop a running thread. When a caller times out, its
    task keeps running; the worker remembers it, and the next caller
    waits for it within its own budget instead of queueing behind it.
    So there is at most one abandoned task, nothing is ever queued
    behind it, and no task starts after its caller has given up. If the
    abandoned task never returns, every later call fails after its own
    budget until it does.
    """

    def __init__(self, thread_name_prefix: str):
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=thread_name_prefix,
        )
        self._lock = threading.Lock()
        # (future, operation, monotonic time it was abandoned) or None.
        self._abandoned = None

    def call(self, source: str, timeout: float, fn, /, *args, **kwargs):
        """Run ``fn(*args, **kwargs)`` on the worker and return its result.

        Raises whatever ``fn`` raises, or ``BrowserTimeoutError`` when the
        budget runs out.
        """
        operation = _operation_name(fn)
        queued_at = time.monotonic()
        with self._lock:
            started = time.monotonic()
            deadline = started + timeout
            lock_wait = started - queued_at
            self._wait_for_abandoned(source, operation, timeout, deadline)
            task = {"source": source, "operation": operation,
                    "timeout": timeout, "deadline": deadline}
            future = self._executor.submit(self._run_task, task, fn,
                                           args, kwargs)
            # Decide "did it finish in time" with wait(), never by catching
            # TimeoutError from result(): a task may raise TimeoutError
            # itself (a socket timeout, a used-up step budget), and that
            # must reach the caller unchanged, not be read as expiry.
            wait([future], timeout=max(0.0, deadline - time.monotonic()))
            if future.done():
                # Also covers a task that ended just after wait() gave
                # up: deliver its outcome rather than abandon finished work.
                return future.result()
            self._abandoned = (future, operation, time.monotonic())
            future.add_done_callback(
                lambda _f, s=source, o=operation:
                logger.debug("abandoned %s %s finished", s, o))
            waited = (f" (after {lock_wait:.0f}s waiting for earlier "
                      f"{source} calls)" if lock_wait >= 1 else "")
            raise BrowserTimeoutError(
                f"{source} {operation} timed out after {timeout:g}s"
                f"{waited}; the browser task is still running and "
                f"will finish in the background"
            )

    def _wait_for_abandoned(self, source, operation, timeout, deadline):
        """Wait, within the caller's budget, for an abandoned task to end."""
        if self._abandoned is None:
            return
        future, stale_operation, abandoned_at = self._abandoned
        done, _ = wait([future], timeout=max(0.0, deadline - time.monotonic()))
        if not done:
            raise BrowserTimeoutError(
                f"{source} {operation} timed out after {timeout:g}s: the "
                f"browser is still busy with an earlier {stale_operation} "
                f"that timed out "
                f"{time.monotonic() - abandoned_at:.0f}s ago"
            )
        self._abandoned = None
        if deadline - time.monotonic() < _MIN_STEP_S:
            # Starting now would only abandon another task at once.
            raise BrowserTimeoutError(
                f"{source} {operation} timed out after {timeout:g}s waiting "
                f"for an earlier {stale_operation} to finish"
            )

    @staticmethod
    def _run_task(task, fn, args, kwargs):
        _task_local.task = task
        try:
            return fn(*args, **kwargs)
        finally:
            _task_local.task = None

    def shutdown(self, wait: bool = True):
        """Stop the worker thread once its current task ends."""
        self._executor.shutdown(wait=wait)


def cleanup_browsers():
    """Close all thread-local Playwright browser instances."""
    if hasattr(_thread_local, 'context'):
        try:
            _thread_local.context.close()
        except Exception:
            pass
        del _thread_local.context

    if hasattr(_thread_local, 'browser'):
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        del _thread_local.browser

    if hasattr(_thread_local, 'playwright'):
        try:
            _thread_local.playwright.stop()
        except Exception:
            pass
        del _thread_local.playwright


class PlaywrightScraper(BaseScraper):
    """Base class for scrapers that need Playwright with stealth mode."""

    engine = "browser"

    # Budget for closing one subclass's browser in cleanup().
    _CLEANUP_TIMEOUT_S = 10.0

    # NOTE: do NOT define `_worker` on this base class.
    # `__init_subclass__` below gives every subclass its OWN worker
    # so WeebCentral, MangaKatana, MangaClash, MangaHere etc.
    # can run their search/get_chapters/get_pages calls in PARALLEL inside
    # the search worker's 8-slot pool.
    #
    # A single shared worker thread on the base class would serialise
    # every Playwright-based source through one browser thread — with 5+
    # such sources in the popular set, the slow ones starve the rest and
    # the search appears to hang.

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "_worker" not in cls.__dict__:
            cls._worker = BrowserWorker(thread_name_prefix=f"pw-{cls.__name__}")

    @classmethod
    def _run_serialized(cls, fn, *args, timeout: float, **kwargs):
        """Run ``fn`` on this class's browser worker within ``timeout``.

        The budget covers the task itself plus any earlier timed-out
        task the worker is still finishing, but not waiting behind other
        live callers; see ``BrowserWorker`` for the rules. A timeout
        raises ``BrowserTimeoutError`` naming the source, operation and
        budget.
        """
        return cls._worker.call(cls.name, timeout, fn, *args, **kwargs)

    def _get_browser_in_thread(self):
        """Get or create the thread-local browser.

        ATOMIC: if `firefox.launch()` fails, we don't leave a half-
        initialised `_thread_local` behind. The old code set
        `_thread_local.playwright = sync_playwright().start()` first,
        and if the next line (`firefox.launch(...)`) raised, the next
        call to this function would see `hasattr(_thread_local,
        'playwright')` → True, skip the init block, and crash on
        `return _thread_local.browser` with AttributeError. That
        cascading failure took out unrelated scrapers in the same
        worker thread.
        """
        # Hot path: everything already up.
        if (hasattr(_thread_local, 'browser')
                and hasattr(_thread_local, 'context')
                and hasattr(_thread_local, 'playwright')):
            return _thread_local.browser, _thread_local.context

        # Clear any dangling state from a previous partial init before
        # retrying — otherwise sync_playwright().start() raises
        # "already started" on the second attempt in this thread.
        cleanup_browsers()

        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser, context = self._launch_browser(pw)
        except Exception:
            # Roll back the Playwright start so the next call can retry
            # cleanly instead of inheriting half-broken state.
            try:
                pw.stop()
            except Exception:
                pass
            raise

        # Commit all three at once — never leave half-set thread-local.
        _thread_local.playwright = pw
        _thread_local.browser = browser
        _thread_local.context = context
        return browser, context

    def _launch_browser(self, pw):
        """Launch this scraper's browser and context from a started Playwright.

        Stealth Firefox by default. Override for sites that need a
        different engine (e.g. MangaPark, whose Cloudflare challenge only
        lets Chromium through). Runs inside the executor thread, and
        ``_get_browser_in_thread`` rolls Playwright back if this raises.
        The launch keeps Playwright's default limit, cut to the task's
        remaining budget.
        """
        browser = pw.firefox.launch(headless=True,
                                    timeout=step_timeout_ms(180000))
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        )
        return browser, context

    def _fetch_page_content(self, url: str, wait_time: int = 2000, cookies: list = None) -> str:
        """Internal: fetch page content (runs in thread) with retry."""
        from playwright_stealth import Stealth

        last_error = None
        for attempt in range(1, 4):
            browser, context = self._get_browser_in_thread()
            page = context.new_page()
            try:
                Stealth().apply_stealth_sync(page)

                if cookies:
                    context.add_cookies(cookies)

                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                if wait_time > 0:
                    page.wait_for_timeout(wait_time)

                return page.content()
            except Exception as e:
                last_error = e
                if attempt < 3:
                    delay = attempt * 2
                    logger.debug(f"Playwright fetch attempt {attempt}/3 failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
            finally:
                page.close()

        raise last_error

    def _get_page_content(self, url: str, wait_time: int = 2000, cookies: list = None) -> str:
        """
        Get page content using Playwright with stealth.
        Runs in a separate thread to avoid asyncio conflicts.

        Args:
            url: URL to fetch
            wait_time: Extra wait time in ms after load
            cookies: Optional list of cookies to set
        """
        return self._run_serialized(
            self._fetch_page_content, url, wait_time, cookies, timeout=60,
        )

    def _run_js_in_thread(self, url: str, script: str, wait_time: int = 2000):
        """Internal: execute JS on page (runs in thread) with retry."""
        from playwright_stealth import Stealth

        last_error = None
        for attempt in range(1, 4):
            browser, context = self._get_browser_in_thread()
            page = context.new_page()
            try:
                Stealth().apply_stealth_sync(page)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                if wait_time > 0:
                    page.wait_for_timeout(wait_time)

                return page.evaluate(script)
            except Exception as e:
                last_error = e
                if attempt < 3:
                    delay = attempt * 2
                    logger.debug(f"Playwright JS attempt {attempt}/3 failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
            finally:
                page.close()

        raise last_error

    def _execute_js(self, url: str, script: str, wait_time: int = 2000):
        """
        Execute JavaScript on a page and return result.
        Runs in a separate thread to avoid asyncio conflicts.

        Args:
            url: URL to navigate to
            script: JavaScript to execute
            wait_time: Wait time before executing
        """
        return self._run_serialized(
            self._run_js_in_thread, url, script, wait_time, timeout=60,
        )

    @classmethod
    def cleanup(cls):
        """Cleanup browser instances in every subclass's worker thread.

        Each PlaywrightScraper subclass owns its own worker (see
        `__init_subclass__`), so a single base-class cleanup would
        miss the real per-subclass browsers. Walk the subclass tree
        and run cleanup_browsers in each dedicated thread. A worker
        still busy with a timed-out task is skipped after the cleanup
        budget rather than having its browser closed under it.
        """
        seen: set = set()
        def _walk(c):
            for sub in c.__subclasses__():
                if sub in seen:
                    continue
                seen.add(sub)
                if "_worker" in sub.__dict__:
                    try:
                        sub._run_serialized(cleanup_browsers,
                                            timeout=cls._CLEANUP_TIMEOUT_S)
                    except Exception:
                        pass
                _walk(sub)
        _walk(cls)
