"""Unit tests for MangagoScraper's region-block-resilient request path.

mangago.me is DNS-poisoned / SNI-filtered in some regions (issue #151),
so from a blocked network every connect() stalls. These tests prove a
direct MangagoScraper call fails fast there instead of hanging through
BaseScraper's 30s x 3-retry budget, while transient post-connect errors
still get retried. All network is faked; nothing leaves the process.
"""

from __future__ import annotations

import time

import pytest
import requests

from memanga.scrapers.mangago import MangagoScraper


@pytest.fixture
def scraper():
    return MangagoScraper()


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Record and neutralise every sleep so retries don't slow the suite."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


class _FakeGet:
    """session.get stand-in: counts calls, records the timeout kwarg,
    and raises the supplied exception on every call."""

    def __init__(self, raise_exc):
        self.calls = 0
        self.timeouts: list = []
        self._raise = raise_exc

    def __call__(self, url, **kwargs):
        self.calls += 1
        self.timeouts.append(kwargs.get("timeout"))
        raise self._raise


# -- connection failures must fail fast (no BaseScraper 3x retry) --


class TestRegionBlockFailsFast:
    # Every public read path routes through _request, so all three must
    # fail fast, not just search().
    OPS = {
        "search": lambda s: s.search("one piece"),
        "get_chapters": lambda s: s.get_chapters(
            "https://www.mangago.me/read-manga/one_piece/"),
        "get_pages": lambda s: s.get_pages(
            "https://www.mangago.me/read-manga/one_piece/mr/nml_chapter-1/pg-1/"),
    }

    @pytest.mark.parametrize("op", list(OPS.values()), ids=list(OPS))
    @pytest.mark.parametrize("exc", [
        requests.exceptions.ConnectTimeout("connect timed out"),
        requests.exceptions.ConnectionError("Connection reset by peer"),
    ], ids=["connect_timeout", "connection_reset"])
    def test_connection_error_not_retried(self, scraper, monkeypatch,
                                          no_real_sleep, op, exc):
        get = _FakeGet(exc)
        monkeypatch.setattr(scraper.session, "get", get)

        with pytest.raises(requests.exceptions.RequestException):
            op(scraper)

        # BaseScraper would call get() 3 times; the override stops at 1.
        assert get.calls == 1
        # Nothing to back off for, so no exponential-backoff sleep either.
        assert no_real_sleep == []

    def test_bounded_connect_timeout_passed(self, scraper, monkeypatch,
                                            no_real_sleep):
        get = _FakeGet(requests.exceptions.ConnectTimeout("x"))
        monkeypatch.setattr(scraper.session, "get", get)

        with pytest.raises(requests.exceptions.ConnectTimeout):
            scraper.search("one piece")

        assert get.timeouts == [
            (scraper._CONNECT_TIMEOUT, scraper._READ_TIMEOUT)]
        # The connect bound is well under BaseScraper's flat 30s.
        assert scraper._CONNECT_TIMEOUT < 30


# -- transient post-connect errors keep BaseScraper's resilience --


class TestTransientErrorsStillRetry:
    def test_read_timeout_is_retried(self, scraper, monkeypatch, no_real_sleep):
        get = _FakeGet(requests.exceptions.ReadTimeout("slow body"))
        monkeypatch.setattr(scraper.session, "get", get)

        with pytest.raises(requests.exceptions.ReadTimeout):
            scraper.search("one piece")

        # A read hiccup means we did connect, so retry as before: 3 tries.
        assert get.calls == 3

    def test_http_error_is_retried(self, scraper, monkeypatch, no_real_sleep):
        get = _FakeGet(requests.exceptions.HTTPError("503"))
        monkeypatch.setattr(scraper.session, "get", get)

        with pytest.raises(requests.exceptions.HTTPError):
            scraper.search("one piece")

        assert get.calls == 3


# -- download_image bypasses _request but must still bound connect --


class TestDownloadImageBoundedTimeout:
    def test_uses_bounded_timeout_and_swallows_block(self, scraper,
                                                     monkeypatch, tmp_path):
        seen = {}

        def fake_get(url, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            raise requests.exceptions.ConnectTimeout("blocked")

        monkeypatch.setattr(scraper.session, "get", fake_get)

        ok = scraper.download_image(
            "https://i.mangapicgallery.com/x.jpg", tmp_path / "x.jpg")

        assert ok is False  # download_image swallows and reports failure
        assert seen["timeout"] == (
            scraper._CONNECT_TIMEOUT, scraper._READ_TIMEOUT)
