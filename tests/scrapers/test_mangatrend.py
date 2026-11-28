"""Offline tests for Manga Trend: search, the series page's chapter rows
and its partial list, the adult and novel refusals, reader binding, the
``ts_reader`` page list on the wp.com image hosts in served order, and
download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's MangaThemesia pages (search, series and reader).
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import mangatrend as mt
from memanga.scrapers.mangatrend import MangaTrendScraper
from memanga.scrapers.mangathemesia_sites import (MangaThemesiaSourceError,
                                                  MangaThemesiaUnsupportedError)

PARSER_TESTS = {"MangaTrendScraper": ("search", "chapters", "pages")}

SITE = "https://mangatrend.org"
SERIES = f"{SITE}/manga/one-piece-english/"
CHAPTER = f"{SITE}/read-one-piece-1200-english/"
SEARCH = f"{SITE}/?s=One+Piece+English"
EMPTY = f"{SITE}/?s=zzqxjkvwpyd"
UPLOADS = "/mangatrend.org/wp-content/uploads/2026/11"
# The served hosts of chapter 1200's 16 pages, in reader order.
HOSTS = ["i3", "i2", "i0", "i0", "i3", "i0", "i3", "i2", "i0", "i2", "i0", "i2", "i0", "i1",
         "i3", "i2"]
NAMES = ["71279311-9ca2-48c2-8cda-fa113cce6d95", "fbba03fe-1545-4d78-b9bd-15581f18dba8",
         "a7f5f0c8-fcdb-49ed-9d68-c93183bfc3b2", "23f3034a-9849-49db-9665-e5674f09beab",
         "7ca48847-845f-4330-8672-6411fd7dd57d", "a22351a3-ee6b-4a0a-be8c-c8121dc2e799",
         "a16f622d-030c-47fe-973f-4241bab3c374", "361a6780-88e7-49ca-8112-623cf0ffb777",
         "c339714b-8b44-467a-8afb-17384a985d16", "fd0d5fbd-8a62-4e6d-9dff-c0ea69f22fd9",
         "2af06f12-c4b8-4cef-b363-cab5d218357e", "53bfba08-4103-4b57-8374-05af5e8da1ef",
         "96ba0dd9-9c85-4806-a366-239331cd52e5", "16736d11-022f-4685-951b-c242c95d66e5",
         "ad71679d-5673-4334-92e9-3dc25d5c6ae4", "353d1bd5-3c0b-40a0-8fd7-4762cb3b2355"]
PAGES = [f"https://{h}.wp.com{UPLOADS}/{n}.webp" for h, n in zip(HOSTS, NAMES)]
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


def _card(href=SERIES, title="One Piece English", kind="Manga"):
    return (f'<div class="bs"><div class="bsx"><a href="{href}" title="{title}">'
            f'<div class="limit"><span class="type {kind}"></span>'
            f'<img src="https://i1.wp.com/mangatrend.org/wp-content/uploads/2026/02/57.jpeg">'
            f'</div><div class="bigor"><div class="tt">{title}</div><div class="adds">'
            f'<div class="epxs">Chapter 1200</div></div></div></a></div></div>')


def _search(cards):
    inner = "".join(cards) or "<center><h3>Not Found</h3></center>"
    return f'<html><body><div class="listupd">{inner}</div></body></html>'


def _row(number, href=None, label=None, date="November 26, 2026"):
    href = f"{SITE}/read-one-piece-{number}-english/" if href is None else href
    label = f"Chapter {number}" if label is None else label
    link = (f'<a href="{href}"><span class="chapternum">{label}</span>'
            f'<span class="chapterdate">{date}</span></a>') if href else (
        f'<span class="chapternum">{label}</span>')
    return (f'<li data-num="{number}"><div class="chbox"><div class="eph-num">{link}</div>'
            f'</div></li>')


def _series(rows=None, genres=("one piece",), kind="Manga"):
    rows = [_row(n) for n in range(1200, 1172, -1)] if rows is None else rows
    tags = " ".join(f'<a href="{SITE}/genres/{g.replace(" ", "-")}/" rel="tag">{g}</a>'
                    for g in genres)
    return (f'<html><head><link href="{SERIES}" rel="canonical"/>'
            f'<meta content="{SITE}/wp-content/uploads/2026/02/57.jpeg" property="og:image"/>'
            f'</head><body><h1 class="entry-title" itemprop="name">One Piece English</h1>'
            f'<table class="infotable"><tbody><tr><td>Status</td><td>Ongoing</td></tr>'
            f'<tr><td>Type</td><td>{kind}</td></tr></tbody></table>'
            f'<div class="seriestugenre">{tags}</div>'
            f'<div class="eplister" id="chapterlist"><ul>{"".join(rows)}</ul></div>'
            f'</body></html>')


def _reader(images=None, url=CHAPTER, protected=False, is_novel=False, sources=None, calls=1,
            default="Server 1"):
    images = PAGES if images is None else images
    sources = [{"source": "Server 1", "images": images}] if sources is None else sources
    data = {"post_id": 13634, "prevUrl": f"{SITE}/read-one-piece-1199-english/", "nextUrl": "",
            "mode": "full", "sources": sources, "lazyload": False, "defaultSource": default,
            "contentmode": "advanced", "protected": protected, "is_novel": is_novel,
            "unlock_token": None}
    script = f"<script>ts_reader.run({json.dumps(data)});</script>" * calls
    return (f'<html><head><link href="{url}" rel="canonical"/></head><body>'
            f'<h1 class="entry-title">Read One Piece 1200 English</h1>'
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
    scraper = MangaTrendScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = MangaTrendScraper()
        assert (scraper.name, scraper.base_url, scraper.engine) == ("mangatrend", SITE, "http")
        assert scraper.content_language == "en"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = MangaTrendScraper()
        cookie = create_cookie("wordpress_test_cookie", "x", domain="mangatrend.org")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SITE}/manga/one-piece-english"])
    def test_series_url(self, url):
        assert MangaTrendScraper()._series_url(url) == SERIES

    @pytest.mark.parametrize("url", [CHAPTER, f"{SITE}/read-one-piece-1200-english"])
    def test_chapter_url(self, url):
        assert MangaTrendScraper()._chapter_url(url) == CHAPTER

    @pytest.mark.parametrize("url", [
        "https://www.mangatrend.org/manga/one-piece-english/",
        "https://karhscans.com/manga/one-piece-english/",
        f"{SITE}/series/one-piece-english/",
        f"{SITE}/manga/one-piece-english/?tab=chapters",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(MangaThemesiaUnsupportedError):
            MangaTrendScraper()._series_url(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_exact_title_finds_the_series(self):
        site = _site({SEARCH: dict(text=_search([_card()]))})
        assert [(m.title, m.url) for m in site.search("One Piece English")] == [
            ("One Piece English", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_not_found_is_no_results(self):
        assert _site({EMPTY: dict(text=_search([]))}).search("zzqxjkvwpyd") == []

    def test_a_card_off_the_site_is_left_out(self):
        cards = [_card(href="https://karhscans.com/manga/one-piece-english/"), _card()]
        results = _site({SEARCH: dict(text=_search(cards))}).search("One Piece English")
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
        assert [c.number for c in chapters] == [str(n) for n in range(1200, 1172, -1)]
        assert (chapters[0].url, chapters[0].title, chapters[0].date) == (
            CHAPTER, "Chapter 1200", "November 26, 2026")
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_a_list_not_starting_at_chapter_1_is_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            _site({SERIES: dict(text=_series())}).get_chapters(SERIES)
        assert "lists 28 chapter(s), 1173 to 1200" in caplog.text

    def test_a_list_from_chapter_1_has_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _site({SERIES: dict(text=_series([_row(2), _row(1)]))}).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["2", "1"]
        assert "earlier chapters" not in caplog.text

    def test_a_row_without_a_link_raises(self):
        rows = [_row(1201, href=""), _row(1200)]
        with pytest.raises(MangaThemesiaSourceError, match="may be locked"):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    def test_a_row_linking_off_the_site_raises(self):
        rows = [_row(1200, href="https://karhscans.com/read-one-piece-1200-english/")]
        with pytest.raises(MangaThemesiaSourceError, match="not to a chapter of this site"):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    def test_a_row_whose_label_disagrees_is_left_out_with_a_warning(self, caplog):
        rows = [_row(1200), _row(1199, label="Chapter 1198")]
        with caplog.at_level(logging.WARNING, logger="memanga.scrapers.mangathemesia_sites"):
            chapters = _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["1200"]
        assert "1 chapter row(s)" in caplog.text

    @pytest.mark.parametrize("genres, kind, reason", [
        (("one piece", "Adult"), "Manga", "adult genre"),
        (("Smut",), "Manhwa", "adult genre"),
        (("one piece",), "Novel", "is a novel"),
        (("one piece",), "Web Novel", "is a novel"),
    ])
    def test_an_adult_or_novel_series_is_refused(self, genres, kind, reason):
        page = _series(genres=genres, kind=kind)
        with pytest.raises(MangaThemesiaSourceError, match=reason):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(MangaThemesiaSourceError, match="HTTP 301"):
            _site({SERIES: dict(status=301)}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_read_as_served_across_the_four_image_hosts(self):
        site = _site({CHAPTER: dict(text=_reader())})
        pages = site.get_pages(CHAPTER)
        assert pages == PAGES
        assert {p.split("/")[2] for p in pages} == {"i0.wp.com", "i1.wp.com", "i2.wp.com",
                                                    "i3.wp.com"}
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    def test_served_order_is_kept_and_never_sorted(self):
        reordered = PAGES[8:] + PAGES[:8]
        assert _site({CHAPTER: dict(text=_reader(reordered))}).get_pages(CHAPTER) == reordered

    @pytest.mark.parametrize("page, reason", [
        (_reader(url=f"{SITE}/read-one-piece-1199-english/"), "not the chapter asked for"),
        (_reader(protected=True), "protected"),
        (_reader(is_novel=True), "novel chapter"),
        (_reader(calls=0), "0 reader page lists"),
        (_reader(sources=[]), "without image sources"),
        (_reader(sources=[{"source": "A", "images": PAGES}, {"source": "B", "images": PAGES}],
                 default="C"), "one default image source"),
        (_reader(images=[]), "empty reader"),
        (_reader(images=PAGES[:2] + [PAGES[0].replace("i3.wp.com", "i0.wp.com")]), "twice"),
    ])
    def test_a_reader_this_source_does_not_read_raises(self, page, reason):
        with pytest.raises(MangaThemesiaSourceError, match=reason):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("image", [
        f"https://i4.wp.com{UPLOADS}/{NAMES[0]}.webp",
        f"https://mangatrend.org/wp-content/uploads/2026/11/{NAMES[0]}.webp",
        f"https://i0.wp.com/karhscans.com/wp-content/uploads/2026/11/{NAMES[0]}.webp",
        f"http://i0.wp.com{UPLOADS}/{NAMES[0]}.webp",
        f"https://i0.wp.com/mangatrend.org/wp-content/themes/mangareader/assets/img/readerarea.svg",
        "data:image/webp;base64,AAAA",
    ])
    def test_a_page_off_the_served_image_path_raises(self, image):
        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            _site({CHAPTER: dict(text=_reader([PAGES[0], image]))}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [PAGES[8], PAGES[13], PAGES[15]])
    def test_a_page_is_saved_from_its_served_host(self, url, tmp_path):
        target = tmp_path / "pages" / "009.webp"
        site = _site({url: dict(content=WEBP)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == WEBP
        assert site.session.calls == [(url, {"allow_redirects": False,
                                             "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [dict(content=b"<html>not an image</html>"),
                                        dict(status=302, content=WEBP)])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "009.webp"
        target.write_bytes(b"older")
        assert _site({PAGES[8]: answer}).download_image(PAGES[8], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"https://mangatrend.org/wp-content/uploads/2026/11/{NAMES[8]}.webp",
        f"https://i4.wp.com{UPLOADS}/{NAMES[8]}.webp",
        f"{SITE}/wp-content/uploads/2026/02/57.jpeg",
    ])
    def test_a_url_off_the_served_image_path_is_refused_without_a_request(self, url, tmp_path):
        site = _site({})
        assert site.download_image(url, tmp_path / "x.webp") is False
        assert site.session.calls == []
