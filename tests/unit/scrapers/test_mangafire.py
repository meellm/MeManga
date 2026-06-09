"""Unit tests for MangaFire scraper failure handling."""

from __future__ import annotations

import pytest


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class TestMangaFireGetChapters:
    def test_parses_ajax_chapter_list(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "status": 200,
                "result": """
                    <ul>
                      <li data-number="2"><a href="/read/demo.abc/en/chapter-2" title="Chapter 2"></a></li>
                      <li data-number="1"><a href="/read/demo.abc/en/chapter-1" title="Chapter 1"></a></li>
                    </ul>
                """,
            }),
        ])

        chapters = scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        assert [ch.number for ch in chapters] == ["1", "2"]
        assert chapters[0].url == "https://mangafire.to/read/demo.abc/en/chapter-1"

    def test_cloudflare_ajax_error_raises_instead_of_empty_list(self):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "status": 522,
                "title": "Error 522: Connection timed out",
                "error_name": "connection_timeout",
                "retryable": True,
                "retry_after": 120,
                "cloudflare_error": True,
            }),
        ])

        with pytest.raises(MangaFireError) as exc:
            scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        message = str(exc.value)
        assert "status=522" in message
        assert "Connection timed out" in message
        assert "retryable=True" in message
        assert "retry_after=120s" in message

    def test_request_errors_retry_before_failing(self, monkeypatch):
        import requests
        from memanga.scrapers import mangafire as mf

        monkeypatch.setattr(mf.time, "sleep", lambda _seconds: None)

        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            requests.Timeout("temporary timeout"),
            _Response(payload={
                "status": 200,
                "result": '<li data-number="1"><a href="/read/demo.abc/en/chapter-1" title="Chapter 1"></a></li>',
            }),
        ])

        chapters = scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        assert scraper.session.calls == 2
        assert [ch.number for ch in chapters] == ["1"]


class TestVRFBrowserInitAtomicity:
    """Issue #28: a failed firefox.launch() must surface the real error,
    not a masking AttributeError on a half-initialised thread-local.

    The frozen release exe could not launch Firefox; the original
    non-atomic init left `_vrf_thread_local.playwright` set, so the retry
    skipped init and raised `'thread_local' object has no attribute
    'page'` — hiding the actual launch failure and making the bug
    undiagnosable.
    """

    class _FakeFirefox:
        def launch(self, **kwargs):
            raise RuntimeError("Executable doesn't exist: firefox")

    class _FakePlaywright:
        def __init__(self):
            self.firefox = TestVRFBrowserInitAtomicity._FakeFirefox()
            self.stopped = False

        def stop(self):
            self.stopped = True

    class _FakeContextManager:
        def __init__(self, started):
            self._started = started

        def start(self):
            return self._started

    def _patch(self, monkeypatch):
        from memanga.scrapers import mangafire as mf
        # Clear any thread-local state from earlier tests in this thread.
        mf.VRFGenerator().close()
        for attr in ("playwright", "browser", "context", "page"):
            if hasattr(mf._vrf_thread_local, attr):
                delattr(mf._vrf_thread_local, attr)
        started = self._FakePlaywright()
        monkeypatch.setattr(mf, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            mf, "sync_playwright",
            lambda: self._FakeContextManager(started),
        )
        return mf, started

    def test_launch_failure_surfaces_real_error(self, monkeypatch):
        mf, started = self._patch(monkeypatch)
        gen = mf.VRFGenerator()
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()
        # Playwright start was rolled back; no half-initialised state left.
        assert started.stopped is True
        assert not hasattr(mf._vrf_thread_local, "playwright")
        assert not hasattr(mf._vrf_thread_local, "page")

    def test_retry_still_surfaces_real_error_not_attribute_error(self,
                                                                 monkeypatch):
        mf, _ = self._patch(monkeypatch)
        gen = mf.VRFGenerator()
        # First attempt fails…
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()
        # …and so does the retry, with the SAME real error — never an
        # AttributeError about a missing 'page' on the thread-local.
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()
