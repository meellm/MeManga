"""Offline tests for MangaHome: URL identity, search, chapter rows, the
chapterfun reader and download.

The session is replaced with canned answers, so no network is used. The
page shapes follow the site's markup. The reader answers are built in the
packed form, and one test reads a real packed answer of the same engine.
"""

from __future__ import annotations

import io
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import mangahome as mh
from memanga.scrapers.mangahome import (MangaHomeScraper, MangaHomeSourceError,
                                        MangaHomeUnsupportedError, _reader_values)

SITE = "https://www.mangahome.com"
SERIES = f"{SITE}/manga/nightmare_of_solomon"
CHAPTER = f"{SERIES}/v01/c001"
SEARCH = f"{SITE}/search?page=1&name_method=cw&name=solo"
CDN = "//zjcdn.mangahere.org/store/manga/123/01.0/compressed"
CHAPTER_ID = "999"


class _Response:
    def __init__(self, url, status=200, text="", content=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode() if content is None else content
        self.headers = {}

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
    scraper = MangaHomeScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _post(href, title):
    return (f'<li><div class="post"><a href="{href}"><img src="/cover.jpg"></a>'
            f'<p class="title"><a href="{href}" title="{title}">{title}</a></p></div></li>')


def _results(*posts):
    return f'<html><body><ul class="manga-list">{"".join(posts)}</ul></body></html>'


def _no_results(query, extra=""):
    return ('<html><body><div class="main-content"><div class="search-none">'
            '<img src="//static.mangahome.com/images/searchnone.png" /><p>\n'
            '    Oh dear, we searched and searched…but we found nothing for\n'
            f'       {query}.\n    </p></div></div>{extra}</body></html>')


def _row(href, label="Ch 1", date="Jan 02,2020"):
    return (f'<li><a href="{href}"><span class="pc-none">{label}</span></a>'
            f'<span class="time">{date}</span></li>')


def _series(*rows, notice=""):
    return (f'<html><body><h1>Nightmare of Solomon</h1>{notice}'
            f'<ul class="detail-chlist">{"".join(rows)}</ul></body></html>')


def _chapter_page(count=17, chapter_id=CHAPTER_ID, selectors=None, notice=""):
    selectors = (count, count) if selectors is None else selectors
    boxes = "".join(
        "<select>" + "".join(f"<option>{n}</option>" for n in range(1, shown + 1))
        + "<option>Featured</option></select>"
        for shown in selectors)
    return (f'<html><body>{notice}{boxes}<script>var chapter_id = {chapter_id};'
            f' var imagecount = {count};</script></body></html>')


def _image(n):
    return f"https:{CDN}/p{n:03d}.jpg"


def _packed(pix, *entries):
    values = ",".join(f'"{entry}"' for entry in entries)
    code = f'function f(){{var pix="{pix}";var pvalue=[{values}];return pvalue}}'
    return ("eval(function(p,a,c,k,e,d){return p}('" + code + "',36,1,''.split('|'),0,{}))")


def _call_url(page):
    return f"{CHAPTER}/chapterfun.ashx?cid={CHAPTER_ID}&page={page}&key="


def _answer(page, count):
    entries = [f"/p{page:03d}.jpg"]
    if page < count:
        entries.append(f"/p{page + 1:03d}.jpg")
    return _packed(CDN, *entries)


def _reader(count=17, **overrides):
    routes = {CHAPTER: dict(text=_chapter_page(count))}
    for page in range(1, count + 1):
        routes[_call_url(page)] = dict(text=_answer(page, count))
    for page, body in overrides.items():
        routes[_call_url(int(page.lstrip("p")))] = dict(text=body)
    return routes


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url", [
        SERIES, f"{SERIES}/", "https://mangahome.com/manga/nightmare_of_solomon",
        "http://www.mangahome.com/manga/nightmare_of_solomon",
    ])
    def test_a_series_url_has_one_slug(self, url):
        assert MangaHomeScraper()._series_slug(url) == "nightmare_of_solomon"

    @pytest.mark.parametrize("url", [
        "https://www.mangahome.com.example.test/manga/x",
        "https://m.mangahome.com/manga/x",
        "https://www.mangahere.cc/manga/x",
        "https://u@www.mangahome.com/manga/x",
        "https://www.mangahome.com:8443/manga/x",
        "https://www.mangahome.com/manga/x?page=2",
        "https://www.mangahome.com/manga/x#top",
        "ftp://www.mangahome.com/manga/x",
        "/manga/x",
        "https://www.mangahome.com/manga",
        "https://www.mangahome.com/directory/x",
        "https://www.mangahome.com/manga/x/c001",
        "https://www.mangahome.com/manga//x",
        "https://www.mangahome.com/manga/../x",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(MangaHomeUnsupportedError):
            MangaHomeScraper()._series_slug(url)

    @pytest.mark.parametrize("url, canonical, number", [
        (CHAPTER, CHAPTER, "001"),
        (f"{CHAPTER}/", CHAPTER, "001"),
        (f"{SERIES}/c012.5", f"{SERIES}/c012.5", "012.5"),
        (f"{SERIES}/vTBD/c050", f"{SERIES}/vTBD/c050", "050"),
        ("https://mangahome.com/manga/nightmare_of_solomon/v01/c001", CHAPTER, "001"),
    ])
    def test_a_chapter_url_keeps_its_whole_path(self, url, canonical, number):
        assert MangaHomeScraper()._chapter_parts(url) == (
            "nightmare_of_solomon", number, canonical)

    @pytest.mark.parametrize("url", [
        SERIES,
        f"{SERIES}/v01",
        f"{SERIES}/x/c001",
        f"{SERIES}/v01/c001/1.html",
        f"{SERIES}/v01/c1.2.3",
        f"{SERIES}/c",
        f"{SITE}/",
    ])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site({})

        with pytest.raises(MangaHomeUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (MangaHomeScraper.engine, MangaHomeScraper.content_language,
                MangaHomeScraper.nsfw) == ("http", "en", True)
        assert MangaHomeScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = MangaHomeScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("session", "x", domain=".mangahome.com"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_in_the_sites_order(self):
        scraper = _site({SEARCH: dict(text=_results(
            _post("/manga/only_you", "Only You"),
            _post("/manga/nightmare_of_solomon", "Nightmare of Solomon")))})

        results = scraper.search(" solo ")

        assert [(m.title, m.url) for m in results] == [
            ("Only You", f"{SITE}/manga/only_you"), ("Nightmare of Solomon", SERIES)]
        (url, kwargs), = scraper.session.calls
        assert url == SEARCH and kwargs["allow_redirects"] is False

    def test_a_query_is_sent_as_one_value(self):
        url = f"{SITE}/search?page=1&name_method=cw&name=a%26b%3Dc%20d"
        scraper = _site({url: dict(text=_no_results("a&amp;b=c d"))})

        assert scraper.search("a&b=c d") == []

    def test_a_cut_title_uses_the_full_one(self):
        post = ('<li><div class="post"><p class="title"><a href="/manga/long" '
                'title="A Very Long Title">A Very...</a></p></div></li>')

        assert _site({SEARCH: dict(text=_results(post))}).search("solo")[0].title == (
            "A Very Long Title")

    def test_a_blank_query_sends_nothing(self):
        scraper = _site({})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_the_sites_found_nothing_page_is_no_results(self):
        url = f"{SITE}/search?page=1&name_method=cw&name=zzqxjkvwpyd"
        scraper = _site({url: dict(text=_no_results("zzqxjkvwpyd"))})

        assert scraper.search("zzqxjkvwpyd") == []
        assert len(scraper.session.calls) == 1

    def test_the_notice_is_read_from_the_pages_utf8_bytes(self):
        page = _no_results("solo").encode()
        route = dict(text=page.decode("latin-1"), content=page)

        assert _site({SEARCH: route}).search("solo") == []

    @pytest.mark.parametrize("route", [
        dict(text=_no_results("other")),
        dict(text=_no_results("solo").replace("found nothing", "found something")),
        dict(text=_no_results("solo").replace("solo.", "solo")),
        dict(text=_no_results("solo", '<div class="search-none">more</div>')),
        dict(text=_no_results("solo", _results(_post("/manga/x", "X")))),
        dict(text=_no_results("solo", '<ul class="manga-list"></ul>')),
        dict(text=_no_results("solo", '<div class="post"></div>')),
        dict(text=_results()),
        dict(text='<html><body><div class="search-none"></div></body></html>'),
        dict(text="x", content=_no_results("solo").encode() + b"\xff"),
    ], ids=["other-query", "other-text", "no-full-stop", "two-notices", "notice-and-results",
            "notice-and-empty-list", "notice-and-row", "empty-list-without-notice", "blank-notice",
            "not-utf8"])
    def test_anything_but_the_exact_notice_is_an_error(self, route):
        with pytest.raises(MangaHomeSourceError, match="did not serve a result list"):
            _site({SEARCH: route}).search("solo")

    @pytest.mark.parametrize("page", [
        "<html><head><title>Just a moment...</title></head><body></body></html>",
        '<html><body><div class="post"><p class="title"><a href="/manga/x">x</a></p></div>'
        "</body></html>",
        "",
    ], ids=["challenge", "no-result-list", "empty-body"])
    def test_a_page_without_the_result_list_is_an_error(self, page):
        with pytest.raises(MangaHomeSourceError, match="did not serve a result list"):
            _site({SEARCH: dict(text=page)}).search("solo")

    @pytest.mark.parametrize("post", [
        '<li><div class="post"></div></li>',
        '<li><div class="post"><p class="title"><a>x</a></p></div></li>',
        '<li><div class="post"><p class="title"><a href="/manga/x"> </a></p></div></li>',
        '<li><div class="post"><p class="title"><a href="/manga/x">cut...</a></p></div></li>',
    ], ids=["no-link", "no-href", "blank-title", "cut-title-without-full"])
    def test_a_result_without_link_or_title_is_an_error(self, post):
        with pytest.raises(MangaHomeSourceError, match="without its link or title"):
            _site({SEARCH: dict(text=_results(post))}).search("solo")

    @pytest.mark.parametrize("href", [
        "https://example.test/manga/x", "//example.test/manga/x", "/manga/x/c001", "/directory/x",
    ], ids=["other-site", "scheme-relative", "chapter", "other-section"])
    def test_a_result_that_is_not_a_series_is_an_error(self, href):
        with pytest.raises(MangaHomeSourceError, match="not a series"):
            _site({SEARCH: dict(text=_results(_post(href, "X")))}).search("solo")

    def test_a_repeated_result_is_listed_once(self):
        scraper = _site({SEARCH: dict(text=_results(
            _post("/manga/x", "X"), _post(f"{SITE}/manga/x", "X again")))})

        assert len(scraper.search("solo")) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(mh, "_MAX_SEARCH_RESULTS", 2)
        posts = [_post(f"/manga/s{n}", f"S{n}") for n in range(5)]

        assert len(_site({SEARCH: dict(text=_results(*posts))}).search("solo")) == 2

    def test_a_redirected_search_is_an_error(self):
        with pytest.raises(MangaHomeSourceError, match="HTTP 301"):
            _site({SEARCH: dict(status=301)}).search("solo")

    def test_a_refused_search_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("solo")


# ── Chapters ────────────────────────────────────────────────────────

SLUG_PATH = "/manga/nightmare_of_solomon"


def _chapters(*rows, **page):
    return _site({SERIES: dict(text=_series(*rows, **page))}).get_chapters(SERIES)


class TestChapters:
    def test_the_observed_volume_row(self):
        scraper = _site({SERIES: dict(text=_series(_row(
            f"{SLUG_PATH}/v01/c001", "Nightmare of Solomon 1 Ch 1")))})

        chapter, = scraper.get_chapters(f"{SERIES}/")

        assert (chapter.number, chapter.title, chapter.url, chapter.date) == (
            "1", "Nightmare of Solomon 1 Ch 1", CHAPTER, "Jan 02,2020")
        (url, kwargs), = scraper.session.calls
        assert url == SERIES and kwargs["allow_redirects"] is False

    def test_rows_are_sorted_by_number(self):
        chapters = _chapters(_row(f"{SLUG_PATH}/v01/c002"), _row(f"{SLUG_PATH}/v02/c010"),
                             _row(f"{SLUG_PATH}/v01/c001.5"), _row(f"{SLUG_PATH}/c000"))

        assert [c.number for c in chapters] == ["10", "2", "1.5", "0"]

    def test_the_same_link_listed_twice_is_one_chapter_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mh.logger.name):
            chapters = _chapters(_row(f"{SLUG_PATH}/v01/c002"), _row(f"{SITE}{SLUG_PATH}/v01/c002"))

        assert [c.number for c in chapters] == ["2"]
        assert "1 chapter row(s)" in caplog.text and "repeat" in caplog.text

    def test_one_number_in_two_volumes_is_an_error(self):
        with pytest.raises(MangaHomeSourceError, match="two links for chapter 1"):
            _chapters(_row(f"{SLUG_PATH}/v01/c001"), _row(f"{SLUG_PATH}/v02/c001"))

    def test_a_row_without_a_link_stops_the_list_as_possibly_locked(self):
        with pytest.raises(MangaHomeSourceError, match="may be locked"):
            _chapters(_row(f"{SLUG_PATH}/v01/c002"), "<li><span>Ch 1</span></li>")

    @pytest.mark.parametrize("href", [
        "/manga/other/v01/c001",
        "https://example.test/manga/nightmare_of_solomon/v01/c001",
        "//example.test/manga/nightmare_of_solomon/v01/c001",
        f"{SLUG_PATH}/v01/special",
        f"{SLUG_PATH}/v01/c001/2.html",
        f"{SLUG_PATH}/v01/c001?x=1",
    ], ids=["other-series", "other-site", "scheme-relative", "no-number", "page-link", "query"])
    def test_a_row_linked_elsewhere_is_an_error(self, href):
        with pytest.raises(MangaHomeSourceError):
            _chapters(_row(href))

    @pytest.mark.parametrize("notice", [
        "<div>This series has been licensed</div>",
        "<div>It HAS BEEN LICENSED, so it is not available</div>",
    ])
    def test_a_licensed_series_is_an_explicit_error(self, notice):
        with pytest.raises(MangaHomeSourceError, match="licensed"):
            _chapters(_row(f"{SLUG_PATH}/v01/c001"), notice=notice)

    def test_the_word_licensed_elsewhere_is_not_a_notice(self):
        chapters = _chapters(_row(f"{SLUG_PATH}/v01/c001"),
                             notice="<p>This story has been licensed</p><div>Summary</div>")

        assert len(chapters) == 1

    def test_a_series_page_without_chapters_is_an_error_not_an_empty_list(self):
        with pytest.raises(MangaHomeSourceError, match="lists no chapters"):
            _chapters()

    @pytest.mark.parametrize("page", [
        "<html><head><title>Just a moment...</title></head><body></body></html>", "",
    ], ids=["challenge", "empty-body"])
    def test_a_page_that_is_not_a_series_is_an_error(self, page):
        with pytest.raises(MangaHomeSourceError, match="not a series page"):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirected_series_is_an_error(self):
        with pytest.raises(MangaHomeSourceError, match="HTTP 302"):
            _site({SERIES: dict(status=302)}).get_chapters(SERIES)

    def test_a_refused_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES: dict(status=404)}).get_chapters(SERIES)

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mh, "_MAX_CHAPTERS", 1)

        with pytest.raises(MangaHomeSourceError, match="more chapters"):
            _chapters(_row(f"{SLUG_PATH}/c002"), _row(f"{SLUG_PATH}/c001"))


# ── Reader answers ──────────────────────────────────────────────────

class TestReaderValues:
    def test_a_real_packed_answer_of_the_engine_is_read_as_data(self, load_fixture):
        pix, entries = _reader_values(load_fixture("mangahere", "chapterfun_page1.js"))

        assert pix == "//zjcdn.mangahere.org/store/manga/8602/001.0/compressed"
        assert entries == ["/u1.01.jpg", "/u1.02.jpg"]

    def test_two_entries_are_read_in_order(self):
        assert _reader_values(_packed(CDN, "/a.jpg", "/b.jpg")) == (CDN, ["/a.jpg", "/b.jpg"])

    @pytest.mark.parametrize("script", [
        "",
        'var pix="//x";var pvalue=["/a.jpg"];',
        _packed(CDN, "/a.jpg") + _packed(CDN, "/b.jpg"),
        _packed(CDN),
        _packed(CDN, "/a.jpg").replace("var pix", "var other"),
        _packed(CDN, "/a.jpg").replace("var pvalue", "var other"),
        _packed(CDN, "/a.jpg").replace('["/a.jpg"]', '["/a.jpg",other]'),
        _packed(CDN, "/a.jpg").replace(",36,1,", ",0,1,"),
        _packed(CDN, "/a.jpg").replace(",36,1,", ",1,1,"),
        _packed(CDN, "/a.jpg").replace(",36,1,", ",63,1,"),
        _packed(CDN, "/a.jpg").replace(",36,1,", ",36,999999999,"),
    ], ids=["empty", "not-packed", "two-scripts", "no-entries", "no-pix", "no-pvalue",
            "not-only-strings", "radix-zero", "radix-one", "radix-high", "count-too-high"])
    def test_anything_else_is_refused(self, script):
        with pytest.raises(ValueError):
            _reader_values(script)


class TestPages:
    def test_every_page_from_its_own_call(self):
        scraper = _site(_reader())

        assert scraper.get_pages(CHAPTER) == [_image(n) for n in range(1, 18)]
        urls = [url for url, _ in scraper.session.calls]
        assert urls == [CHAPTER] + [_call_url(n) for n in range(1, 18)]
        for _, kwargs in scraper.session.calls[1:]:
            assert kwargs["headers"] == {"Referer": CHAPTER,
                                         "X-Requested-With": "XMLHttpRequest"}
            assert kwargs["allow_redirects"] is False

    def test_a_second_image_on_the_last_answer_is_not_a_page(self):
        scraper = _site(_reader(2, p2=_packed(CDN, "/p002.jpg", "/p003.jpg")))

        assert scraper.get_pages(CHAPTER) == [_image(1), _image(2)]

    def test_answers_with_one_image_each_are_read(self):
        scraper = _site(_reader(2, p1=_packed(CDN, "/p001.jpg")))

        assert scraper.get_pages(CHAPTER) == [_image(1), _image(2)]

    def test_a_single_page_chapter(self):
        assert _site(_reader(1)).get_pages(CHAPTER) == [_image(1)]

    def test_an_answer_that_disagrees_with_the_one_before_is_an_error(self):
        routes = _reader(3, p2=_packed(CDN, "/p009.jpg", "/p003.jpg"))

        with pytest.raises(MangaHomeSourceError, match="disagrees"):
            _site(routes).get_pages(CHAPTER)

    def test_an_aligned_pair_is_an_error_not_a_repeated_page(self):
        routes = _reader(3, p2=_packed(CDN, "/p001.jpg", "/p002.jpg"))

        with pytest.raises(MangaHomeSourceError, match="disagrees"):
            _site(routes).get_pages(CHAPTER)

    def test_a_repeated_page_is_an_error_and_never_dropped(self):
        routes = _reader(3, p1=_packed(CDN, "/p001.jpg"), p2=_packed(CDN, "/p001.jpg"))

        with pytest.raises(MangaHomeSourceError, match="twice"):
            _site(routes).get_pages(CHAPTER)

    def test_a_failed_call_fails_the_chapter(self):
        routes = _reader(3)
        routes[_call_url(2)] = dict(status=403)

        with pytest.raises(requests.HTTPError):
            _site(routes).get_pages(CHAPTER)

    def test_a_redirected_call_is_an_error(self):
        routes = _reader(3)
        routes[_call_url(2)] = dict(status=302)

        with pytest.raises(MangaHomeSourceError, match="HTTP 302"):
            _site(routes).get_pages(CHAPTER)

    def test_an_oversized_answer_is_an_error(self):
        routes = _reader(1)
        routes[_call_url(1)] = dict(text="x", content=b"x" * (mh._MAX_SCRIPT_BYTES + 1))

        with pytest.raises(MangaHomeSourceError, match="too large"):
            _site(routes).get_pages(CHAPTER)

    def test_an_answer_that_is_not_packed_is_an_error(self):
        with pytest.raises(MangaHomeSourceError, match="unreadable reader answer"):
            _site(_reader(2, p2="<html>blocked</html>")).get_pages(CHAPTER)

    def test_more_than_two_images_is_an_error(self):
        routes = _reader(2, p1=_packed(CDN, "/p001.jpg", "/p002.jpg", "/p003.jpg"))

        with pytest.raises(MangaHomeSourceError, match="unexpected reader answer"):
            _site(routes).get_pages(CHAPTER)

    @pytest.mark.parametrize("pix, entry", [
        ("https://zjcdn.mangahere.org/store", "/a.jpg"),
        ("/store", "/a.jpg"),
        ("//example.test/store", "/a.jpg"),
        ("//zjcdn2.mangahere.org/store", "/a.jpg"),
        ("//zjcdn.mangahere.org.example.test/store", "/a.jpg"),
        ("//zjcdn.mangahere.org:8443/store", "/a.jpg"),
        ("//u@zjcdn.mangahere.org/store", "/a.jpg"),
        (CDN, "a.jpg"),
        (CDN, "//example.test/a.jpg"),
        (CDN, "/../a.jpg"),
        (CDN, "/a.svg"),
        (CDN, "/a.jpg?x=1"),
        (CDN, "/a.jpg#x"),
    ], ids=["absolute-prefix", "relative-prefix", "other-host", "other-shard", "lookalike",
            "port", "login", "relative-entry", "host-in-entry", "dot-dot", "svg", "query",
            "fragment"])
    def test_an_invalid_image_is_an_error_and_never_dropped(self, pix, entry):
        routes = _reader(1, p1=_packed(pix, entry))

        with pytest.raises(MangaHomeSourceError):
            _site(routes).get_pages(CHAPTER)

    @pytest.mark.parametrize("page, why", [
        ("<html></html>", "does not state"),
        ("<script>var chapter_id = 1;</script>", "does not state"),
        ("<script>var imagecount = 2;</script>", "does not state"),
        ("<script>var chapter_id = 1; var chapter_id = 2; var imagecount = 2;</script>",
         "does not state"),
        ("<script>var chapter_id = 1; var imagecount = 2; var imagecount = 3;</script>",
         "does not state"),
        (_chapter_page(0, selectors=(1,)), "states 0 pages"),
        (_chapter_page(3, selectors=()), "page selectors"),
        (_chapter_page(3, selectors=(3, 2)), "page selectors"),
        (_chapter_page(3, selectors=(4, 4)), "page selectors"),
    ], ids=["nothing", "no-count", "no-id", "two-ids", "two-counts", "zero-pages", "no-selector",
            "selector-disagrees", "selectors-differ"])
    def test_a_chapter_page_without_one_clear_count_is_an_error(self, page, why):
        scraper = _site({CHAPTER: dict(text=page)})

        with pytest.raises(MangaHomeSourceError, match=why):
            scraper.get_pages(CHAPTER)
        assert len(scraper.session.calls) == 1

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mh, "_MAX_PAGES", 2)

        with pytest.raises(MangaHomeSourceError, match="states 3 pages"):
            _site({CHAPTER: dict(text=_chapter_page(3))}).get_pages(CHAPTER)

    def test_a_licensed_chapter_is_an_explicit_error(self):
        page = _chapter_page(3, notice="<div>This chapter has been licensed</div>")
        scraper = _site({CHAPTER: dict(text=page)})

        with pytest.raises(MangaHomeSourceError, match="licensed"):
            scraper.get_pages(CHAPTER)
        assert len(scraper.session.calls) == 1

    def test_a_redirected_chapter_is_an_error(self):
        with pytest.raises(MangaHomeSourceError, match="HTTP 302"):
            _site({CHAPTER: dict(status=302)}).get_pages(CHAPTER)

    def test_a_refused_chapter_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({CHAPTER: dict(status=403)}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        png = _png()
        scraper = _site({_image(1): dict(content=png)})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(_image(1), target) is True
        assert target.read_bytes() == png
        (sent, kwargs), = scraper.session.calls
        assert sent == _image(1)
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""),
        dict(status=302, content=b""), dict(status=403, content=b""),
    ], ids=["html", "empty", "redirect", "refused"])
    def test_a_failed_page_clears_an_older_file(self, answer, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")

        assert _site({_image(1): answer}).download_image(_image(1), target) is False
        assert not target.exists()

    def test_a_url_off_the_image_host_is_not_requested(self, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper = _site({})

        assert scraper.download_image("https://example.test/a.jpg", target) is False
        assert scraper.session.calls == []
        assert not target.exists()
