"""Tests for memanga.gui.workers.BackgroundWorker."""

from __future__ import annotations

import threading
import pytest


@pytest.fixture
def worker(event_bus):
    from memanga.gui.workers import BackgroundWorker
    w = BackgroundWorker(event_bus)
    yield w
    w.shutdown()


class TestWorkerLifecycle:
    def test_construct(self, worker):
        assert worker._max_concurrent_downloads >= 1

    def test_submit_task_returns_future(self, worker):
        called = []
        fut = worker.submit_task(lambda: called.append(1))
        fut.result(timeout=2)
        assert called == [1]


class TestPauseResume:
    def test_starts_not_paused(self, worker):
        assert worker.is_paused() is False

    def test_pause_sets_flag(self, worker):
        worker.pause_all()
        assert worker.is_paused() is True

    def test_resume_clears_flag(self, worker):
        worker.pause_all()
        worker.resume_all()
        assert worker.is_paused() is False


class TestCancelFlags:
    def test_active_tasks_starts_empty(self, worker):
        assert worker.active_tasks == {}

    def test_cancel_download_unknown_is_noop(self, worker):
        worker.cancel_download("never-existed")


class TestPingSources:
    def test_dispatches_to_pool(self, worker, state, monkeypatch):
        # Patch requests.head so we don't hit the network.
        import requests
        import time
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        monkeypatch.setattr(requests, "head", lambda *a, **k: resp)

        worker.ping_sources(["mock.test"], state)
        # ping_sources runs on the shared pool, which then spins up its
        # own inner ThreadPoolExecutor — wait for the state update to
        # actually land. Polling with a short deadline keeps the test
        # fast on success without flaking on slow CI.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            h = state.get_source_health("mock.test")
            if h.get("status"):
                break
            time.sleep(0.05)
        h = state.get_source_health("mock.test")
        assert h.get("status") == "ok"


class TestCountChapters:
    """Lazy chapter-count probe used by the search page to show "47 ch"
    chips next to results so users can spot out-of-date sources at a
    glance.
    """

    def test_publishes_event_with_count(self, event_bus, monkeypatch):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)

        # Fake scraper that returns 5 chapters for any URL.
        class _Fake:
            def get_chapters(self, _url):
                return [object() for _ in range(5)]
        import memanga.scrapers as scr
        monkeypatch.setattr(scr, "get_scraper", lambda _d: _Fake())

        seen = []
        event_bus.subscribe("search_chapter_count", lambda d: seen.append(d))

        w.count_chapters("mangadex.org", "https://x/m")
        # Poll until the background task lands an event — pool has 3
        # workers and the count_chapters task races with sentinel-style
        # waits, so just spin-wait for the publish.
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not seen:
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        assert seen and seen[0]["count"] == 5
        assert seen[0]["source"] == "mangadex.org"
        assert seen[0]["url"] == "https://x/m"

    def test_failure_publishes_minus_one(self, event_bus, monkeypatch):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        # Disable retry back-off so the test doesn't sit through the
        # production 4 + 8 + 16 s wait waiting for each attempt to
        # fail. The retry behaviour itself is exercised by
        # test_retries_on_transient_failure below.
        w._COUNT_RETRY_DELAYS = ()

        class _Boom:
            def get_chapters(self, _url): raise IOError("network")
        import memanga.scrapers as scr
        monkeypatch.setattr(scr, "get_scraper", lambda _d: _Boom())

        seen = []
        event_bus.subscribe("search_chapter_count", lambda d: seen.append(d))
        w.count_chapters("mangadex.org", "https://x/m")
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not seen:
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        assert seen and seen[0]["count"] == -1

    def test_retries_on_transient_failure(self, event_bus, monkeypatch):
        """A transient failure must be retried so the chip fills in
        once the source recovers, instead of staying blank after a
        single network blip.
        """
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        # Compress the retry schedule to keep the test fast.
        w._COUNT_RETRY_DELAYS = (0.05, 0.05)

        calls = {"n": 0}
        class _FlakyThenOk:
            def get_chapters(self, _url):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise IOError("transient")
                return [object() for _ in range(7)]
        import memanga.scrapers as scr
        monkeypatch.setattr(scr, "get_scraper", lambda _d: _FlakyThenOk())

        seen = []
        event_bus.subscribe("search_chapter_count", lambda d: seen.append(d))
        w.count_chapters("mangadex.org", "https://x/m")
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not seen:
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        assert calls["n"] == 3, f"expected 3 attempts, got {calls['n']}"
        assert seen and seen[0]["count"] == 7

    def test_offline_is_noop(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        class _OfflineMon:
            is_online = False
        w = BackgroundWorker(event_bus)
        w.network = _OfflineMon()

        seen = []
        event_bus.subscribe("search_chapter_count", lambda d: seen.append(d))
        w.count_chapters("mangadex.org", "https://x/m")
        event_bus.poll()
        assert seen == []


class TestCheckUpdates:
    """Issue #30: explicit per-manga checks must bypass the reading-only
    filter that the library-wide sweep applies to non-reading manga."""

    def _run_check(self, worker, event_bus, state, monkeypatch,
                   manga_list, force):
        import time
        import memanga.downloader as downloader
        checked = []

        def _fake_check(manga, _state, return_all=False):
            checked.append(manga.get("title"))
            return ([], []) if return_all else []

        monkeypatch.setattr(downloader, "check_for_updates", _fake_check)

        done = []
        event_bus.subscribe("check_complete", lambda d: done.append(d))
        worker.check_updates(manga_list, state, config=None, force=force)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not done:
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        assert done, "check_complete never fired"
        return checked

    def test_sweep_skips_non_reading(self, worker, event_bus, state,
                                     monkeypatch):
        checked = self._run_check(worker, event_bus, state, monkeypatch, [
            {"title": "Reading one", "status": "reading",
             "source": "mock.test", "url": "u"},
            {"title": "Plan one", "status": "plan",
             "source": "mock.test", "url": "u"},
        ], force=False)
        assert checked == ["Reading one"]

    def test_force_checks_non_reading(self, worker, event_bus, state,
                                      monkeypatch):
        checked = self._run_check(worker, event_bus, state, monkeypatch, [
            {"title": "Plan one", "status": "plan",
             "source": "mock.test", "url": "u"},
        ], force=True)
        assert checked == ["Plan one"]


class TestSearchRelevanceFilter:
    """Regression for the 'searching Blue Lock returns Beastars, Tokyo
    Ghoul, …' bug. Single-manga aggregators (TGManga, BeastarsManga,
    AjimeNoIppo, …) blindly return their one hardcoded manga regardless
    of the query string. The worker's _result_matches_query() drops
    those obvious mismatches before publishing."""

    def test_exact_match_passes(self):
        from memanga.gui.workers import _result_matches_query
        assert _result_matches_query("Blue Lock", "blue lock")

    def test_substring_match_passes(self):
        from memanga.gui.workers import _result_matches_query
        assert _result_matches_query("Blue Lock Legions", "blue lock")
        assert _result_matches_query("Blue Lock - Episode Nagi", "blue lock")

    def test_unrelated_singleton_dropped(self):
        from memanga.gui.workers import _result_matches_query
        # Single-manga scrapers return their hard-coded title regardless
        # of the query; the filter must drop those mismatches.
        assert not _result_matches_query("Beastars", "blue lock")
        assert not _result_matches_query("Tokyo Ghoul", "blue lock")
        assert not _result_matches_query("Hajime no Ippo", "blue lock")
        assert not _result_matches_query("One Piece", "blue lock")

    def test_single_token_requires_all(self):
        from memanga.gui.workers import _result_matches_query
        assert _result_matches_query("Naruto", "naruto")
        assert not _result_matches_query("Boruto", "naruto")

    def test_long_query_allows_partial(self):
        from memanga.gui.workers import _result_matches_query
        # 3-token query → at least 2 of 3 (60%) tokens must hit.
        assert _result_matches_query("Spy x Family", "spy x family")
        # Title with only 1 of 3 tokens fails.
        assert not _result_matches_query("Other Series", "spy x family")

    def test_empty_query_passes_everything(self):
        from memanga.gui.workers import _result_matches_query
        assert _result_matches_query("Anything", "")


class TestPopularitySort:
    """Sources must be searched + presented in popularity order so the
    most-trusted aggregators (MangaDex, MangaPill, MangaFire, …) always
    appear above the long-tail."""

    def test_known_sources_ordered_by_rank(self):
        from memanga.gui.workers import sort_sources_by_popularity
        out = sort_sources_by_popularity([
            "akiramanga.com",          # unranked
            "mangapill.com",           # rank 1
            "mangabuddy.com",          # rank 3
            "mangadex.org",            # rank 0
        ])
        assert out == ["mangadex.org", "mangapill.com",
                        "mangabuddy.com", "akiramanga.com"]

    def test_unranked_sources_sort_alphabetically(self):
        from memanga.gui.workers import sort_sources_by_popularity
        out = sort_sources_by_popularity(["zzz.com", "aaa.com", "mmm.com"])
        assert out == ["aaa.com", "mmm.com", "zzz.com"]

    def test_source_rank(self):
        from memanga.gui.workers import source_rank
        assert source_rank("mangadex.org") < source_rank("mangapill.com")
        assert source_rank("anything-unranked.com") == 999
