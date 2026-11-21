"""Offline tests for ManhuaTop: URL identity, search, the paged chapter
list, reader pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the API's field names. Their values for fields whose form
is not known (ids, dates, ``extra``, ``pageCount``, ``index``) are stand-ins
and say nothing about what the site serves.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import manhuatop as mt
from memanga.scrapers.manhuatop import (ManhuaTopScraper, ManhuaTopSourceError,
                                        ManhuaTopUnsupportedError)

SITE = "https://manhuatop.org"
SLUG = "martial-god"
SERIES = f"{SITE}/manhua/{SLUG}/"
CHAPTER = f"{SERIES}chapter-135/"
SEARCH = f"{SITE}/api/discovery?path=/search/martial/"
CONTENT = f"{SITE}/api/reader?resource=content&path=%2Fmanhua%2F{SLUG}%2Fchapter-135%2F"
IMAGE = "https://s3.manhuatop.org/manga/1/135/{:03d}.jpg"
IMAGES = [IMAGE.format(n) for n in range(1, 16)]


class _Response:
    def __init__(self, url, status=200, data=None, text=None, content=None):
        self.url = url
        self.status_code = status
        self.text = json.dumps(data) if text is None else text
        self.content = self.text.encode() if content is None else content
        self.headers = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    """Answers each URL from ``routes``; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(url, **self.routes[url])


def _site(routes):
    scraper = ManhuaTopScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


def _chapters_url(page):
    return (f"{SITE}/api/reader?resource=chapters&path=%2Fmanhua%2F{SLUG}%2F"
            f"%3Ftab%3Dchapters%26chapter_page%3D{page}")


def _row(number, **overrides):
    slug = f"chapter-{str(number).replace('.', '-')}"
    row = {"id": 1000 + int(float(number) * 10), "mangaId": 7, "volumeId": 0, "slug": slug,
           "title": f"Chapter {number}", "extra": None, "date": "2026-04-19",
           "path": f"/manhua/{SLUG}/{slug}/"}
    row.update(overrides)
    return row


def _page(rows, total, page=1, has_more=False):
    return {"hasMore": has_more, "items": rows, "order": "desc", "page": page,
            "revision": 1, "total": total}


def _routes(*pages, total=None):
    total = sum(len(rows) for rows in pages) if total is None else total
    return {_chapters_url(n): dict(data=_page(rows, total, n, n < len(pages)))
            for n, rows in enumerate(pages, 1)}


def _chapters(*pages, **kwargs):
    return _site(_routes(*pages, **kwargs)).get_chapters(SERIES)


def _card(path, title="Martial God"):
    return {"id": 1, "slug": "x", "title": title, "excerpt": "", "path": path,
            "status": "on-going", "contentFormat": "x", "updatedAt": "x", "thumbnail": None,
            "rating": 0, "votes": 0, "views": 0, "mangaType": "x", "badge": "unknown",
            "latestChapters": [], "trendingViews": 0}


def _results(*cards, has_more=False):
    return {"hasMore": has_more, "items": list(cards), "page": 1, "perPage": 24,
            "state": {}, "synthetic": False, "trending": []}


def _content(images=None, **overrides):
    urls = IMAGES if images is None else images
    data = {"images": [{"index": i, "url": url, "width": 720, "height": 13378}
                       for i, url in enumerate(urls)],
            "pageCount": len(urls), "revision": 1, "type": "image"}
    data.update(overrides)
    return data


def _pages(data):
    return _site({CONTENT: dict(data=data)}).get_pages(CHAPTER)


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url", [
        SERIES, f"{SITE}/manhua/{SLUG}", f"https://www.manhuatop.org/manhua/{SLUG}/",
        f"http://manhuatop.org/manhua/{SLUG}/",
    ])
    def test_a_series_url_has_one_slug(self, url):
        assert ManhuaTopScraper()._series_slug(url) == SLUG

    @pytest.mark.parametrize("url", [
        "https://manhuatop.org.example.test/manhua/x/",
        "https://s3.manhuatop.org/manhua/x/",
        "https://u@manhuatop.org/manhua/x/",
        "https://manhuatop.org:8443/manhua/x/",
        "https://manhuatop.org/manhua/x/?tab=chapters",
        "https://manhuatop.org/manhua/x/#top",
        "ftp://manhuatop.org/manhua/x/",
        "/manhua/x/",
        "https://manhuatop.org/manhua/",
        "https://manhuatop.org/manga/x/",
        "https://manhuatop.org/manhua/x/chapter-1/",
        "https://manhuatop.org/manhua//x/",
        "https://manhuatop.org/manhua/../x/",
        "https://manhuatop.org/manhua/x y/",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ManhuaTopUnsupportedError):
            ManhuaTopScraper()._series_slug(url)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}chapter-1/extra/", f"{SITE}/"])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site({})

        with pytest.raises(ManhuaTopUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (ManhuaTopScraper.engine, ManhuaTopScraper.content_language,
                ManhuaTopScraper.nsfw) == ("api", "en", False)
        assert ManhuaTopScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = ManhuaTopScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("session", "x", domain=".manhuatop.org"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_in_the_sites_order(self):
        scraper = _site({SEARCH: dict(data=_results(
            _card("/manhua/one/", "One"), _card("/manhua/two/", "Two"), has_more=True))})

        results = scraper.search(" martial ")

        assert [(m.title, m.url) for m in results] == [
            ("One", f"{SITE}/manhua/one/"), ("Two", f"{SITE}/manhua/two/")]
        (url, kwargs), = scraper.session.calls
        assert url == SEARCH and kwargs["allow_redirects"] is False

    def test_a_query_is_one_segment_of_the_nested_address(self):
        url = f"{SITE}/api/discovery?path=/search/solo%2520leveling%2526x%252Fy/"
        scraper = _site({url: dict(data=_results())})

        assert scraper.search("solo leveling&x/y") == []
        assert scraper.session.calls[0][0] == url

    def test_a_blank_query_sends_nothing(self):
        scraper = _site({})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_a_one_character_query_is_an_error_and_sends_nothing(self):
        scraper = _site({})

        with pytest.raises(ManhuaTopSourceError, match="at least 2"):
            scraper.search(" a ")
        assert scraper.session.calls == []

    def test_an_empty_result_list_is_no_results(self):
        assert _site({SEARCH: dict(data=_results())}).search("martial") == []

    @pytest.mark.parametrize("route", [
        dict(text="<html>Just a moment...</html>"),
        dict(data=[]),
        dict(data={"hasMore": False}),
        dict(data={"items": []}),
        dict(data={"items": "x", "hasMore": False}),
        dict(data={"items": [], "hasMore": "false"}),
        dict(data={"items": [], "hasMore": True}),
    ], ids=["html", "not-object", "no-items", "no-has-more", "items-not-list",
            "has-more-not-bool", "empty-with-more"])
    def test_an_answer_that_is_not_a_result_list_is_an_error(self, route):
        with pytest.raises(ManhuaTopSourceError):
            _site({SEARCH: route}).search("martial")

    @pytest.mark.parametrize("card", [
        "x",
        {"path": "/manhua/x/"},
        _card("/manhua/x/", title="  "),
        _card("/manhua/x/", title=None),
        {"title": "X", "path": None},
        _card("https://example.test/manhua/x/"),
        _card("//example.test/manhua/x/"),
        _card("/manhua/x/chapter-1/"),
        _card("/novel/x/"),
    ], ids=["not-object", "no-title", "blank-title", "null-title", "null-path", "other-site",
            "scheme-relative", "chapter", "other-kind"])
    def test_a_result_that_cannot_be_read_is_an_error(self, card):
        with pytest.raises(ManhuaTopSourceError):
            _site({SEARCH: dict(data=_results(card))}).search("martial")

    def test_a_repeated_result_is_listed_once(self):
        scraper = _site({SEARCH: dict(data=_results(
            _card("/manhua/one/"), _card("/manhua/one/", "Again")))})

        assert len(scraper.search("martial")) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_SEARCH_RESULTS", 2)
        cards = [_card(f"/manhua/s{n}/") for n in range(5)]

        assert len(_site({SEARCH: dict(data=_results(*cards))}).search("martial")) == 2

    def test_a_redirected_search_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="HTTP 301"):
            _site({SEARCH: dict(status=301, data={})}).search("martial")

    def test_a_refused_search_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403, data={})}).search("martial")


# ── Chapters ────────────────────────────────────────────────────────

def _rows(*numbers):
    return [_row(n) for n in numbers]


class TestChapterPagination:
    def test_the_whole_list_at_the_size_the_site_serves(self, caplog):
        # 137 rows over pages of 50, 50 and 37. The middle page's extra
        # half chapter is a stand-in for a row not yet seen.
        first = _rows(*range(135, 85, -1))
        middle = _rows(*range(85, 62, -1), "62.5", *range(62, 36, -1))
        last = _rows(*range(36, -1, -1))
        scraper = _site(_routes(first, middle, last))

        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = scraper.get_chapters(SERIES)

        assert (len(first), len(middle), len(last)) == (50, 50, 37)
        assert len(chapters) == 137
        assert (chapters[0].number, chapters[-1].number) == ("135", "0")
        assert "62.5" in [c.number for c in chapters]
        assert len({c.url for c in chapters}) == 137
        assert [url for url, _ in scraper.session.calls] == [
            _chapters_url(1), _chapters_url(2), _chapters_url(3)]
        assert all(kw["allow_redirects"] is False for _, kw in scraper.session.calls)
        assert caplog.text == ""

    def test_the_page_size_is_not_assumed(self):
        chapters = _chapters(_rows(7, 6, 5), _rows(4, 3, 2), _rows(1))

        assert [c.number for c in chapters] == ["7", "6", "5", "4", "3", "2", "1"]

    def test_one_page_is_one_request(self):
        scraper = _site(_routes(_rows(2, 1)))

        assert len(scraper.get_chapters(SERIES)) == 2
        assert len(scraper.session.calls) == 1

    @pytest.mark.parametrize("second, why", [
        (_page(_rows(3), 5, 2, True), "has 1 rows, not 2"),
        (_page([], 5, 2, True), "has 0 rows, not 2"),
        (_page(_rows(3, 2), 6, 2, True), "states 6 chapters, not 5"),
        (_page(_rows(3, 2, 1, 0), 5, 2, False), "more rows than its total"),
        (_page(_rows(3, 2), 5, 1, True), "served page 1"),
        (_page(_rows(3, 2), 5, 2, False), "about further pages"),
    ], ids=["short-middle-page", "empty-page", "total-changes", "too-many-rows", "same-page-again",
            "says-no-more-too-early"])
    def test_a_list_that_does_not_add_up_is_an_error(self, second, why):
        routes = {_chapters_url(1): dict(data=_page(_rows(5, 4), 5, 1, True)),
                  _chapters_url(2): dict(data=second),
                  _chapters_url(3): dict(data=_page(_rows(1), 5, 3, False))}

        with pytest.raises(ManhuaTopSourceError, match=why):
            _site(routes).get_chapters(SERIES)

    def test_saying_there_are_more_on_the_last_page_is_an_error(self):
        routes = {_chapters_url(1): dict(data=_page(_rows(2, 1), 2, 1, True))}

        with pytest.raises(ManhuaTopSourceError, match="about further pages"):
            _site(routes).get_chapters(SERIES)

    @pytest.mark.parametrize("data", [
        {"items": _rows(1)},
        {"total": 1},
        {"items": "x", "total": 1},
        {"items": _rows(1), "total": "1"},
        {"items": _rows(1), "total": True},
        {"items": _rows(1), "total": -1},
        [],
    ], ids=["no-total", "no-items", "items-not-list", "total-text", "total-bool", "total-negative",
            "not-object"])
    def test_an_answer_without_rows_and_total_is_an_error(self, data):
        with pytest.raises(ManhuaTopSourceError):
            _site({_chapters_url(1): dict(data=data)}).get_chapters(SERIES)

    @pytest.mark.parametrize("data", [_page([], 0), _page([], 3)], ids=["zero", "rows-missing"])
    def test_a_series_without_chapters_is_an_error_not_an_empty_list(self, data):
        with pytest.raises(ManhuaTopSourceError, match="lists no chapters"):
            _site({_chapters_url(1): dict(data=data)}).get_chapters(SERIES)

    def test_a_refused_later_page_fails_the_list(self):
        routes = _routes(_rows(4, 3), _rows(2, 1))
        routes[_chapters_url(2)] = dict(status=403, data={})

        with pytest.raises(requests.HTTPError):
            _site(routes).get_chapters(SERIES)

    def test_a_redirected_list_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="HTTP 302"):
            _site({_chapters_url(1): dict(status=302, data={})}).get_chapters(SERIES)

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_CHAPTERS", 1)

        with pytest.raises(ManhuaTopSourceError, match="more chapters"):
            _chapters(_rows(2, 1))


class TestChapterRows:
    def test_row_fields(self):
        chapter, = _chapters([_row(12, date="2026-04-19")])

        assert (chapter.number, chapter.title, chapter.url, chapter.date) == (
            "12", "Chapter 12", f"{SERIES}chapter-12/", "2026-04-19")

    def test_a_half_chapter_and_chapter_zero(self):
        chapters = _chapters(_rows("1.5", 1, 0))

        assert [c.number for c in chapters] == ["1.5", "1", "0"]
        assert chapters[0].url == f"{SERIES}chapter-1-5/"

    def test_an_extra_label_is_shown_and_changes_nothing_else(self):
        chapter, = _chapters([_row(3, extra="  Season  2 ")])

        assert (chapter.number, chapter.title) == ("3", "Chapter 3 - Season 2")

    @pytest.mark.parametrize("extra", [None, "", "  ", 7, {"x": 1}])
    def test_any_other_extra_is_not_read(self, extra):
        chapter, = _chapters([_row(3, extra=extra)])

        assert chapter.title == "Chapter 3"

    @pytest.mark.parametrize("overrides", [
        {"badge": "unknown"}, {"synthetic": True}, {"volumeId": None},
    ], ids=["badge", "synthetic", "no-volume"])
    def test_unknown_fields_do_not_drop_a_row(self, overrides):
        assert len(_chapters([_row(3, **overrides)])) == 1

    @pytest.mark.parametrize("date", [None, "", 20260419])
    def test_a_date_that_is_not_text_is_left_out(self, date):
        assert _chapters([_row(3, date=date)])[0].date is None

    def test_the_same_link_listed_twice_is_one_chapter_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _chapters([_row(3), _row(3, id=9999), _row(2)])

        assert [c.number for c in chapters] == ["3", "2"]
        assert "1 chapter row(s)" in caplog.text and "repeat" in caplog.text

    def test_two_links_for_one_number_is_an_error(self):
        other = _row(5, slug="chapter-5-0", path=f"/manhua/{SLUG}/chapter-5-0/", id=2)

        with pytest.raises(ManhuaTopSourceError, match="two links for chapter 5"):
            _chapters([_row(5, id=1), other])

    def test_one_link_with_two_numbers_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="not a plain numbered"):
            _chapters([_row(5), _row(5, title="Chapter 6")])

    def test_one_id_with_two_links_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="one chapter id two links"):
            _chapters([_row(5, id=1), _row(4, id=1)])

    def test_rows_of_two_series_are_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="mixes several series"):
            _chapters([_row(5), _row(4, mangaId=8)])

    @pytest.mark.parametrize("overrides", [{"id": None}, {"id": ""}, {"id": True}, {"mangaId": None}],
                             ids=["no-id", "blank-id", "bool-id", "no-series-id"])
    def test_a_row_without_its_ids_is_an_error(self, overrides):
        with pytest.raises(ManhuaTopSourceError, match="without its ids"):
            _chapters([_row(5, **overrides)])

    @pytest.mark.parametrize("path", [None, ""], ids=["null", "empty"])
    def test_a_row_without_a_reader_link_stops_the_list(self, path):
        with pytest.raises(ManhuaTopSourceError, match="without a reader link"):
            _chapters([_row(5), _row(4, path=path)])

    @pytest.mark.parametrize("path", [
        "/manhua/other/chapter-4/",
        "/manhua/martial-god/chapter-5/",
        "/manhua/martial-god/",
        "/manhua/martial-god/chapter-4/x/",
        "https://example.test/manhua/martial-god/chapter-4/",
        "//example.test/manhua/martial-god/chapter-4/",
        "chapter-4/",
    ], ids=["other-series", "other-chapter", "series", "deep", "other-site", "scheme-relative",
            "relative"])
    def test_a_row_linked_elsewhere_is_an_error(self, path):
        with pytest.raises(ManhuaTopSourceError):
            _chapters([_row(4, path=path)])

    @pytest.mark.parametrize("overrides", [
        {"title": "Volume 3"},
        {"title": "Chapter"},
        {"title": "chapter 4"},
        {"title": "Chapter 5"},
        {"title": "Chapter 4 : End"},
        {"title": "Chapter 4,5"},
        {"title": None},
        {"title": "Chapter " + "9" * 400},
        {"slug": "extra-4", "path": f"/manhua/{SLUG}/extra-4/"},
        {"slug": "chapter-4-2", "path": f"/manhua/{SLUG}/chapter-4-2/"},
        {"slug": None},
    ], ids=["volume", "no-number", "lowercase", "numbers-disagree", "with-text", "comma",
            "null-title", "oversized", "other-slug", "slug-part", "null-slug"])
    def test_a_row_without_one_clear_number_is_an_error(self, overrides):
        with pytest.raises(ManhuaTopSourceError):
            _chapters([_row(4, **overrides)])

    SUFFIXED = dict(slug="chapter-115_1", path=f"/manhua/{SLUG}/chapter-115_1/")

    def test_a_served_suffixed_row_keeps_its_link_and_the_titles_number(self):
        served = _row(115, id="940748", mangaId="88737", volumeId=None, title="Chapter 115",
                      extra="", date="2026-05-04T16:08:26Z", **self.SUFFIXED)

        chapters = _chapters([_row(116, mangaId="88737"), served, _row(114, mangaId="88737")])

        assert [c.number for c in chapters] == ["116", "115", "114"]
        assert (chapters[1].title, chapters[1].url, chapters[1].date) == (
            "Chapter 115", f"{SERIES}chapter-115_1/", "2026-05-04T16:08:26Z")

    def test_a_suffixed_chapter_is_read_at_its_served_path(self):
        url = f"{SITE}/api/reader?resource=content&path=%2Fmanhua%2F{SLUG}%2Fchapter-115_1%2F"
        scraper = _site({url: dict(data=_content())})

        assert scraper.get_pages(f"{SERIES}chapter-115_1/") == IMAGES
        assert scraper.session.calls[0][0] == url

    @pytest.mark.parametrize("title, slug", [
        ("Chapter 116", "chapter-115_1"),
        ("Chapter 115.1", "chapter-115_1"),
        ("Chapter 115", "chapter-115_2"),
        ("Chapter 115", "chapter-115_"),
        ("Chapter 115", "chapter-115_1_1"),
        ("Chapter 115.5", "chapter-115-5_1"),
        ("Chapter 115", "chapter_115_1"),
    ], ids=["other-number", "suffix-as-decimal", "unobserved-suffix", "empty-suffix",
            "two-suffixes", "suffix-on-decimal", "other-separator"])
    def test_a_suffix_is_read_only_in_its_served_form(self, title, slug):
        row = _row(115, title=title, slug=slug, path=f"/manhua/{SLUG}/{slug}/")

        with pytest.raises(ManhuaTopSourceError, match="not a plain numbered"):
            _chapters([row])

    @pytest.mark.parametrize("path", [
        f"/manhua/{SLUG}/chapter-115/", "/manhua/other/chapter-115_1/",
    ], ids=["path-without-suffix", "other-series"])
    def test_a_suffixed_slug_must_match_its_served_path(self, path):
        row = _row(115, slug="chapter-115_1", path=path)

        with pytest.raises(ManhuaTopSourceError, match="not a chapter of it"):
            _chapters([row])

    def test_a_plain_and_a_suffixed_link_for_one_number_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="two links for chapter 115"):
            _chapters([_row(115, id=1), _row(115, id=2, **self.SUFFIXED)])

    def test_the_same_suffixed_link_listed_twice_is_one_chapter(self, caplog):
        row = _row(115, **self.SUFFIXED)

        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _chapters([row, dict(row)])

        assert [c.url for c in chapters] == [f"{SERIES}chapter-115_1/"]
        assert "1 chapter row(s)" in caplog.text

    def test_a_row_that_is_not_an_object_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="malformed row"):
            _chapters(["x"])


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_reader_order(self):
        scraper = _site({CONTENT: dict(data=_content())})

        assert scraper.get_pages(CHAPTER) == IMAGES
        (url, kwargs), = scraper.session.calls
        assert url == CONTENT and kwargs["allow_redirects"] is False

    def test_a_chapter_url_without_its_slash_is_the_same_chapter(self):
        scraper = _site({CONTENT: dict(data=_content())})

        assert scraper.get_pages(CHAPTER.rstrip("/")) == IMAGES

    def test_a_long_strip_is_a_normal_page(self):
        data = _content(IMAGES[:1])
        data["images"][0].update(width=720, height=65535)

        assert _pages(data) == IMAGES[:1]

    def test_an_image_over_the_pixel_limit_is_an_error(self):
        data = _content(IMAGES[:1])
        data["images"][0].update(width=4096, height=65535)

        with pytest.raises(ManhuaTopSourceError, match="invalid page size"):
            _pages(data)

    @pytest.mark.parametrize("size", [(-1, 10), (10, -1)])
    def test_a_negative_size_is_an_error(self, size):
        data = _content(IMAGES[:1])
        data["images"][0].update(width=size[0], height=size[1])

        with pytest.raises(ManhuaTopSourceError, match="invalid page size"):
            _pages(data)

    @pytest.mark.parametrize("size", [(None, None), ("720", "13378"), (0, 0)])
    def test_a_size_that_says_nothing_does_not_drop_a_page(self, size):
        data = _content(IMAGES[:1])
        data["images"][0].update(width=size[0], height=size[1])

        assert _pages(data) == IMAGES[:1]

    def test_a_stated_count_that_differs_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="states 16 pages"):
            _pages(_content(pageCount=16))

    @pytest.mark.parametrize("stated", [None, "15"])
    def test_a_count_in_another_form_is_not_read(self, stated):
        assert _pages(_content(pageCount=stated)) == IMAGES

    def test_pages_numbered_from_one_are_in_order(self):
        data = _content(IMAGES[:3])
        for n, image in enumerate(data["images"], 1):
            image["index"] = n

        assert _pages(data) == IMAGES[:3]

    @pytest.mark.parametrize("indexes", [(1, 0, 2), (0, 2, 3), (5, 6, 7), (0, 0, 1)],
                             ids=["swapped", "gap", "late-start", "repeat"])
    def test_pages_served_out_of_order_are_an_error(self, indexes):
        data = _content(IMAGES[:3])
        for index, image in zip(indexes, data["images"]):
            image["index"] = index

        with pytest.raises(ManhuaTopSourceError, match="out of order"):
            _pages(data)

    @pytest.mark.parametrize("bad", [
        "",
        None,
        7,
        "http://s3.manhuatop.org/manga/1/a.jpg",
        "/manga/1/a.jpg",
        "//s3.manhuatop.org/manga/1/a.jpg",
        "https://manhuatop.org/manga/1/a.jpg",
        "https://s4.manhuatop.org/manga/1/a.jpg",
        "https://s3.manhuatop.org.example.test/manga/1/a.jpg",
        "https://s3.manhuatop.org:8443/manga/1/a.jpg",
        "https://u@s3.manhuatop.org/manga/1/a.jpg",
        "https://s3.manhuatop.org/manga/1/a.jpg?x=1",
        "https://s3.manhuatop.org/manga/1/a.jpg#x",
        "https://s3.manhuatop.org/manga/../a.jpg",
        "https://s3.manhuatop.org/manga/1/a.svg",
        " https://s3.manhuatop.org/manga/1/a.jpg",
        "data:image/png;base64,AAAA",
    ], ids=["empty", "null", "number", "http", "relative", "scheme-relative", "site-host",
            "other-shard", "lookalike", "port", "login", "query", "fragment", "dot-dot", "svg",
            "leading-space", "data-uri"])
    def test_an_invalid_page_is_an_error_and_never_dropped(self, bad):
        data = _content([IMAGES[0], IMAGES[1]])
        data["images"].append({"index": 2, "url": bad, "width": 720, "height": 1000})
        data["pageCount"] = 3

        with pytest.raises(ManhuaTopSourceError, match="not an image of this site"):
            _pages(data)

    def test_a_repeated_page_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="twice"):
            _pages(_content([IMAGES[0], IMAGES[1], IMAGES[0]]))

    @pytest.mark.parametrize("data", [
        {"pageCount": 0}, {"images": []}, {"images": "x"}, {"images": None},
    ], ids=["no-images", "empty", "not-list", "null"])
    def test_a_reader_without_pages_is_an_error(self, data):
        with pytest.raises(ManhuaTopSourceError, match="no page images"):
            _pages(data)

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_PAGES", 2)

        with pytest.raises(ManhuaTopSourceError, match="more pages"):
            _pages(_content())

    def test_a_refused_chapter_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({CONTENT: dict(status=403, data={})}).get_pages(CHAPTER)

    def test_a_reader_answer_that_is_not_json_is_an_error(self):
        with pytest.raises(ManhuaTopSourceError, match="not JSON"):
            _site({CONTENT: dict(text="<html></html>")}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        png = _png()
        scraper = _site({IMAGES[0]: dict(content=png, text="")})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(IMAGES[0], target) is True
        assert target.read_bytes() == png
        (sent, kwargs), = scraper.session.calls
        assert sent == IMAGES[0]
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>", text=""),
        dict(content=b"", text=""),
        dict(status=302, content=b"", text=""),
        dict(status=403, content=b"", text=""),
    ], ids=["html", "empty", "redirect", "refused"])
    def test_a_failed_page_clears_an_older_file(self, answer, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")

        assert _site({IMAGES[0]: answer}).download_image(IMAGES[0], target) is False
        assert not target.exists()

    def test_a_url_off_the_image_host_is_not_requested(self, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper = _site({})

        assert scraper.download_image("https://example.test/a.jpg", target) is False
        assert scraper.session.calls == []
        assert not target.exists()
