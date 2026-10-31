"""Tests for BaseScraper helpers (Chapter, Manga, retry, etc.).

These cover the bits of memanga.scrapers.base that aren't tied to
any one site — the dataclasses, rate-limit logic, get_cover_url
fallback, get_new_chapters filtering, and the looks_like_image body
sniffer shared with the GUI cover fetch.
"""

from __future__ import annotations

import io
import time
import pytest
import requests
from PIL import Image

from datetime import datetime, timezone

from memanga.scrapers.base import (
    BaseScraper, Chapter, Manga, MAX_RETRY_AFTER, _retry, is_image_file,
    is_retryable_request_error, looks_like_image, parse_retry_after,
)



def _image_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 40, 40)).save(buf, fmt)
    return buf.getvalue()


_JPEG = _image_bytes("JPEG")
_PNG = _image_bytes("PNG")


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

    def test_retry_if_false_raises_without_retrying(self):
        calls = []
        def fn():
            calls.append(1)
            raise OSError("permanent")
        with pytest.raises(OSError):
            _retry(fn, max_attempts=3, base_delay=0.001, retry_if=lambda e: False)
        assert len(calls) == 1


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


class TestRetryableRequestError:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_statuses(self, status):
        assert is_retryable_request_error(_http_error(status))

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
    def test_permanent_statuses(self, status):
        assert not is_retryable_request_error(_http_error(status))

    @pytest.mark.parametrize("error", [
        requests.ConnectionError("refused"),
        requests.Timeout("slow"),
        requests.exceptions.ChunkedEncodingError("cut off"),
    ])
    def test_transport_errors_are_retryable(self, error):
        assert is_retryable_request_error(error)

    def test_invalid_url_is_not_retryable(self):
        assert not is_retryable_request_error(requests.exceptions.InvalidURL("bad"))

    def test_mangaball_still_retries_an_expired_csrf_token(self):
        from memanga.scrapers.mangaball import _is_retryable_post_error
        assert _is_retryable_post_error(_http_error(419))
        assert not _is_retryable_post_error(_http_error(404))


# ──────────────────────────────────────────────────────────────────────
# HTTP 429 Retry-After
# ──────────────────────────────────────────────────────────────────────


_NOW = datetime(2015, 10, 21, 7, 28, 0, tzinfo=timezone.utc)


class TestParseRetryAfter:
    @pytest.mark.parametrize("value,expected", [
        ("0", 0.0),
        ("120", 120.0),
        ("  7 ", 7.0),
    ])
    def test_delay_seconds(self, value, expected):
        assert parse_retry_after(value, now=_NOW) == expected

    @pytest.mark.parametrize("value", [
        "Wed, 21 Oct 2015 07:28:30 GMT",      # IMF-fixdate
        "Wednesday, 21-Oct-15 07:28:30 GMT",  # obsolete RFC 850
        "Wed Oct 21 07:28:30 2015",           # obsolete asctime (no zone = UTC)
    ])
    def test_http_date_forms(self, value):
        assert parse_retry_after(value, now=_NOW) == 30.0

    def test_http_date_in_the_past_means_no_wait(self):
        assert parse_retry_after("Wed, 21 Oct 2015 07:00:00 GMT", now=_NOW) == 0.0

    def test_http_date_defaults_to_local_utc_clock(self):
        wait = parse_retry_after("Fri, 01 Jan 2100 00:00:00 GMT")
        assert wait is not None and wait > MAX_RETRY_AFTER

    @pytest.mark.parametrize("value", [
        None, "", "   ", "-5", "1.5", "+3", "1e3", "\u0663", "soon",
        "5, 10",  # two Retry-After headers folded into one value
        "Wed, 32 Oct 2015 07:28:30 GMT",
    ])
    def test_missing_or_malformed_is_none(self, value):
        assert parse_retry_after(value, now=_NOW) is None


def _rate_limited(retry_after=None, date=None, url="https://cdn.example.test/ch/1.jpg?token=secret"):
    response = requests.Response()
    response.status_code = 429
    response.url = url
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    if date is not None:
        response.headers["Date"] = date
    return requests.HTTPError("429 Client Error", response=response)


class TestRetryHonorsRetryAfter:
    @pytest.fixture
    def sleeps(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("memanga.scrapers.base.time.sleep", sleeps.append)
        return sleeps

    def _flaky(self, *errors):
        """Callable raising each error in turn, then returning "ok"."""
        pending = list(errors)
        calls = []
        def fn():
            calls.append(1)
            if pending:
                raise pending.pop(0)
            return "ok"
        return fn, calls

    def test_waits_for_retry_after_seconds(self, sleeps):
        fn, calls = self._flaky(_rate_limited("5"))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [5.0]
        assert len(calls) == 2

    def test_waits_until_http_date_measured_from_server_date(self, sleeps):
        # Local clock is irrelevant: the wait is Retry-After minus Date.
        fn, _ = self._flaky(_rate_limited(
            "Wed, 21 Oct 2015 07:28:12 GMT", date="Wed, 21 Oct 2015 07:28:00 GMT",
        ))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [12.0]

    def test_backoff_is_a_floor_for_short_retry_after(self, sleeps):
        fn, _ = self._flaky(_rate_limited("0"), _rate_limited("1"))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [1.0, 2.0]

    def test_wait_at_the_cap_is_honored(self, sleeps):
        fn, _ = self._flaky(_rate_limited(str(int(MAX_RETRY_AFTER))))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [MAX_RETRY_AFTER]

    @pytest.mark.parametrize("retry_after", [
        str(int(MAX_RETRY_AFTER) + 1),
        "Fri, 01 Jan 2100 00:00:00 GMT",
    ])
    def test_wait_over_the_cap_raises_without_retrying(self, sleeps, retry_after):
        fn, calls = self._flaky(_rate_limited(retry_after))
        with pytest.raises(requests.HTTPError):
            _retry(fn, max_attempts=3, base_delay=1.0)
        assert sleeps == []
        assert len(calls) == 1

    @pytest.mark.parametrize("retry_after", [None, "soon", "-1"])
    def test_missing_or_malformed_retry_after_keeps_backoff(self, sleeps, retry_after):
        fn, calls = self._flaky(_rate_limited(retry_after), _rate_limited(retry_after))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [1.0, 2.0]
        assert len(calls) == 3

    def test_persistent_429_raises_after_max_attempts(self, sleeps):
        fn, calls = self._flaky(*[_rate_limited("2") for _ in range(3)])
        with pytest.raises(requests.HTTPError):
            _retry(fn, max_attempts=3, base_delay=1.0)
        assert sleeps == [2.0, 2.0]
        assert len(calls) == 3

    def test_other_errors_ignore_retry_after(self, sleeps):
        error = _rate_limited("30")
        error.response.status_code = 503
        fn, _ = self._flaky(error, IOError("reset"))
        assert _retry(fn, max_attempts=3, base_delay=1.0) == "ok"
        assert sleeps == [1.0, 2.0]

    def test_logs_rate_limiting_with_host_only(self, sleeps, caplog):
        fn, _ = self._flaky(_rate_limited("5"))
        with caplog.at_level("INFO", logger="memanga.scrapers.base"):
            _retry(fn, max_attempts=3, base_delay=1.0)
        messages = [r.getMessage() for r in caplog.records]
        assert any("cdn.example.test" in m and "429" in m and "5.0s" in m for m in messages)
        assert not any("token" in m or "/ch/" in m for m in messages)

    def test_logs_a_warning_when_the_wait_is_too_long(self, sleeps, caplog):
        fn, _ = self._flaky(_rate_limited("3600"))
        with caplog.at_level("INFO", logger="memanga.scrapers.base"):
            with pytest.raises(requests.HTTPError):
                _retry(fn, max_attempts=3, base_delay=1.0)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "3600s" in warnings[0].getMessage()
        assert "token" not in warnings[0].getMessage()

    def test_request_honors_retry_after(self, monkeypatch, sleeps):
        s = _DummyScraper()
        s._rate_limit = 0
        responses = []
        def fake_get(url, **kw):
            response = requests.Response()
            response.url = url
            response._content = b"ok"
            if not responses:
                response.status_code = 429
                response.headers["Retry-After"] = "4"
            else:
                response.status_code = 200
            responses.append(response)
            return response
        monkeypatch.setattr(s.session, "get", fake_get)

        assert s._request("https://dummy.test/page").status_code == 200
        assert len(responses) == 2
        assert sleeps == [4.0]


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


class TestRequestRetries:
    def _scraper(self, monkeypatch, statuses):
        s = _DummyScraper()
        s._rate_limit = 0
        monkeypatch.setattr("memanga.scrapers.base.time.sleep", lambda _s: None)
        calls = []
        def fake_get(url, **kw):
            calls.append(url)
            response = requests.Response()
            response.status_code = statuses[min(len(calls), len(statuses)) - 1]
            response._content = b"ok"
            return response
        monkeypatch.setattr(s.session, "get", fake_get)
        return s, calls

    @pytest.mark.parametrize("status", [403, 404, 410])
    def test_permanent_http_error_is_not_retried(self, monkeypatch, status):
        s, calls = self._scraper(monkeypatch, [status])
        with pytest.raises(requests.HTTPError):
            s._request("https://x/gone")
        assert len(calls) == 1

    def test_server_error_is_retried(self, monkeypatch):
        s, calls = self._scraper(monkeypatch, [503, 200])
        assert s._request("https://x/busy").text == "ok"
        assert len(calls) == 2


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
                             lambda *a, **k: fake_response(content=_JPEG))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").read_bytes() == _JPEG

    @pytest.mark.parametrize("body,ctype", [
        (b"<!DOCTYPE html><html><body>Just a moment...</body></html>",
         "text/html; charset=UTF-8"),
        # The header is not trusted: markup labeled as an image is still markup.
        (b"<html>hotlink blocked</html>", "image/jpeg"),
        (b"", "image/jpeg"),
        (b"", ""),
    ])
    def test_non_image_body_is_a_failed_page(self, monkeypatch, tmp_path,
                                             fake_response, body, ctype):
        # Issue #229: a 200 block page or empty body must not be saved
        # as page bytes and reported as success.
        s = _DummyScraper()
        monkeypatch.setattr(s, "_request", lambda *a, **k: fake_response(
            content=body, headers={"Content-Type": ctype}))
        path = tmp_path / "page_007.jpg"
        assert s.download_image("https://x", path) is False
        assert not path.exists()

    def test_image_without_image_content_type_is_kept(self, monkeypatch, tmp_path,
                                                      fake_response):
        # TIFF has no sniffed magic number and some CDNs label images
        # application/octet-stream; Pillow still recognises the bytes.
        s = _DummyScraper()
        tiff = _image_bytes("TIFF")
        monkeypatch.setattr(s, "_request", lambda *a, **k: fake_response(
            content=tiff, headers={"Content-Type": "application/octet-stream"}))
        path = tmp_path / "p.tif"
        assert s.download_image("https://x", path) is True
        assert path.read_bytes() == tiff

    def test_non_image_body_removes_stale_file(self, monkeypatch, tmp_path,
                                               fake_response):
        s = _DummyScraper()
        path = tmp_path / "page_007.jpg"
        path.write_bytes(_JPEG)
        monkeypatch.setattr(s, "_request", lambda *a, **k: fake_response(
            content=b"<html>hotlink blocked</html>"))
        assert s.download_image("https://x", path) is False
        assert not path.exists()

    def test_failure_returns_false(self, monkeypatch, tmp_path):
        s = _DummyScraper()
        def boom(*a, **k):
            raise IOError()
        monkeypatch.setattr(s, "_request", boom)
        assert s.download_image("https://x", tmp_path / "p.jpg") is False


# ──────────────────────────────────────────────────────────────────────
# looks_like_image — shared body sniffer (issue #174)
# ──────────────────────────────────────────────────────────────────────


class TestLooksLikeImage:
    """Canonical tests for the helper that keeps HTML block pages from
    being written where image bytes belong. memanga.gui.workers re-exports
    it for the cover fetch; this is where its behaviour is pinned down.
    """

    @pytest.mark.parametrize("name,body", [
        ("jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 16),
        ("png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16),
        ("gif87a", b"GIF87a" + b"\x00" * 16),
        ("gif89a", b"GIF89a" + b"\x00" * 16),
        ("bmp", b"BM" + b"\x00" * 16),
        ("webp", b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16),
        ("avif", b"\x00\x00\x00 ftypavifmif1" + b"\x00" * 8),
        ("heic", b"\x00\x00\x00 ftypheicmif1" + b"\x00" * 8),
    ])
    def test_magic_bytes_pass_without_a_content_type(self, name, body):
        # No header at all: the bytes alone have to carry the decision,
        # since some CDNs serve images as application/octet-stream.
        assert looks_like_image(body) is True

    def test_content_type_rescues_a_format_we_do_not_sniff(self):
        # SVG is XML — no magic number to match, so only the header can
        # tell it apart from a block page.
        svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
        assert looks_like_image(svg, "image/svg+xml") is True

    def test_content_type_parameters_and_case_are_ignored(self):
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        assert looks_like_image(svg, "Image/SVG+XML; charset=utf-8") is True

    @pytest.mark.parametrize("body,ctype", [
        (b"<!DOCTYPE html><html><body>Forbidden</body></html>",
         "text/html; charset=UTF-8"),
        (b"<html>blocked</html>", ""),
        (b"", "image/jpeg"),          # empty body is never an image
        (b"", ""),
        (b"RIFF\x24\x00\x00\x00AVI LIST", ""),   # RIFF, but not WEBP
        (b"\x00\x00\x00 ftypmp42", ""),           # ISO-BMFF, but video
    ])
    def test_rejects_non_images(self, body, ctype):
        assert looks_like_image(body, ctype) is False


# ──────────────────────────────────────────────────────────────────────
# is_image_file — saved-page check used by the downloader (issue #229)
# ──────────────────────────────────────────────────────────────────────


class TestIsImageFile:
    @pytest.mark.parametrize("fmt", ["JPEG", "PNG", "GIF", "BMP", "TIFF"])
    def test_decodable_images_pass(self, tmp_path, fmt):
        p = tmp_path / "page"
        p.write_bytes(_image_bytes(fmt))
        assert is_image_file(p) is True

    def test_webp_passes(self, tmp_path):
        from PIL import features
        if not features.check("webp"):
            pytest.skip("Pillow built without WebP")
        p = tmp_path / "p.webp"
        p.write_bytes(_image_bytes("WEBP"))
        assert is_image_file(p) is True

    @pytest.mark.parametrize("body", [
        b"",
        b"<!DOCTYPE html><html><body>Forbidden</body></html>",
        b"<html>blocked</html>",
    ])
    def test_rejects_non_image_bytes(self, tmp_path, body):
        p = tmp_path / "p.jpg"
        p.write_bytes(body)
        assert is_image_file(p) is False

    @pytest.mark.parametrize("body", [
        b"\xff\xd8\xff\xe0" + b"\x00" * 16,   # JPEG signature, no image
        _JPEG[: len(_JPEG) // 2],              # body cut short
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,  # PNG signature, no image
        _PNG[:-20],                            # IDAT/IEND cut off
    ], ids=["jpeg-signature-only", "jpeg-truncated",
            "png-signature-only", "png-truncated"])
    def test_rejects_corrupt_bytes_behind_a_valid_signature(self, tmp_path, body):
        # Issue #229: a signature alone is not an image; CBZ/ZIP would
        # store these bytes verbatim as a page nobody can open.
        p = tmp_path / "p.img"
        p.write_bytes(body)
        assert is_image_file(p) is False

    _AVIF_SIGNATURE = b"\x00\x00\x00 ftypavifmif1" + b"\x00" * 8

    def test_format_without_a_decoder_is_judged_by_signature(
            self, tmp_path, monkeypatch):
        # A Pillow build without AVIF support cannot decode the page, so
        # its signature is all there is to go on.
        from PIL import features
        try:
            from PIL import AvifImagePlugin
            monkeypatch.setattr(AvifImagePlugin, "SUPPORTED", False)
        except ImportError:
            pass  # older Pillow: no AVIF plugin at all
        real = features.check_module
        monkeypatch.setattr(features, "check_module",
                            lambda name: name != "avif" and real(name))
        p = tmp_path / "p.avif"
        p.write_bytes(self._AVIF_SIGNATURE)
        assert is_image_file(p) is True

    def test_format_with_a_decoder_must_decode(self, tmp_path):
        from PIL import features
        if "avif" not in features.modules or not features.check_module("avif"):
            pytest.skip("Pillow built without AVIF")
        p = tmp_path / "p.avif"
        p.write_bytes(self._AVIF_SIGNATURE)
        assert is_image_file(p) is False

    def test_missing_file(self, tmp_path):
        assert is_image_file(tmp_path / "nope.jpg") is False


# ──────────────────────────────────────────────────────────────────────
# Page pixel limit (issue #386)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
class TestPagePixelLimit:
    @pytest.mark.parametrize("size", [(2048, 65536), (100_000, 100_000)],
                             ids=["just-over", "far-over"])
    def test_over_limit_page_raises_instead_of_failing_silently(
            self, tmp_path, declared_png, size):
        from memanga.image_limits import ImageTooLargeError
        p = tmp_path / "page.png"
        p.write_bytes(declared_png(*size))
        with pytest.raises(ImageTooLargeError):
            is_image_file(p)

    def test_over_limit_page_still_identifies_as_an_image(self, declared_png):
        # Its download is kept so the page check can say why it's refused.
        from memanga.scrapers.base import _identifies_as_image
        assert _identifies_as_image(declared_png(100_000, 100_000)) is True

    def test_page_at_the_limit_is_decoded_as_before(self, tmp_path,
                                                    monkeypatch):
        from memanga import image_limits
        monkeypatch.setattr(image_limits, "MAX_PAGE_PIXELS", 32 * 32)
        p = tmp_path / "page"
        p.write_bytes(_image_bytes("PNG"))
        assert is_image_file(p) is True
