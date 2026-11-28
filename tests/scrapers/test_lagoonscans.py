"""Offline tests for Lagoon Scans: search, the series page's chapter rows
and its partial list, the adult and novel refusals, reader binding, the
``ts_reader`` page list in served order, and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's MangaThemesia pages (search, series and reader).
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import lagoonscans as ls
from memanga.scrapers.lagoonscans import LagoonScansScraper
from memanga.scrapers.mangathemesia_sites import (MangaThemesiaSourceError,
                                                  MangaThemesiaUnsupportedError)

PARSER_TESTS = {"LagoonScansScraper": ("search", "chapters", "pages")}

SITE = "https://lagoonscans.com"
SERIES = f"{SITE}/manga/magic-emperor/"
CHAPTER = f"{SITE}/magic-emperor-chapter-941/"
SEARCH = f"{SITE}/?s=Magic+Emperor"
EMPTY = f"{SITE}/?s=zzqxjkvwpyd"
UPLOADS = f"{SITE}/wp-content/uploads/2026/11"
PAGES = [f"{UPLOADS}/{n}-{tag}.jpg" for n, tag in enumerate(
    ["5u8gOJoq", "JDvQXr4D", "duAFnlHz", "bjyKx7Ls", "NiZ8YlN8", "o4lrvol4", "zv4gF8rx"], 1)]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _card(href=SERIES, title="Magic Emperor", kind="Manhua"):
    return (f'<div class="bs"><div class="bsx"><a href="{href}" title="{title}">'
            f'<div class="limit"><span class="type {kind}"></span>'
            f'<img src="https://i0.wp.com/lagoonscans.com/wp-content/uploads/2026/07/100001.jpg'
            f'?resize=285,425"></div><div class="bigor"><div class="tt">{title}</div>'
            f'<div class="adds"><div class="epxs">Chapter 941</div></div></div></a></div></div>')


def _search(cards):
    inner = "".join(cards) or "<center><h3>Not Found</h3></center>"
    return f'<html><body><div class="listupd">{inner}</div></body></html>'


def _row(number, href=None, label=None, date="November 27, 2026", first=False):
    href = f"{SITE}/magic-emperor-chapter-{number}/" if href is None else href
    label = f"Chapter {number}" if label is None else label
    link = (f'<a href="{href}"><span class="chapternum">{label}</span>'
            f'<span class="chapterdate">{date}</span></a>') if href else (
        f'<span class="chapternum">{label}</span>')
    cls = ' class="first-chapter"' if first else ""
    return (f'<li data-num="{number}"{cls}><div class="chbox"><div class="eph-num">{link}'
            f'</div><div class="dt"></div></div></li>')


def _series(rows=None, genres=("action", "Adventure", "Drama", "Fantasy", "Shounen"),
            kind="Manhua", sidebar_genres=("Adult",)):
    rows = [_row(n) for n in range(941, 931, -1)] if rows is None else rows
    tags = " ".join(f'<a href="{SITE}/genres/{g.lower()}/" rel="tag">{g}</a>' for g in genres)
    side = ", ".join(f'<a href="{SITE}/genres/{g.lower()}/" rel="tag">{g}</a>'
                     for g in sidebar_genres)
    return (f'<html><head><link rel="canonical" href="{SERIES}" /></head><body>'
            f'<h1 class="entry-title" itemprop="name">Magic Emperor</h1>'
            f'<table class="infotable"><tbody><tr><td>Status</td><td>Ongoing</td></tr>'
            f'<tr><td>Type</td><td>{kind}</td></tr><tr><td>Author</td>'
            f'<td>Wuer Manhua, Ye Xiao</td></tr></tbody></table>'
            f'<div class="seriestugenre">{tags}</div>'
            f'<div class="eplister" id="chapterlist"><ul>{"".join(rows)}</ul></div>'
            # The sidebar lists other series' genres; they are not this series'.
            f'<div id="sidebar"><span><b>Genres</b>: {side}</span></div></body></html>')


def _reader(images=None, url=CHAPTER, protected=False, sources=None, calls=1, default="Server 1"):
    images = PAGES if images is None else images
    sources = [{"source": "Server 1", "images": images}] if sources is None else sources
    data = {"post_id": 94378, "prevUrl": f"{SITE}/magic-emperor-chapter-940/", "nextUrl": "",
            "mode": "full", "sources": sources, "lazyload": False, "defaultSource": default,
            "protected": protected, "unlock_token": None}
    script = f"<script>ts_reader.run({json.dumps(data)});</script>" * calls
    return (f'<html><head><link rel="canonical" href="{url}" /></head><body>'
            f'<h1 class="entry-title">Magic Emperor Chapter 941</h1>'
            f'<div id="readerarea"></div>{script}</body></html>')


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
    scraper = LagoonScansScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = LagoonScansScraper()
        assert (scraper.name, scraper.base_url, scraper.engine) == ("lagoonscans", SITE, "http")
        assert scraper.content_language == "en"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = LagoonScansScraper()
        cookie = create_cookie("wordpress_test_cookie", "x", domain="lagoonscans.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SITE}/manga/magic-emperor"])
    def test_series_url(self, url):
        assert LagoonScansScraper()._series_url(url) == SERIES

    @pytest.mark.parametrize("url", [CHAPTER, f"{SITE}/magic-emperor-chapter-941"])
    def test_chapter_url(self, url):
        assert LagoonScansScraper()._chapter_url(url) == CHAPTER

    @pytest.mark.parametrize("url", [
        "https://www.lagoonscans.com/manga/magic-emperor/",
        "https://scythescans.com/manga/magic-emperor/",
        f"{SITE}/series/magic-emperor/",
        f"{SITE}/manga/magic-emperor/?tab=chapters",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(MangaThemesiaUnsupportedError):
            LagoonScansScraper()._series_url(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_exact_title_finds_the_series(self):
        site = _site({SEARCH: dict(text=_search([_card()]))})
        assert [(m.title, m.url) for m in site.search("Magic Emperor")] == [
            ("Magic Emperor", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_not_found_is_no_results(self):
        assert _site({EMPTY: dict(text=_search([]))}).search("zzqxjkvwpyd") == []

    def test_a_card_off_the_site_is_left_out(self):
        cards = [_card(href="https://scythescans.com/manga/magic-emperor/"), _card()]
        results = _site({SEARCH: dict(text=_search(cards))}).search("Magic Emperor")
        assert [m.url for m in results] == [SERIES]

    def test_a_page_without_the_result_list_raises(self):
        with pytest.raises(MangaThemesiaSourceError, match="did not serve a result list"):
            _site({EMPTY: dict(text="<html><body>Just a moment</body></html>")}).search(
                "zzqxjkvwpyd")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_the_served_rows_newest_first_with_their_dates(self):
        site = _site({SERIES: dict(text=_series())})
        chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == [str(n) for n in range(941, 931, -1)]
        assert (chapters[0].url, chapters[0].title, chapters[0].date) == (
            CHAPTER, "Chapter 941", "November 27, 2026")
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_a_list_not_starting_at_chapter_1_is_reported(self, caplog):
        rows = [_row(n) for n in range(941, 932, -1)] + [_row(932, first=True)]
        with caplog.at_level(logging.WARNING, logger=ls.logger.name):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)
        assert "lists 10 chapter(s), 932 to 941" in caplog.text

    def test_a_list_from_chapter_1_has_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=ls.logger.name):
            chapters = _site({SERIES: dict(text=_series([_row(2), _row(1)]))}).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["2", "1"]
        assert "earlier chapters" not in caplog.text

    def test_a_decimal_chapter_is_read(self):
        chapters = _site({SERIES: dict(text=_series([_row("941.5"), _row(941)]))}).get_chapters(
            SERIES)
        assert [c.number for c in chapters] == ["941.5", "941"]

    def test_a_row_without_a_link_raises(self):
        rows = [_row(942, href=""), _row(941)]
        with pytest.raises(MangaThemesiaSourceError, match="may be locked"):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    def test_a_row_linking_off_the_site_raises(self):
        rows = [_row(941, href="https://scythescans.com/magic-emperor-chapter-941/")]
        with pytest.raises(MangaThemesiaSourceError, match="not to a chapter of this site"):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    def test_a_row_whose_label_disagrees_is_left_out_with_a_warning(self, caplog):
        rows = [_row(941), _row(940, label="Chapter 939")]
        with caplog.at_level(logging.WARNING, logger="memanga.scrapers.mangathemesia_sites"):
            chapters = _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["941"]
        assert "1 chapter row(s)" in caplog.text

    @pytest.mark.parametrize("genres, kind, reason", [
        (("Action", "Adult"), "Manhua", "adult genre"),
        (("Action", "Mature"), "Manhwa", "adult genre"),
        (("Action",), "Novel", "is a novel"),
        (("Action",), "Light Novel", "is a novel"),
    ])
    def test_an_adult_or_novel_series_is_refused(self, genres, kind, reason):
        page = _series(genres=genres, kind=kind)
        with pytest.raises(MangaThemesiaSourceError, match=reason):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_sidebar_genres_of_other_series_do_not_count(self):
        page = _series(sidebar_genres=("Adult", "Hentai"))
        assert _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_page_that_is_not_a_series_page_raises(self):
        with pytest.raises(MangaThemesiaSourceError, match="not a series page"):
            _site({SERIES: dict(text="<html><body>Just a moment</body></html>")}).get_chapters(
                SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(MangaThemesiaSourceError, match="HTTP 301"):
            _site({SERIES: dict(status=301)}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_read_in_served_order(self):
        site = _site({CHAPTER: dict(text=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    def test_served_order_is_kept_even_when_names_run_backwards(self):
        backwards = list(reversed(PAGES))
        assert _site({CHAPTER: dict(text=_reader(backwards))}).get_pages(CHAPTER) == backwards

    def test_the_default_source_is_read_when_several_are_served(self):
        sources = [{"source": "Server 2", "images": PAGES[:2]},
                   {"source": "Server 1", "images": PAGES}]
        assert _site({CHAPTER: dict(text=_reader(sources=sources))}).get_pages(CHAPTER) == PAGES

    @pytest.mark.parametrize("page, reason", [
        (_reader(url=f"{SITE}/magic-emperor-chapter-940/"), "not the chapter asked for"),
        (_reader(protected=True), "protected"),
        (_reader(calls=0), "0 reader page lists"),
        (_reader(calls=2), "2 reader page lists"),
        (_reader(sources=[]), "without image sources"),
        (_reader(sources=[{"source": "A", "images": PAGES}, {"source": "B", "images": PAGES}],
                 default="C"), "one default image source"),
        (_reader(images=[]), "empty reader"),
        (_reader(images=PAGES[:2] + [PAGES[0]]), "twice"),
    ])
    def test_a_reader_this_source_does_not_read_raises(self, page, reason):
        with pytest.raises(MangaThemesiaSourceError, match=reason):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("image", [
        "https://i0.wp.com/lagoonscans.com/wp-content/uploads/2026/11/1-5u8gOJoq.jpg",
        "https://scythescans.com/wp-content/uploads/2026/11/1-5u8gOJoq.jpg",
        "http://lagoonscans.com/wp-content/uploads/2026/11/1-5u8gOJoq.jpg",
        f"{SITE}/wp-content/themes/mangareader/assets/img/readerarea.svg",
        "data:image/jpeg;base64,AAAA",
    ])
    def test_a_page_off_the_upload_path_raises(self, image):
        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            _site({CHAPTER: dict(text=_reader([PAGES[0], image]))}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "004.jpg"
        site = _site({PAGES[3]: dict(content=JPEG)})
        assert site.download_image(PAGES[3], target) is True
        assert target.read_bytes() == JPEG
        assert site.session.calls == [(PAGES[3], {"allow_redirects": False,
                                                  "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [dict(content=b"<html>not an image</html>"),
                                        dict(status=302, content=JPEG)])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "004.jpg"
        target.write_bytes(b"older")
        assert _site({PAGES[3]: answer}).download_image(PAGES[3], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://i0.wp.com/lagoonscans.com/wp-content/uploads/2026/11/1-5u8gOJoq.jpg",
        f"{SITE}/login/",
        "https://scythescans.com/wp-content/uploads/2026/11/1-5u8gOJoq.jpg",
    ])
    def test_a_url_off_the_upload_path_is_refused_without_a_request(self, url, tmp_path):
        site = _site({})
        assert site.download_image(url, tmp_path / "x.jpg") is False
        assert site.session.calls == []
