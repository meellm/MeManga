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
