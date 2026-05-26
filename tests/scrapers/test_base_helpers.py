"""Tests for BaseScraper helpers (Chapter, Manga, retry, etc.).

These cover the bits of memanga.scrapers.base that aren't tied to
any one site — the dataclasses, rate-limit logic, get_cover_url
fallback, and get_new_chapters filtering.
"""

from __future__ import annotations

import time
import pytest

from memanga.scrapers.base import (
    BaseScraper, Chapter, Manga, _retry,
)


# ──────────────────────────────────────────────────────────────────────
# Chapter dataclass + .numeric property
# ──────────────────────────────────────────────────────────────────────


class TestChapterNumeric:
    @pytest.mark.parametrize("raw,expected", [
        ("1", 1.0),
        ("10.5", 10.5),
        ("Chapter 7", 7.0),
        ("vol1 chapter 23.5", 1.0),  # picks the FIRST number
        ("Extra", 0.0),
        ("0", 0.0),
    ])
    def test_extraction(self, raw, expected):
        c = Chapter(number=raw, title="", url="")
        assert c.numeric == expected

    def test_sorts_by_numeric(self):
        cs = [Chapter("10", "", ""), Chapter("2", "", ""), Chapter("1.5", "", "")]
        cs.sort()
        assert [c.number for c in cs] == ["1.5", "2", "10"]


# ──────────────────────────────────────────────────────────────────────
# Manga dataclass
# ──────────────────────────────────────────────────────────────────────


class TestMangaDataclass:
    def test_default_chapters_is_independent_list(self):
        m1 = Manga(title="A", url="u1")
        m2 = Manga(title="B", url="u2")
        m1.chapters.append(Chapter("1", "", ""))
        # Default-factory ensures lists aren't shared
        assert m2.chapters == []

    def test_optional_fields_default_none(self):
        m = Manga(title="X", url="u")
        assert m.cover_url is None
        assert m.description is None


# ──────────────────────────────────────────────────────────────────────
# Retry helper
# ──────────────────────────────────────────────────────────────────────


class TestRetry:
    def test_returns_immediately_on_success(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        assert _retry(fn) == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise IOError("transient")
            return "ok"
        assert _retry(fn, max_attempts=5, base_delay=0.001) == "ok"
        assert len(calls) == 3

    def test_raises_after_max_attempts(self):
        def fn():
            raise IOError("nope")
        with pytest.raises(IOError):
            _retry(fn, max_attempts=2, base_delay=0.001)

    def test_only_retries_specified_exceptions(self):
        def fn():
            raise ValueError("unrelated")
        with pytest.raises(ValueError):
            _retry(fn, max_attempts=3, base_delay=0.001, exceptions=(IOError,))


# ──────────────────────────────────────────────────────────────────────
# Concrete subclass for testing BaseScraper instance behavior
# ──────────────────────────────────────────────────────────────────────


class _DummyScraper(BaseScraper):
    base_url = "https://dummy.test"
    def search(self, query): return []
    def get_chapters(self, url): return []
    def get_pages(self, url): return []


class TestRateLimit:
    def test_enforces_minimum_gap_between_requests(self, monkeypatch, fake_response):
        s = _DummyScraper()
        s._rate_limit = 0.05  # 50ms gap

        calls = []
        def fake_get(url, **kw):
            calls.append(time.monotonic())
            return fake_response(text="x")
        monkeypatch.setattr(s.session, "get", fake_get)

        s._request("https://x/1")
        s._request("https://x/2")
        # Second call must be at least 50ms after the first
        assert calls[1] - calls[0] >= 0.04


class TestGetCoverUrl:
    def test_returns_og_image_when_present(self, monkeypatch):
        s = _DummyScraper()
        html = '<html><head><meta property="og:image" content="https://cdn.x/cover.jpg"></head></html>'
        monkeypatch.setattr(s, "_get_html", lambda *a, **k: html)
        assert s.get_cover_url("https://x/manga") == "https://cdn.x/cover.jpg"

    def test_returns_none_when_no_meta(self, monkeypatch):
        s = _DummyScraper()
        monkeypatch.setattr(s, "_get_html", lambda *a, **k: "<html></html>")
        assert s.get_cover_url("https://x/manga") is None

    def test_returns_none_on_exception(self, monkeypatch):
        s = _DummyScraper()
        def boom(*a, **k):
            raise IOError("fail")
        monkeypatch.setattr(s, "_get_html", boom)
        assert s.get_cover_url("https://x/manga") is None


class TestGetNewChapters:
    def test_filters_only_newer(self, monkeypatch):
        s = _DummyScraper()
        all_chapters = [Chapter("1", "", ""), Chapter("2", "", ""),
                         Chapter("3", "", ""), Chapter("3.5", "", "")]
        monkeypatch.setattr(s, "get_chapters", lambda url: all_chapters)
        new = s.get_new_chapters("https://x", last_chapter=2.0)
        # Only ch 3 and 3.5 are strictly > 2.0
        assert [c.number for c in new] == ["3", "3.5"]

    def test_returns_empty_when_caught_up(self, monkeypatch):
        s = _DummyScraper()
        monkeypatch.setattr(s, "get_chapters",
                             lambda url: [Chapter("1", "", "")])
        assert s.get_new_chapters("https://x", last_chapter=10.0) == []


class TestDownloadImage:
    def test_writes_to_disk_on_success(self, monkeypatch, tmp_path, fake_response):
        s = _DummyScraper()
        monkeypatch.setattr(s, "_request",
                             lambda *a, **k: fake_response(content=b"data"))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").read_bytes() == b"data"

    def test_failure_returns_false(self, monkeypatch, tmp_path):
        s = _DummyScraper()
        def boom(*a, **k):
            raise IOError()
        monkeypatch.setattr(s, "_request", boom)
        assert s.download_image("https://x", tmp_path / "p.jpg") is False
