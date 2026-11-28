"""Offline tests for ChaosTrad: the one supported series, search over the
home page's series menu, the chapter cards, reader binding, pages and
download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the markup the site serves on its home, series and reader
pages.
"""

from __future__ import annotations

import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import chaostrad as ct
from memanga.scrapers.chaostrad import (ChaosTradScraper, ChaosTradSourceError,
                                        ChaosTradUnsupportedError)

PARSER_TESTS = {"ChaosTradScraper": ("search", "chapters", "pages")}

SITE = "https://chaostrad.fr"
HOME = f"{SITE}/"
SERIES = f"{SITE}/comics/shadow-manga"
CHAPTER = f"{SERIES}/4"
FOLDER = "Shadow the Hedgehog Manga-4"
HEXES = [f"{index:032x}" for index in range(1, 30)]
SRCS = [f"/uploads/chapter_images/{FOLDER}/{h}.webp" for h in HEXES]
PAGES = [f"{SITE}/uploads/chapter_images/Shadow%20the%20Hedgehog%20Manga-4/{h}.webp"
         for h in HEXES]
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8

MENU = [
    ("/comics/sonic-idw", "IDW [Série Principale]"),
    ("/search/idw-serie-derivees", "IDW [Série Dérivées]"),
    ("/search/idw-specials", "IDW [Spéciaux]"),
    ("/comics/shadow-manga", "Shadow the hedgehog [Manga]"),
    ("/comics/sonic3", "Sonic 3 Tokyo Mission [Manga]"),
    ("/comics/sonicxfortnite", "Sonic X Fortnite"),
]
DATES = {"4": "10.05.2025", "3": "01.02.2025", "2": "09.11.2024", "1": "22.09.2024"}


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
    scraper = ChaosTradScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _menu_link(href, label, text=True):
    shown = label if text else ""
    return (f'<a title="Chapitre de {label}" href="{href}">\n'
            f'  {shown}\n  <img class="uil uil-arrow-right" src="/assets/images/icons/'
            f'arrow-right-white.svg" alt="Fleche menu1">\n</a>')


def _home(menu=MENU, text=True, menus=1):
    links = "\n".join(_menu_link(href, label, text) for href, label in menu)
    # The mobile menu repeats the links outside the desktop series menu.
    block = f'<div id="comics-submenu" class="submenu">{links}</div>'
    return (f'<html><body><div id="project-subnav-mobile2">{links}</div>'
            f'<a title="Comics" href="" id="comics-main">Comics</a>'
            f'{block * menus}</body></html>')


def _head(url, title):
    return (f'<head><meta charset="UTF-8"/><title>\n\t\t{title}\n\t- ChaosTrad\n</title>'
            f'<link rel="canonical" href="{url}"/>'
            f'<meta name="description" content="Découvrez les bandes dessinées Sonic IDW">'
            f'<meta property="og:url" content="{url}">'
            f'<meta property="og:image" content="/assets/images/icons/logo.png"></head>')


def _card(number, href=None, data_number=None, date=None):
    href = f"/comics/shadow-manga/{number}" if href is None else href
    data_number = number if data_number is None else data_number
    date = DATES.get(number, "01.01.2024") if date is None else date
    return (f'<div data-number="{data_number}" class="col-md-4"><div class="comic-card">'
            f'<a title="Voir le chapitre Shadow the Hedgehog Manga #{number}" class="comic-link"'
            f' href="{href}"><div class="comic-card"><img src="/uploads/chapter_images/'
            f'Shadow the Hedgehog Manga-{number}/{"a" * 32}_thumbnail.webp"></div>'
            f'<h2>Shadow the Hedgehog Manga\n #{number}</h2>'
            f'<p class="release-date">{date}</p></a></div></div>')


def _series(cards=None, count=None, url=SERIES):
    cards = [_card(n) for n in ("4", "3", "2", "1")] if cards is None else cards
    count = len(cards) if count is None else count
    heading = "" if count is False else f'<h2>{count}\n Comics</h2>'
    return (f'<html>{_head(url, "Shadow the Hedgehog Manga")}<body>'
            f'<section id="First"><h1>Shadow the Hedgehog Manga</h1>'
            f'<div id="TagFilter"><div class="nav-tabs">{heading}</div></div>'
            f'<div id="comics-sans-arc"><div class="row chapters-container">{"".join(cards)}'
            f'</div></div></section></body></html>')


def _reader(srcs=SRCS, url=CHAPTER, title_number="4", selected="/comics/shadow-manga/4",
            backlink="/comics/shadow-manga", holders=1):
    options = "".join(
        f'<option data-arc-id="" value="/comics/shadow-manga/{n}"'
        f'{" selected" if f"/comics/shadow-manga/{n}" == selected else ""}>'
        f'Shadow the Hedgehog Manga #{n}</option>' for n in ("1", "2", "3", "4"))
    images = "".join(
        f'<img thumbnail-data="{src[:-5]}_thumbnail.webp" src="{src}" alt="Page {i + 1}"'
        f' class="comic-image" loading="lazy"/>' for i, src in enumerate(srcs))
    return (f'<html>{_head(url, f"Shadow the Hedgehog Manga #{title_number}")}<body>'
            f'<section id="First"><ul class="links"><li><a title="Accueil" href="/">Accueil</a>'
            f'</li><li><a title="Chapitres" href="{backlink}">Shadow the Hedgehog Manga</a></li>'
            f'</ul><select id="chapitreSelect">{options}</select>'
            f'{f"<div id=tel class=tel>{images}</div>" * holders}'
            f'<div class="download-container"><span class="text">Télécharger le chapitre'
            f'</span></div></section></body></html>')


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = ChaosTradScraper()
        assert scraper.name == "chaostrad"
        assert scraper.base_url == SITE
        assert scraper.engine == "http"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is False

    def test_requests_are_spaced(self):
        assert ChaosTradScraper()._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = ChaosTradScraper()
        cookie = create_cookie("site_session", "x", domain="chaostrad.fr")
        request = MockRequest(requests.Request("GET", CHAPTER).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_the_supported_series(self, url):
        assert ChaosTradScraper()._series_slug(url) == "shadow-manga"

    @pytest.mark.parametrize("slug", ["sonic3", "sonic-idw", "sonicxfortnite", "other"])
    def test_other_series_are_refused_before_a_request(self, slug):
        site = _site({})
        with pytest.raises(ChaosTradUnsupportedError, match="not supported"):
            site.get_chapters(f"{SITE}/comics/{slug}")
        with pytest.raises(ChaosTradUnsupportedError, match="not supported"):
            site.get_pages(f"{SITE}/comics/{slug}/1")
        assert site.session.calls == []

    @pytest.mark.parametrize("url", [
        "http://chaostrad.fr/comics/shadow-manga",
        "https://www.chaostrad.fr/comics/shadow-manga",
        "https://chaostrad.fr:8443/comics/shadow-manga",
        "https://chaostrad.fr/comics/shadow-manga?page=2",
        "https://chaostrad.fr/comics/shadow-manga#top",
        "https://chaostrad.fr/search/idw-specials",
        "https://chaostrad.fr/comics",
        "/comics/shadow-manga",
        "https://chaostrad.fr/comics/shadow manga",
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(ChaosTradUnsupportedError):
            ChaosTradScraper()._series_slug(url)

    @pytest.mark.parametrize("url", [
        f"{SERIES}/4.5", f"{SERIES}/0", f"{SERIES}/04", f"{SERIES}/four",
        f"{SERIES}/4/2", SERIES,
    ])
    def test_a_chapter_form_not_read_is_refused(self, url):
        with pytest.raises(ChaosTradUnsupportedError):
            ChaosTradScraper()._chapter_ref(url)

    def test_a_chapter_link(self):
        assert ChaosTradScraper()._chapter_ref(f"{CHAPTER}/") == ("shadow-manga", "4")


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.parametrize("query", [
        "Shadow the hedgehog [Manga]", "  shadow   THE hedgehog [manga] ", "shadow"])
    def test_the_supported_series_is_found_by_its_menu_label(self, query):
        site = _site({HOME: dict(text=_home())})
        results = site.search(query)
        assert [(m.title, m.url) for m in results] == [("Shadow the hedgehog [Manga]", SERIES)]
        assert site.session.calls == [(HOME, {"allow_redirects": False})]

    def test_a_term_with_no_match_is_empty(self):
        assert _site({HOME: dict(text=_home())}).search("zzqxjkvwpyd") == []

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search("  ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("query", ["Sonic 3 Tokyo Mission [Manga]", "IDW", "Fortnite"])
    def test_a_matching_series_not_read_is_left_out_with_a_warning(self, query, caplog):
        with caplog.at_level(logging.WARNING, logger=ct.logger.name):
            assert _site({HOME: dict(text=_home())}).search(query) == []
        assert "not supported" in caplog.text

    def test_only_the_supported_series_of_several_matches_is_returned(self, caplog):
        with caplog.at_level(logging.WARNING, logger=ct.logger.name):
            results = _site({HOME: dict(text=_home())}).search("[Manga]")
        assert [m.url for m in results] == [SERIES]
        assert "Sonic 3 Tokyo Mission [Manga]" in caplog.text

    def test_the_link_title_is_read_without_its_prefix_when_the_link_has_no_text(self):
        site = _site({HOME: dict(text=_home(text=False))})
        assert [m.title for m in site.search("Shadow the hedgehog [Manga]")] == [
            "Shadow the hedgehog [Manga]"]
        assert site.search("Chapitre") == []

    @pytest.mark.parametrize("answer", [
        dict(text=_home(menus=0)),
        dict(text=_home(menus=2)),
        dict(text=_home(menu=[])),
        dict(status=301, text=""),
    ])
    def test_a_home_page_without_one_series_menu_raises(self, answer):
        with pytest.raises(ChaosTradSourceError):
            _site({HOME: answer}).search("shadow")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_chapters_newest_first_with_their_dates(self):
        site = _site({SERIES: dict(text=_series())})
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url, c.date, c.title) for c in chapters] == [
            ("4", f"{SERIES}/4", "2025-05-10", None),
            ("3", f"{SERIES}/3", "2025-02-01", None),
            ("2", f"{SERIES}/2", "2024-11-09", None),
            ("1", f"{SERIES}/1", "2024-09-22", None),
        ]
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_served_order_does_not_decide_the_order(self):
        cards = [_card(n) for n in ("1", "4", "2", "3")]
        chapters = _site({SERIES: dict(text=_series(cards))}).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["4", "3", "2", "1"]

    @pytest.mark.parametrize("date", ["", "2025-05-10", "31.02.2025", "10.5.2025"])
    def test_an_unreadable_date_is_left_empty(self, date):
        cards = [_card("1", date=date)] if date else [_card("1", date=" ")]
        chapters = _site({SERIES: dict(text=_series(cards))}).get_chapters(SERIES)
        assert chapters[0].date is None

    @pytest.mark.parametrize("cards", [
        [_card("4"), _card("4")],
        [_card("4", href="/comics/sonic3/4")],
        [_card("4", href="/comics/shadow-manga/4.5")],
        [_card("4", href="https://elsewhere.example/comics/shadow-manga/4")],
        [_card("4", href="")],
        [_card("4", data_number="3")],
    ])
    def test_a_card_out_of_place_raises(self, cards):
        with pytest.raises(ChaosTradSourceError):
            _site({SERIES: dict(text=_series(cards))}).get_chapters(SERIES)

    @pytest.mark.parametrize("page", [
        _series(count=5),
        _series(count=False),
        _series(cards=[]),
        _series(url=f"{SITE}/comics/sonic3"),
    ])
    def test_a_series_page_that_does_not_add_up_raises(self, page):
        with pytest.raises(ChaosTradSourceError):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(ChaosTradSourceError, match="HTTP 302"):
            _site({SERIES: dict(status=302)}).get_chapters(SERIES)

    def test_a_refusal_is_not_retried(self):
        site = _site({SERIES: dict(status=403)})
        with pytest.raises(requests.HTTPError):
            site.get_chapters(SERIES)
        assert len(site.session.calls) == 1


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_in_served_order_with_spaces_encoded(self):
        site = _site({CHAPTER: dict(text=_reader())})
        pages = site.get_pages(CHAPTER)
        assert pages == PAGES
        assert len(pages) == 29
        assert all(" " not in page for page in pages)
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    @pytest.mark.parametrize("page", [
        _reader(url=f"{SERIES}/3"),
        _reader(title_number="3"),
        _reader(selected="/comics/shadow-manga/3"),
        _reader(selected=None),
        _reader(backlink="/comics/sonic3"),
    ])
    def test_a_reader_for_another_chapter_raises(self, page):
        with pytest.raises(ChaosTradSourceError, match="not this chapter|not the page asked for"):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("srcs", [
        [],
        ["data:image/webp;base64,AAAA"],
        ["blob:https://chaostrad.fr/1"],
        [SRCS[0][:-5] + "_thumbnail.webp"],
        ["https://elsewhere.example" + SRCS[0]],
        ["/assets/images/icons/logo.png"],
        [SRCS[0], SRCS[0]],
        [SRCS[0], f"/uploads/chapter_images/Shadow the Hedgehog Manga-3/{HEXES[1]}.webp"],
    ])
    def test_a_page_this_source_does_not_read_raises(self, srcs):
        with pytest.raises(ChaosTradSourceError):
            _site({CHAPTER: dict(text=_reader(srcs=srcs))}).get_pages(CHAPTER)

    @pytest.mark.parametrize("holders", [0, 2])
    def test_a_reader_without_one_page_block_raises(self, holders):
        with pytest.raises(ChaosTradSourceError, match="no page images"):
            _site({CHAPTER: dict(text=_reader(holders=holders))}).get_pages(CHAPTER)

    def test_no_cover_is_read(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "0001.webp"
        site = _site({PAGES[14]: dict(content=WEBP)})
        assert site.download_image(PAGES[14], target) is True
        assert target.read_bytes() == WEBP
        assert site.session.calls == [(PAGES[14], {
            "allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=WEBP),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "0001.webp"
        target.write_bytes(b"older")
        assert _site({PAGES[0]: answer}).download_image(PAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"{SITE}/assets/images/icons/logo.png",
        PAGES[0].replace("https:", "http:"),
        PAGES[0].replace("chaostrad.fr", "www.chaostrad.fr"),
        f"{SITE}{SRCS[0]}",
        None,
    ])
    def test_a_url_off_the_image_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "0001.webp"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
