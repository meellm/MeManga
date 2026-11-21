"""Offline tests for RawUwuScraper (rawuwu.net).

Every reply here is a synthetic fixture and no request leaves the test.
Field shapes follow what the site's JSON routes serve; ids, titles and
page addresses are invented.
"""

from __future__ import annotations

import http.cookiejar
import io
import json
import logging

import pytest
import requests
from PIL import Image

from memanga.downloader.formats.cbz import _manga_language
from memanga.scrapers import rawuwu
from memanga.scrapers.rawuwu import (
    RawUwuScraper, RawUwuSourceError, chapter_parts, series_id)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"RawUwuScraper": ("search", "chapters", "pages")}

BASE = "https://rawuwu.net"
API = f"{BASE}/spa"
SERVER = "https://s3.rawuwu.net/"
SERIES_URL = f"{BASE}/raw/701"
CHAPTER_URL = f"{BASE}/read/701/chapter-3#id=9003"
SERIES_API = f"{API}/manga/701"
READER_API = f"{API}/manga/701/3"
SEARCH_API = f"{API}/search?query=%E3%83%86%E3%82%B9%E3%83%88&page=1"
WHEN = "2026-01-02T03:04:05.678Z"
EMPTY = {"manga_list": [], "pagi": {"current": 1, "offset": 0}}


def _hit(series=701, name="Test Work", **changes):
    row = {"manga_name": name, "manga_cover_img": f"{BASE}/img/thumb/test.webp",
           "manga_id": series, "ja_manga_name": None,
           "manga_chapters": [{"manga_id": series, "chapter_id": 9003, "chapter_number": 3,
                               "chapter_date_published": "2026-01-02T04:04:05+01:00"}],
           "score": 1}
    row.update(changes)
    return row


def _paging(next_page=0, prev=0, pages=None, cur=1, offset=0):
    return {"pages": [{"page": 1, "act": True}] if pages is None else pages,
            "button": {"next": next_page, "prev": prev}, "cur_page": cur, "offset": offset}


def _results(*rows, paging=None):
    return {"manga_list": list(rows), "pagi": _paging() if paging is None else paging}


def _row(chapter_id="9003", number=3, title="", when=WHEN):
    return {"chapter_id": chapter_id, "chapter_title": title, "chapter_number": number,
            "chapter_views": 1, "chapter_date_published": when}


def _series(*rows, **detail):
    fields = {"manga_id": 701, "manga_name": "Test Work", "manga_others_name": "テスト作品",
              "manga_status": False, "manga_description": "x", "manga_date_published": WHEN,
              "manga_updated": WHEN, "manga_cover_img": f"{BASE}/img/thumb/test.webp",
              "manga_cover_img_normal": None, "manga_cover_img_full": f"{BASE}/img/test.jpeg",
              "manga_views": 1}
    fields.update(detail)
    return {"detail": fields, "tags": [], "authors": [], "chapters": list(rows)}


def _source(number, series=701, chapter=9003):
    return f"data/aa/bb/{series}/{chapter}/{number:03d}-800x1200.webp"


def _image(number):
    return SERVER + _source(number)


def _content(*sources):
    return "".join(
        f'<div class="page-wrapper" id="page{i}"><div class="chapter-img shine">'
        f'<img class="lazy" data-src="{source}" width="800" height="1200" loading="lazy" '
        f'alt="Page {i + 1}"/></div></div>' for i, source in enumerate(sources))


def _reader(*sources, hidden=True, **detail):
    used = sources or (_source(0), _source(1), _source(2))
    fields = {"manga_id": 701, "manga_others_name": "テスト作品", "manga_name": "Test Work",
              "chapter_id": "9003", "chapter_title": "", "chapter_number": 3,
              "chapter_date_published": WHEN, "manga_cover_img": f"{BASE}/img/thumb/test.webp",
              "manga_cover_img_normal": None, "manga_cover_img_full": f"{BASE}/img/test.jpeg",
              "tags": [], "chapter_content": _content(*used), "server": SERVER,
              "slaves": ["https://other-cdn.example/"]}
    fields.update(detail)
    return {"prev": "/read/701/chapter-2", "next": "", "hidden": hidden,
            "chapter_detail": fields, "options": "<option>#3</option>"}


def _webp():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (10, 20, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


class _Reply:
    def __init__(self, content=b"", status=200):
        self.status_code = status
        self._content = content
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def close(self):
        self.closed = True


def _json(data):
    return _Reply(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _http_error(status):
    return requests.HTTPError(f"{status} error", response=_Reply(status=status))


FAILED_REPLIES = [
    _Reply(status=302), _Reply(status=204), _Reply(b"<html>challenge</html>"),
    _Reply(b"NaN"), _http_error(403), _http_error(503), requests.Timeout("slow"),
]
FAILED_IDS = ["redirect", "no-content", "html", "nan", "403", "503", "timeout"]


@pytest.fixture
def scraper():
    return RawUwuScraper()


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


# ── URLs ──────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("url", [SERIES_URL, f"{SERIES_URL}/"])
    def test_a_series_url_names_its_id(self, url):
        assert series_id(url) == 701

    @pytest.mark.parametrize("url", [
        "http://rawuwu.net/raw/701", "https://www.rawuwu.net/raw/701",
        "https://rawsakura.org/raw/701", "https://rawuwu.net:8443/raw/701",
        "https://u@rawuwu.net/raw/701", f"{SERIES_URL}?x=1", f"{SERIES_URL}#x",
        f"{BASE}/read/701", f"{BASE}/raw/0", f"{BASE}/raw/07", f"{BASE}/raw/abc",
        f"{SERIES_URL}/x", CHAPTER_URL, "", None, 7,
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ValueError):
            series_id(url)

    @pytest.mark.parametrize("url, parts", [
        (CHAPTER_URL, (701, "3", 9003)),
        (f"{BASE}/read/701/chapter-12.5#id=9", (701, "12.5", 9)),
        (f"{BASE}/read/701/chapter-0#id=9", (701, "0", 9)),
        (f"{BASE}/read/701/chapter-100#id=9", (701, "100", 9)),
    ])
    def test_a_chapter_url_names_its_parts(self, url, parts):
        assert chapter_parts(url) == parts

    @pytest.mark.parametrize("url", [
        f"{BASE}/read/701/chapter-3", f"{BASE}/read/701/chapter-3#id=0",
        f"{BASE}/read/701/chapter-3#x=9003", f"{BASE}/read/701/chapter-3?x=1#id=9003",
        f"{BASE}/read/701/chapter-03#id=9003", f"{BASE}/read/701/chapter-3.0#id=9003",
        f"{BASE}/read/701/chapter-3.50#id=9003", f"{BASE}/read/701/chapter-x#id=9003",
        f"{BASE}/raw/701/chapter-3#id=9003", "http://rawuwu.net/read/701/chapter-3#id=9003",
        SERIES_URL, "", None,
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_parts(url)


# ── Search ────────────────────────────────────────────────────────────


class TestSearch:
    def test_served_rows_keep_their_order(self, scraper, site):
        served, calls = site
        served[SEARCH_API] = _json(_results(_hit(701, "Test Work"), _hit(702, "Other Work")))
        found = scraper.search("テスト")
        assert [(m.title, m.url) for m in found] == [
            ("Test Work", f"{BASE}/raw/701"), ("Other Work", f"{BASE}/raw/702")]
        assert found[0].cover_url == f"{BASE}/img/thumb/test.webp"
        assert found[0].chapters == []
        assert [c[0] for c in calls] == [SEARCH_API]
        assert calls[0][1]["allow_redirects"] is False and calls[0][1]["headers"] == {}

    def test_the_served_empty_is_no_results(self, scraper, site):
        served, calls = site
        served[f"{API}/search?query=zzqqxx&page=1"] = _json(EMPTY)
        assert scraper.search("zzqqxx") == []
        assert len(calls) == 1

    @pytest.mark.parametrize("paging", [
        _paging(next_page=2),
        _paging(pages=[{"page": 1, "act": True}, {"page": 2, "act": False}]),
    ], ids=["next-button", "second-page"])
    def test_a_reply_with_more_results_fails_clearly(self, scraper, site, paging):
        served, calls = site
        served[SEARCH_API] = _json(_results(_hit(), paging=paging))
        with pytest.raises(RawUwuSourceError, match="more search results"):
            scraper.search("テスト")
        assert len(calls) == 1

    @pytest.mark.parametrize("data", [
        {"manga_list": [], "pagi": _paging()},
        _results(_hit(), paging={"current": 1, "offset": 0}),
        {"manga_list": [], "pagi": {"current": 2, "offset": 0}},
        {"manga_list": [], "pagi": {"current": True, "offset": 0}},
        {"manga_list": [], "pagi": {"current": 1, "offset": 0, "x": 1}},
        {"manga_list": []},
        {"manga_list": None, "pagi": {"current": 1, "offset": 0}},
        _results(_hit(), paging=_paging(prev=1)),
        _results(_hit(), paging=_paging(cur=2)),
        _results(_hit(), paging=_paging(offset=20)),
        _results(_hit(), paging=_paging(pages=[])),
        _results(_hit(), paging=_paging(pages=[{"page": 2, "act": True}])),
        _results(_hit(), paging=_paging(next_page="0")),
        {**_results(_hit()), "extra": 1},
    ], ids=["empty-with-result-paging", "hit-with-empty-paging", "empty-later-page",
            "empty-bool-page", "empty-extra-key", "no-paging", "no-list", "prev-page", "cur-page",
            "offset", "no-pages", "other-page", "text-next", "extra-key"])
    def test_an_unknown_reply_is_not_an_empty_result(self, scraper, site, data):
        served, _ = site
        served[SEARCH_API] = _json(data)
        with pytest.raises(RawUwuSourceError):
            scraper.search("テスト")

    @pytest.mark.parametrize("query, encoded", [
        ("a&b=c d/e?#", "a%26b%3Dc%20d%2Fe%3F%23"), ("One Piece", "One%20Piece"),
        ("  テスト  ", "%E3%83%86%E3%82%B9%E3%83%88"), ("ピ", "%E3%83%94"),
        ("ピ", "%E3%83%94"), ("ヒ", "%E3%83%92"),
    ], ids=["reserved", "latin-case", "trimmed", "handakuten", "decomposed", "plain"])
    def test_the_query_is_encoded_without_losing_characters(self, scraper, site, query, encoded):
        served, calls = site
        url = f"{API}/search?query={encoded}&page=1"
        served[url] = _json(EMPTY)
        assert scraper.search(query) == []
        assert [c[0] for c in calls] == [url]

    @pytest.mark.parametrize("query", ["", "   ", "　"])
    def test_a_blank_query_sends_nothing(self, scraper, site, query):
        _, calls = site
        assert scraper.search(query) == []
        assert calls == []

    def test_a_query_that_cannot_be_encoded_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.search("x\ud800")
        assert calls == []

    @pytest.mark.parametrize("row", [
        "x", None, {}, _hit(extra=1), _hit(isLocked=False),
        {k: v for k, v in _hit().items() if k != "score"},
        _hit(manga_id=None), _hit(manga_id=True), _hit(manga_id=0), _hit(manga_id="701"),
        _hit(manga_id=10 ** 12), _hit(manga_name=None), _hit(manga_name="  "),
    ], ids=["text", "null", "empty", "unknown-field", "lock-field", "missing-field", "null-id",
            "bool-id", "zero-id", "text-id", "huge-id", "null-name", "blank-name"])
    def test_an_unusable_row_raises(self, scraper, site, row):
        served, _ = site
        served[SEARCH_API] = _json(_results(row))
        with pytest.raises(RawUwuSourceError):
            scraper.search("テスト")

    def test_a_repeated_series_raises(self, scraper, site):
        served, _ = site
        served[SEARCH_API] = _json(_results(_hit(701), _hit(701, "Other")))
        with pytest.raises(RawUwuSourceError, match="listed twice"):
            scraper.search("テスト")

    @pytest.mark.parametrize("image", ["http://x/c.webp", "/c.webp", "", None])
    def test_an_unusable_cover_is_left_out(self, scraper, site, image):
        served, _ = site
        served[SEARCH_API] = _json(_results(_hit(manga_cover_img=image)))
        assert scraper.search("テスト")[0].cover_url is None

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reply_raises(self, scraper, site, reply):
        served, _ = site
        served[SEARCH_API] = reply
        with pytest.raises(RawUwuSourceError):
            scraper.search("テスト")


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _list_from(self, scraper, site, *rows, **detail):
        served, _ = site
        served[SERIES_API] = _json(_series(*rows, **detail))
        return scraper.get_chapters(SERIES_URL)

    def test_rows_are_ordered_and_missing_numbers_stay_missing(self, scraper, site):
        rows = [_row("9005", 5), _row("9003", 3), _row("9001", 1)]
        chapters = self._list_from(scraper, site, *rows)
        assert [c.number for c in chapters] == ["1", "3", "5"]
        assert [c.url for c in chapters] == [
            f"{BASE}/read/701/chapter-1#id=9001", f"{BASE}/read/701/chapter-3#id=9003",
            f"{BASE}/read/701/chapter-5#id=9005"]
        assert all(c.title is None and c.date == WHEN for c in chapters)

    def test_one_request(self, scraper, site):
        _, calls = site
        self._list_from(scraper, site, _row())
        assert [c[0] for c in calls] == [SERIES_API]
        assert calls[0][1]["allow_redirects"] is False and calls[0][1]["stream"] is True

    @pytest.mark.parametrize("served_id", ["9003", 9003], ids=["text", "number"])
    def test_a_chapter_id_is_normalized(self, scraper, site, served_id):
        chapter = self._list_from(scraper, site, _row(served_id))[0]
        assert chapter.url == f"{BASE}/read/701/chapter-3#id=9003"

    @pytest.mark.parametrize("number, label", [(12, "12"), (12.0, "12"), (12.5, "12.5"), (0, "0"),
                                               (100, "100")])
    def test_number_forms(self, scraper, site, number, label):
        chapter = self._list_from(scraper, site, _row(number=number))[0]
        assert chapter.number == label
        assert chapter.url == f"{BASE}/read/701/chapter-{label}#id=9003"

    def test_a_served_title_is_kept(self, scraper, site):
        assert self._list_from(scraper, site, _row(title="Voyage"))[0].title == "Voyage"

    @pytest.mark.parametrize("when", ["2026-13-02T03:04:05.678Z", "2026-01-02", "", None, 7])
    def test_an_unusable_date_is_left_out(self, scraper, site, when):
        assert self._list_from(scraper, site, _row(when=when))[0].date is None

    @pytest.mark.parametrize("change", [
        {"chapter_id": None}, {"chapter_id": True}, {"chapter_id": 0}, {"chapter_id": "0"},
        {"chapter_id": "07"}, {"chapter_id": "x"}, {"chapter_id": 9.5},
        {"chapter_number": None}, {"chapter_number": True}, {"chapter_number": "3"},
        {"chapter_number": -1}, {"chapter_number": 1e30}, {"chapter_title": None},
        {"chapter_title": 3},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_a_row_with_an_unusable_field_raises(self, scraper, site, change):
        row = _row()
        row.update(change)
        with pytest.raises(RawUwuSourceError):
            self._list_from(scraper, site, row)

    @pytest.mark.parametrize("extra", ["isLocked", "price", "unexpected"])
    def test_a_row_with_an_unknown_field_fails(self, scraper, site, extra):
        row = _row()
        row[extra] = False
        with pytest.raises(RawUwuSourceError, match="known shape"):
            self._list_from(scraper, site, row)

    def test_a_repeated_id_raises(self, scraper, site):
        with pytest.raises(RawUwuSourceError, match="id is listed twice"):
            self._list_from(scraper, site, _row("9001", 1), _row(9001, 2))

    @pytest.mark.parametrize("first, second", [(5, 5), (5, 5.0)])
    def test_a_repeated_number_raises(self, scraper, site, first, second):
        with pytest.raises(RawUwuSourceError, match="number is listed twice"):
            self._list_from(scraper, site, _row("9001", first), _row("9002", second))

    def test_an_empty_list_raises(self, scraper, site):
        with pytest.raises(RawUwuSourceError, match="no chapters"):
            self._list_from(scraper, site)

    @pytest.mark.parametrize("change", [
        {"manga_id": 702}, {"manga_id": "701"}, {"manga_id": True}, {"manga_name": ""},
        {"manga_name": None}, {"isLocked": False},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_an_unusable_series_reply_raises(self, scraper, site, change):
        with pytest.raises(RawUwuSourceError):
            self._list_from(scraper, site, _row(), **change)

    @pytest.mark.parametrize("data", [
        None, [], {}, {**_series(_row()), "extra": 1}, {**_series(_row()), "chapters": None},
    ], ids=["null", "list", "empty", "extra-key", "no-list"])
    def test_a_reply_outside_the_known_shape_raises(self, scraper, site, data):
        served, _ = site
        served[SERIES_API] = _json(data)
        with pytest.raises(RawUwuSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reply_raises(self, scraper, site, reply):
        served, _ = site
        served[SERIES_API] = reply
        with pytest.raises(RawUwuSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_an_oversized_reply_fails(self, monkeypatch, scraper, site):
        served, _ = site
        monkeypatch.setattr(rawuwu, "_MAX_REPLY_BYTES", 8)
        reply = _json(_series(_row()))
        served[SERIES_API] = reply
        with pytest.raises(RawUwuSourceError, match="too large"):
            scraper.get_chapters(SERIES_URL)
        assert reply.closed

    def test_the_listing_logs_its_scope(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.rawuwu")
        self._list_from(scraper, site, _row())
        assert "listing the 1 chapter(s) the series reply names" in caplog.text

    def test_a_url_that_is_not_a_series_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_chapters(CHAPTER_URL)
        assert calls == []


class TestCover:
    def test_the_series_cover(self, scraper, site):
        served, _ = site
        served[SERIES_API] = _json(_series(_row()))
        assert scraper.get_cover_url(SERIES_URL) == f"{BASE}/img/thumb/test.webp"

    @pytest.mark.parametrize("image", [None, "", "/c.webp", "http://x/c.webp"])
    def test_no_usable_cover(self, scraper, site, image):
        served, _ = site
        served[SERIES_API] = _json(_series(_row(), manga_cover_img=image))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_a_failure_is_no_cover(self, scraper, site):
        served, calls = site
        served[SERIES_API] = _http_error(503)
        assert scraper.get_cover_url(SERIES_URL) is None
        assert scraper.get_cover_url("https://example.com/x") is None
        assert len(calls) == 1


# ── Pages ─────────────────────────────────────────────────────────────


class TestPages:
    def test_pages_keep_the_order_of_the_reply(self, scraper, site):
        served, calls = site
        served[READER_API] = _json(_reader(_source(2), _source(0), _source(1)))
        assert scraper.get_pages(CHAPTER_URL) == [_image(2), _image(0), _image(1)]
        assert [c[0] for c in calls] == [READER_API]
        assert calls[0][1]["allow_redirects"] is False and calls[0][1]["headers"] == {}

    @pytest.mark.parametrize("hidden", [True, False])
    def test_the_hidden_flag_does_not_decide_a_chapter(self, scraper, site, hidden):
        served, _ = site
        served[READER_API] = _json(_reader(hidden=hidden))
        assert len(scraper.get_pages(CHAPTER_URL)) == 3

    @pytest.mark.parametrize("hidden", [None, 1, "true"])
    def test_a_hidden_flag_that_is_not_boolean_raises(self, scraper, site, hidden):
        served, _ = site
        served[READER_API] = _json(_reader(hidden=hidden))
        with pytest.raises(RawUwuSourceError, match="known shape"):
            scraper.get_pages(CHAPTER_URL)

    def test_hidden_with_no_pages_is_not_treated_as_a_chapter(self, scraper, site):
        served, _ = site
        served[READER_API] = _json(_reader(chapter_content=""))
        with pytest.raises(RawUwuSourceError, match="no usable page list"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("key", ["locked", "price", "unexpected"])
    def test_an_unknown_reader_field_fails(self, scraper, site, key):
        served, _ = site
        top = _reader()
        top[key] = True
        nested = _reader()
        nested["chapter_detail"][key] = True
        for data in (top, nested):
            served[READER_API] = _json(data)
            with pytest.raises(RawUwuSourceError, match="known shape"):
                scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("change, why", [
        ({"manga_id": 702}, "this series"), ({"manga_id": "701"}, "this series"),
        ({"manga_id": True}, "this series"), ({"chapter_id": "9004"}, "this chapter"),
        ({"chapter_id": 9004}, "this chapter"), ({"chapter_number": 4}, "this chapter"),
        ({"chapter_number": 3.5}, "this chapter"), ({"manga_name": ""}, "title"),
        ({"chapter_id": None}, "usable id"), ({"chapter_number": "3"}, "usable number"),
    ], ids=lambda v: repr(v))
    def test_a_reply_for_something_else_raises(self, scraper, site, change, why):
        served, _ = site
        served[READER_API] = _json(_reader(**change))
        with pytest.raises(RawUwuSourceError, match=why):
            scraper.get_pages(CHAPTER_URL)

    def test_a_chapter_id_served_as_a_number_is_the_same_chapter(self, scraper, site):
        served, _ = site
        served[READER_API] = _json(_reader(chapter_id=9003))
        assert len(scraper.get_pages(CHAPTER_URL)) == 3

    @pytest.mark.parametrize("server", [
        "https://other-cdn.example/", "http://s3.rawuwu.net/", "https://s3.rawuwu.net",
        "https://rawuwu.net/", None])
    def test_another_image_host_raises(self, scraper, site, server):
        served, _ = site
        served[READER_API] = _json(_reader(server=server))
        with pytest.raises(RawUwuSourceError, match="image host"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("source", [
        "/data/aa/bb/701/9003/000-800x1200.webp",
        "https://s3.rawuwu.net/data/aa/bb/701/9003/000-800x1200.webp",
        "data/aa/bb/702/9003/000-800x1200.webp", "data/aa/bb/701/9004/000-800x1200.webp",
        "data/AA/bb/701/9003/000-800x1200.webp", "data/aa/bb/701/9003/000-800x1200.jpg",
        "data/aa/bb/701/9003/000.webp", "data/aa/bb/701/9003/../000-800x1200.webp",
        "data/aa/bb/701/9003/000-800x1200.webp?x=1",
    ], ids=["rooted", "absolute", "other-series", "other-chapter", "case", "other-type",
            "no-size", "dots", "query"])
    def test_an_unusable_page_address_raises(self, scraper, site, source):
        served, _ = site
        served[READER_API] = _json(_reader(source))
        with pytest.raises(RawUwuSourceError, match="page address"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("content", [
        '<div><img class="lazy" src="data/aa/bb/701/9003/000-800x1200.webp"/></div>',
        '<div><img data-src=""/></div>',
    ], ids=["no-data-src", "empty-data-src"])
    def test_an_image_without_its_address_raises(self, scraper, site, content):
        served, _ = site
        served[READER_API] = _json(_reader(chapter_content=content))
        with pytest.raises(RawUwuSourceError, match="page address"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("content", [None, 7, "", "<p>nothing</p>"])
    def test_a_reply_without_pages_raises(self, scraper, site, content):
        served, _ = site
        served[READER_API] = _json(_reader(chapter_content=content))
        with pytest.raises(RawUwuSourceError, match="page list"):
            scraper.get_pages(CHAPTER_URL)

    def test_a_repeated_page_raises(self, scraper, site):
        served, _ = site
        served[READER_API] = _json(_reader(_source(1), _source(1)))
        with pytest.raises(RawUwuSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    def test_too_many_pages_raise(self, monkeypatch, scraper, site):
        served, _ = site
        monkeypatch.setattr(rawuwu, "_MAX_PAGES", 2)
        served[READER_API] = _json(_reader())
        with pytest.raises(RawUwuSourceError, match="page list"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reader_raises(self, scraper, site, reply):
        served, _ = site
        served[READER_API] = reply
        with pytest.raises(RawUwuSourceError):
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
        picture = _webp()
        reply = _Reply(picture)
        served[_image(0)] = reply
        path = tmp_path / "out" / "001.webp"
        assert scraper.download_image(_image(0), path) is True
        assert path.read_bytes() == picture
        assert calls[0][1]["headers"] == {"Referer": f"{BASE}/"}
        assert calls[0][1]["allow_redirects"] is False and reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(b"<html>blocked</html>"), _Reply(b""), _Reply(status=302),
        _Reply(b"partial", status=206), _http_error(403), requests.ConnectionError("reset"),
    ], ids=["html", "empty", "redirect", "partial", "403", "transport"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        served, _ = site
        served[_image(0)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_image(0), path) is False
        assert not path.exists()

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        served, _ = site
        monkeypatch.setattr(rawuwu, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(_webp())
        served[_image(0)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_image(0), path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        f"https://other-cdn.example/{_source(0)}", f"http://s3.rawuwu.net/{_source(0)}",
        f"https://rawuwu.net/{_source(0)}", f"{_image(0)}?x=1", f"{_image(0)}#x",
        f"{SERVER}data/aa/bb/701/9003/000.webp", f"{SERVER}data/aa/bb/701/9003/000-800x1200.jpg",
        None,
    ])
    def test_an_unknown_page_address_fails_without_a_request(self, scraper, site, tmp_path, url):
        _, calls = site
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(url, path) is False
        assert calls == [] and not path.exists()


# ── Metadata ─────────────────────────────────────────────────────────


class TestMetadata:
    def test_source_metadata(self):
        assert (RawUwuScraper.name, RawUwuScraper.base_url) == ("rawuwu", BASE)
        assert RawUwuScraper.engine == "api" and RawUwuScraper.nsfw is True

    def test_no_language_or_direction_is_claimed(self):
        assert RawUwuScraper.content_language is None
        assert RawUwuScraper.reading_direction is None
        assert _manga_language({"title": "Unknown series"}, RawUwuScraper()) is None

    def test_cookies_are_not_kept(self):
        built = RawUwuScraper()
        assert isinstance(built.session.cookies.get_policy(), http.cookiejar.DefaultCookiePolicy)
        assert built.session.cookies.get_policy().allowed_domains() == ()
        assert built.worker_copy().session.cookies.get_policy().allowed_domains() == ()
