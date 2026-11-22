"""Offline tests for MangaRwScraper (mangarw.com).

Every reply here is a synthetic fixture and no request leaves the test.
Field shapes follow what the site's API serves; ids, titles and page
addresses are invented.
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
from memanga.scrapers import mangarw
from memanga.scrapers.mangarw import (
    MangaRwScraper, MangaRwSourceError, chapter_ids, series_id)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaRwScraper": ("search", "chapters", "pages")}

BASE = "https://mangarw.com"
API = "https://api.mangarw.com/api/v1"
STORAGE = "https://storage.mangabuzz.org"
PAGE_ID = "00000000-0000-4000-8000-000000000001"
SERIES_URL = f"{BASE}/manga/example-slug/701"
CHAPTER_URL = f"{BASE}/read?id=9003#series=701"
SERIES_API = f"{API}/manga/701"
CHAPTERS_API = f"{API}/manga/701/chapters?order=desc"
READER_API = f"{API}/chapter/9003"
WHEN = "2026-01-02T03:04:05.678Z"


def _row(row_id=9003, index=3, title=None, created=WHEN):
    return {"id": row_id, "title": f"第{index}話" if title is None else title, "index": index,
            "createdAt": created}


def _series(count=1, **changes):
    data = {"id": 701, "title": "テスト作品", "alternative": "Test Work", "description": "x",
            "image": "https://cdn.example/covers/test.jpg", "status": "ongoing", "isAdult": False,
            "createdAt": WHEN, "updatedAt": WHEN, "genres": [], "tags": [], "views": 1,
            "viewsDay": 1, "viewsWeek": 1, "viewsMonth": 1, "bookmarkCount": 1,
            "chapterCount": count}
    data.update(changes)
    return data


def _reader(first=0, last=2):
    return {"id": 9003, "title": "第3話", "mangaId": 701,
            "manga": {"id": 701, "title": "テスト作品",
                      "image": "https://cdn.example/covers/test.jpg", "isAdult": False},
            "storageUrl": STORAGE,
            "content": [{"type": "selfhosted",
                         "data": {"from": first, "to": last, "url": f"/{PAGE_ID}/{{page}}.webp"}}]}


def _hit(series=701, title="テスト作品", **changes):
    row = {"id": series, "title": title, "image": "https://cdn.example/covers/test.jpg",
           "status": "ongoing", "updatedAt": WHEN, "latestChapter": {"id": 9002, "title": "第2話"}}
    row.update(changes)
    return row


def _image(number):
    return f"{STORAGE}/{PAGE_ID}/{number}.webp"


def _page(number):
    return f"{_image(number)}#chapter=9003"


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
    return _Reply(json.dumps({"data": data}, ensure_ascii=False).encode("utf-8"))


def _http_error(status):
    return requests.HTTPError(f"{status} error", response=_Reply(status=status))


@pytest.fixture
def scraper():
    return MangaRwScraper()


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
    @pytest.mark.parametrize("url", [
        SERIES_URL, f"{SERIES_URL}/", f"{BASE}/manga/テスト作品/701",
        f"{BASE}/manga/%E3%83%86%E3%82%B9%E3%83%88/701", f"{BASE}/manga/another-slug/701",
    ])
    def test_the_id_is_the_identity_and_the_slug_is_opaque(self, url):
        assert series_id(url) == 701

    @pytest.mark.parametrize("url", [
        "http://mangarw.com/manga/x/701", "https://www.mangarw.com/manga/x/701",
        "https://mangaraw.co.uk/manga/x/701", "https://api.mangarw.com/manga/x/701",
        "https://mangarw.com:8443/manga/x/701", "https://user@mangarw.com/manga/x/701",
        f"{SERIES_URL}?x=1", f"{SERIES_URL}#x", f"{BASE}/manga/701", f"{BASE}/manga/x/0",
        f"{BASE}/manga/x/07", f"{BASE}/manga/x/abc", f"{BASE}/manga/x/701/extra",
        f"{BASE}/manga/../701", f"{BASE}/manga/./701", CHAPTER_URL, "", None, 7,
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ValueError):
            series_id(url)

    def test_a_chapter_url_carries_both_ids(self):
        assert chapter_ids(CHAPTER_URL) == (701, 9003)

    @pytest.mark.parametrize("url", [
        f"{BASE}/read?id=9003", f"{BASE}/read#series=701", f"{BASE}/read?id=9003#x=701",
        f"{BASE}/read?id=9003&x=1#series=701", f"{BASE}/read?id=0#series=701",
        f"{BASE}/read?id=9003#series=0", f"{BASE}/read?id=abc#series=701",
        f"{BASE}/reader?id=9003#series=701", "http://mangarw.com/read?id=9003#series=701",
        "https://mangaraw.co.uk/read?id=9003#series=701", SERIES_URL, "", None,
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_ids(url)


# ── Search ────────────────────────────────────────────────────────────


SEARCH_API = f"{API}/search/?keyword=%E3%83%86%E3%82%B9%E3%83%88"


class TestSearch:
    def test_served_rows_keep_their_order(self, scraper, site):
        served, calls = site
        served[SEARCH_API] = _json([_hit(701, "テスト作品"), _hit(702, "恋するテスト")])
        found = scraper.search("テスト")
        assert [m.title for m in found] == ["テスト作品", "恋するテスト"]
        assert [series_id(m.url) for m in found] == [701, 702]
        assert found[0].cover_url == "https://cdn.example/covers/test.jpg"
        assert [c[0] for c in calls] == [SEARCH_API]
        assert calls[0][1]["allow_redirects"] is False
        assert calls[0][1]["headers"]["Referer"] == f"{BASE}/"

    def test_a_true_empty_is_no_results(self, scraper, site):
        served, calls = site
        served[f"{API}/search/?keyword=zzqqxx"] = _json([])
        assert scraper.search("zzqqxx") == []
        assert len(calls) == 1

    @pytest.mark.parametrize("query", ["", "   ", "　"])
    def test_a_blank_query_sends_nothing(self, scraper, site, query):
        _, calls = site
        assert scraper.search(query) == []
        assert calls == []

    @pytest.mark.parametrize("query, encoded", [
        ("a&b=c d/e?#", "a%26b%3Dc%20d%2Fe%3F%23"),
        ("One Piece", "One%20Piece"),
        ("  テスト  ", "%E3%83%86%E3%82%B9%E3%83%88"),
        ("ピ", "%E3%83%94"),
        ("ピ", "%E3%83%94"),
        ("ヒ", "%E3%83%92"),
        ("ガ", "%E3%82%AC"),
        ("ガ", "%E3%82%AC"),
    ], ids=["reserved", "latin-case", "trimmed", "handakuten", "decomposed-handakuten", "plain",
            "dakuten", "decomposed-dakuten"])
    def test_the_query_is_encoded_without_losing_characters(self, scraper, site, query, encoded):
        served, calls = site
        url = f"{API}/search/?keyword={encoded}"
        served[url] = _json([])
        assert scraper.search(query) == []
        assert [c[0] for c in calls] == [url]

    def test_a_query_that_cannot_be_encoded_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.search("x\ud800")
        assert calls == []

    def test_a_result_url_uses_the_title_as_its_opaque_slug(self, scraper, site):
        served, _ = site
        rows = [_hit(701, "A/B 作品?"), _hit(702, ".."), _hit(703, "x\ud800")]
        served[SEARCH_API] = _Reply(json.dumps({"data": rows}).encode("ascii"))
        found = scraper.search("テスト")
        assert found[0].url == f"{BASE}/manga/A%2FB%20%E4%BD%9C%E5%93%81%3F/701"
        assert found[1].url == f"{BASE}/manga/manga/702"
        assert [series_id(m.url) for m in found] == [701, 702, 703]

    def test_chapter_fields_are_not_read(self, scraper, site):
        served, _ = site
        served[SEARCH_API] = _json([_hit(latestChapter={"id": 1, "title": "第999話"})])
        assert scraper.search("テスト")[0].chapters == []

    @pytest.mark.parametrize("image", ["http://x/c.jpg", "/c.jpg", ""])
    def test_an_unusable_cover_is_left_out(self, scraper, site, image):
        served, _ = site
        served[SEARCH_API] = _json([_hit(image=image)])
        assert scraper.search("テスト")[0].cover_url is None

    @pytest.mark.parametrize("row", [
        "x", None, {},
        _hit(extra=1),
        {k: v for k, v in _hit().items() if k != "latestChapter"},
        {k: v for k, v in _hit().items() if k != "image"},
    ], ids=["text", "null", "empty", "unknown-field", "no-latest", "no-image"])
    def test_a_row_outside_the_known_shape_raises(self, scraper, site, row):
        served, _ = site
        served[SEARCH_API] = _json([row])
        with pytest.raises(MangaRwSourceError, match="known shape"):
            scraper.search("テスト")

    @pytest.mark.parametrize("change", [
        {"id": None}, {"id": True}, {"id": 0}, {"id": -1}, {"id": "701"}, {"id": 7.5},
        {"id": 10 ** 12}, {"title": None}, {"title": "  "}, {"title": 3},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_a_row_with_an_unusable_field_raises(self, scraper, site, change):
        served, _ = site
        row = _hit()
        row.update(change)
        served[SEARCH_API] = _json([row])
        with pytest.raises(MangaRwSourceError):
            scraper.search("テスト")

    def test_a_repeated_series_raises(self, scraper, site):
        served, _ = site
        served[SEARCH_API] = _json([_hit(701), _hit(701, "Other")])
        with pytest.raises(MangaRwSourceError, match="listed twice"):
            scraper.search("テスト")

    @pytest.mark.parametrize("reply", [
        _json(None), _json({}), _json("x"), _Reply(status=302), _Reply(b"<html></html>"),
        _Reply(b"[]"), _Reply(b'{"data": [], "total": 0}'), _http_error(403),
        requests.Timeout("slow"),
    ], ids=["null", "object", "text", "redirect", "html", "not-object", "extra-top-key", "403",
            "timeout"])
    def test_a_failed_reply_raises(self, scraper, site, reply):
        served, _ = site
        served[SEARCH_API] = reply
        with pytest.raises(MangaRwSourceError):
            scraper.search("テスト")


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _chapters_from(self, scraper, site, rows, **series):
        served, _ = site
        served[SERIES_API] = _json(_series(len(rows), **series))
        served[CHAPTERS_API] = _json(rows)
        return scraper.get_chapters(SERIES_URL)

    def test_rows_are_ordered_by_their_index_and_keep_their_ids(self, scraper, site):
        rows = [_row(9003, 3), _row(9010, 1.5), _row(9001, 1), _row(9002, 2)]
        chapters = self._chapters_from(scraper, site, rows)
        assert [c.number for c in chapters] == ["1", "1.5", "2", "3"]
        assert [c.url for c in chapters] == [
            f"{BASE}/read?id=9001#series=701", f"{BASE}/read?id=9010#series=701",
            f"{BASE}/read?id=9002#series=701", f"{BASE}/read?id=9003#series=701"]
        assert all(c.date == WHEN and c.title is None for c in chapters)

    def test_the_requests_are_bounded(self, scraper, site):
        _, calls = site
        self._chapters_from(scraper, site, [_row()])
        assert [c[0] for c in calls] == [SERIES_API, CHAPTERS_API]
        for _, kwargs in calls:
            assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
            assert kwargs["headers"]["Referer"] == f"{BASE}/"

    @pytest.mark.parametrize("index, title, label", [
        (1197, "第1197話", "1197"), (1133.1, "第1133.1話", "1133.1"),
        (1025.5, "第1025.5話", "1025.5"), (12.0, "第12話", "12"), (0, "第0話", "0"),
        (100, "第100話", "100"),
    ])
    def test_index_forms(self, scraper, site, index, title, label):
        chapters = self._chapters_from(scraper, site, [_row(index=index, title=title)])
        assert chapters[0].number == label
        assert chapters[0].title is None

    @pytest.mark.parametrize("title", ["第12話 冒険", "番外編", "Special"])
    def test_a_title_with_more_than_the_number_is_kept(self, scraper, site, title):
        chapters = self._chapters_from(scraper, site, [_row(index=12, title=title)])
        assert (chapters[0].number, chapters[0].title) == ("12", title)

    @pytest.mark.parametrize("index, title", [
        (12, "第13話"), (12, "第12.5話"), (12.5, "第12話"), (12, "第21話 x")])
    def test_a_title_and_index_that_disagree_raise(self, scraper, site, index, title):
        with pytest.raises(MangaRwSourceError, match="disagree"):
            self._chapters_from(scraper, site, [_row(index=index, title=title)])

    @pytest.mark.parametrize("change", [
        {"id": None}, {"id": True}, {"id": 0}, {"id": -1}, {"id": "9003"}, {"id": 9.5},
        {"index": None}, {"index": True}, {"index": "3"}, {"index": -1}, {"index": 1e30},
        {"index": [3]},
        {"title": None}, {"title": "  "}, {"title": 3},
        {"createdAt": None}, {"createdAt": ""}, {"createdAt": 1700000000},
        {"createdAt": "2026-01-02"}, {"createdAt": "2026-01-02T03:04:05Z"},
        {"createdAt": "2026-13-02T03:04:05.678Z"},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_a_row_with_an_unusable_field_raises(self, scraper, site, change):
        row = _row()
        row.update(change)
        with pytest.raises(MangaRwSourceError):
            self._chapters_from(scraper, site, [row])

    @pytest.mark.parametrize("extra", ["isLocked", "price", "unexpected"])
    def test_a_row_with_an_unknown_field_fails_instead_of_being_read(self, scraper, site, extra):
        row = _row()
        row[extra] = False
        with pytest.raises(MangaRwSourceError, match="known shape"):
            self._chapters_from(scraper, site, [row])

    @pytest.mark.parametrize("missing", ["id", "title", "index", "createdAt"])
    def test_a_row_with_a_missing_field_raises(self, scraper, site, missing):
        row = _row()
        del row[missing]
        with pytest.raises(MangaRwSourceError, match="known shape"):
            self._chapters_from(scraper, site, [row])

    def test_a_row_that_is_not_an_object_raises(self, scraper, site):
        with pytest.raises(MangaRwSourceError):
            self._chapters_from(scraper, site, ["x"])

    def test_a_repeated_id_raises(self, scraper, site):
        with pytest.raises(MangaRwSourceError, match="id is listed twice"):
            self._chapters_from(scraper, site, [_row(9001, 1), _row(9001, 2)])

    @pytest.mark.parametrize("first, second", [(5, 5), (5, 5.0), (5.5, 5.5)])
    def test_a_repeated_number_raises(self, scraper, site, first, second):
        rows = [_row(9001, first, "x"), _row(9002, second, "y")]
        with pytest.raises(MangaRwSourceError, match="number is listed twice"):
            self._chapters_from(scraper, site, rows)

    def test_an_empty_list_raises(self, scraper, site):
        with pytest.raises(MangaRwSourceError, match="no chapters"):
            self._chapters_from(scraper, site, [])

    @pytest.mark.parametrize("stated", [0, 1, 3])
    def test_a_list_that_disagrees_with_the_stated_count_raises(self, scraper, site, stated):
        served, _ = site
        served[SERIES_API] = _json(_series(stated))
        served[CHAPTERS_API] = _json([_row(9001, 1), _row(9002, 2)])
        with pytest.raises(MangaRwSourceError, match="the series states"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"id": 702}, {"id": None}, {"id": "701"}, {"id": True}, {"title": ""}, {"title": None},
        {"isAdult": None}, {"isAdult": 0}, {"chapterCount": None}, {"chapterCount": "1"},
        {"chapterCount": True}, {"chapterCount": -1},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_an_unusable_series_reply_raises(self, scraper, site, change):
        served, _ = site
        served[SERIES_API] = _json(_series(1, **change))
        served[CHAPTERS_API] = _json([_row()])
        with pytest.raises(MangaRwSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_an_adult_series_is_listed(self, scraper, site):
        chapters = self._chapters_from(scraper, site, [_row()], isAdult=True)
        assert [c.number for c in chapters] == ["3"]

    @pytest.mark.parametrize("data", [None, {}, "x", {"rows": []}])
    def test_a_chapter_reply_without_a_list_raises(self, scraper, site, data):
        served, _ = site
        served[SERIES_API] = _json(_series(1))
        served[CHAPTERS_API] = _json(data)
        with pytest.raises(MangaRwSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _Reply(status=204), _Reply(b"<html>challenge</html>"),
        _Reply(b'{"data": NaN}'), _Reply(b"[]"), _Reply(b'{"data": [], "extra": 1}'),
        _http_error(403), _http_error(503), requests.Timeout("slow"),
    ], ids=["redirect", "no-content", "html", "nan", "not-object", "extra-top-key", "403", "503",
            "timeout"])
    @pytest.mark.parametrize("endpoint", [SERIES_API, CHAPTERS_API], ids=["series", "chapters"])
    def test_a_failed_reply_raises(self, scraper, site, endpoint, reply):
        served, _ = site
        served[SERIES_API] = _json(_series(1))
        served[CHAPTERS_API] = _json([_row()])
        served[endpoint] = reply
        with pytest.raises(MangaRwSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_an_oversized_reply_fails(self, monkeypatch, scraper, site):
        served, _ = site
        monkeypatch.setattr(mangarw, "_MAX_REPLY_BYTES", 8)
        reply = _json(_series(1))
        served[SERIES_API] = reply
        with pytest.raises(MangaRwSourceError, match="too large"):
            scraper.get_chapters(SERIES_URL)
        assert reply.closed

    def test_the_listing_logs_its_scope(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.mangarw")
        self._chapters_from(scraper, site, [_row()])
        assert "listing the 1 chapter(s) the API names" in caplog.text

    def test_a_url_that_is_not_a_series_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_chapters(f"{BASE}/browse")
        assert calls == []


class TestCover:
    def test_the_series_cover(self, scraper, site):
        served, _ = site
        served[SERIES_API] = _json(_series())
        assert scraper.get_cover_url(SERIES_URL) == "https://cdn.example/covers/test.jpg"

    @pytest.mark.parametrize("image", [None, "", "/c.jpg", "http://x/c.jpg", 7])
    def test_no_usable_cover(self, scraper, site, image):
        served, _ = site
        served[SERIES_API] = _json(_series(image=image))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_a_failure_is_no_cover(self, scraper, site):
        served, calls = site
        served[SERIES_API] = _http_error(503)
        assert scraper.get_cover_url(SERIES_URL) is None
        assert scraper.get_cover_url("https://example.com/x") is None
        assert len(calls) == 1


# ── Pages ─────────────────────────────────────────────────────────────


def _set_range(data, **values):
    data["content"][0]["data"].update(values)


class TestPages:
    def test_a_range_expands_in_order(self, scraper, site):
        served, calls = site
        served[READER_API] = _json(_reader(0, 14))
        assert scraper.get_pages(CHAPTER_URL) == [_page(n) for n in range(15)]
        assert [c[0] for c in calls] == [READER_API]
        assert calls[0][1]["allow_redirects"] is False

    @pytest.mark.parametrize("first, last, numbers", [(0, 0, [0]), (1, 3, [1, 2, 3])])
    def test_the_served_range_is_used(self, scraper, site, first, last, numbers):
        served, _ = site
        served[READER_API] = _json(_reader(first, last))
        assert scraper.get_pages(CHAPTER_URL) == [_page(n) for n in numbers]

    def test_an_adult_flag_on_the_series_is_accepted(self, scraper, site):
        served, _ = site
        data = _reader()
        data["manga"]["isAdult"] = True
        served[READER_API] = _json(data)
        assert len(scraper.get_pages(CHAPTER_URL)) == 3

    @pytest.mark.parametrize("change, why", [
        (lambda d: d.update(id=9004), "this chapter"),
        (lambda d: d.update(id="9003"), "this chapter"),
        (lambda d: d.update(id=True), "this chapter"),
        (lambda d: d.update(mangaId=702), "this series"),
        (lambda d: d.update(mangaId="701"), "this series"),
        (lambda d: d["manga"].update(id=702), "this series"),
        (lambda d: d["manga"].update(isAdult=None), "this series"),
        (lambda d: d["manga"].pop("image"), "this series"),
        (lambda d: d["manga"].update(extra=1), "this series"),
        (lambda d: d.update(manga=None), "this series"),
        (lambda d: d.update(title=""), "title"),
        (lambda d: d["manga"].update(title=None), "title"),
        (lambda d: d.update(isLocked=False), "known shape"),
        (lambda d: d.pop("content"), "known shape"),
    ], ids=["other-chapter", "string-id", "bool-id", "other-series", "string-series",
            "owner-other-series", "owner-adult-null", "owner-missing-key", "owner-extra-key",
            "no-owner", "empty-title", "owner-no-title", "unknown-field", "no-content"])
    def test_a_reply_for_something_else_raises(self, scraper, site, change, why):
        served, _ = site
        data = _reader()
        change(data)
        served[READER_API] = _json(data)
        with pytest.raises(MangaRwSourceError, match=why):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("storage", [
        "https://evil.example", "http://storage.mangabuzz.org",
        "https://storage.mangabuzz.org/", "https://cdn.mangabuzz.org", None])
    def test_another_image_host_raises(self, scraper, site, storage):
        served, _ = site
        data = _reader()
        data["storageUrl"] = storage
        served[READER_API] = _json(data)
        with pytest.raises(MangaRwSourceError, match="image host"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("change", [
        lambda d: d.update(content=[]),
        lambda d: d.update(content={}),
        lambda d: d.update(content=None),
        lambda d: d.update(content=[d["content"][0], d["content"][0]]),
        lambda d: d.update(content=["x"]),
        lambda d: d["content"][0].update(type="hotlink"),
        lambda d: d["content"][0].update(type="external"),
        lambda d: d["content"][0].update(extra=1),
        lambda d: d["content"][0].update(data=[]),
        lambda d: d["content"][0]["data"].update(extra=1),
        lambda d: d["content"][0]["data"].pop("url"),
    ], ids=["empty", "object", "null", "two-blocks", "text-block", "hotlink", "external",
            "block-extra", "data-list", "range-extra", "range-no-url"])
    def test_an_unsupported_page_list_raises(self, scraper, site, change):
        served, _ = site
        data = _reader()
        change(data)
        served[READER_API] = _json(data)
        with pytest.raises(MangaRwSourceError, match="unsupported page list"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("values", [
        {"from": 3, "to": 2}, {"from": -1}, {"from": True}, {"from": "0"}, {"from": None},
        {"to": "2"}, {"to": None}, {"to": 1.5}, {"from": 0, "to": 1000},
        {"from": 99999, "to": 100000},
    ], ids=lambda v: repr(v))
    def test_an_unusable_range_raises(self, scraper, site, values):
        served, _ = site
        data = _reader()
        _set_range(data, **values)
        served[READER_API] = _json(data)
        with pytest.raises(MangaRwSourceError, match="page range"):
            scraper.get_pages(CHAPTER_URL)

    def test_the_largest_range_is_accepted(self, scraper, site):
        served, _ = site
        served[READER_API] = _json(_reader(0, 999))
        assert len(scraper.get_pages(CHAPTER_URL)) == 1000

    @pytest.mark.parametrize("template", [
        None, 7, "", f"{PAGE_ID}/{{page}}.webp", f"/{PAGE_ID}/0.webp", f"/{PAGE_ID}/{{page}}.jpg",
        f"/{PAGE_ID}/{{page}}/{{page}}.webp", f"/../{PAGE_ID}/{{page}}.webp", "/x/{page}.webp",
        f"https://evil.example/{PAGE_ID}/{{page}}.webp", f"/{PAGE_ID}/{{page}}.webp?x=1",
    ])
    def test_an_unusable_page_address_raises(self, scraper, site, template):
        served, _ = site
        data = _reader()
        _set_range(data, url=template)
        served[READER_API] = _json(data)
        with pytest.raises(MangaRwSourceError, match="page address"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _Reply(b"<html></html>"), _Reply(b"[]"), _http_error(403),
        requests.ConnectionError("reset"),
    ], ids=["redirect", "not-json", "not-object", "403", "transport"])
    def test_a_failed_reader_raises(self, scraper, site, reply):
        served, _ = site
        served[READER_API] = reply
        with pytest.raises(MangaRwSourceError):
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
        assert scraper.download_image(_page(0), path) is True
        assert path.read_bytes() == picture
        assert calls[0][0] == _image(0)
        kwargs = calls[0][1]
        assert kwargs["headers"]["Referer"] == f"{BASE}/read?id=9003"
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        assert reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(b"<html>blocked</html>"), _Reply(b""), _Reply(status=302),
        _Reply(b"partial", status=206), _http_error(403), _http_error(503),
        requests.ConnectionError("reset"), requests.exceptions.ChunkedEncodingError("cut"),
    ], ids=["html", "empty", "redirect", "partial", "403", "503", "transport", "cut"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        served, _ = site
        served[_image(0)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_page(0), path) is False
        assert not path.exists()

    def test_a_body_that_breaks_while_streaming_fails(self, scraper, site, tmp_path):
        served, _ = site

        class _Broken(_Reply):
            def iter_content(self, size):
                yield _webp()[:4]
                raise requests.exceptions.ChunkedEncodingError("cut")

        reply = _Broken()
        served[_image(0)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_page(0), path) is False
        assert not path.exists() and reply.closed

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        served, _ = site
        monkeypatch.setattr(mangarw, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(_webp())
        served[_image(0)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_page(0), path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        f"https://evil.example/{PAGE_ID}/0.webp#chapter=9003",
        f"http://storage.mangabuzz.org/{PAGE_ID}/0.webp#chapter=9003",
        f"{STORAGE}/{PAGE_ID}/0.webp?x=1#chapter=9003", f"{STORAGE}/{PAGE_ID}/0.webp",
        f"{STORAGE}/{PAGE_ID}/0.webp#x", f"{STORAGE}/{PAGE_ID}/0.webp#chapter=0",
        f"{STORAGE}/{PAGE_ID}/0.webp#chapter=abc", f"{STORAGE}/{PAGE_ID}/0.jpg#chapter=9003",
        f"{STORAGE}/{PAGE_ID}/01.webp#chapter=9003", f"{STORAGE}/x/0.webp#chapter=9003",
        f"https://storage.mangabuzz.org:8443/{PAGE_ID}/0.webp#chapter=9003", None,
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
        assert MangaRwScraper.name == "mangarw"
        assert MangaRwScraper.base_url == BASE
        assert MangaRwScraper.engine == "api"
        assert MangaRwScraper.nsfw is True

    def test_no_language_or_direction_is_claimed(self):
        assert MangaRwScraper.content_language is None
        assert MangaRwScraper.reading_direction is None
        assert _manga_language({"title": "Unknown series"}, MangaRwScraper()) is None

    def test_cookies_are_not_kept(self):
        scraper = MangaRwScraper()
        policy = scraper.session.cookies.get_policy()
        assert isinstance(policy, http.cookiejar.DefaultCookiePolicy)
        assert policy.allowed_domains() == ()
        assert scraper.worker_copy().session.cookies.get_policy().allowed_domains() == ()
