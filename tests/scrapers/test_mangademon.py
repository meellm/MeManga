"""Offline tests for Manga Demon: URL identity, search, chapter rows, the
redirect to the reader, reader pages and download.

The session is replaced with canned answers, so no network is used. Rows
and the reader follow markup the site serves. The search result markup is
built from its known selectors, because no result page was stored.
"""

from __future__ import annotations

import io
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import mangademon as md
from memanga.scrapers.mangademon import (MangaDemonScraper, MangaDemonSourceError,
                                         MangaDemonUnsupportedError)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaDemonScraper": ("search", "chapters", "pages")}

SITE = "https://demonicscans.org"
SERIES = f"{SITE}/manga/Solo-Leveling"
LINK = f"{SITE}/chaptered.php?manga=6&chapter=200.5"
READER = f"{SITE}/title/Solo-Leveling/chapter/200.5/1"
SEARCH = f"{SITE}/search.php?manga=solo"
IMAGES = ["https://demoniclibs.com/Solo Leveling/200.5/1.jpg",
          "https://demoniclibs.com/Solo Leveling/200.5/2.jpg"]
AD = ('<a href="/premium.php?return_to=%2Freader.php%3Fpages%3D1%26manga%3DSolo-Leveling'
      '%26chapter%3D200.5"><img style="max-width:100%;" class="imgholder" '
      'src="/img/free_ads.jpg"></a><br>')


class _Response:
    def __init__(self, url, status=200, text="", content=None, headers=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode() if content is None else content
        self.headers = headers or {}

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
    scraper = MangaDemonScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _result(href, title):
    return (f'<a href="{href}"><img src="https://readermc.org/images/thumbnails/x.webp">'
            f'<div class="seach-right"><div>{title}</div></div></a>')


def _row(number, manga=6, label=None, date="2024-07-13"):
    label = f"Chapter {number}" if label is None else label
    return (f'<li> <a href="/chaptered.php?manga={manga}&chapter={number}" class="chplinks" '
            f'title="Solo Leveling {number}"> {label} '
            f'<span style="float:right;text-align: right;">{date}</span> </a> </li>')


def _series(*rows, info=True, heading=True, listing=True):
    box = '<div id="manga-info-container"></div>' if info else ""
    title = '<h1 class="border-box big-fat-titles">Solo Leveling</h1>' if heading else ""
    chapters = f'<div id="chapters-list">{"".join(rows)}</div>' if listing else ""
    return f"<html><body>{box}{title}{chapters}</body></html>"


def _picker(number="200.5", manga=6):
    return (f'<select onchange="location = this.value;">'
            f"<option value='/chaptered.php?manga={manga}&chapter=200'>Chapter:200</option>"
            f"<option value='/chaptered.php?manga={manga}&chapter={number}' selected>"
            f"Chapter:{number}</option></select>")


def _image(src, n=1):
    return (f'<img style="max-width:100%;" onerror="tryAgain(this)" '
            f'alt="Solo Leveling Chapter 200.5 {n}" class="imgholder" src="{src}" ><br>')


def _reader(images=None, number="200.5", manga=6, picker=None, extra="", heading=None):
    sources = IMAGES if images is None else images
    pages = "".join(_image(src, n) for n, src in enumerate(sources, 1))
    title = f"Chapter {number}" if heading is None else heading
    choice = _picker(number, manga) if picker is None else picker
    return (f'<html><body><div class="chapter-info"><h1><a href="/manga/Solo-Leveling">'
            f'Solo Leveling</a></h1><h2>{title}</h2><div class="chapters-nav">'
            f'<a class="prevchap " href="/chaptered.php?manga={manga}&chapter=200">Prev</a>'
            f'{choice}</div></div><div class="main-width center-m">{AD}{extra}{pages}</div>'
            f'</body></html>')


def _hop(location="title/Solo-Leveling/chapter/200.5/1", status=302):
    return dict(status=status, headers={"Location": location} if location is not None else {})


def _pages(reader=None, hop=None):
    routes = {LINK: _hop() if hop is None else hop}
    if reader is not None:
        routes[READER] = dict(text=reader)
    return _site(routes).get_pages(LINK)


def _chapters(*rows, **page):
    return _site({SERIES: dict(text=_series(*rows, **page))}).get_chapters(SERIES)


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url, slug", [
        (SERIES, "Solo-Leveling"),
        (f"{SERIES}/", "Solo-Leveling"),
        ("https://www.demonicscans.org/manga/Solo-Leveling", "Solo-Leveling"),
        ("http://demonicscans.org/manga/Solo-Leveling", "Solo-Leveling"),
        (f"{SITE}/manga/Swordmaster%2527s-Youngest-Son", "Swordmaster%2527s-Youngest-Son"),
        (f"{SITE}/manga/Mechanic%253A-Slayer", "Mechanic%253A-Slayer"),
    ])
    def test_a_series_slug_is_kept_as_served(self, url, slug):
        assert MangaDemonScraper()._series_slug(url) == slug

    @pytest.mark.parametrize("url", [
        "https://demonicscans.org.example.test/manga/x",
        "https://demoniclibs.com/manga/x",
        "https://u@demonicscans.org/manga/x",
        "https://demonicscans.org:8443/manga/x",
        "https://demonicscans.org/manga/x?y=1",
        "https://demonicscans.org/manga/x#top",
        "ftp://demonicscans.org/manga/x",
        "/manga/x",
        "https://demonicscans.org/manga",
        "https://demonicscans.org/title/x",
        "https://demonicscans.org/manga/x/y",
        "https://demonicscans.org/manga/..",
        "https://demonicscans.org/manga/a b",
        "https://demonicscans.org/manga/a%2Fb",
        "https://demonicscans.org/manga/%2e%2e",
        "https://demonicscans.org/manga/a%zz",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(MangaDemonUnsupportedError):
            MangaDemonScraper()._series_slug(url)

    def test_a_chapter_link_is_its_series_id_and_number(self):
        assert MangaDemonScraper()._chapter_ref(LINK) == ("6", "200.5")

    @pytest.mark.parametrize("url", [
        SERIES,
        READER,
        f"{SITE}/chaptered.php",
        f"{SITE}/chaptered.php?manga=Solo-Leveling&chapter=1",
        f"{SITE}/chaptered.php?chapter=1&manga=6",
        f"{SITE}/chaptered.php?manga=6&chapter=1&x=2",
        f"{SITE}/chaptered.php?manga=6&chapter=1.2.3",
        f"{SITE}/other.php?manga=6&chapter=1",
        "https://example.test/chaptered.php?manga=6&chapter=1",
    ])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site({})

        with pytest.raises(MangaDemonUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (MangaDemonScraper.engine, MangaDemonScraper.content_language,
                MangaDemonScraper.nsfw) == ("http", "en", False)
        assert MangaDemonScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = MangaDemonScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("session", "x", domain=".demonicscans.org"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_keep_the_order_and_served_slugs(self):
        slug = "Solo-Dungeon%253A-I%2527m-Going-to-Enjoy-My-Weekends-to-the-Fullest"
        scraper = _site({SEARCH: dict(text=_result("/manga/Solo-Leveling", "Solo Leveling")
                                      + _result(f"/manga/{slug}", "Solo Dungeon"))})

        results = scraper.search(" solo ")

        assert [(m.title, m.url) for m in results] == [
            ("Solo Leveling", SERIES), ("Solo Dungeon", f"{SITE}/manga/{slug}")]
        (url, kwargs), = scraper.session.calls
        assert url == SEARCH and kwargs["allow_redirects"] is False

    def test_a_query_is_sent_as_one_value(self):
        url = f"{SITE}/search.php?manga=a%26b%3Dc%20d"

        assert _site({url: dict(text="")}).search("a&b=c d") == []

    def test_a_blank_query_sends_nothing(self):
        scraper = _site({})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_the_sites_zero_byte_answer_is_no_results(self):
        scraper = _site({SEARCH: dict(text="")})

        assert scraper.search("solo") == []
        assert len(scraper.session.calls) == 1

    @pytest.mark.parametrize("page", [
        " ",
        "\n",
        "<html><head><title>Just a moment...</title></head><body></body></html>",
        "<html><body><div class='seach-right'><div>No link</div></div></body></html>",
    ], ids=["space", "newline", "challenge", "no-link"])
    def test_any_other_answer_without_rows_is_an_error(self, page):
        with pytest.raises(MangaDemonSourceError, match="did not serve results"):
            _site({SEARCH: dict(text=page)}).search("solo")

    @pytest.mark.parametrize("row", [
        '<a href="/manga/x">x</a>',
        '<a href="/manga/x"><div class="seach-right"><div> </div></div></a>',
    ], ids=["no-title-element", "blank-title"])
    def test_a_result_without_its_title_is_an_error(self, row):
        with pytest.raises(MangaDemonSourceError, match="without its title"):
            _site({SEARCH: dict(text=row)}).search("solo")

    @pytest.mark.parametrize("href", [
        "https://example.test/manga/x", "//example.test/manga/x", "/title/x", "/manga/x/y",
    ], ids=["other-site", "scheme-relative", "other-section", "deep"])
    def test_a_result_that_is_not_a_series_is_an_error(self, href):
        with pytest.raises(MangaDemonSourceError, match="not a series"):
            _site({SEARCH: dict(text=_result(href, "X"))}).search("solo")

    def test_a_repeated_result_is_listed_once(self):
        page = _result("/manga/x", "X") + _result(f"{SITE}/manga/x", "X again")

        assert len(_site({SEARCH: dict(text=page)}).search("solo")) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(md, "_MAX_SEARCH_RESULTS", 2)
        page = "".join(_result(f"/manga/s{n}", f"S{n}") for n in range(5))

        assert len(_site({SEARCH: dict(text=page)}).search("solo")) == 2

    def test_a_page_that_is_not_utf8_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="not UTF-8"):
            _site({SEARCH: dict(content=b"<a href='/manga/x'>\xff</a>")}).search("solo")

    def test_a_redirected_search_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="HTTP 301"):
            _site({SEARCH: dict(status=301)}).search("solo")

    def test_a_refused_search_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("solo")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_a_row_keeps_its_served_link_and_date(self):
        scraper = _site({SERIES: dict(text=_series(_row("200.5")))})

        chapter, = scraper.get_chapters(f"{SERIES}/")

        assert (chapter.number, chapter.title, chapter.url, chapter.date) == (
            "200.5", "Chapter 200.5", LINK, "2024-07-13")
        (url, kwargs), = scraper.session.calls
        assert url == SERIES and kwargs["allow_redirects"] is False

    def test_decimal_and_zero_rows_are_sorted_by_number(self):
        chapters = _chapters(_row("179.6"), _row("179.01"), _row("200"), _row("0"))

        assert [c.number for c in chapters] == ["200", "179.6", "179.01", "0"]

    def test_the_same_link_listed_twice_is_one_chapter_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=md.logger.name):
            chapters = _chapters(_row("2"), _row("2"), _row("1"))

        assert [c.number for c in chapters] == ["2", "1"]
        assert "1 chapter row(s)" in caplog.text and "repeat" in caplog.text

    def test_two_links_for_one_number_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="two links for chapter 2"):
            _chapters(_row("2"), _row("2.0"))

    def test_rows_of_two_series_ids_are_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="several series ids"):
            _chapters(_row("2"), _row("1", manga=7))

    @pytest.mark.parametrize("label", [
        "Chapter 3", "Chapter", "chapter 2", "Volume 2", "Chapter 2 : End", "",
    ], ids=["other-number", "no-number", "lowercase", "volume", "with-text", "blank"])
    def test_a_label_that_does_not_match_its_link_is_an_error(self, label):
        with pytest.raises(MangaDemonSourceError, match="does not match its link"):
            _chapters(_row("2", label=label))

    @pytest.mark.parametrize("row", [
        '<li><a class="chplinks">Chapter 2</a></li>',
        '<li><a class="chplinks" href="">Chapter 2</a></li>',
        '<li><a href="/chaptered.php?manga=6&chapter=2">Chapter 2</a></li>',
    ], ids=["no-href", "empty-href", "other-class"])
    def test_a_row_without_its_link_stops_the_list(self, row):
        with pytest.raises(MangaDemonSourceError, match="may be locked"):
            _chapters(_row("3"), row)

    @pytest.mark.parametrize("href", [
        "/chaptered.php?manga=Solo-Leveling&chapter=2",
        "/chaptered.php?manga=6&chapter=two",
        "/title/Solo-Leveling/chapter/2/1",
        "https://example.test/chaptered.php?manga=6&chapter=2",
    ], ids=["slug-id", "text-number", "reader-path", "other-site"])
    def test_a_row_linked_elsewhere_is_an_error(self, href):
        row = f'<li><a class="chplinks" href="{href}">Chapter 2</a></li>'

        with pytest.raises(MangaDemonSourceError, match="links a chapter to"):
            _chapters(row)

    def test_a_badged_chapter_is_refused(self):
        row = _row("3").replace("</a>", '<span class="toffee-badge">x</span></a>')

        with pytest.raises(MangaDemonSourceError, match="badge"):
            _chapters(_row("4"), row)

    @pytest.mark.parametrize("page", [
        dict(info=False), dict(heading=False), dict(listing=False),
    ], ids=["no-info", "no-title", "no-list"])
    def test_a_page_that_is_not_a_series_is_an_error(self, page):
        with pytest.raises(MangaDemonSourceError, match="not a series page"):
            _chapters(_row("1"), **page)

    def test_a_series_without_chapters_is_an_error_not_an_empty_list(self):
        with pytest.raises(MangaDemonSourceError, match="lists no chapters"):
            _chapters()

    def test_a_redirected_series_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="HTTP 302"):
            _site({SERIES: dict(status=302)}).get_chapters(SERIES)

    def test_a_refused_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES: dict(status=404)}).get_chapters(SERIES)

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(md, "_MAX_CHAPTERS", 1)

        with pytest.raises(MangaDemonSourceError, match="more chapters"):
            _chapters(_row("2"), _row("1"))


# ── Reader ──────────────────────────────────────────────────────────

class TestPages:
    def test_the_story_images_through_the_one_redirect(self):
        scraper = _site({LINK: _hop(), READER: dict(text=_reader())})

        assert scraper.get_pages(LINK) == IMAGES
        assert [url for url, _ in scraper.session.calls] == [LINK, READER]
        assert all(kw["allow_redirects"] is False for _, kw in scraper.session.calls)

    def test_a_double_encoded_reader_slug_is_kept(self):
        link = f"{SITE}/chaptered.php?manga=6&chapter=200.5"
        reader = f"{SITE}/title/Swordmaster%2527s/chapter/200.5/1"
        scraper = _site({link: _hop("title/Swordmaster%2527s/chapter/200.5/1"),
                         reader: dict(text=_reader())})

        assert scraper.get_pages(link) == IMAGES
        assert scraper.session.calls[1][0] == reader

    def test_the_reader_is_read_as_utf8_whatever_charset_it_states(self):
        page = _reader(extra="<p>Dépense’s</p>").encode()
        routes = {LINK: _hop(), READER: dict(text=page.decode("latin-1"), content=page)}

        assert _site(routes).get_pages(LINK) == IMAGES

    def test_a_reader_that_is_not_utf8_is_an_error(self):
        routes = {LINK: _hop(), READER: dict(text="x", content=_reader().encode() + b"\xff")}

        with pytest.raises(MangaDemonSourceError, match="not UTF-8"):
            _site(routes).get_pages(LINK)

    @pytest.mark.parametrize("hop", [
        _hop(status=200),
        _hop(status=301),
        _hop(None),
        _hop(""),
        _hop("/title/Solo-Leveling/chapter/200.5/1"),
        _hop("https://example.test/title/Solo-Leveling/chapter/200.5/1"),
        _hop("//example.test/title/Solo-Leveling/chapter/200.5/1"),
        _hop("title/Solo-Leveling/chapter/200/1"),
        _hop("title/Solo-Leveling/chapter/200.5/2"),
        _hop("title/../chapter/200.5/1"),
        _hop("title/a%2Fb/chapter/200.5/1"),
        _hop("title/Solo-Leveling/chapter/200.5/1?x=1"),
        _hop("premium.php"),
    ], ids=["no-redirect", "permanent", "no-location", "empty", "leading-slash", "other-site",
            "scheme-relative", "other-chapter", "other-page", "dot-dot", "encoded-slash", "query",
            "other-path"])
    def test_any_other_redirect_is_not_followed(self, hop):
        scraper = _site({LINK: hop})

        with pytest.raises(MangaDemonSourceError, match="not its reader page"):
            scraper.get_pages(LINK)
        assert len(scraper.session.calls) == 1

    def test_a_refused_chapter_link_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({LINK: dict(status=403)}).get_pages(LINK)

    def test_a_redirected_reader_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="HTTP 302"):
            _site({LINK: _hop(), READER: dict(status=302)}).get_pages(LINK)

    @pytest.mark.parametrize("page", [
        _reader(heading="Chapter 200"),
        _reader(picker=_picker("200")),
        _reader(picker=_picker("200.5", manga=7)),
        _reader(picker="<select><option value='x'>x</option></select>"),
        "<html><body></body></html>",
    ], ids=["other-heading", "other-chapter-selected", "other-series-selected", "nothing-selected",
            "empty"])
    def test_a_reader_for_something_else_is_an_error(self, page):
        with pytest.raises(MangaDemonSourceError, match="is not this chapter"):
            _pages(page)

    @pytest.mark.parametrize("extra", [
        '<a href="/title/Solo-Leveling/chapter/200.5/2">Next</a>',
        '<select><option value="/title/Solo-Leveling/chapter/200.5/2">2</option></select>',
        '<a href="/reader.php?pages=2&manga=Solo-Leveling&chapter=200.5">Next</a>',
    ], ids=["next-link", "page-selector", "reader-link"])
    def test_a_reader_that_continues_on_another_page_is_an_error(self, extra):
        with pytest.raises(MangaDemonSourceError, match="continues on another page"):
            _pages(_reader(extra=extra))

    @pytest.mark.parametrize("extra", [
        '<a href="/title/Solo-Leveling/chapter/200/2">Other chapter</a>',
        '<a href="/title/Solo-Leveling/chapter/200.5/1">This page</a>',
        '<a href="http://[bad">Broken ad</a>',
    ], ids=["other-chapter", "same-page", "malformed"])
    def test_links_that_are_not_a_next_page_do_not_stop_the_chapter(self, extra):
        assert _pages(_reader(extra=extra)) == IMAGES

    def test_a_badged_reader_is_refused(self):
        with pytest.raises(MangaDemonSourceError, match="badge"):
            _pages(_reader(extra='<span class="toffee-badge">x</span>'))

    def test_a_linked_image_other_than_the_ad_is_an_error(self):
        extra = f'<a href="/other.php"><img class="imgholder" src="{IMAGES[0]}"></a>'

        with pytest.raises(MangaDemonSourceError, match="cannot place"):
            _pages(_reader(extra=extra))

    @pytest.mark.parametrize("bad", [
        "",
        "/img/free_ads.jpg",
        "http://demoniclibs.com/Solo Leveling/200.5/1.jpg",
        "//demoniclibs.com/Solo Leveling/200.5/1.jpg",
        "https://librarydm.com/Solo Leveling/200.5/1.jpg",
        "https://demoniclibs.com.example.test/a.jpg",
        "https://demoniclibs.com:8443/a.jpg",
        "https://u@demoniclibs.com/a.jpg",
        "https://demoniclibs.com/a.jpg?x=1",
        "https://demoniclibs.com/a.jpg#x",
        "https://demoniclibs.com/../a.jpg",
        "https://demoniclibs.com/a.svg",
        " https://demoniclibs.com/a.jpg",
        "data:image/png;base64,AAAA",
    ], ids=["empty", "ad-not-linked", "http", "scheme-relative", "other-library", "lookalike",
            "port", "login", "query", "fragment", "dot-dot", "svg", "leading-space", "data-uri"])
    def test_an_invalid_page_is_an_error_and_never_dropped(self, bad):
        with pytest.raises(MangaDemonSourceError, match="not an image of this site"):
            _pages(_reader([IMAGES[0], bad]))

    def test_a_repeated_page_is_an_error(self):
        with pytest.raises(MangaDemonSourceError, match="twice"):
            _pages(_reader([IMAGES[0], IMAGES[1], IMAGES[0]]))

    def test_a_reader_with_only_the_ad_has_no_pages(self):
        with pytest.raises(MangaDemonSourceError, match="no page images"):
            _pages(_reader([]))

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(md, "_MAX_PAGES", 1)

        with pytest.raises(MangaDemonSourceError, match="more pages"):
            _pages(_reader())


class TestServedImageHosts:
    """A normal chapter's reader serves its pages from mangafifth.org."""

    PAGES = [f"https://mangafifth.org/Solo Leveling/200/{n}.webp" for n in range(1, 16)]
    LINK = f"{SITE}/chaptered.php?manga=6&chapter=200"
    READER = f"{SITE}/title/Solo-Leveling/chapter/200/1"

    def _routes(self, images):
        return {self.LINK: _hop("title/Solo-Leveling/chapter/200/1"),
                self.READER: dict(text=_reader(images, number="200"))}

    def test_every_page_of_a_normal_chapter_in_served_order(self):
        scraper = _site(self._routes(self.PAGES))

        assert scraper.get_pages(self.LINK) == self.PAGES
        assert [url for url, _ in scraper.session.calls] == [self.LINK, self.READER]

    @pytest.mark.parametrize("bad", [
        "http://mangafifth.org/Solo Leveling/200/2.webp",
        "//mangafifth.org/Solo Leveling/200/2.webp",
        "https://www.mangafifth.org/Solo Leveling/200/2.webp",
        "https://cdn.mangafifth.org/Solo Leveling/200/2.webp",
        "https://mangasixth.org/Solo Leveling/200/2.webp",
        "https://mangafifth.com/Solo Leveling/200/2.webp",
        "https://mangafifth.org.example.test/2.webp",
        "https://mangafifth.org:8443/2.webp",
        "https://u@mangafifth.org/2.webp",
        "https://mangafifth.org/2.webp?x=1",
        "https://mangafifth.org/2.webp#x",
        "https://mangafifth.org/../2.webp",
        "https://mangafifth.org/2.svg",
    ], ids=["http", "scheme-relative", "www-sibling", "cdn-sibling", "other-name", "other-tld",
            "lookalike", "port", "login", "query", "fragment", "dot-dot", "svg"])
    def test_anything_but_the_exact_host_is_an_error(self, bad):
        with pytest.raises(MangaDemonSourceError, match="not an image of this site"):
            _site(self._routes([self.PAGES[0], bad])).get_pages(self.LINK)

    def test_one_file_on_both_hosts_is_a_repeat(self):
        same = self.PAGES[0].replace("mangafifth.org", "demoniclibs.com")

        with pytest.raises(MangaDemonSourceError, match="twice"):
            _site(self._routes([self.PAGES[0], same])).get_pages(self.LINK)

    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        png = _png()
        scraper = _site({self.PAGES[0]: dict(content=png)})
        target = tmp_path / "page_001.webp"

        assert scraper.download_image(self.PAGES[0], target) is True
        assert target.read_bytes() == png
        (sent, kwargs), = scraper.session.calls
        assert sent == self.PAGES[0]
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    def test_a_sibling_host_is_not_requested(self, tmp_path):
        scraper = _site({})

        assert scraper.download_image("https://www.mangafifth.org/a.webp",
                                      tmp_path / "page_001.webp") is False
        assert scraper.session.calls == []


# ── Download ────────────────────────────────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        png = _png()
        scraper = _site({IMAGES[0]: dict(content=png)})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(IMAGES[0], target) is True
        assert target.read_bytes() == png
        (sent, kwargs), = scraper.session.calls
        assert sent == IMAGES[0]
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""),
        dict(status=302, content=b""), dict(status=403, content=b""),
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

        assert scraper.download_image("https://librarydm.com/a.jpg", target) is False
        assert scraper.session.calls == []
        assert not target.exists()
