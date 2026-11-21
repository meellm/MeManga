"""Offline tests for SenMangaScraper (raw.senmanga.com).

Every reply here is a synthetic fixture and no request leaves the test.
Field shapes follow what the site's API serves.
"""

from __future__ import annotations

import io
import logging

import pytest
import requests
from PIL import Image

from memanga.downloader.formats.cbz import _manga_language
from memanga.scrapers import _SCRAPER_PATHS, SCRAPERS, get_scraper, senmanga
from memanga.scrapers.catalog import source_catalog
from memanga.scrapers.senmanga import (
    SenMangaScraper, SenMangaSourceError, chapter_ids, series_slug)
from memanga.search import BROKEN_SEARCH_SOURCES, sweep

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"SenMangaScraper": ("chapters", "pages")}

BASE = "https://raw.senmanga.com"
SERIES_URL = f"{BASE}/manga/one-piece"
CDN = "https://cdn.rawkuma.com"
CHAPTER_ID = "1197.430413"
PREVIOUS_ID = "1196.418124"
CHAPTER_URL = f"{SERIES_URL}/chapter-{CHAPTER_ID}/"
SERIES_API = f"{BASE}/api/manga/one-piece"
READ_API = f"{BASE}/api/read/one-piece/{CHAPTER_ID}"
WHEN = "2026-11-01T15:35:00Z"


def _row(number="1197", url=CHAPTER_ID, title=None, when=WHEN, **changes):
    row = {"dateAgo": "19 days ago", "datetime": when,
           "full_url": f"{SERIES_URL}/chapter-{url}/", "last_update": when, "number": number,
           "slug": number, "title": f"Chapter {number}" if title is None else title, "url": url}
    row.update(changes)
    return row


def _series(rows, **changes):
    data = {"title": "One Piece", "slug": "one-piece", "alt_name": "ワンピース",
            "cover": f"{CDN}/covers/one-piece.jpg", "genre": "Action,Adventure", "type": "Manga",
            "status": None, "description": "x", "chapterList": rows}
    data.update(changes)
    return data


def _page(name):
    return f"{CDN}/o/one-piece-raw/1197/{name}.jpg"


def _read(pages):
    return {"chapter": "1197", "nextChapter": None, "pages": pages, "previousChapter": "1196",
            "series": _series([_row(), _row("1196", PREVIOUS_ID)])}


def _jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


class _Reply:
    def __init__(self, payload=None, status=200, content=b"", bad_json=False):
        self.status_code = status
        self._payload = payload
        self._content = content
        self._bad_json = bad_json
        self.closed = False

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def close(self):
        self.closed = True


@pytest.fixture
def scraper():
    return SenMangaScraper()


@pytest.fixture
def site(monkeypatch, scraper):
    """Serves replies by exact URL and records every request."""
    served, calls = {}, []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        if url not in served:
            raise AssertionError(f"unexpected request {url}")
        reply = served[url]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_request", fake_request)
    return served, calls


def _http_error(status):
    return requests.HTTPError(f"{status} error", response=_Reply(status=status))


# ── URLs ──────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("url", [SERIES_URL, f"{SERIES_URL}/"])
    def test_series_url(self, url):
        assert series_slug(url) == "one-piece"

    @pytest.mark.parametrize("url", [
        "http://raw.senmanga.com/manga/one-piece",
        "https://www.senmanga.com/manga/one-piece",
        "https://senmanga.com/manga/one-piece",
        "https://raw.senmanga.com:8443/manga/one-piece",
        "https://user@raw.senmanga.com/manga/one-piece",
        f"{SERIES_URL}?x=1", f"{SERIES_URL}#x",
        f"{BASE}/one-piece", f"{BASE}/manga/", f"{BASE}/manga/../x", CHAPTER_URL, "", None,
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ValueError):
            series_slug(url)

    @pytest.mark.parametrize("url", [CHAPTER_URL, CHAPTER_URL.rstrip("/")])
    def test_chapter_url(self, url):
        assert chapter_ids(url) == ("one-piece", CHAPTER_ID)

    @pytest.mark.parametrize("url", [
        SERIES_URL, f"{SERIES_URL}/{CHAPTER_ID}", f"{SERIES_URL}/chapter-/",
        f"{SERIES_URL}/chapter-../", f"{BASE}/manga/../chapter-1.1/",
        f"https://cdn.rawkuma.com/manga/one-piece/chapter-{CHAPTER_ID}/",
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_ids(url)


# ── Search ────────────────────────────────────────────────────────────


class TestSearchIsUnsupported:
    @pytest.mark.parametrize("query", ["One Piece", "ワンピース", "zzqqxxnomatch", "", "   "])
    def test_search_raises_before_any_request(self, scraper, site, query):
        _, calls = site
        with pytest.raises(SenMangaSourceError, match="direct URL"):
            scraper.search(query)
        assert calls == []

    def test_an_explicit_sweep_reports_it_without_a_request(self, monkeypatch):
        def no_network(*args, **kwargs):
            raise AssertionError("a request was sent")

        monkeypatch.setattr(requests.Session, "send", no_network)
        results, failures = sweep("One Piece", ["raw.senmanga.com"])
        assert results == []
        assert [f.source for f in failures] == ["raw.senmanga.com"]
        assert "direct URL" in failures[0].error

    def test_the_default_sweep_leaves_it_out(self):
        assert "raw.senmanga.com" in BROKEN_SEARCH_SOURCES


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _list(self, scraper, site, rows, **changes):
        served, _ = site
        served[SERIES_API] = _Reply(_series(rows, **changes))
        return scraper.get_chapters(SERIES_URL)

    def test_numbers_come_from_the_rows_not_their_order_or_ids(self, scraper, site):
        rows = [_row("1197", CHAPTER_ID, when="2026-11-01T15:35:00Z"),
                _row("2", "9.100", when="2020-01-01T00:00:00Z"),
                _row("1196", PREVIOUS_ID, when="2026-11-02T00:00:00Z"),
                _row("1", "2.50", when="2020-01-02T00:00:00Z")]
        chapters = self._list(scraper, site, rows)
        assert [c.number for c in chapters] == ["1", "2", "1196", "1197"]
        assert [c.url for c in chapters] == [
            f"{SERIES_URL}/chapter-2.50/", f"{SERIES_URL}/chapter-9.100/",
            f"{SERIES_URL}/chapter-{PREVIOUS_ID}/", f"{SERIES_URL}/chapter-{CHAPTER_ID}/"]
        assert chapters[2].date == "2026-11-02T00:00:00Z"
        assert chapters[3].date == "2026-11-01T15:35:00Z"

    @pytest.mark.parametrize("served_number, label", [
        ("1197", "1197"), ("1197.0", "1197"), ("10.5", "10.5"), ("10.50", "10.5"),
        ("0", "0"), ("007", "7"), ("100", "100"),
    ])
    def test_number_forms(self, scraper, site, served_number, label):
        chapters = self._list(scraper, site, [_row(served_number)])
        assert chapters[0].number == label
        assert chapters[0].title is None

    @pytest.mark.parametrize("title", [
        "Chapter 12: 冒険", "Chapter 12 - 冒険", "Chapter 12 冒険", "第12話", "Special"])
    def test_a_title_with_more_than_the_number_is_kept(self, scraper, site, title):
        chapters = self._list(scraper, site, [_row("12", title=title)])
        assert (chapters[0].number, chapters[0].title) == ("12", title)

    @pytest.mark.parametrize("number, title", [
        ("12", "Chapter 13"), ("12", "Chapter 12.5"), ("12.5", "Chapter 12"),
        ("12", "Chapter 21: x")])
    def test_a_title_and_number_that_disagree_raise(self, scraper, site, number, title):
        with pytest.raises(SenMangaSourceError, match="disagree"):
            self._list(scraper, site, [_row(number, title=title)])

    @pytest.mark.parametrize("change", [
        {"number": None}, {"number": True}, {"number": 1197}, {"number": 1197.0}, {"number": "-1"},
        {"number": "x"}, {"number": ""}, {"number": "1e3"}, {"number": "12a"}, {"number": [1]},
        {"url": None}, {"url": ""}, {"url": 1197}, {"url": "../x"}, {"url": "a/b"},
        {"title": None}, {"title": "  "},
        {"datetime": None}, {"datetime": ""}, {"datetime": 1700000000},
        {"datetime": "yesterday"}, {"datetime": "2026-11-01"},
        {"datetime": "2026-11-01T15:35:00+00:00"}, {"datetime": "2026-13-01T15:35:00Z"},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_a_row_with_an_unusable_field_raises(self, scraper, site, change):
        row = _row()
        row.update(change)
        with pytest.raises(SenMangaSourceError):
            self._list(scraper, site, [row])

    def test_a_row_with_a_download_field_is_listed(self, scraper, site):
        chapters = self._list(scraper, site, [_row(download="synthetic")])
        assert [c.number for c in chapters] == ["1197"]

    def test_a_row_that_is_not_an_object_raises(self, scraper, site):
        with pytest.raises(SenMangaSourceError):
            self._list(scraper, site, ["x"])

    def test_a_repeated_id_raises(self, scraper, site):
        with pytest.raises(SenMangaSourceError, match="id is listed twice"):
            self._list(scraper, site, [_row("1", "1.1"), _row("2", "1.1")])

    @pytest.mark.parametrize("first, second", [("5", "5"), ("5", "5.0"), ("5.5", "5.50")])
    def test_a_repeated_number_raises(self, scraper, site, first, second):
        rows = [_row(first, "5.1", title="x"), _row(second, "5.2", title="y")]
        with pytest.raises(SenMangaSourceError, match="number is listed twice"):
            self._list(scraper, site, rows)

    def test_an_empty_list_raises(self, scraper, site):
        with pytest.raises(SenMangaSourceError, match="no chapters"):
            self._list(scraper, site, [])

    @pytest.mark.parametrize("changes", [
        {"slug": "other"}, {"slug": None}, {"title": ""}, {"title": None},
        {"chapterList": None}, {"chapterList": {}},
    ], ids=["other-slug", "no-slug", "empty-title", "no-title", "no-list", "list-object"])
    def test_a_malformed_series_raises(self, scraper, site, changes):
        with pytest.raises(SenMangaSourceError):
            self._list(scraper, site, [_row()], **changes)

    @pytest.mark.parametrize("reply", [
        _Reply(status=301), _Reply(bad_json=True), _Reply([]), _http_error(404),
        requests.Timeout("slow"),
    ], ids=["redirect", "not-json", "not-object", "404", "timeout"])
    def test_a_failed_series_request_raises(self, scraper, site, reply):
        served, _ = site
        served[SERIES_API] = reply
        with pytest.raises(SenMangaSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_the_listing_logs_that_no_total_is_known(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.senmanga")
        self._list(scraper, site, [_row()])
        assert "listing 1 chapter(s)" in caplog.text
        assert "no total" in caplog.text

    def test_a_url_that_is_not_a_series_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_chapters(f"{BASE}/search")
        assert calls == []


class TestCover:
    def test_the_series_cover(self, scraper, site):
        served, _ = site
        served[SERIES_API] = _Reply(_series([_row()]))
        assert scraper.get_cover_url(SERIES_URL) == f"{CDN}/covers/one-piece.jpg"

    @pytest.mark.parametrize("cover", [None, "", "/cover.jpg", "http://x/c.jpg", 7])
    def test_no_usable_cover(self, scraper, site, cover):
        served, _ = site
        served[SERIES_API] = _Reply(_series([_row()], cover=cover))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_a_failure_is_no_cover(self, scraper, site):
        served, _ = site
        served[SERIES_API] = _http_error(503)
        assert scraper.get_cover_url(SERIES_URL) is None
        assert scraper.get_cover_url("https://example.com/x") is None


# ── Pages ─────────────────────────────────────────────────────────────


def _no_row(data):
    data["series"]["chapterList"] = [_row("1196", PREVIOUS_ID)]


def _two_rows(data):
    data["series"]["chapterList"].append(_row("1198", CHAPTER_ID))


class TestPages:
    def test_pages_keep_the_served_order(self, scraper, site):
        served, calls = site
        pages = [_page("10"), _page("2"), _page("1"), _page("z")]
        served[READ_API] = _Reply(_read(pages))
        assert scraper.get_pages(CHAPTER_URL) == pages
        assert [c[0] for c in calls] == [READ_API]
        assert calls[0][1]["allow_redirects"] is False

    @pytest.mark.parametrize("previous, following", [
        ("1196", None), (None, "1198"), ("1196", "1198"), (None, None)])
    def test_neighbours_are_strings_or_null(self, scraper, site, previous, following):
        served, _ = site
        data = _read([_page("1")])
        data.update(previousChapter=previous, nextChapter=following)
        served[READ_API] = _Reply(data)
        assert scraper.get_pages(CHAPTER_URL) == [_page("1")]

    @pytest.mark.parametrize("change", [
        lambda d: d.update(chapter="1196"),
        lambda d: d.update(chapter=CHAPTER_ID),
        lambda d: d.update(chapter="Chapter 1197"),
        lambda d: d.update(chapter=1197),
        lambda d: d.update(chapter=None),
        lambda d: d.update(chapter={"url": CHAPTER_ID}),
        lambda d: d.pop("chapter"),
        lambda d: d["series"]["chapterList"][0].update(number="1198"),
        lambda d: d["series"]["chapterList"][0].update(slug="1198"),
        lambda d: d["series"]["chapterList"][0].pop("number"),
        lambda d: d["series"]["chapterList"][0].pop("slug"),
        _no_row,
        _two_rows,
    ], ids=["other-chapter", "chapter-is-id", "chapter-is-title", "number-chapter", "null-chapter",
            "object-chapter", "no-chapter", "row-number-differs", "row-slug-differs",
            "row-no-number", "row-no-slug", "id-not-listed", "id-listed-twice"])
    def test_a_reply_for_another_chapter_raises(self, scraper, site, change):
        served, _ = site
        data = _read([_page("1")])
        change(data)
        served[READ_API] = _Reply(data)
        with pytest.raises(SenMangaSourceError, match="this chapter"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("change, why", [
        (lambda d: d["series"].update(slug="bleach"), "this series"),
        (lambda d: d["series"].pop("slug"), "this series"),
        (lambda d: d.update(series=None), "this series"),
        (lambda d: d.update(series="one-piece"), "this series"),
        (lambda d: d["series"].pop("chapterList"), "chapter list"),
        (lambda d: d["series"].update(chapterList={}), "chapter list"),
        (lambda d: d["series"]["chapterList"].append("x"), "chapter list"),
        (lambda d: d.pop("previousChapter"), "neighbouring"),
        (lambda d: d.pop("nextChapter"), "neighbouring"),
        (lambda d: d.update(previousChapter={"url": PREVIOUS_ID}), "neighbouring"),
        (lambda d: d.update(nextChapter={"url": "1198.1"}), "neighbouring"),
        (lambda d: d.update(previousChapter=1196), "neighbouring"),
        (lambda d: d.update(nextChapter=""), "neighbouring"),
        (lambda d: d.update(pages=None), "no page list"),
        (lambda d: d.update(pages={}), "no page list"),
        (lambda d: d.update(pages=[]), "no pages"),
    ], ids=["other-series", "series-no-slug", "no-series", "series-text", "no-list", "list-object",
            "row-text", "no-previous", "no-next", "object-previous", "object-next",
            "number-previous", "empty-next", "null-pages", "object-pages", "empty-pages"])
    def test_a_malformed_reply_raises(self, scraper, site, change, why):
        served, _ = site
        data = _read([_page("1")])
        change(data)
        served[READ_API] = _Reply(data)
        with pytest.raises(SenMangaSourceError, match=why):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        None, 7, "", "/o/x/1.jpg",
        "http://cdn.rawkuma.com/o/x/1.jpg",
        "https://rawkuma.com/o/x/1.jpg",
        "https://evil.example/o/x/1.jpg",
        "https://cdn.rawkuma.com.evil.example/o/x/1.jpg",
        "https://cdn.rawkuma.com:8443/o/x/1.jpg",
        "https://user@cdn.rawkuma.com/o/x/1.jpg",
        "https://CDN.RAWKUMA.COM/o/x/1.jpg",
        "https://cdn.rawkuma.com/o/x/1.jpg?sig=1",
        "https://cdn.rawkuma.com/o/x/1.jpg#x",
        "https://cdn.rawkuma.com/o/../1.jpg",
        "https://cdn.rawkuma.com/o/x/",
        "https://cdn.rawkuma.com",
        "https://cdn.rawkuma.com/o/x y.jpg",
        "https://cdn.rawkuma.com\\@evil.example/1.jpg",
    ])
    def test_an_unusable_image_url_raises(self, scraper, site, bad):
        served, _ = site
        served[READ_API] = _Reply(_read([_page("1"), bad]))
        with pytest.raises(SenMangaSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_a_repeated_page_raises(self, scraper, site):
        served, _ = site
        served[READ_API] = _Reply(_read([_page("1"), _page("2"), _page("1")]))
        with pytest.raises(SenMangaSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _Reply(bad_json=True), _Reply([]), _http_error(403),
        requests.ConnectionError("reset"),
    ], ids=["redirect", "not-json", "not-object", "403", "transport"])
    def test_a_failed_reader_request_raises(self, scraper, site, reply):
        served, _ = site
        served[READ_API] = reply
        with pytest.raises(SenMangaSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_a_url_that_is_not_a_chapter_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_pages(SERIES_URL)
        assert calls == []


# ── Images ────────────────────────────────────────────────────────────


class TestDownloadImage:
    def test_the_bytes_are_saved_as_served(self, scraper, site, tmp_path):
        served, calls = site
        picture = _jpeg()
        reply = _Reply(content=picture)
        served[_page("1")] = reply
        path = tmp_path / "out" / "001.jpg"
        assert scraper.download_image(_page("1"), path) is True
        assert path.read_bytes() == picture
        kwargs = calls[0][1]
        assert kwargs["headers"]["Referer"] == f"{BASE}/"
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        assert reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(content=b"<html>blocked</html>"), _Reply(content=b""), _Reply(status=302),
        _Reply(status=206, content=b"partial"), _http_error(403), _http_error(503),
        requests.ConnectionError("reset"), requests.exceptions.ChunkedEncodingError("cut"),
    ], ids=["html", "empty", "redirect", "partial", "403", "503", "transport", "cut"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        served, _ = site
        served[_page("1")] = reply
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(_page("1"), path) is False
        assert not path.exists()

    def test_a_body_that_breaks_while_streaming_fails(self, scraper, site, tmp_path):
        served, _ = site

        class _Broken(_Reply):
            def iter_content(self, size):
                yield _jpeg()[:4]
                raise requests.exceptions.ChunkedEncodingError("cut")

        reply = _Broken()
        served[_page("1")] = reply
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(_page("1"), path) is False
        assert not path.exists() and reply.closed

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        served, _ = site
        monkeypatch.setattr(senmanga, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(content=_jpeg())
        served[_page("1")] = reply
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(_page("1"), path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        "https://evil.example/o/x/1.jpg", "http://cdn.rawkuma.com/o/x/1.jpg",
        "https://cdn.rawkuma.com/o/x/1.jpg?x=1", "https://cdn.rawkuma.com:8443/o/x/1.jpg"])
    def test_an_off_host_page_fails_without_a_request(self, scraper, site, tmp_path, url):
        _, calls = site
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(url, path) is False
        assert calls == [] and not path.exists()


# ── Metadata and registration ────────────────────────────────────────


class TestMetadata:
    def test_source_metadata(self):
        assert SenMangaScraper.name == "senmanga"
        assert SenMangaScraper.base_url == BASE
        assert SenMangaScraper.engine == "api"
        assert SenMangaScraper.nsfw is True

    def test_no_language_or_direction_is_claimed(self):
        assert SenMangaScraper.content_language is None
        assert SenMangaScraper.reading_direction is None
        assert _manga_language({"title": "Unknown series"}, SenMangaScraper()) is None

    def test_registered_on_its_own_host_only(self):
        assert isinstance(get_scraper("raw.senmanga.com"), SenMangaScraper)
        assert [d for d in SCRAPERS
                if d == "senmanga.com" or d.endswith(".senmanga.com")] == ["raw.senmanga.com"]
        # Rawkuma is a separate source with its own scraper.
        assert [d for d, path in _SCRAPER_PATHS.items()
                if path == "senmanga:SenMangaScraper"] == ["raw.senmanga.com"]
        assert SCRAPERS["rawkuma.net"] is not SenMangaScraper

    def test_catalog_states_direct_url_only(self):
        row = next(r for r in source_catalog() if r.domain == "raw.senmanga.com")
        assert row.aliases == () and row.language is None and row.nsfw is True
        assert row.engine == "api"
        assert "direct series URL" in row.note
        assert row.search_status == "Not searched (unreliable)"
        assert row.search_skip.note == "Search endpoint ignores queries; use direct series URLs."
        assert row.popularity is None and row.default_enabled is False
