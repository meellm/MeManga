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


class TestPauseResumeQueue:
    """Issue #40 — Pause All / Resume All must hold the queue and then
    refill every free slot, without dropping queued items or breaching
    `_max_concurrent_downloads`.
    """

    @pytest.fixture
    def gated_downloads(self, monkeypatch):
        """Patch the downloader with a fake that blocks until released,
        so tests can hold jobs "in flight" and observe real concurrency.
        """
        import time
        import memanga.downloader as dl

        class Harness:
            def __init__(self):
                self.gates: dict[str, threading.Event] = {}
                self.running: set[str] = set()
                self.max_running = 0
                self._lock = threading.Lock()

            def release(self, *task_ids):
                for tid in task_ids:
                    self.gates[tid].set()

            def release_all(self):
                for gate in self.gates.values():
                    gate.set()

            def wait_for(self, predicate, timeout=5.0):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if predicate():
                        return True
                    time.sleep(0.02)
                return predicate()

        h = Harness()

        def fake_download_chapter(manga, chapter, output_dir, output_format,
                                   state, progress_callback=None,
                                   naming_template=None, cancel_event=None,
                                   **kwargs):
            tid = f"{manga['title']}:{chapter.number}"
            with h._lock:
                h.running.add(tid)
                h.max_running = max(h.max_running, len(h.running))
            h.gates[tid].wait(timeout=10)
            with h._lock:
                h.running.discard(tid)
            return None

        monkeypatch.setattr(dl, "download_chapter", fake_download_chapter)
        return h

    def _queue(self, worker, harness, n, state):
        """Queue chapters M:1..M:n through the public API."""
        import types
        for i in range(1, n + 1):
            tid = f"M:{i}"
            harness.gates[tid] = threading.Event()
            worker.download_chapter(
                {"title": "M"}, types.SimpleNamespace(number=str(i)),
                "/tmp/out", "pdf", state,
            )

    def test_resume_refills_all_free_slots(self, worker, gated_downloads,
                                           state):
        # Everything queued while paused; resume must start a full
        # `_max_concurrent_downloads` batch, not just one job.
        worker.pause_all()
        self._queue(worker, gated_downloads, 4, state)
        assert len(worker._download_queue) == 4

        worker.resume_all()
        assert gated_downloads.wait_for(
            lambda: len(gated_downloads.running) == 2)
        assert len(worker._download_queue) == 2
        assert worker._active_downloads == 2
        gated_downloads.release_all()

    def test_toggle_while_in_flight_keeps_queue_and_cap(
            self, worker, gated_downloads, state):
        # Pause/resume while jobs are running used to release a slot no
        # job ever held — each toggle dequeued one extra item past the
        # concurrency cap, where a later Pause All could no longer hold
        # it ("the queue drops").
        self._queue(worker, gated_downloads, 6, state)
        assert gated_downloads.wait_for(
            lambda: len(gated_downloads.running) == 2)

        for _ in range(3):
            worker.pause_all()
            worker.resume_all()

        # Nothing new may start while both slots are taken.
        assert not gated_downloads.wait_for(
            lambda: len(gated_downloads.running) > 2, timeout=0.3)
        assert len(worker._download_queue) == 4
        assert worker._active_downloads == 2

        gated_downloads.release_all()
        assert gated_downloads.wait_for(
            lambda: len(worker._download_queue) == 0
            and worker._active_downloads == 0)
        assert gated_downloads.max_running == 2

    def test_pause_resume_drains_everything(self, worker, event_bus,
                                             gated_downloads, state):
        # Full reported flow: queue, pause, let in-flight finish,
        # resume — every chapter must still complete exactly once.
        completed = []
        event_bus.subscribe("download_complete",
                            lambda d: completed.append(d["task_id"]))
        self._queue(worker, gated_downloads, 5, state)
        assert gated_downloads.wait_for(
            lambda: len(gated_downloads.running) == 2)

        worker.pause_all()
        gated_downloads.release("M:1", "M:2")
        assert gated_downloads.wait_for(
            lambda: worker._active_downloads == 0)
        assert len(worker._download_queue) == 3  # queue held, not dropped

        worker.resume_all()
        gated_downloads.release_all()
        assert gated_downloads.wait_for(
            lambda: len(worker._download_queue) == 0
            and worker._active_downloads == 0)
        event_bus.poll()
        assert sorted(completed) == [f"M:{i}" for i in range(1, 6)]
        assert gated_downloads.max_running == 2


class TestPartialDownload:
    """Partial-chapter tolerance (issue #86): the worker forwards the
    config-derived settings to the downloader and surfaces the accepted
    partial in the download_complete event."""

    def test_partial_info_forwarded_and_surfaced(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        import types
        import time
        import memanga.downloader as dl

        seen_kwargs = {}

        def fake_download_chapter(manga, chapter, output_dir, output_format,
                                   state, progress_callback=None,
                                   naming_template=None, cancel_event=None,
                                   allow_partial=False, partial_threshold=0.0,
                                   on_partial=None, **kwargs):
            seen_kwargs["allow_partial"] = allow_partial
            seen_kwargs["partial_threshold"] = partial_threshold
            # Simulate an accepted partial download.
            if on_partial is not None:
                on_partial([6], 40)
            return tmp_path / "out.pdf"

        monkeypatch.setattr(dl, "download_chapter", fake_download_chapter)

        completed = []
        event_bus.subscribe("download_complete", lambda d: completed.append(d))

        worker.download_chapter(
            {"title": "Vinland Saga"}, types.SimpleNamespace(number="71"),
            str(tmp_path), "pdf", state,
            allow_partial=True, partial_threshold=5,
        )

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not completed:
            event_bus.poll()
            time.sleep(0.02)

        assert seen_kwargs == {"allow_partial": True, "partial_threshold": 5}
        assert completed and completed[0].get("partial") == {
            "failed_pages": [6], "total": 40}
        assert completed[0].get("source") == "unknown"
        # The shared pipeline recorded the partial before the event.
        record = state.get_partial_chapter("Vinland Saga", "71")
        assert record["failed_pages"] == [6]
        assert state.is_chapter_downloaded("Vinland Saga", "71")


class TestBackupFirst:
    """Backup-first parity with the CLI (issue #86): when a primary
    download fails and the manga has a backup source, the worker prefers
    a *complete* backup download over keeping a primary partial. Only if
    the backup also fails does partial tolerance salvage the best partial
    (backup first, then primary) within threshold."""

    # Manga with a real backup source configured (sources array, len 2).
    _MANGA = {
        "title": "Vinland Saga",
        "sources": [
            {"url": "https://primary.test/vs", "source": "primary.test"},
            {"url": "https://backup.test/vs", "source": "backup.test"},
        ],
    }

    def _run(self, worker, event_bus, monkeypatch, fake_dl,
             allow_partial, partial_threshold, tmp_path, state):
        """Drive a single download through the worker with a faked
        downloader + backup lookup; return (completes, errors, cancels)."""
        import types
        import time
        import memanga.downloader as dl

        # Backup lookup returns a chapter tagged as backup so the fake
        # downloader can tell primary and backup attempts apart.
        backup_ch = types.SimpleNamespace(
            number="71", url="https://backup.test/vs/71",
            source="backup.test", is_backup=True)
        monkeypatch.setattr(
            dl, "_find_chapter_on_backup",
            lambda manga, num, state=None: backup_ch)
        monkeypatch.setattr(dl, "download_chapter", fake_dl)

        completes, errors, cancels = [], [], []
        event_bus.subscribe("download_complete", lambda d: completes.append(d))
        event_bus.subscribe("download_error", lambda d: errors.append(d))
        event_bus.subscribe("download_cancelled", lambda d: cancels.append(d))

        chapter = types.SimpleNamespace(number="71", url="https://primary.test/vs/71")
        worker.download_chapter(
            self._MANGA, chapter, str(tmp_path), "pdf", state,
            allow_partial=allow_partial, partial_threshold=partial_threshold)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not (completes or errors or cancels):
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        return completes, errors, cancels

    def test_primary_error_backup_complete_no_partial(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        # Primary raises; backup delivers a complete chapter → completes
        # from backup with no partial warning.
        from memanga.downloader import DownloaderError

        def fake_dl(manga, chapter, output_dir, output_format, state=None,
                    on_partial=None, **kw):
            if not getattr(chapter, "is_backup", False):
                raise DownloaderError("primary boom",
                                      failed_pages=[3], total_pages=10)
            return tmp_path / "backup.pdf"  # complete, no on_partial

        completes, errors, cancels = self._run(
            worker, event_bus, monkeypatch, fake_dl,
            allow_partial=True, partial_threshold=5, tmp_path=tmp_path,
            state=state)

        assert not errors and not cancels
        assert len(completes) == 1
        assert completes[0].get("from_backup") is True
        assert "partial" not in completes[0]

    def test_primary_partial_still_prefers_complete_backup(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        # Even when the primary *could* have been kept as a partial within
        # threshold, the presence of a backup means the primary is tried
        # with partial disabled first, so it errors and the complete
        # backup wins.
        from memanga.downloader import DownloaderError

        seen = {"primary_allow_partial": None}

        def fake_dl(manga, chapter, output_dir, output_format, state=None,
                    allow_partial=False, on_partial=None, **kw):
            if not getattr(chapter, "is_backup", False):
                seen["primary_allow_partial"] = allow_partial
                raise DownloaderError("primary incomplete")
            return tmp_path / "backup.pdf"

        completes, errors, cancels = self._run(
            worker, event_bus, monkeypatch, fake_dl,
            allow_partial=True, partial_threshold=90, tmp_path=tmp_path,
            state=state)

        # Primary was attempted with partial disabled (backup exists).
        assert seen["primary_allow_partial"] is False
        assert not errors and len(completes) == 1
        assert completes[0].get("from_backup") is True
        assert "partial" not in completes[0]

    def test_backup_partial_under_threshold_kept_from_backup(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        # Primary fails, backup can't complete either, but the backup
        # partial is within threshold → keep the backup partial.
        from memanga.downloader import DownloaderError

        def fake_dl(manga, chapter, output_dir, output_format, state=None,
                    allow_partial=False, on_partial=None, **kw):
            if not getattr(chapter, "is_backup", False):
                raise DownloaderError("primary boom")
            if not allow_partial:
                raise DownloaderError("backup incomplete")  # complete attempt
            if on_partial is not None:
                on_partial([4], 20)  # 5% missing, within threshold
            return tmp_path / "backup_partial.pdf"

        completes, errors, cancels = self._run(
            worker, event_bus, monkeypatch, fake_dl,
            allow_partial=True, partial_threshold=10, tmp_path=tmp_path,
            state=state)

        assert not errors and len(completes) == 1
        assert completes[0].get("from_backup") is True
        assert completes[0].get("partial") == {"failed_pages": [4], "total": 20}

    def test_all_fail_over_threshold_errors(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        # Primary fails, backup complete fails, and neither backup nor
        # primary partial is within threshold → download_error, and the
        # message names both sources.
        from memanga.downloader import DownloaderError

        def fake_dl(manga, chapter, output_dir, output_format, state=None,
                    allow_partial=False, on_partial=None, **kw):
            # Over-threshold partials raise from the real downloader; the
            # fake mimics that by always raising.
            raise DownloaderError("incomplete")

        completes, errors, cancels = self._run(
            worker, event_bus, monkeypatch, fake_dl,
            allow_partial=True, partial_threshold=1, tmp_path=tmp_path,
            state=state)

        assert not completes and not cancels
        assert len(errors) == 1
        assert "Primary" in errors[0]["error"] and "Backup" in errors[0]["error"]
        # One failure record, with the same text as the event.
        record = state.get_failed_chapters("Vinland Saga")["71"]
        assert record["error"] == errors[0]["error"]
        assert record["source"] == "unknown+backup.test"

    def test_partial_disabled_backup_complete_still_used(
            self, worker, event_bus, monkeypatch, tmp_path, state):
        # With partial tolerance off, a failing primary still falls back to
        # a *complete* backup (parity with the CLI multi-source backup),
        # but no partial is ever kept.
        from memanga.downloader import DownloaderError

        def fake_dl(manga, chapter, output_dir, output_format, state=None,
                    allow_partial=False, on_partial=None, **kw):
            if not getattr(chapter, "is_backup", False):
                raise DownloaderError("primary boom")
            if not allow_partial:
                return tmp_path / "backup.pdf"
            raise AssertionError("partial salvage must not run when disabled")

        completes, errors, cancels = self._run(
            worker, event_bus, monkeypatch, fake_dl,
            allow_partial=False, partial_threshold=0, tmp_path=tmp_path,
            state=state)

        assert not errors and len(completes) == 1
        assert completes[0].get("from_backup") is True
        assert "partial" not in completes[0]


class TestCancelFlags:
    def test_active_tasks_starts_empty(self, worker):
        assert worker.active_tasks == {}

    def test_cancel_download_unknown_is_noop(self, worker):
        worker.cancel_download("never-existed")


class TestDownloadChapter:
    def test_forwards_post_processing_config(self, worker, monkeypatch,
                                             state):
        import time
        import types
        from pathlib import Path
        import memanga.downloader as dl

        seen = {}

        def fake_download_chapter(manga, chapter, output_dir, output_format,
                                  **kwargs):
            seen.update(kwargs)
            return Path("/tmp/out/M/Chapter 1.cbz")

        monkeypatch.setattr(dl, "download_chapter", fake_download_chapter)

        post_processing = {
            "enabled": True,
            "command": "echo ok",
            "fail_on_error": True,
        }
        worker.download_chapter(
            {"title": "M"},
            types.SimpleNamespace(number="1"),
            "/tmp/out",
            "cbz",
            state,
            post_processing=post_processing,
        )

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)

        assert seen["post_processing"] is post_processing

    def test_download_error_records_failed_chapter(self, worker, monkeypatch,
                                                   event_bus):
        import time
        import types
        import memanga.downloader as dl

        class FakeState:
            def __init__(self):
                self.failed = []

            def add_failed_chapter(self, *args, **kwargs):
                self.failed.append(args)

        def fake_download_chapter(manga, chapter, output_dir, output_format,
                                  **kwargs):
            raise dl.DownloaderError("post-processing command exited with code 3")

        monkeypatch.setattr(dl, "download_chapter", fake_download_chapter)

        errors = []
        event_bus.subscribe("download_error", errors.append)
        state = FakeState()
        chapter = types.SimpleNamespace(number="1", source="mock.test")

        worker.download_chapter(
            {"title": "M", "source": "mock.test"},
            chapter,
            "/tmp/out",
            "cbz",
            state,
            post_processing={
                "enabled": True,
                "command": "exit 3",
                "fail_on_error": True,
            },
        )

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not state.failed:
            time.sleep(0.02)
        event_bus.poll()

        assert state.failed == [
            ("M", "1", "mock.test",
             "post-processing command exited with code 3")
        ]
        assert errors


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


class _RecordingCache:
    """Stand-in for CoverCache that records calls instead of touching
    disk or QPixmap."""

    def __init__(self):
        self.saved = {}
        self.failed = []

    def save_to_disk(self, url, content):
        self.saved[url] = content

    def mark_failed(self, url):
        self.failed.append(url)


class TestCoverFetch:
    """Issue #48 — MangaPill covers live on a hotlink-protected CDN
    that answers 403 (or an HTML block page) unless the request carries
    the site's Referer. The generic cover fetch must send the right
    Referer and must refuse to cache non-image bodies.
    """

    _CDN_URL = "https://cdn.readdetectiveconan.com/file/mangapill/i/580.webp"
    _WEBP_BYTES = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16

    def test_mangapill_cdn_url_gets_referer(self):
        from memanga.gui.workers import cover_request_headers
        headers = cover_request_headers(self._CDN_URL)
        assert headers["Referer"] == "https://mangapill.com/"

    def test_unknown_host_gets_no_referer(self):
        from memanga.gui.workers import cover_request_headers
        headers = cover_request_headers(
            "https://uploads.mangadex.org/covers/abc/def.512.jpg")
        assert "Referer" not in headers
        assert "User-Agent" in headers

    def test_mangahere_cdn_url_gets_referer(self):
        # Issue #174: fmcdn.mangahere.com answers a refererless request
        # with a 403 HTML page, so the cover stayed blank.
        from memanga.gui.workers import cover_request_headers
        headers = cover_request_headers(
            "https://fmcdn.mangahere.com/store/manga/8602/cover.jpg")
        assert headers["Referer"] == "https://www.mangahere.cc/"

    # looks_like_image now lives in memanga.scrapers.base and is pinned
    # down there (tests/scrapers/test_base_helpers.py). These only check
    # that the workers re-export still behaves for the cover fetch.
    def test_looks_like_image_accepts_magic_bytes(self):
        from memanga.gui.workers import looks_like_image
        assert looks_like_image(b"\xff\xd8\xff" + b"\x00" * 16)          # JPEG
        assert looks_like_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)     # PNG
        assert looks_like_image(self._WEBP_BYTES)                        # WEBP

    def test_looks_like_image_content_type_fallback(self):
        from memanga.gui.workers import looks_like_image
        # SVG has no magic number — trust the Content-Type header.
        assert looks_like_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                "image/svg+xml")

    def test_looks_like_image_rejects_html_and_empty(self):
        from memanga.gui.workers import looks_like_image
        assert not looks_like_image(b"<!DOCTYPE html><html>blocked",
                                    "text/html; charset=UTF-8")
        assert not looks_like_image(b"")

    def _run_fetch(self, worker, event_bus, monkeypatch, body, ctype):
        """Drive fetch_cover against a faked requests.get; return the
        (recording cache, captured request headers, error events)."""
        import time
        import requests

        captured = {}

        class _Resp:
            content = body
            headers = {"Content-Type": ctype}

            def raise_for_status(self):
                pass

        def _fake_get(url, timeout=None, headers=None):
            captured.update(headers or {})
            return _Resp()

        monkeypatch.setattr(requests, "get", _fake_get)

        errors = []
        event_bus.subscribe(
            "cover_loaded",
            lambda d: errors.append(d) if d.get("error") else None)

        cache = _RecordingCache()
        worker.fetch_cover(self._CDN_URL, cache=cache)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not (cache.saved or cache.failed):
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()
        return cache, captured, errors

    def test_image_response_saved_with_referer(self, worker, event_bus,
                                               monkeypatch):
        cache, captured, errors = self._run_fetch(
            worker, event_bus, monkeypatch,
            self._WEBP_BYTES, "image/webp")
        assert captured.get("Referer") == "https://mangapill.com/"
        assert cache.saved == {self._CDN_URL: self._WEBP_BYTES}
        assert cache.failed == []
        assert errors == []

    def test_html_block_page_marks_failed(self, worker, event_bus,
                                          monkeypatch):
        # 200 + HTML must not reach the disk cache — a cached non-image
        # is never refetched and leaves the cover permanently blank.
        cache, _captured, errors = self._run_fetch(
            worker, event_bus, monkeypatch,
            b"<!DOCTYPE html><html>blocked</html>",
            "text/html; charset=UTF-8")
        assert cache.saved == {}
        assert cache.failed == [self._CDN_URL]
        assert errors and errors[0]["url"] == self._CDN_URL


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

    def test_correlated_check_tags_progress(self, worker, event_bus, state,
                                            monkeypatch):
        import time
        import memanga.downloader as downloader

        def _fake_check(_manga, _state, return_all=False):
            return ([], []) if return_all else []

        monkeypatch.setattr(downloader, "check_for_updates", _fake_check)

        progress = []
        done = []
        event_bus.subscribe("check_progress", lambda d: progress.append(d))
        event_bus.subscribe("check_complete", lambda d: done.append(d))

        worker.check_updates([
            {"title": "Correlated one", "status": "reading",
             "source": "mock.test", "url": "u"},
        ], state, config=None, force=True, request_id="Correlated one:1")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not done:
            event_bus.poll()
            time.sleep(0.02)
        event_bus.poll()

        assert progress
        assert progress[0]["request_id"] == "Correlated one:1"
        assert done[0]["request_id"] == "Correlated one:1"


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


class TestSharedChapterPipeline:
    """Issue #295: GUI downloads run through the same chapter pipeline as
    `memanga check` and `failed retry`. The pipeline writes the records
    and does the delivery; the worker turns its hooks and outcome into
    the events the pages listen to."""

    _MANGA = {"title": "Vinland Saga", "source": "primary.test",
              "url": "https://primary.test/vs"}
    _KINDLE = {
        "kindle_email": "reader@example.com",
        "sender_email": "sender@example.com",
        "app_password": "secret",
    }

    def _chapter(self):
        from memanga.downloader import ChapterWithSource
        from memanga.scrapers.base import Chapter
        return ChapterWithSource(
            Chapter(number="71", url="https://primary.test/c/71"),
            "primary.test", "https://primary.test/vs")

    def _run(self, worker, event_bus, state, monkeypatch, fake_dl,
             fake_send=None, output_format="pdf", **kwargs):
        """Queue one chapter and collect every event it publishes."""
        import time
        import memanga.downloader as dl
        import memanga.emailer as emailer

        monkeypatch.setattr(dl, "download_chapter", fake_dl)
        monkeypatch.setattr(dl, "_find_chapter_on_backup",
                            lambda manga, num, state=None: None)
        if fake_send is not None:
            monkeypatch.setattr(emailer, "send_to_kindle", fake_send)

        events = []
        for name in ("download_started", "download_progress",
                     "download_complete", "download_error",
                     "download_cancelled", "kindle_sent", "kindle_error",
                     "kindle_skipped"):
            event_bus.subscribe(name, lambda d, n=name: events.append((n, d)))

        worker.download_chapter(self._MANGA, self._chapter(),
                                "/tmp/out", output_format, state, **kwargs)

        terminal = {"download_complete", "download_error", "download_cancelled"}
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            event_bus.poll()
            if any(n in terminal for n, _ in events):
                break
            time.sleep(0.02)
        event_bus.poll()
        return events

    @staticmethod
    def _names(events):
        return [n for n, _ in events]

    def test_complete_records_state_before_event(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        state.add_failed_chapter("Vinland Saga", "71", "primary.test", "boom")
        seen = {}

        def fake_dl(manga, chapter, output_dir, output_format, **kwargs):
            seen.update(kwargs)
            kwargs["progress_callback"](1, 2)
            return pdf

        events = self._run(worker, event_bus, state, monkeypatch, fake_dl,
                           naming_template="{title} {chapter}")

        assert self._names(events) == [
            "download_started", "download_progress", "download_complete"]
        payload = events[-1][1]
        assert payload["path"] == str(pdf)
        assert payload["source"] == "primary.test"
        assert payload["from_backup"] is False
        assert "partial" not in payload
        assert events[1][1] == {"task_id": "Vinland Saga:71",
                                "current": 1, "total": 2}
        # GUI-only inputs reach the downloader through the pipeline.
        assert seen["naming_template"] == "{title} {chapter}"
        assert seen["cancel_event"] is not None
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        assert state.get_failed_chapters("Vinland Saga") == {}

    def test_kindle_send_then_delete_after_send(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        sent = []

        def fake_send(**kwargs):
            sent.append(kwargs)
            assert pdf.exists()

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf, fake_send,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_sent", "download_complete"]
        # Issue #338: one event says it was sent and the copy deleted.
        assert self._names(events).count("kindle_sent") == 1
        assert events[-2][1] == {"task_id": "Vinland Saga:71", "path": str(pdf),
                                 "title": "Vinland Saga", "chapter": "71",
                                 "local_copy": "deleted"}
        assert "kindle_skipped" not in self._names(events)
        assert sent[0]["pdf_path"] == pdf
        assert sent[0]["app_password"] == "secret"
        assert not pdf.exists()
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, True)

    def test_kindle_send_without_delete_keeps_file(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf, lambda **kw: None,
            kindle_cfg=dict(self._KINDLE))

        assert self._names(events)[-2:] == ["kindle_sent", "download_complete"]
        # No deletion was asked for, so the event says nothing about it.
        assert events[-2][1] == {"task_id": "Vinland Saga:71", "path": str(pdf),
                                 "title": "Vinland Saga", "chapter": "71"}
        assert pdf.exists()
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, False)

    def test_kindle_send_with_failed_delete_reports_kept_copy(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        # Issue #338: sent, but the local copy could not be deleted. The
        # event says so, with the reason, instead of claiming a deletion.
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")

        real_unlink = type(pdf).unlink

        def refuse(self, *args, **kwargs):
            if self == pdf:
                raise PermissionError("in use")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(type(pdf), "unlink", refuse)
        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf, lambda **kw: None,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_sent", "download_complete"]
        assert self._names(events).count("kindle_sent") == 1
        assert events[-2][1] == {"task_id": "Vinland Saga:71", "path": str(pdf),
                                 "title": "Vinland Saga", "chapter": "71",
                                 "local_copy": "kept",
                                 "delete_error": "in use"}
        assert "kindle_error" not in self._names(events)
        assert pdf.exists()
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, False)

    @pytest.mark.parametrize("fmt", ["jpg", "png", "webp"])
    def test_image_folder_skips_kindle_with_event(
            self, worker, event_bus, state, monkeypatch, tmp_path, fmt):
        # Issue #340: image formats save a folder of pages. Like the CLI,
        # the GUI skips Kindle delivery and says so, instead of staying
        # silent; the folder and the chapter record are kept.
        folder = tmp_path / "Vinland Saga" / "Chapter 71"
        folder.mkdir(parents=True)
        (folder / f"001.{fmt}").write_bytes(b"img")
        sent = []

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: folder,
            lambda **kw: sent.append(kw),
            output_format=fmt,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_skipped", "download_complete"]
        assert events[-2][1] == {
            "task_id": "Vinland Saga:71", "title": "Vinland Saga",
            "chapter": "71", "path": str(folder),
            "reason": "Image folders can't be sent to Kindle; "
                      "only PDF and EPUB can.",
        }
        assert "kindle_sent" not in self._names(events)
        assert "kindle_error" not in self._names(events)
        assert sent == []
        assert (folder / f"001.{fmt}").exists()
        assert state.is_chapter_downloaded("Vinland Saga", "71")

    @pytest.mark.parametrize("fmt", ["cbz", "zip"])
    def test_archive_skips_kindle_with_event(
            self, worker, event_bus, state, monkeypatch, tmp_path, fmt):
        # Issue #362: Kindle rejects CBZ and ZIP. The GUI skips them like
        # image folders, says why, and keeps the file and the chapter.
        archive = tmp_path / f"Vinland Saga - Chapter 71.{fmt}"
        archive.write_bytes(b"PK")
        sent = []

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: archive,
            lambda **kw: sent.append(kw),
            output_format=fmt,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_skipped", "download_complete"]
        assert events[-2][1]["reason"] == (
            f"{fmt.upper()} files can't be sent to Kindle; only PDF and EPUB can.")
        assert "kindle_sent" not in self._names(events)
        assert "kindle_error" not in self._names(events)
        assert sent == []
        assert archive.exists()
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        assert state.failures.get_all_undelivered() == {}

    def test_kindle_failure_keeps_file_and_chapter(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        from memanga.emailer import EmailError
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")

        def fake_send(**kwargs):
            raise EmailError("SMTP down")

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf, fake_send,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_error", "download_complete"]
        assert events[-2][1]["error"] == "SMTP down"
        assert (events[-2][1]["title"], events[-2][1]["chapter"]) == (
            "Vinland Saga", "71")
        assert pdf.exists()
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        # Issue #360: kept for a later send.
        record = state.failures.get_undelivered("Vinland Saga")["71"]
        assert record["path"] == str(pdf)

    def _resend(self, worker, event_bus, state, monkeypatch, fake_send,
                manga=None, **kwargs):
        """Send the recorded chapter again; collect events until done."""
        import time
        import memanga.emailer as emailer

        monkeypatch.setattr(emailer, "send_to_kindle", fake_send)
        events = []
        for name in ("kindle_sent", "kindle_error", "kindle_resend_done"):
            event_bus.subscribe(name, lambda d, n=name: events.append((n, d)))

        worker.send_pending(manga or self._MANGA, "71", state,
                            dict(self._KINDLE), **kwargs)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            event_bus.poll()
            if any(n == "kindle_resend_done" for n, _ in events):
                break
            time.sleep(0.02)
        return events

    def test_send_pending_sends_deletes_and_clears_record(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        state.add_downloaded_chapter("Vinland Saga", "71")
        state.add_download_history("Vinland Saga", "71", "pdf", str(pdf), 0.1)
        state.failures.add_undelivered("Vinland Saga", "71", str(pdf), "SMTP down")
        sent = []

        def fake_send(**kwargs):
            assert kwargs["pdf_path"].exists()
            sent.append(kwargs)

        events = self._resend(worker, event_bus, state, monkeypatch, fake_send,
                              delete_after_send=True)

        assert self._names(events) == ["kindle_sent", "kindle_resend_done"]
        assert events[0][1]["local_copy"] == "deleted"
        assert events[-1][1]["sent"] is True
        assert sent[0]["pdf_path"] == pdf
        assert sent[0]["app_password"] == "secret"
        assert not pdf.exists()
        assert state.failures.get_undelivered("Vinland Saga") == {}
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        # Issue #338: History shows the chapter as sent and deleted.
        history = state.get_download_history()
        assert len(history) == 1
        assert (history[0]["kindle_sent"],
                history[0]["deleted_after_send"]) == (True, True)

    def test_send_pending_without_delete_marks_history_sent(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        state.add_downloaded_chapter("Vinland Saga", "71")
        state.add_download_history("Vinland Saga", "71", "pdf", str(pdf), 0.1)
        state.failures.add_undelivered("Vinland Saga", "71", str(pdf), "SMTP down")

        events = self._resend(worker, event_bus, state, monkeypatch,
                              lambda **kw: None)

        assert self._names(events) == ["kindle_sent", "kindle_resend_done"]
        assert "local_copy" not in events[0][1]
        assert pdf.exists()
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, False)

    def test_send_pending_honors_kindle_opt_out(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        """#341: the shared resend step never emails a manga that opted
        out, even when handed Kindle settings."""
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        state.failures.add_undelivered("Vinland Saga", "71", str(pdf), "SMTP down")
        before = state.failures.get_undelivered("Vinland Saga")
        sent = []

        events = self._resend(worker, event_bus, state, monkeypatch,
                              lambda **kw: sent.append(kw),
                              manga={**self._MANGA, "send_to_kindle": False},
                              delete_after_send=True)

        assert self._names(events) == ["kindle_resend_done"]
        assert events[-1][1]["sent"] is False
        assert sent == []
        assert pdf.exists()
        assert state.failures.get_undelivered("Vinland Saga") == before

    def test_send_pending_failure_keeps_record_and_file(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        from memanga.emailer import EmailError
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        state.failures.add_undelivered("Vinland Saga", "71", str(pdf), "SMTP down")

        def fake_send(**kwargs):
            raise EmailError("Mailbox full")

        events = self._resend(worker, event_bus, state, monkeypatch, fake_send,
                              delete_after_send=True)

        assert self._names(events) == ["kindle_error", "kindle_resend_done"]
        assert events[0][1]["error"] == "Mailbox full"
        assert events[-1][1] == {"task_id": "Vinland Saga:71",
                                 "title": "Vinland Saga", "chapter": "71",
                                 "sent": False}
        assert pdf.exists()
        record = state.failures.get_undelivered("Vinland Saga")["71"]
        assert (record["error"], record["attempts"]) == ("Mailbox full", 2)

    def test_kindle_preparation_error_still_completes(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        # Not an EmailError (e.g. no temp folder for splitting the PDF):
        # still a failed delivery, never a failed chapter.
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")

        def fake_send(**kwargs):
            raise OSError("No space left on device")

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf, fake_send,
            kindle_cfg=dict(self._KINDLE), delete_after_send=True)

        assert self._names(events)[-2:] == ["kindle_error", "download_complete"]
        assert events[-2][1]["error"] == "No space left on device"
        assert "download_error" not in self._names(events)
        assert pdf.exists()
        assert state.is_chapter_downloaded("Vinland Saga", "71")
        assert state.get_failed_chapters("Vinland Saga") == {}

    def test_no_kindle_cfg_never_sends_or_deletes(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")
        sent = []

        events = self._run(
            worker, event_bus, state, monkeypatch,
            lambda manga, chapter, *a, **k: pdf,
            lambda **kw: sent.append(kw),
            delete_after_send=True)

        assert self._names(events)[-1] == "download_complete"
        assert sent == []
        assert pdf.exists()

    def test_partial_writes_one_record_and_one_warning(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        pdf = tmp_path / "ch71.pdf"
        pdf.write_bytes(b"%PDF")

        def fake_dl(manga, chapter, output_dir, output_format, **kwargs):
            kwargs["on_partial"]([3], 30)
            return pdf

        events = self._run(worker, event_bus, state, monkeypatch, fake_dl,
                           allow_partial=True, partial_threshold=10)

        assert events[-1][0] == "download_complete"
        assert events[-1][1]["partial"] == {"failed_pages": [3], "total": 30}
        assert state.get_partial_chapter("Vinland Saga", "71")["failed_pages"] == [3]
        warnings = [n for n in state.get("notifications", [])
                    if "partial" in n["message"]]
        assert len(warnings) == 1

    def test_failure_records_and_reports_once(
            self, worker, event_bus, state, monkeypatch):
        from memanga.downloader import DownloaderError

        def fake_dl(manga, chapter, output_dir, output_format, **kwargs):
            raise DownloaderError("HTTP 503", failed_pages=[2], total_pages=9)

        events = self._run(worker, event_bus, state, monkeypatch, fake_dl)

        assert self._names(events) == ["download_started", "download_error"]
        assert events[-1][1] == {"task_id": "Vinland Saga:71",
                                 "error": "HTTP 503",
                                 "title": "Vinland Saga", "chapter": "71"}
        record = state.get_failed_chapters("Vinland Saga")["71"]
        assert (record["source"], record["error"]) == ("primary.test", "HTTP 503")
        assert record["failed_pages"] == [2]
        assert not state.is_chapter_downloaded("Vinland Saga", "71")

    def test_cancel_reports_cancelled_without_records(
            self, worker, event_bus, state, monkeypatch):
        def fake_dl(manga, chapter, output_dir, output_format, **kwargs):
            raise InterruptedError("Download cancelled")

        events = self._run(worker, event_bus, state, monkeypatch, fake_dl)

        assert self._names(events) == ["download_started", "download_cancelled"]
        assert state.get_failed_chapters("Vinland Saga") == {}
        assert not state.is_chapter_downloaded("Vinland Saga", "71")

    def test_progress_after_cancel_flag_stops_download(
            self, worker, event_bus, state, monkeypatch, tmp_path):
        # The progress hook raises once the task's cancel flag is set,
        # as the worker's progress callback always has.
        def fake_dl(manga, chapter, output_dir, output_format, **kwargs):
            worker.cancel_download("Vinland Saga:71")
            kwargs["progress_callback"](1, 2)
            return tmp_path / "never.pdf"

        events = self._run(worker, event_bus, state, monkeypatch, fake_dl)

        assert self._names(events)[-1] == "download_cancelled"
        assert not state.is_chapter_downloaded("Vinland Saga", "71")
