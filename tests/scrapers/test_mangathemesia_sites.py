"""Offline tests for the French MangaThemesia readers, SushiScan and
Lelmanga: URL identity, search, chapter lists, reader pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the shapes these sites serve: ``.listupd .bs .bsx`` result
cards, chapter rows with a "Chapitre N" label and a ``data-num`` that is the
bare number on Lelmanga and the whole label on SushiScan, a plain JSON
``ts_reader.run`` page list on SushiScan, and ``img`` elements in
``div#readerarea`` on Lelmanga, through the wp.com image hosts.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import get_scraper
from memanga.scrapers import mangathemesia_sites as mt
from memanga.scrapers.mangathemesia_sites import (LelMangaScraper,
                                                  MangaThemesiaSourceError,
                                                  MangaThemesiaUnsupportedError,
                                                  SushiScanScraper)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {
    "LelMangaScraper": ("search", "chapters", "pages"),
    "SushiScanScraper": ("search", "chapters", "pages"),
}

SUSHI = "https://sushiscan.net"
LEL = "https://www.lelmanga.com"
SUSHI_SERIES = f"{SUSHI}/catalogue/kagurabachi/"
LEL_SERIES = f"{LEL}/manga/one-piece-aces-story"
SUSHI_CHAPTER = f"{SUSHI}/kagurabachi-chapitre-119/"
LEL_CHAPTER = f"{LEL}/one-piece-aces-story-4"


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


def _site(cls, routes):
    scraper = cls()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the sites' ────────────────────────────────────

def _card(href, title):
    return (f'<div class="bs"><div class="bsx"><a href="{href}" title="{title}">'
            f'<div class="limit"><img src="{SUSHI}/cover.webp"></div>'
            f'<div class="bigor"><div class="tt">{title}</div>'
            f'<div class="adds"><div class="epxs">Chapitre 1</div></div></div>'
            f'</a></div></div>')


def _results(*cards):
    return ('<html><body><div class="listupd">' + "".join(cards) + '</div>'
            '<div class="pagination"><a class="next" href="/page/2">Suivant</a></div>'
            '</body></html>')


def _row(url, number, label=None, date="19 avril 2026"):
    label = f"Chapitre {number}" if label is None else label
    return (f'<li data-num="{number}"><div class="chbox"><div class="eph-num">'
            f'<a href="{url}"><span class="chapternum">{label}</span>'
            f'<span class="chapterdate">{date}</span></a></div></div></li>')


def _sushi_row(url, number, label=None, raw=None, date="19 avril 2026"):
    """A SushiScan row: its ``data-num`` repeats the label unless ``raw`` is given."""
    label = f"Chapitre {number}" if label is None else label
    return _row(url, label if raw is None else raw, label=label, date=date)


def _series(*rows, title="Kagurabachi"):
    heading = f'<h1 class="entry-title">{title}</h1>' if title else ""
    return (f'<html><body>{heading}<div class="eplister" id="chapterlist"><ul>'
            + "".join(rows) + '</ul></div></body></html>')


def _sushi_chapter(n):
    return f"{SUSHI}/kagurabachi-chapitre-{n}/"


def _lel_chapter(n):
    return f"{LEL}/one-piece-aces-story-{n}"


SUSHI_PAGES = [f"https://c.sushiscan.net/wp-content/uploads97/KagurabachiChap119-{n:02d}.webp"
               for n in range(1, 18)]
# As served: file numbers skip (001-2 then 003: a merged page), several
# image hosts, and a query on every URL.
LEL_PAGES = [
    "https://i2.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/001-2.jpg?lmv=a1",
    "https://i2.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/003.jpg?lmv=a1",
    "https://i0.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/004-1.png?lmv=a1",
    "https://i1.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/045.png?lmv=a1",
    "https://i3.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/047.png?lmv=a1",
    "https://i3.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/046.png?lmv=a1",
]


def _ts_reader(images=None, **overrides):
    data = {"prevUrl": _sushi_chapter(118), "nextUrl": "", "mode": "full",
            "contentmode": "default", "protected": False, "is_novel": False,
            "post_id": 1, "lazyload": True, "lazyloadPlaceHolder": "", "noimagehtml": "",
            "progressBar": True, "defaultSource": "Server 1",
            "sources": [{"source": "Server 1",
                         "images": SUSHI_PAGES if images is None else images}]}
    data.update(overrides)
    return ('<html><body><div id="readerarea"></div><script>ts_reader.run('
            + json.dumps(data) + ');</script></body></html>')


def _lel_reader(*sources, reader=True):
    images = "".join(f'<img src="{src}" class="ts-main-image">' for src in sources)
    area = f'<div id="readerarea">{images}</div>' if reader else ""
    return (f'<html><body><img class="logo" src="{LEL}/wp-content/uploads/logo.png">'
            f'{area}<img src="https://i0.wp.com/www.lelmanga.com/wp-content/uploads/footer.png">'
            f'</body></html>')


# ── URL identity and registration ───────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("cls, url, canonical", [
        (SushiScanScraper, SUSHI_SERIES, SUSHI_SERIES),
        (SushiScanScraper, f"{SUSHI}/catalogue/kagurabachi", SUSHI_SERIES),
        (SushiScanScraper, "https://www.sushiscan.net/catalogue/kagurabachi/", SUSHI_SERIES),
        (SushiScanScraper, "http://sushiscan.net/catalogue/kagurabachi/", SUSHI_SERIES),
        (LelMangaScraper, LEL_SERIES, LEL_SERIES),
        (LelMangaScraper, f"{LEL_SERIES}/", LEL_SERIES),
        (LelMangaScraper, "https://lelmanga.com/manga/one-piece-aces-story", LEL_SERIES),
        (LelMangaScraper, f"{LEL}/manhwa/shards-of-a-broken-glass-slipper",
         f"{LEL}/manhwa/shards-of-a-broken-glass-slipper"),
    ])
    def test_a_series_url_has_one_canonical_form(self, cls, url, canonical):
        assert cls()._series_url(url) == canonical

    @pytest.mark.parametrize("cls, url", [
        (SushiScanScraper, "https://sushiscan.net.example.test/catalogue/x/"),
        (SushiScanScraper, "https://sushiscan.fr/catalogue/x/"),
        (SushiScanScraper, "https://sushiscan.st/catalogue/x/"),
        (SushiScanScraper, "https://c.sushiscan.net/catalogue/x/"),
        (SushiScanScraper, "https://user@sushiscan.net/catalogue/x/"),
        (SushiScanScraper, "https://sushiscan.net:8443/catalogue/x/"),
        (SushiScanScraper, "https://sushiscan.net/catalogue/x/?page=2"),
        (SushiScanScraper, "https://sushiscan.net/catalogue/x/#top"),
        (SushiScanScraper, "ftp://sushiscan.net/catalogue/x/"),
        (SushiScanScraper, "/catalogue/x/"),
        (SushiScanScraper, "https://sushiscan.net/catalogue/"),
        (SushiScanScraper, "https://sushiscan.net/manga/x/"),
        (SushiScanScraper, "https://sushiscan.net/catalogue/x/y/"),
        (SushiScanScraper, "https://sushiscan.net/catalogue//x/"),
        (SushiScanScraper, "https://sushiscan.net/catalogue/../x/"),
        (LelMangaScraper, "https://www.lelmanga.com/catalogue/x"),
        (LelMangaScraper, "https://www.lelmanga.com/manhua/x"),
        (LelMangaScraper, "https://mangahub.fr/manga/x"),
    ])
    def test_other_urls_are_not_series(self, cls, url):
        with pytest.raises(MangaThemesiaUnsupportedError):
            cls()._series_url(url)

    @pytest.mark.parametrize("cls, url", [
        (SushiScanScraper, SUSHI_SERIES),
        (SushiScanScraper, f"{SUSHI}/catalogue"),
        (SushiScanScraper, f"{SUSHI}/"),
        (LelMangaScraper, LEL_SERIES),
        (LelMangaScraper, f"{LEL}/manga"),
    ])
    def test_a_series_page_is_not_a_chapter_and_sends_nothing(self, cls, url):
        scraper = _site(cls, {})

        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_an_unsupported_url_is_a_value_error(self):
        assert issubclass(MangaThemesiaUnsupportedError, ValueError)
        assert issubclass(MangaThemesiaSourceError, RuntimeError)


class TestRegistration:
    @pytest.mark.parametrize("domain, cls", [
        ("sushiscan.net", SushiScanScraper),
        ("www.sushiscan.net", SushiScanScraper),
        ("lelmanga.com", LelMangaScraper),
        ("www.lelmanga.com", LelMangaScraper),
    ])
    def test_each_host_resolves_to_its_own_class(self, domain, cls):
        assert type(get_scraper(domain)) is cls

    @pytest.mark.parametrize("domain", ["sushiscan.fr", "sushiscan.st"])
    def test_lookalike_domains_are_not_registered(self, domain):
        from memanga.scrapers import UnsupportedSourceError

        with pytest.raises(UnsupportedSourceError):
            get_scraper(domain)

    @pytest.mark.parametrize("domain, row", [
        ("sushiscan.net",
         "| sushiscan.net | — | http | fr | No | Included in search | French manga scans |"),
        ("lelmanga.com",
         "| lelmanga.com | — | http | fr | No | Included in search | French manga and manhwa scans |"),
    ])
    def test_catalog_and_docs_list_the_source(self, domain, row):
        from memanga.scrapers import DEFAULT_ENABLED_SOURCES
        from memanga.scrapers.catalog import source_catalog

        info = {r.domain: r for r in source_catalog()}[domain]
        assert (info.engine, info.language, info.search_status) == (
            "http", "fr", "Included in search")
        assert domain not in DEFAULT_ENABLED_SOURCES
        docs = Path(__file__).resolve().parents[2] / "docs" / "SUPPORTED_SOURCES.md"
        # The generated table has coverage columns after the notes.
        assert any(line.startswith(f"{row} ")
                   for line in docs.read_text(encoding="utf-8").splitlines())

    @pytest.mark.parametrize("cls", [SushiScanScraper, LelMangaScraper])
    def test_source_metadata(self, cls):
        assert (cls.engine, cls.content_language, cls.nsfw) == ("http", "fr", False)
        assert cls.reading_direction is None

    @pytest.mark.parametrize("cls", [SushiScanScraper, LelMangaScraper])
    def test_cookies_a_site_sets_are_not_kept(self, cls):
        scraper = cls()
        request = MockRequest(requests.Request("GET", f"{scraper.base_url}/").prepare())
        domain = "." + scraper.base_url.split("//")[1].removeprefix("www.")

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("session", "x", domain=domain), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

SUSHI_SEARCH = f"{SUSHI}/page/1?s=kagurabachi"
LEL_SEARCH = f"{LEL}/?s=one+piece"


class TestSearch:
    def test_sushiscan_results(self):
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(
            text=_results(_card(SUSHI_SERIES, "Kagurabachi")))})

        results = scraper.search(" kagurabachi ")

        assert [(m.title, m.url) for m in results] == [("Kagurabachi", SUSHI_SERIES)]
        (url, kwargs), = scraper.session.calls
        assert url == SUSHI_SEARCH and kwargs["allow_redirects"] is False

    def test_lelmanga_results_keep_the_sites_order_and_kinds(self):
        manhwa = f"{LEL}/manhwa/shards-of-a-broken-glass-slipper"
        scraper = _site(LelMangaScraper, {LEL_SEARCH: dict(text=_results(
            _card(LEL_SERIES, "One Piece: Ace’s Story"),
            _card(f"{LEL}/manga/one-piece", "One Piece"),
            _card(manhwa, "Shards Of A Broken Glass Slipper")))})

        assert [(m.title, m.url) for m in scraper.search("one piece")] == [
            ("One Piece: Ace’s Story", LEL_SERIES),
            ("One Piece", f"{LEL}/manga/one-piece"),
            ("Shards Of A Broken Glass Slipper", manhwa),
        ]

    def test_other_sites_links_and_repeats_are_left_out(self):
        scraper = _site(LelMangaScraper, {LEL_SEARCH: dict(text=_results(
            _card(LEL_SERIES, "Ace"),
            _card(f"{LEL_SERIES}/", "Ace again"),
            _card("https://example.test/manga/other", "Elsewhere"),
            _card(f"{LEL}/one-piece-aces-story-4", "A chapter")))})

        assert [m.title for m in scraper.search("one piece")] == ["Ace"]

    def test_an_empty_result_list_is_no_results(self):
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(text=_results())})

        assert scraper.search("kagurabachi") == []

    @pytest.mark.parametrize("page", [
        "<html><head><title>Just a moment...</title></head><body></body></html>",
        "<html><body><div class='bs'><div class='bsx'></div></div></body></html>",
        "",
    ], ids=["challenge", "no-result-list", "empty-body"])
    def test_a_page_without_the_result_list_is_an_error_not_no_results(self, page):
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(text=page)})

        with pytest.raises(MangaThemesiaSourceError, match="did not serve a result list"):
            scraper.search("kagurabachi")

    @pytest.mark.parametrize("card", [
        '<div class="bs"><div class="bsx"><a href="https://sushiscan.net/catalogue/x/">x</a></div></div>',
        '<div class="bs"><div class="bsx"><a title="X">x</a></div></div>',
        '<div class="bs"><div class="bsx"><a href="https://sushiscan.net/catalogue/x/" title="  ">x</a></div></div>',
        '<div class="bs"><div class="bsx"></div></div>',
    ], ids=["no-title", "no-href", "blank-title", "no-link"])
    def test_a_result_without_link_or_title_is_an_error(self, card):
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(text=_results(card))})

        with pytest.raises(MangaThemesiaSourceError, match="without its link or title"):
            scraper.search("kagurabachi")

    def test_a_redirected_search_is_an_error(self):
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(status=301)})

        with pytest.raises(MangaThemesiaSourceError, match="HTTP 301"):
            scraper.search("kagurabachi")

    def test_a_refused_search_raises(self):
        scraper = _site(LelMangaScraper, {LEL_SEARCH: dict(status=403)})

        with pytest.raises(requests.HTTPError):
            scraper.search("one piece")

    def test_a_query_is_sent_as_one_value(self):
        url = f"{SUSHI}/page/1?s=a%26b%3Dc+d"
        scraper = _site(SushiScanScraper, {url: dict(text=_results())})

        assert scraper.search("a&b=c d") == []

    def test_a_blank_query_sends_nothing(self):
        scraper = _site(SushiScanScraper, {})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_SEARCH_RESULTS", 2)
        cards = [_card(f"{SUSHI}/catalogue/s{n}/", f"S{n}") for n in range(5)]
        scraper = _site(SushiScanScraper, {SUSHI_SEARCH: dict(text=_results(*cards))})

        assert len(scraper.search("kagurabachi")) == 2


# ── Chapters ────────────────────────────────────────────────────────

def _sushi_chapters(*rows, **page):
    scraper = _site(SushiScanScraper, {SUSHI_SERIES: dict(text=_series(*rows, **page))})
    return scraper.get_chapters(SUSHI_SERIES)


def _lel_chapters(*rows):
    scraper = _site(LelMangaScraper, {LEL_SERIES: dict(text=_series(*rows, title="Ace"))})
    return scraper.get_chapters(LEL_SERIES)


# The 122 rows of the real Kagurabachi list: 1 to 119 and three half chapters.
KAGURABACHI_NUMBERS = sorted([str(n) for n in range(1, 120)] + ["112.5", "92.5", "58.5"],
                             key=float, reverse=True)


class TestChapters:
    def test_chapters_newest_first_with_decimals(self):
        chapters = _sushi_chapters(
            _sushi_row(_sushi_chapter(119), 119),
            _sushi_row(_sushi_chapter("118-5"), "118.5"),
            _sushi_row(_sushi_chapter(118), 118, date="14 avril 2026"),
            _sushi_row(_sushi_chapter(1), 1, date="1 octobre 2024"))

        assert [c.number for c in chapters] == ["119", "118.5", "118", "1"]
        assert [c.title for c in chapters] == [
            "Chapitre 119", "Chapitre 118.5", "Chapitre 118", "Chapitre 1"]
        assert chapters[1].url == _sushi_chapter("118-5")
        assert (chapters[2].date, chapters[3].date) == ("14 avril 2026", "1 octobre 2024")

    def test_rows_are_sorted_by_number_not_page_order(self):
        chapters = _sushi_chapters(_sushi_row(_sushi_chapter(2), 2),
                                   _sushi_row(_sushi_chapter(10), 10),
                                   _sushi_row(_sushi_chapter(1), 1))

        assert [c.number for c in chapters] == ["10", "2", "1"]

    def test_the_whole_sushiscan_list_with_its_half_chapters(self, caplog):
        rows = [_sushi_row(_sushi_chapter(n.replace(".", "-")), n) for n in KAGURABACHI_NUMBERS]

        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _sushi_chapters(*rows)

        assert len(chapters) == 122
        assert [c.number for c in chapters] == KAGURABACHI_NUMBERS
        assert [c.title for c in chapters] == [f"Chapitre {n}" for n in KAGURABACHI_NUMBERS]
        assert len({c.url for c in chapters}) == 122
        assert caplog.text == ""

    def test_sushiscan_spacing_in_the_row_is_not_part_of_the_number(self):
        row = _sushi_row(_sushi_chapter("12-5"), "12.5", label="\n  Chapitre\n 12.5 ",
                         raw="  Chapitre  12.5 ")

        chapter, = _sushi_chapters(row)

        assert (chapter.number, chapter.title) == ("12.5", "Chapitre 12.5")

    @pytest.mark.parametrize("raw, label", [
        ("119", "Chapitre 119"),
        ("Chapitre 119", "Chapitre 118"),
        ("Chapitre 112.5", "Chapitre 112"),
        ("Chapitre 112", "Chapitre 112.5"),
        ("", "Chapitre 5"),
        ("Chapitre 5", ""),
        ("Volume 3", "Volume 3"),
        ("Spécial", "Spécial"),
        ("chapitre 5", "chapitre 5"),
        ("Chapitres 5", "Chapitres 5"),
        ("Chapitre 4,5", "Chapitre 4,5"),
        ("Chapitre 1-2", "Chapitre 1-2"),
        ("Chapitre 1.", "Chapitre 1."),
        ("Chapitre .5", "Chapitre .5"),
        ("Chapitre 1.2.3", "Chapitre 1.2.3"),
        ("Chapitre 5 : Fin", "Chapitre 5 : Fin"),
        ("Chapitre 5 Chapitre 6", "Chapitre 5 Chapitre 6"),
        ("Chapitre ٣", "Chapitre ٣"),
        ("Chapitre " + "9" * 400, "Chapitre " + "9" * 400),
    ], ids=["bare-number", "numbers-disagree", "decimal-vs-whole", "whole-vs-decimal",
            "no-data-num", "no-label", "volume", "special", "lowercase", "plural", "comma",
            "range", "trailing-dot", "leading-dot", "two-dots", "with-title", "two-numbers",
            "other-digits", "oversized"])
    def test_a_sushiscan_row_not_exactly_its_label_stops_the_list(self, raw, label):
        with pytest.raises(MangaThemesiaSourceError, match="not a plain numbered chapter"):
            _sushi_chapters(_sushi_row(_sushi_chapter(119), 119),
                            _sushi_row(_sushi_chapter("x"), 5, label=label, raw=raw))

    def test_a_sushiscan_row_without_its_label_element_stops_the_list(self):
        row = (f'<li data-num="Chapitre 5"><div class="eph-num">'
               f'<a href="{_sushi_chapter(5)}">Chapitre 5</a></div></li>')

        with pytest.raises(MangaThemesiaSourceError, match="not a plain numbered chapter"):
            _sushi_chapters(row)

    def test_a_chapter_slug_need_not_match_the_series_slug(self):
        # As served: /catalogue/hajimenoippo/ lists /hajime-no-ippo-chapitre-1510/.
        url = f"{SUSHI}/catalogue/hajimenoippo/"
        chapter = f"{SUSHI}/hajime-no-ippo-chapitre-1510/"
        scraper = _site(SushiScanScraper, {url: dict(
            text=_series(_sushi_row(chapter, 1510), title="Hajime no Ippo"))})

        assert [c.url for c in scraper.get_chapters(url)] == [chapter]

    def test_lelmanga_chapters_keep_their_url_form(self):
        rows = [_row(_lel_chapter(n), n, date="December 2, 2021") for n in (4, 3, 2, 1)]
        scraper = _site(LelMangaScraper, {LEL_SERIES: dict(text=_series(*rows, title="Ace"))})

        chapters = scraper.get_chapters(LEL_SERIES)

        assert [c.number for c in chapters] == ["4", "3", "2", "1"]
        assert chapters[0].url == LEL_CHAPTER
        assert chapters[0].date == "December 2, 2021"

    def test_the_series_is_fetched_at_its_canonical_url_without_redirects(self):
        scraper = _site(SushiScanScraper, {SUSHI_SERIES: dict(
            text=_series(_sushi_row(_sushi_chapter(1), 1)))})

        scraper.get_chapters(f"{SUSHI}/catalogue/kagurabachi")

        (url, kwargs), = scraper.session.calls
        assert url == SUSHI_SERIES and kwargs["allow_redirects"] is False

    def test_a_row_without_a_link_stops_the_list_as_possibly_locked(self):
        locked = ('<li data-num="Chapitre 120"><div class="eph-num"><span class="chapternum">'
                  'Chapitre 120</span></div></li>')

        with pytest.raises(MangaThemesiaSourceError, match="may be locked"):
            _sushi_chapters(locked, _sushi_row(_sushi_chapter(119), 119))

    @pytest.mark.parametrize("href", [
        "https://example.test/kagurabachi-chapitre-119/",
        "https://c.sushiscan.net/kagurabachi-chapitre-119/",
        f"{SUSHI}/catalogue/kagurabachi/",
        f"{SUSHI}/a/b/",
        f"{SUSHI}/kagurabachi-chapitre-119/?x=1",
        "/kagurabachi-chapitre-119/",
    ], ids=["other-site", "image-host", "series-page", "deep-path", "query", "relative"])
    def test_a_row_linked_elsewhere_is_an_error(self, href):
        with pytest.raises(MangaThemesiaSourceError, match="not to a chapter of this site"):
            _sushi_chapters(_sushi_row(href, 119))

    @pytest.mark.parametrize("row", [
        _row(_lel_chapter("v3"), 3, label="Volume 3"),
        _row(_lel_chapter("x"), 4, label="Chapitre 5"),
        _row(_lel_chapter("y"), "4,5", label="Chapitre 4,5"),
        _row(_lel_chapter("z"), "abc", label="Chapitre 6"),
        _row(_lel_chapter("w"), 7, label="Spécial"),
        _row(_lel_chapter("r"), "Chapitre 6", label="Chapitre 6"),
    ], ids=["volume", "number-disagrees", "comma-decimal", "bad-data-num", "no-number",
            "label-as-data-num"])
    def test_a_lelmanga_row_not_a_plain_chapter_is_reported_not_guessed(self, row, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _lel_chapters(_row(_lel_chapter(1), 1), row)

        assert [c.number for c in chapters] == ["1"]
        assert "1 chapter row(s)" in caplog.text and "not listed" in caplog.text

    def test_lelmanga_reads_a_decimal_from_its_bare_number(self):
        chapters = _lel_chapters(_row(_lel_chapter("4-5"), "4.5"), _row(_lel_chapter(4), 4))

        assert [c.number for c in chapters] == ["4.5", "4"]

    def test_one_number_with_two_links_keeps_the_first_and_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _sushi_chapters(_sushi_row(_sushi_chapter("2-new"), 2),
                                       _sushi_row(_sushi_chapter(2), 2))

        assert [c.url for c in chapters] == [_sushi_chapter("2-new")]
        assert "repeat a number" in caplog.text

    def test_a_repeated_row_is_listed_once(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _sushi_chapters(_sushi_row(_sushi_chapter(2), 2),
                                       _sushi_row(_sushi_chapter(2), 2))

        assert [c.number for c in chapters] == ["2"]
        assert caplog.text == ""

    def test_one_link_with_two_numbers_is_an_error(self):
        with pytest.raises(MangaThemesiaSourceError, match="two chapter numbers"):
            _sushi_chapters(_sushi_row(_sushi_chapter(2), 2), _sushi_row(_sushi_chapter(2), 3))

    def test_a_list_with_no_usable_row_is_an_error(self):
        with pytest.raises(MangaThemesiaSourceError, match="no chapter row"):
            _lel_chapters(_row(_lel_chapter("v1"), 1, label="Volume 1"))

    def test_a_series_page_without_chapters_is_an_error_not_an_empty_list(self):
        with pytest.raises(MangaThemesiaSourceError, match="lists no chapters"):
            _sushi_chapters()

    @pytest.mark.parametrize("page", [
        "<html><head><title>Just a moment...</title></head><body></body></html>",
        _series(_sushi_row(_sushi_chapter(1), 1), title=""),
    ], ids=["challenge", "no-series-title"])
    def test_a_page_that_is_not_a_series_is_an_error(self, page):
        scraper = _site(SushiScanScraper, {SUSHI_SERIES: dict(text=page)})

        with pytest.raises(MangaThemesiaSourceError, match="not a series page"):
            scraper.get_chapters(SUSHI_SERIES)

    def test_a_redirected_series_is_an_error(self):
        scraper = _site(SushiScanScraper, {SUSHI_SERIES: dict(status=302)})

        with pytest.raises(MangaThemesiaSourceError, match="HTTP 302"):
            scraper.get_chapters(SUSHI_SERIES)

    def test_a_refused_series_raises(self):
        scraper = _site(SushiScanScraper, {SUSHI_SERIES: dict(status=404)})

        with pytest.raises(requests.HTTPError):
            scraper.get_chapters(SUSHI_SERIES)

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_CHAPTERS", 1)

        with pytest.raises(MangaThemesiaSourceError, match="more chapters"):
            _sushi_chapters(_sushi_row(_sushi_chapter(2), 2), _sushi_row(_sushi_chapter(1), 1))


# ── SushiScan reader ────────────────────────────────────────────────

def _sushi_pages(page):
    scraper = _site(SushiScanScraper, {SUSHI_CHAPTER: dict(text=page)})
    return scraper.get_pages(SUSHI_CHAPTER)


class TestSushiScanPages:
    def test_every_listed_page_in_reader_order(self):
        scraper = _site(SushiScanScraper, {SUSHI_CHAPTER: dict(text=_ts_reader())})

        assert scraper.get_pages(SUSHI_CHAPTER) == SUSHI_PAGES
        (url, kwargs), = scraper.session.calls
        assert url == SUSHI_CHAPTER and kwargs["allow_redirects"] is False

    def test_the_list_order_is_kept_as_served(self):
        shuffled = [SUSHI_PAGES[2], SUSHI_PAGES[0], SUSHI_PAGES[1]]

        assert _sushi_pages(_ts_reader(shuffled)) == shuffled

    def test_the_default_of_several_sources_is_read(self):
        other = ["https://c.sushiscan.net/wp-content/uploads97/other-01.webp"]
        page = _ts_reader(sources=[{"source": "Server 2", "images": other},
                                   {"source": "Server 1", "images": SUSHI_PAGES}])

        assert _sushi_pages(page) == SUSHI_PAGES

    @pytest.mark.parametrize("page, why", [
        ('<html><body><div id="readerarea"></div></body></html>', "0 reader page lists"),
        (_ts_reader() + _ts_reader(), "2 reader page lists"),
        ('<script>ts_reader.run({"sources": [}</script>', "not JSON"),
        (_ts_reader(sources=[]), "without image sources"),
        (_ts_reader(sources="x"), "without image sources"),
        (_ts_reader(sources=["x"]), "without images"),
        (_ts_reader(sources=[{"source": "Server 1"}]), "without images"),
        (_ts_reader(defaultSource="Server 9",
                    sources=[{"source": "A", "images": SUSHI_PAGES},
                             {"source": "B", "images": SUSHI_PAGES}]), "one default"),
        (_ts_reader([]), "empty reader"),
    ], ids=["no-reader", "two-readers", "bad-json", "no-sources", "sources-not-list",
            "source-not-object", "no-images", "no-default-source", "empty-list"])
    def test_a_reader_without_one_valid_list_is_an_error(self, page, why):
        with pytest.raises(MangaThemesiaSourceError, match=why):
            _sushi_pages(page)

    def test_an_encoded_reader_script_is_not_decoded(self):
        page = ('<html><body><div id="readerarea"></div><script '
                'src="data:text/javascript;base64,dHNfcmVhZGVyLnJ1bih7fSk7"></script></body></html>')

        with pytest.raises(MangaThemesiaSourceError, match="0 reader page lists"):
            _sushi_pages(page)

    @pytest.mark.parametrize("bad", [
        "",
        None,
        7,
        "http://c.sushiscan.net/wp-content/uploads97/a.webp",
        "/wp-content/uploads97/a.webp",
        "//c.sushiscan.net/wp-content/uploads97/a.webp",
        "https://sushiscan.net/wp-content/uploads97/a.webp",
        "https://i0.wp.com/c.sushiscan.net/wp-content/uploads97/a.webp",
        "https://c.sushiscan.net:8443/wp-content/uploads97/a.webp",
        "https://u@c.sushiscan.net/wp-content/uploads97/a.webp",
        "https://c.sushiscan.net/wp-content/themes/logo.webp",
        "https://c.sushiscan.net/wp-content/uploads97/logo.svg",
        "https://c.sushiscan.net/wp-content/uploads97/a.webp#x",
        "https://c.sushiscan.net/wp-content/uploads97/../a.webp",
        " https://c.sushiscan.net/wp-content/uploads97/a.webp",
        "data:image/png;base64,AAAA",
    ], ids=["empty", "null", "number", "http", "relative", "scheme-relative", "site-host",
            "other-cdn", "port", "login", "theme-path", "svg", "fragment", "dot-dot",
            "leading-space", "data-uri"])
    def test_an_invalid_page_is_an_error_and_never_dropped(self, bad):
        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            _sushi_pages(_ts_reader([*SUSHI_PAGES[:2], bad]))

    def test_a_repeated_page_is_an_error(self):
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            _sushi_pages(_ts_reader([SUSHI_PAGES[0], SUSHI_PAGES[1], SUSHI_PAGES[0]]))

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mt, "_MAX_PAGES", 2)

        with pytest.raises(MangaThemesiaSourceError, match="more pages"):
            _sushi_pages(_ts_reader())

    def test_a_redirected_chapter_is_an_error(self):
        scraper = _site(SushiScanScraper, {SUSHI_CHAPTER: dict(status=302)})

        with pytest.raises(MangaThemesiaSourceError, match="HTTP 302"):
            scraper.get_pages(SUSHI_CHAPTER)


# ── Lelmanga reader ─────────────────────────────────────────────────

def _lel_pages(page):
    scraper = _site(LelMangaScraper, {LEL_CHAPTER: dict(text=page)})
    return scraper.get_pages(LEL_CHAPTER)


class TestLelmangaPages:
    def test_every_reader_image_in_document_order_with_its_query(self):
        # File numbers skip and are out of order at the end: nothing is
        # sorted, filled in or dropped, and images outside the reader
        # (the theme's logo and footer) are not pages.
        assert _lel_pages(_lel_reader(*LEL_PAGES)) == LEL_PAGES

    @pytest.mark.parametrize("bad", [
        f"{LEL}/wp-content/uploads/logo.png",
        "https://i4.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/a.png",
        "https://i0.wp.com/example.test/wp-content/uploads/2021/12/a.png",
        "https://i0.wp.com/www.lelmanga.com/wp-content/themes/logo.png",
        "http://i0.wp.com/www.lelmanga.com/wp-content/uploads/2021/12/a.png",
        "/www.lelmanga.com/wp-content/uploads/2021/12/a.png",
        "data:image/gif;base64,R0lGOD",
    ], ids=["site-host", "unobserved-cdn-shard", "other-site-via-cdn", "theme-path", "http",
            "relative", "placeholder"])
    def test_an_image_in_the_reader_that_is_not_a_page_is_an_error(self, bad):
        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            _lel_pages(_lel_reader(LEL_PAGES[0], bad))

    def test_an_image_without_src_is_an_error(self):
        page = _lel_reader(LEL_PAGES[0]).replace(
            '</div><img src="https://i0', '<img data-src="x"></div><img src="https://i0', 1)

        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            _lel_pages(page)

    def test_one_file_from_two_image_hosts_is_a_repeat(self):
        same = LEL_PAGES[1].replace("i2.wp.com", "i0.wp.com")

        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            _lel_pages(_lel_reader(LEL_PAGES[1], same))

    def test_an_empty_reader_is_an_error(self):
        with pytest.raises(MangaThemesiaSourceError, match="empty reader"):
            _lel_pages(_lel_reader())

    def test_a_page_without_the_reader_is_an_error(self):
        with pytest.raises(MangaThemesiaSourceError, match="0 readers"):
            _lel_pages(_lel_reader(reader=False))

    def test_two_readers_are_an_error(self):
        area = f'<div id="readerarea"><img src="{LEL_PAGES[0]}"></div>'

        with pytest.raises(MangaThemesiaSourceError, match="2 readers"):
            _lel_pages(f"<html><body>{area}{area}</body></html>")

    def test_a_refused_chapter_raises(self):
        scraper = _site(LelMangaScraper, {LEL_CHAPTER: dict(status=403)})

        with pytest.raises(requests.HTTPError):
            scraper.get_pages(LEL_CHAPTER)


# ── Download ────────────────────────────────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


CASES = [(SushiScanScraper, SUSHI_PAGES[0], f"{SUSHI}/"),
         (LelMangaScraper, LEL_PAGES[0], f"{LEL}/")]


class TestDownload:
    @pytest.mark.parametrize("cls, url, referer", CASES)
    def test_a_page_is_saved_with_the_site_as_referer(self, cls, url, referer, tmp_path):
        png = _png()
        scraper = _site(cls, {url: dict(content=png)})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(url, target) is True
        assert target.read_bytes() == png
        (sent, kwargs), = scraper.session.calls
        assert sent == url
        assert kwargs["headers"] == {"Referer": referer}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("cls, url, referer", CASES)
    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""), dict(status=302, content=b""),
    ], ids=["html", "empty", "redirect"])
    def test_an_answer_that_is_not_an_image_clears_an_older_file(
            self, cls, url, referer, answer, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper = _site(cls, {url: answer})

        assert scraper.download_image(url, target) is False
        assert not target.exists()

    @pytest.mark.parametrize("cls, url, referer", CASES)
    def test_a_refused_page_fails(self, cls, url, referer, tmp_path):
        scraper = _site(cls, {url: dict(status=403)})

        assert scraper.download_image(url, tmp_path / "page_001.jpg") is False

    @pytest.mark.parametrize("cls, url", [
        (SushiScanScraper, "https://example.test/wp-content/uploads97/a.webp"),
        (LelMangaScraper, "https://i0.wp.com/example.test/wp-content/uploads/a.png"),
    ])
    def test_a_url_off_the_image_hosts_is_not_requested(self, cls, url, tmp_path):
        scraper = _site(cls, {})

        assert scraper.download_image(url, tmp_path / "page_001.jpg") is False
        assert scraper.session.calls == []
