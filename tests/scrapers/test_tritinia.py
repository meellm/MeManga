"""Offline tests for Tritinia Scans: search, the series page and its AJAX
chapter rows, the partial-list warning, the adult and novel refusals, the
paged reader's bound page list in served order, and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's Madara pages (search, series, the chapter POST
answer and the paged reader).
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import tritinia as tr
from memanga.scrapers.tritinia import TritiniaScraper, TritiniaSourceError

PARSER_TESTS = {"TritiniaScraper": ("search", "chapters", "pages")}

SITE = "https://tritinia.org"
SLUG = "kekkon-shiyou-rikon-zentei-de"
TITLE = "Kekkon shiyou. Rikon zentei de."
SERIES = f"{SITE}/manga/{SLUG}/"
AJAX = f"{SERIES}ajax/chapters/"
CHAPTER = f"{SERIES}ch-16/"
SEARCH = f"{SITE}/?s=Kekkon+shiyou.+Rikon+zentei+de.&post_type=wp-manga"
EMPTY = f"{SITE}/?s=zzqxjkvwpyd&post_type=wp-manga"
FOLDER = f"{SITE}/wp-content/uploads/WP-manga/data/manga_695995f0dc8f9/c544dea6019037341c5112fd23ee58bd"
COVER = f"{SITE}/wp-content/uploads/2026/01/5ea84372-9a27-437c-a822-300628fc8105.jpg"
# The served names of chapter 16's 44 pages: 033 and 044 to 048 are not served.
NAMES = ["000.png"] + [f"{n:03d}.jpg" for n in range(1, 44) if n != 33] + ["049.jpg"]
PAGES = [f"{FOLDER}/{name}" for name in NAMES]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


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
    """Answers each (method, URL) from ``routes``; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _Response(url, **self.routes[("GET", url)])

    def post(self, url, timeout=None, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _Response(url, **self.routes[("POST", url)])


def _site(routes):
    scraper = TritiniaScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _search(rows=None, empty=False):
    rows = [(SERIES, TITLE)] if rows is None else rows
    if empty:
        body = ('<div class="results_content"><div class="not-found-content"><p>'
                'No matches found. Try a different search...</p></div></div>')
    else:
        body = '<div class="tab-content-wrap"><div class="c-tabs-item">' + "".join(
            f'<div class="row c-tabs-item__content"><div class="tab-thumb c-image-hover">'
            f'<a href="{href}" title="{title}"><img data-src="{COVER}" '
            f'src="{SITE}/wp-content/themes/madara/images/dflazy.jpg"></a></div>'
            f'<div class="tab-summary"><div class="post-title"><h3 class="h4">'
            f'<a href="{href}">{title}</a></h3></div></div></div>' for href, title in rows
        ) + "</div></div>"
    return f'<html><body class="search"><div class="search-wrap">{body}</div></body></html>'


def _series(genres=("Comedy", "Drama", "Josei", "Romance"), kind="Manga", badges=(),
            post_id="2648", canonical=SERIES):
    genre_links = ", ".join(f'<a href="{SITE}/manga-genre/{g.lower()}/" rel="tag">{g}</a>'
                            for g in genres)
    badge_html = "".join(f'<span class="manga-title-badges">{b}</span>' for b in badges)
    return (f'<html><head><link href="{canonical}" rel="canonical"/></head>'
            f'<body class="wp-manga-template-default postid-{post_id} manga-page">'
            f'<div class="post-title">{badge_html}<h1>{TITLE}</h1></div>'
            f'<div class="summary_image"><a href="{SERIES}"><img data-src="{COVER}" '
            f'src="{SITE}/wp-content/themes/madara/images/dflazy.jpg"></a></div>'
            f'<div class="post-content_item"><div class="summary-heading"><h5>Genre(s)</h5></div>'
            f'<div class="summary-content"><div class="genres-content">{genre_links}</div></div>'
            f'</div><div class="post-content_item"><div class="summary-heading"><h5>Type</h5>'
            f'</div><div class="summary-content">{kind}</div></div>'
            f'<div id="manga-chapters-holder"></div>'
            f'<script>var manga = {{"manga_id":"{post_id}"}};</script></body></html>')


def _row(label, href, date="January 19, 2026", cls="wp-manga-chapter"):
    link = f'<a href="{href}">\n\t\t{label}\t\t</a>' if href else f"<span>{label}</span>"
    return (f'<li class="{cls}">{link}<span class="chapter-release-date"><i>{date}</i>'
            f' </span></li>')


ROWS = [_row("Ch. 16", f"{SERIES}ch-16/"), _row("Ch. 15", f"{SERIES}ch-15/", "January 4, 2026")]


def _chapters(rows=None):
    rows = ROWS if rows is None else rows
    return ('<div class="page-content-listing single-page"><div class="listing-chapters_wrap">'
            f'<ul class="main version-chap no-volumn">{"".join(rows)}</ul></div></div>')


def _pager(count):
    return ('<select class="selectpicker" id="single-pager">' + "".join(
        f'<option data-redirect="{CHAPTER}p/{n}/" value="{n}">{n}/{count}</option>'
        for n in range(1, count + 1)) + "</select>")


def _reader(pages=None, url=CHAPTER, current="ch-16", slug="ch-16", manga_id="2648",
            post_id="2648", crumb=SERIES, first=None, pagers=(None, None), lists=1,
            extra="", reader_class="reading-content"):
    pages = PAGES if pages is None else pages
    first = pages[0] if first is None and pages else (first or "")
    pager_html = "".join(_pager(len(pages) if count is None else count) for count in pagers)
    array = json.dumps(pages).replace("/", "\\/")
    script = f'<script id="chapter_preloaded_images">var chapter_preloaded_images = {array}</script>'
    return (f'<html><head><link href="{url}" rel="canonical"/></head>'
            f'<body class="wp-manga-template-default postid-{post_id} manga-page reading-manga">'
            f'<ol class="breadcrumb"><li><a href="{SITE}/">Home</a></li>'
            f'<li><a href="{crumb}">{TITLE}</a></li><li class="active">Ch. 16</li></ol>'
            f'{pager_html}{extra}<div class="{reader_class}">'
            f'<input data-id="5418" id="wp-manga-current-chap" type="hidden" value="{current}">'
            f'<img class="wp-manga-chapter-img img-responsive lazyload effect-fade" '
            f'data-image-paged="0" data-src="{first}" id="image-0">{script * lists}</div>'
            f'<script>var manga = {{"base_url":"{SERIES}","manga_id":"{manga_id}",'
            f'"chapter_slug":"{slug}"}};</script></body></html>')


def _routes(series=None, chapters=None, reader=None):
    return {("GET", SERIES): dict(text=_series() if series is None else series),
            ("POST", AJAX): dict(text=_chapters() if chapters is None else chapters),
            ("GET", CHAPTER): dict(text=_reader() if reader is None else reader)}


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = TritiniaScraper()
        assert (scraper.name, scraper.base_url) == ("tritinia", SITE)
        assert scraper.content_language == "en"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = TritiniaScraper()
        cookie = create_cookie("wordpress_test_cookie", "x", domain="tritinia.org")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SITE}/manga/{SLUG}"])
    def test_series_url(self, url):
        assert TritiniaScraper()._series_parts(url) == (SERIES, SLUG)

    def test_chapter_url(self):
        assert TritiniaScraper()._chapter_parts(f"{SERIES}ch-16") == (CHAPTER, SLUG, "ch-16")

    @pytest.mark.parametrize("url", [
        f"http://tritinia.org/manga/{SLUG}/",
        f"https://www.tritinia.org/manga/{SLUG}/",
        f"{SITE}/series/{SLUG}/",
        f"{SERIES}?style=list",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(TritiniaSourceError):
            TritiniaScraper()._series_parts(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_exact_title_finds_the_series_with_its_cover(self):
        site = _site({("GET", SEARCH): dict(text=_search())})
        assert [(m.title, m.url, m.cover_url) for m in site.search(TITLE)] == [
            (TITLE, SERIES, COVER)]
        assert site.session.calls == [("GET", SEARCH, {"allow_redirects": False})]

    def test_no_matches_is_no_results(self):
        assert _site({("GET", EMPTY): dict(text=_search(empty=True))}).search("zzqxjkvwpyd") == []

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("page", [
        "<html><body>Just a moment</body></html>",
        _search([("https://elsewhere.example/manga/x/", "X")]),
        _search([(SERIES, TITLE), (SERIES, TITLE)]),
        _search([(SERIES, "")]),
    ])
    def test_a_search_page_this_source_cannot_read_raises(self, page):
        with pytest.raises(TritiniaSourceError):
            _site({("GET", EMPTY): dict(text=page)}).search("zzqxjkvwpyd")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_the_served_rows_oldest_first_with_their_dates(self):
        site = _site(_routes())
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url, c.date) for c in chapters] == [
            ("15", f"{SERIES}ch-15/", "2026-01-04"), ("16", CHAPTER, "2026-01-19")]
        assert [(m, u) for m, u, _ in site.session.calls] == [("GET", SERIES), ("POST", AJAX)]
        assert site.session.calls[1][2]["headers"] == {
            "X-Requested-With": "XMLHttpRequest", "Referer": SERIES}

    def test_a_list_not_starting_at_chapter_1_is_reported_once(self, caplog):
        with caplog.at_level(logging.WARNING, logger=tr.logger.name):
            _site(_routes()).get_chapters(SERIES)
        assert caplog.text.count("lists 2 chapter(s), 15 to 16") == 1

    def test_a_list_from_chapter_1_has_no_warning(self, caplog):
        rows = [_row("Ch. 2", f"{SERIES}ch-2/"), _row("Ch. 1.5", f"{SERIES}ch-1-5/"),
                _row("Ch. 1", f"{SERIES}ch-1/")]
        with caplog.at_level(logging.WARNING, logger=tr.logger.name):
            chapters = _site(_routes(chapters=_chapters(rows))).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["1", "1.5", "2"]
        assert "earlier chapters" not in caplog.text

    @pytest.mark.parametrize("rows, reason", [
        ([_row("Ch. 16", "")], "locked or paid"),
        ([_row("Ch. 16", f"{SERIES}ch-16/", cls="wp-manga-chapter premium-block")], "locked or paid"),
        ([_row("Ch. 16", f"{SERIES}ch-16/", cls="wp-manga-chapter coin")], "locked or paid"),
        ([_row("Chapter 16", f"{SERIES}ch-16/")], "unknown form"),
        ([_row("Ch. 16", "https://elsewhere.example/manga/x/ch-16/")], "elsewhere"),
        ([_row("Ch. 16", f"{SITE}/manga/another-series/ch-16/")], "another series"),
        ([_row("Ch. 16", f"{SERIES}ch-16/"), _row("Ch. 16", f"{SERIES}ch-16-b/")], "twice"),
        ([], "no chapters"),
    ])
    def test_a_row_this_source_does_not_read_raises(self, rows, reason):
        with pytest.raises(TritiniaSourceError, match=reason):
            _site(_routes(chapters=_chapters(rows))).get_chapters(SERIES)

    @pytest.mark.parametrize("series, reason", [
        (_series(genres=("Romance", "Smut")), "adult"),
        (_series(badges=("18+",)), "adult"),
        (_series(kind="Novel"), "novel"),
        (_series(canonical=f"{SITE}/manga/other/"), "not a series page"),
        (_series(post_id=""), "not a series page"),
    ])
    def test_a_series_page_not_read_raises_before_its_rows(self, series, reason):
        site = _site(_routes(series=series))
        with pytest.raises(TritiniaSourceError, match=reason):
            site.get_chapters(SERIES)
        assert [m for m, _, _ in site.session.calls] == ["GET"]

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(TritiniaSourceError, match="HTTP 301"):
            _site({("GET", SERIES): dict(status=301)}).get_chapters(SERIES)

    def test_the_cover_comes_from_the_series_page(self):
        assert _site(_routes()).get_cover_url(SERIES) == COVER


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_all_served_pages_are_read_in_served_order(self):
        site = _site(_routes())
        pages = site.get_pages(CHAPTER)
        assert pages == PAGES and len(pages) == 44
        assert pages[21].endswith("/021.jpg") and pages[43].endswith("/049.jpg")
        assert [(m, u) for m, u, _ in site.session.calls] == [("GET", CHAPTER), ("GET", SERIES)]

    def test_names_out_of_order_are_kept_as_served(self):
        served = [PAGES[0], PAGES[2], PAGES[1]]
        assert _site(_routes(reader=_reader(served))).get_pages(CHAPTER) == served

    @pytest.mark.parametrize("reader, reason", [
        (_reader(url=f"{SERIES}ch-15/"), "another page"),
        (_reader(current="ch-15"), "does not name this chapter"),
        (_reader(slug="ch-15"), "does not name this chapter"),
        (_reader(crumb=f"{SITE}/manga/other/"), "does not name this chapter"),
        (_reader(manga_id="9999", post_id="9999"), "names another series"),
        (_reader(post_id="9999"), "does not name this chapter"),
        (_reader(extra='<div id="chapter-protector-data"></div>'), "protected"),
        (_reader(reader_class="reading-content premium-block"), "locked or paid"),
        (_reader(lists=0), "0 page lists"),
        (_reader(lists=2), "2 page lists"),
        (_reader(pages=[]), "lists no pages"),
        (_reader(first=PAGES[1]), "first page"),
        (_reader(pagers=(44, 43)), "counts its pages differently"),
        (_reader(pagers=()), "counts its pages differently"),
    ])
    def test_a_reader_this_source_does_not_read_raises(self, reader, reason):
        with pytest.raises(TritiniaSourceError, match=reason):
            _site(_routes(reader=reader)).get_pages(CHAPTER)

    @pytest.mark.parametrize("pages", [
        [PAGES[0], PAGES[0]],
        [PAGES[0], PAGES[1].replace("c544dea6019037341c5112fd23ee58bd", "0" * 32)],
        [PAGES[0], "https://elsewhere.example/wp-content/uploads/WP-manga/data/manga_1/"
                   + "a" * 32 + "/001.jpg"],
        [PAGES[0], PAGES[1].replace("https:", "http:")],
        [PAGES[0], f"{SITE}/wp-content/uploads/2026/01/cover.jpg"],
        [PAGES[0], PAGES[1] + "?v=1"],
        [PAGES[0], "data:image/jpeg;base64,AAAA"],
    ])
    def test_a_page_list_this_source_does_not_read_raises(self, pages):
        with pytest.raises(TritiniaSourceError):
            _site(_routes(reader=_reader(pages))).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [PAGES[21], PAGES[43], COVER])
    def test_a_served_image_is_saved_with_the_site_as_referer(self, url, tmp_path):
        target = tmp_path / "pages" / "022.jpg"
        site = _site({("GET", url): dict(content=JPEG)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == JPEG
        assert site.session.calls == [("GET", url, {"headers": {"Referer": f"{SITE}/"},
                                                    "allow_redirects": False})]

    @pytest.mark.parametrize("answer", [dict(content=b"<html>not an image</html>"),
                                        dict(status=302, content=JPEG), dict(status=403),
                                        dict(content=b"")])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "022.jpg"
        target.write_bytes(b"older")
        assert _site({("GET", PAGES[21]): answer}).download_image(PAGES[21], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        PAGES[21].replace("https:", "http:"),
        PAGES[21] + "?v=1",
        f"{SITE}/wp-content/themes/madara/images/dflazy.jpg",
        "https://elsewhere.example/wp-content/uploads/2026/01/cover.jpg",
        None,
    ])
    def test_a_url_off_the_image_paths_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "022.jpg"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
