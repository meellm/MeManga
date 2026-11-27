"""Offline tests for Furyo Society: URL identity, the catalogue search, the
series list (volumes, a decimal part, rows the team did not translate, a
malformed title attribute), refusals, the reader binding and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the markup the site serves.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import furyosociety as fs
from memanga.scrapers.furyosociety import (FuryoSocietyScraper, FuryoSocietySourceError,
                                           FuryoSocietyUnsupportedError)

SITE = "https://www.furyosociety.com"
CATALOGUE = f"{SITE}/mangas"
SERIES = f"{SITE}/series/about/"
CHAPTER = f"{SITE}/read/about/fr/19/165/"
FOLDER = f"{SITE}/content/comics/about_51daca539aa42/165-0-vire-du-lycee_61fd0de8b1ca1"
PAGES = [f"{FOLDER}/000-Credits-ABOUTourista13-FuryoSquad.png",
         f"{FOLDER}/A-BOUT!-v19-c165-p01-[FuryoSquad].png",
         f"{FOLDER}/A-BOUT!-v19-c165-p20-[FuryoSquad].png"]
COVER = f"{SITE}/content/comics/about_51daca539aa42/cover_B00BB1ZQD8.01_.S001_.LXXXXXXX_.png"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Response:
    def __init__(self, url, status=200, text=None, content=None):
        self.url = url
        self.status_code = status
        self.text = text or ""
        self.content = self.text.encode() if content is None else content
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
    scraper = FuryoSocietyScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _card(slug, title, href=None, title_href=None):
    href = href or f"{SITE}/series/{slug}/"
    title_href = title_href or href
    return (
        '<div class="fs-card"><div class="fs-card-body"><div class="media">'
        f'<div class="fs-card-img-container d-flex"><a href="{href}">'
        f'<img class="fs-card-img" src="{SITE}/content/comics/{slug}_1/cover.png"></a></div>'
        '<div class="media-body"><div class="fs-card-row"><div class="fs-card-infos">'
        f'<span class="fs-comic-title fs-h-center"><a href="{title_href}" title="{title}">'
        f'{title}</a></span></div></div></div></div></div></div>')


def _mobile(slug, title):
    return (f'<a href="{SITE}/series/{slug}/" class="grid-item-container">'
            f'<div class="fs-manga-title"><span class="fs-comic-title fs-h-center">{title}'
            '</span></div></a>')


DEFAULT_CARDS = [_card("about", "A-BOUT!"), _card("a-bout", "A-BOUT!!"),
                 _card("kiku_one_shot", "KIKU (One shot)")]


def _catalogue(cards=None):
    cards = DEFAULT_CARDS if cards is None else cards
    return (
        '<html><head><title>FuryoSociety | Mangas</title></head><body>'
        '<div id="fs-tous" class="fs-chap-container">'
        f'<div class="fs-card-container desktop"><div class="grid-item-container">{"".join(cards)}'
        '</div></div>'
        f'<div class="fs-card-container mobile">{_mobile("about", "A-BOUT!")}</div></div>'
        '<div id="fs-termines" class="fs-chap-container hidden">'
        f'<div class="fs-card-container desktop">{_card("about", "A-BOUT!")}</div></div>'
        '</body></html>')


def _row(volume, chapter, name, part=None, title=None, meta="Il y a 4 ans", badge="",
         extra_link=""):
    number = chapter if part is None else f"{chapter}.{part}"
    path = f"{volume}/{chapter}/" + ("" if part is None else f"{part}/")
    title = f"Vol.{volume} Chapitre {number}: {name}" if title is None else title
    return (
        '<div class="element desktop"><div class="icon_wrapper fleft small">'
        f'<a href="{SITE}/download/about/fr/{path}"><i class="fa fa-download"></i></a>'
        f'{extra_link}</div>'
        f'<div class="title"><a href="{SITE}/read/about/fr/{path}" title="{title}">'
        f'Chapitre {number}</a></div>'
        f'<div class="name">{name}</div><div class="meta_r">{meta} {badge}</div></div>'
        f'<a href="{SITE}/read/about/fr/{path}" class="element mobile">'
        f'<div class="title-grp"><div class="title">Chapitre {number}</div>'
        f'<div class="name">{name}</div></div><div class="link">Vol.{volume} Ch.{number}</div>'
        f'<div class="meta_r">{meta}</div></a>')


SERVED_ROWS = [
    _row(19, 165, "Viré du lycée"),
    _row(19, 164, "Les conditions de l'idole"),
    _row(10, 81, "Hors-Série : Non traduit par la team"),
    _row(10, 80, "Hors-Série : Non traduit par la team"),
    _row(6, 49, "Extra A-BOUT! Saint Furyo-san", part=1),
    _row(6, 49, "Le coin des toits"),
    # The site leaves the inner quotes of this title unescaped.
    ('<div class="element desktop"><div class="icon_wrapper fleft small">'
     f'<a href="{SITE}/download/about/fr/1/1/"><i class="fa fa-download"></i></a></div>'
     f'<div class="title"><a href="{SITE}/read/about/fr/1/1/" '
     'title="Vol.1 Chapitre 1: Opération "Transfert du nouvel élève" #1">Chapitre 1</a></div>'
     '<div class="name">Opération "Transfert du nouvel élève" #1</div>'
     '<div class="meta_r">Il y a 4 ans </div></div>'),
]


def _series(rows=None, genre="Furyo, Lycée", h1="A-BOUT!",
            synopsis="Mitsumine est le lycée le plus dangereux du Japon ; il devient adulte."):
    rows = SERVED_ROWS if rows is None else rows
    return (
        '<html><head><title>A-BOUT! :: FuryoSociety</title></head><body>'
        '<div class="fs-comic-container 1"><div class="comic-info">'
        f'<div class="fs-mobile-comic-cover fs-large"><img class="comic-cover" src="{COVER}" /></div>'
        '<div class="fs-comic-text-container">'
        f'<div><p class="fs-comic-label">Titre</p><h1 class="fs-comic-title">{h1}</h1></div>'
        '<div><p class="fs-comic-label">Scénario</p><span class="fs-comic-info">Ichikawa Masa</span></div>'
        f'<div><p class="fs-comic-label">Genre</p><span class="fs-comic-info">{genre}</span></div>'
        '<div><p class="fs-comic-label">Type</p><span class="fs-comic-info">Shonen</span></div>'
        f'<div class="fs-comic-description">{synopsis}</div></div></div>'
        '<div class="list fs-chapter-list"><div class="group"><div class="title">Volume 19</div>'
        f'{"".join(rows)}</div></div></div></body></html>')


def _image(index, src=None, holder_index=None, image_id=None):
    src = PAGES[index] if src is None else src
    holder_index = index if holder_index is None else holder_index
    image_id = f"fsimg-{index}" if image_id is None else image_id
    return (f'<div id="fs-{index}" class="fs-reader-page" data-index="{holder_index}">'
            f'<img id="{image_id}" class="open" src="{src}" /></div>')


def _reader(images=None, back=SERIES, selected=CHAPTER, selected_text="Vol.19 Ch.165",
            pages=22, extra="", reader_text=""):
    images = "".join(_image(i) for i in range(3)) if images is None else images
    options = "".join(f'<option value="{n}">Page {n}/21</option>' for n in range(1, pages + 1))
    return (
        '<html><head><title>A-BOUT! ch.165 p.01 | FuryoSociety</title>'
        '<meta name="generator" content="FoOlSlide 2.3.3" /></head><body>'
        f'<img class="fq-logo-lel" src="{SITE}/assets/images/logo_furyosociety_head_new.png" />'
        f'<div class="fs-read-comic-link"><a href="{back}" title="A-BOUT!">A-BOUT!</a></div>'
        '<select id="fs-chapter-selector" class="fs-read-select">'
        f'<option value="{selected}" selected>{selected_text}</option>'
        f'<option value="{SITE}/read/about/fr/19/164/">Vol.19 Ch.164</option></select>'
        f'<a class="fs-download fs-reader-icon" href="{SITE}/download/about/fr/19/165/">dl</a>'
        f'<select id="fs-page-selector" class="fs-read-select">{options}</select>{extra}'
        f'<div class="fs-reader-page-container fs-read">{reader_text}{images}</div>'
        '</body></html>')


# ── Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_metadata(self):
        scraper = FuryoSocietyScraper()
        assert scraper.name == "furyosociety"
        assert scraper.base_url == SITE
        assert scraper.engine == "http"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is True
        assert scraper._rate_limit == 2.2
        adapter = scraper.session.get_adapter(f"{SITE}/mangas")
        assert isinstance(adapter, fs._SpacedAdapter)
        assert adapter.gap == fs._MIN_GAP == 2.2

    def test_no_cookie_is_kept(self):
        scraper = FuryoSocietyScraper()
        cookie = create_cookie("site_session", "x", domain="www.furyosociety.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    def test_series_url(self):
        assert FuryoSocietyScraper()._series_slug(SERIES) == "about"

    @pytest.mark.parametrize("url", [
        f"{SITE}/series/about",
        "http://www.furyosociety.com/series/about/",
        "https://furyosociety.com/series/about/",
        "https://furyosquad.com/series/about/",
        f"{SERIES}?x=1",
        f"{SERIES}#top",
        f"{SITE}/series/About/",
        f"{SITE}/series/../",
        f"{SITE}/mangas",
        CHAPTER,
        None,
    ])
    def test_other_series_urls_are_refused(self, url):
        with pytest.raises(FuryoSocietyUnsupportedError):
            FuryoSocietyScraper()._series_slug(url)

    @pytest.mark.parametrize("url, expected", [
        (CHAPTER, ("about", "19", "165")),
        (f"{SITE}/read/about/fr/6/49/1/", ("about", "6", "49.1")),
    ])
    def test_chapter_url(self, url, expected):
        assert FuryoSocietyScraper()._chapter_ref(url) == expected

    @pytest.mark.parametrize("url", [
        f"{SITE}/read/about/fr/19/165",
        f"{SITE}/read/about/en/19/165/",
        f"{SITE}/read/about/fr/19/0165/",
        f"{SITE}/read/about/fr/19/165/page/2/",
        f"{SITE}/download/about/fr/19/165/",
        "https://furyosociety.com/read/about/fr/19/165/",
        f"{CHAPTER}?x=1",
    ])
    def test_other_chapter_urls_are_refused(self, url):
        with pytest.raises(FuryoSocietyUnsupportedError):
            FuryoSocietyScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_a_search_matches_catalogue_titles(self):
        site = _site({CATALOGUE: dict(text=_catalogue())})
        results = site.search("a-bout")
        assert [(m.title, m.url) for m in results] == [
            ("A-BOUT!", SERIES), ("A-BOUT!!", f"{SITE}/series/a-bout/")]
        assert site.session.calls == [(CATALOGUE, {"allow_redirects": False})]

    def test_only_the_all_series_cards_are_read(self):
        site = _site({CATALOGUE: dict(text=_catalogue())})
        assert len(site._catalogue()) == 3

    def test_no_title_matches_is_no_results(self):
        assert _site({CATALOGUE: dict(text=_catalogue())}).search("zzqxjkvwpyd") == []

    def test_a_blank_query_sends_nothing(self):
        site = _site({})
        assert site.search("  ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("cards", [
        [],
        [_card("about", "A-BOUT!"), _card("about", "A-BOUT!")],
        [_card("about", "A-BOUT!", href="https://furyosociety.com/series/about/")],
        [_card("about", "A-BOUT!", href=f"{SITE}/read/about/fr/19/165/")],
        [_card("about", "A-BOUT!", title_href=f"{SITE}/series/other/")],
        [_card("about", "")],
    ])
    def test_an_unreadable_catalogue_raises(self, cards):
        with pytest.raises(FuryoSocietySourceError):
            _site({CATALOGUE: dict(text=_catalogue(cards))}).search("a-bout")

    def test_a_redirect_raises(self):
        with pytest.raises(FuryoSocietySourceError, match="HTTP 302"):
            _site({CATALOGUE: dict(status=302)}).search("a-bout")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_translated_chapters_newest_first(self, caplog):
        site = _site({SERIES: dict(text=_series())})
        with caplog.at_level(logging.WARNING, logger=fs.logger.name):
            chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == ["165", "164", "49.1", "49", "1"]
        assert chapters[0].url == CHAPTER
        assert chapters[0].title == "Chapitre 165 - Viré du lycée"
        assert chapters[2].url == f"{SITE}/read/about/fr/6/49/1/"
        assert all(c.date is None for c in chapters)
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]
        assert "2 chapter(s) the team marks as not translated" in caplog.text
        assert "Chapitre 81, Chapitre 80" in caplog.text

    def test_the_malformed_title_of_chapter_one_is_read(self):
        chapters = _site({SERIES: dict(text=_series(rows=[SERVED_ROWS[-1]]))}).get_chapters(SERIES)
        assert [(c.number, c.url) for c in chapters] == [("1", f"{SITE}/read/about/fr/1/1/")]

    def test_everyday_words_in_titles_and_synopsis_are_not_refusals(self):
        rows = [_row(19, 165, "Le coin des abonnés du toit")]
        assert len(_site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)) == 1

    def test_only_untranslated_rows_raise(self):
        rows = [_row(10, 81, "Hors-Série : Non traduit par la team")]
        with pytest.raises(FuryoSocietySourceError, match="no translated chapter"):
            _site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("badge", ["Patreon", "VIP", "Accès anticipé", "Premium",
                                       "Verrouillé", "Early access", "Tipeee"])
    def test_a_paid_or_early_offer_on_a_row_raises(self, badge):
        rows = [_row(19, 165, "Viré du lycée", badge=badge)]
        with pytest.raises(FuryoSocietySourceError, match="paid, early or members-only"):
            _site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("badge", ["Réservé aux membres", "Membres", "Connexion",
                                       "Se connecter", "Members only"])
    def test_a_members_or_login_mark_on_a_row_raises_before_any_reader(self, badge):
        rows = [_row(19, 165, "Viré du lycée", badge=badge)]
        site = _site({SERIES: dict(text=_series(rows=rows))})
        with pytest.raises(FuryoSocietySourceError, match="members-only"):
            site.get_chapters(SERIES)
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_members_in_a_story_title_is_not_a_refusal(self):
        rows = [_row(19, 165, "Les membres du gang")]
        assert len(_site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)) == 1

    @pytest.mark.parametrize("change", [
        # a control whose title says what it is
        ('<div class="name">', '<span title="Réservé aux membres"><i class="fa fa-lock"></i>'
                               '</span><div class="name">'),
        # text placed straight in the row, outside any badge
        ('<div class="name">', 'Réservé aux membres<div class="name">'),
        # an image whose alt says what it is
        ('<i class="fa fa-download"></i></a>', '<i class="fa fa-download"></i></a>'
                                               '<img src="/assets/lock.png" alt="VIP">'),
        # a label on the row's own control
        (f'<a href="{SITE}/download/about/fr/19/165/">',
         f'<a href="{SITE}/download/about/fr/19/165/" aria-label="Accès anticipé">'),
        # a badge next to the chapter link
        ('Chapitre 165</a></div>', 'Chapitre 165</a> <span>Membres</span></div>'),
    ])
    def test_a_visible_access_mark_outside_the_story_title_raises_before_any_reader(self, change):
        rows = [_row(19, 165, "Viré du lycée").replace(*change, 1)]
        site = _site({SERIES: dict(text=_series(rows=rows))})
        with pytest.raises(FuryoSocietySourceError, match="members-only"):
            site.get_chapters(SERIES)
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    @pytest.mark.parametrize("change", [
        ('<div class="name">', '<span hidden>VIP</span><div class="name">'),
        ('<div class="name">', '<span style="display: none">Patreon</span><div class="name">'),
        ('<i class="fa fa-download"></i></a>', '<i class="fa fa-download"></i></a>'
                                               '<img src="/assets/flags/fr.png" alt="Français">'),
        ('<div class="name">', '<!-- membres --><div class="name">'),
    ])
    def test_hidden_or_plain_row_content_is_not_a_refusal(self, change):
        rows = [_row(19, 165, "Viré du lycée").replace(*change, 1)]
        assert len(_site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)) == 1

    def test_an_unknown_control_on_a_row_raises(self):
        rows = [_row(19, 165, "Viré du lycée",
                     extra_link='<a href="https://example.org/unlock">x</a>')]
        with pytest.raises(FuryoSocietySourceError, match="cannot place"):
            _site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("genre", ["Hentai", "Action, Adulte", "Smut", "Érotique", "18+"])
    def test_an_adult_genre_raises(self, genre):
        with pytest.raises(FuryoSocietySourceError, match="adult genre"):
            _site({SERIES: dict(text=_series(genre=genre))}).get_chapters(SERIES)

    @pytest.mark.parametrize("row", [
        _row(19, 165, "Viré du lycée", title="Vol.18 Chapitre 165: Viré du lycée"),
        _row(19, 165, "Viré du lycée", title="Vol.19 Chapitre 164: Viré du lycée"),
        _row(19, 165, "Viré du lycée", title=""),
        _row(19, 165, "x").replace(">Chapitre 165</a>", ">Chapitre 166</a>"),
        _row(19, 165, "x").replace(">Chapitre 165</a>", ">Épisode 165</a>"),
        _row(19, 165, "x").replace(f"{SITE}/read/about/", f"{SITE}/read/other/"),
        _row(19, 165, "x").replace("/fr/19/165/", "/en/19/165/"),
        '<div class="element desktop"><div class="title">Chapitre 165</div></div>',
    ])
    def test_a_row_it_cannot_bind_raises(self, row):
        with pytest.raises(FuryoSocietySourceError):
            _site({SERIES: dict(text=_series(rows=[row]))}).get_chapters(SERIES)

    @pytest.mark.parametrize("rows", [
        [_row(19, 165, "a"), _row(19, 165, "a")],
        [_row(19, 165, "a"), _row(20, 165, "b")],
    ])
    def test_a_repeated_number_raises(self, rows):
        with pytest.raises(FuryoSocietySourceError, match="twice"):
            _site({SERIES: dict(text=_series(rows=rows))}).get_chapters(SERIES)

    def test_a_page_that_is_not_a_series_raises(self):
        page = "<html><body><h2>Not Found</h2></body></html>"
        with pytest.raises(FuryoSocietySourceError, match="not a series page"):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_series_without_rows_raises(self):
        with pytest.raises(FuryoSocietySourceError, match="no chapters"):
            _site({SERIES: dict(text=_series(rows=[]))}).get_chapters(SERIES)

    def test_a_redirect_raises(self):
        with pytest.raises(FuryoSocietySourceError, match="HTTP 301"):
            _site({SERIES: dict(status=301)}).get_chapters(SERIES)


# ── Cover (what adding a series reads) ──────────────────────────────

class TestCover:
    def test_the_cover_comes_from_the_series_page(self):
        site = _site({SERIES: dict(text=_series())})
        assert site.get_cover_url(SERIES) == COVER
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    @pytest.mark.parametrize("answer", [
        dict(status=404),
        dict(text="<html><body>Not Found</body></html>"),
        dict(text=_series(genre="Hentai")),
        dict(text=_series().replace(COVER, "https://cdn.example/cover.png")),
    ])
    def test_a_series_it_cannot_confirm_gives_no_cover(self, answer):
        assert _site({SERIES: answer}).get_cover_url(SERIES) is None

    def test_a_url_that_is_not_a_series_sends_nothing(self):
        site = _site({})
        assert site.get_cover_url(f"{SITE}/mangas") is None
        assert site.session.calls == []

    def test_the_served_cover_can_be_downloaded(self, tmp_path):
        site = _site({SERIES: dict(text=_series()), COVER: dict(content=PNG)})
        cover = site.get_cover_url(SERIES)
        target = tmp_path / "cover_art.jpg"
        assert site.download_image(cover, target) is True
        assert target.read_bytes() == PNG
        assert site.session.calls == [
            (SERIES, {"allow_redirects": False}),
            (COVER, {"allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    def test_a_cover_that_is_not_an_image_leaves_no_file(self, tmp_path):
        target = tmp_path / "cover_art.jpg"
        target.write_bytes(b"older")
        site = _site({COVER: dict(content=b"<html>not found</html>")})
        assert site.download_image(COVER, target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        COVER.replace("https://www.", "https://"),
        COVER.replace("www.furyosociety.com", "furyosquad.com"),
        COVER.replace("https:", "http:"),
        f"{COVER}?v=1",
        f"{SITE}/content/comics/about_51daca539aa42/cover.txt",
        f"{SITE}/content/comics/../cover.png",
        f"{SITE}/content/other/about_51daca539aa42/cover.png",
        f"{SITE}/assets/images/logo_furyosociety_head_new.png",
    ])
    def test_a_cover_off_the_comic_folder_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "cover_art.jpg"
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_reader_order(self):
        site = _site({CHAPTER: dict(text=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    def test_the_numeric_page_switch_is_not_pagination(self):
        # The served switch lists 22 entries for 21 images; it is in-page.
        assert _site({CHAPTER: dict(text=_reader(pages=22))}).get_pages(CHAPTER) == PAGES

    @pytest.mark.parametrize("kwargs", [
        dict(back=f"{SITE}/series/other/"),
        dict(selected=f"{SITE}/read/about/fr/19/164/"),
        dict(selected_text="Vol.19 Ch.164"),
        dict(selected_text="Vol.18 Ch.165"),
    ])
    def test_a_reader_for_another_chapter_raises(self, kwargs):
        with pytest.raises(FuryoSocietySourceError, match="not this chapter"):
            _site({CHAPTER: dict(text=_reader(**kwargs))}).get_pages(CHAPTER)

    def test_a_reader_split_over_pages_raises(self):
        extra = f'<a href="{CHAPTER}page/2/">Suivant</a>'
        with pytest.raises(FuryoSocietySourceError, match="another page"):
            _site({CHAPTER: dict(text=_reader(extra=extra))}).get_pages(CHAPTER)

    def test_a_page_switch_with_addresses_raises(self):
        extra = (f'<select id="fs-page-selector"><option value="{CHAPTER}page/2/">2</option>'
                 '</select>')
        with pytest.raises(FuryoSocietySourceError, match="page switch"):
            _site({CHAPTER: dict(text=_reader(extra=extra))}).get_pages(CHAPTER)

    @pytest.mark.parametrize("text", ["Connectez-vous pour lire ce chapitre",
                                      "Chapitre réservé aux membres", "Soutenez-nous sur Patreon"])
    def test_a_login_or_payment_prompt_raises(self, text):
        with pytest.raises(FuryoSocietySourceError, match="log in or pay"):
            _site({CHAPTER: dict(text=_reader(reader_text=f"<p>{text}</p>"))}).get_pages(CHAPTER)

    @pytest.mark.parametrize("images, reason", [
        ("", "no page images"),
        (_image(0, src="data:image/png;base64,AAAA"), "plain address"),
        (_image(0, src="blob:https://www.furyosociety.com/x"), "plain address"),
        (_image(0, src=""), "plain address"),
        (_image(0, src="https://cdn.example/content/comics/a/b/1.png"), "out of place"),
        (_image(0, src=f"{SITE}/assets/images/logo.png"), "out of place"),
        (_image(0, src=COVER), "out of place"),
        (_image(0, src=f"{PAGES[0]}?v=1"), "out of place"),
        (_image(0, src=f"{FOLDER}/page.txt"), "out of place"),
        (_image(0, src=f"{SITE}/content/comics/a/../1.png"), "out of place"),
        (_image(0, image_id="fsimg-1"), "out of place"),
        (_image(0, holder_index=1), "out of place"),
        (_image(0) + _image(2), "out of place"),
        (_image(0) + _image(1, src=PAGES[0]), "twice"),
        (_image(0) + _image(1, src=f"{SITE}/content/comics/about_51daca539aa42/other/1.png"),
         "several folders"),
    ])
    def test_a_page_it_cannot_place_raises(self, images, reason):
        with pytest.raises(FuryoSocietySourceError, match=reason):
            _site({CHAPTER: dict(text=_reader(images=images))}).get_pages(CHAPTER)

    def test_a_redirect_raises(self):
        with pytest.raises(FuryoSocietySourceError, match="HTTP 302"):
            _site({CHAPTER: dict(status=302)}).get_pages(CHAPTER)


# ── Request spacing (the real adapter, slow fake transport) ─────────

class _SlowBody:
    """A response body that takes a while to read, and notes when it ends."""

    def __init__(self, ends):
        self.ends = ends
        self.done = False

    def read(self, amt=None, **kwargs):
        if self.done:
            return b""
        time.sleep(0.1)
        self.done = True
        self.ends.append(time.monotonic())
        return b"ok"


class _SlowTransport(BaseAdapter):
    """Stands in for the network below the source's adapter. Each send takes
    its own delay (a slow connect) and is timed; overlap is counted."""

    def __init__(self, delays, fail=(), slow_body=False):
        super().__init__()
        self.delays = delays
        self.fail = set(fail)
        self.slow_body = slow_body
        self.spans = []
        self.body_ends = []
        self.active = 0
        self.max_active = 0
        self._guard = threading.Lock()

    def send(self, request, **kwargs):
        with self._guard:
            index = len(self.spans)
            self.spans.append([time.monotonic(), None])
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delays[index % len(self.delays)])
            if index in self.fail:
                raise requests.ConnectionError("connection reset")
            response = requests.Response()
            response.status_code = 200
            response.url = request.url
            response.request = request
            if self.slow_body:
                response.raw = _SlowBody(self.body_ends)
            else:
                response._content = b"ok"
            return response
        finally:
            with self._guard:
                self.spans[index][1] = time.monotonic()
                self.active -= 1

    def close(self):
        pass


GAP = 0.2


def _spaced(transport):
    scraper = FuryoSocietyScraper()
    scraper._rate_limit = 0  # the base spacing is off: the source's adapter alone must space
    adapter = scraper.session.get_adapter(f"{SITE}/mangas")
    assert isinstance(adapter, fs._SpacedAdapter)
    adapter.gap = GAP
    adapter.inner = transport
    return scraper


def _run_together(calls):
    barrier = threading.Barrier(len(calls))

    def run(call):
        barrier.wait()
        try:
            return call()
        except requests.RequestException as e:
            return e

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def _assert_spaced(spans):
    spans = sorted(spans)
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end + GAP - 0.01


class TestSpacing:
    def test_four_callers_send_one_at_a_time_with_the_gap(self):
        transport = _SlowTransport(delays=[0.3, 0.05, 0.25, 0.1])
        scraper = _spaced(transport)
        results = _run_together([lambda: scraper._request(CATALOGUE)] * 4)
        assert all(r.status_code == 200 for r in results)
        assert len(transport.spans) == 4 and transport.max_active == 1
        _assert_spaced(transport.spans)

    def test_separate_instances_share_the_spacing(self):
        transport = _SlowTransport(delays=[0.2, 0.05])
        first, second = _spaced(transport), _spaced(transport)
        calls = [lambda: first._request(CATALOGUE), lambda: second._request(CATALOGUE)] * 2
        _run_together(calls)
        assert len(transport.spans) == 4 and transport.max_active == 1
        _assert_spaced(transport.spans)

    def test_a_failed_send_releases_the_lock_and_still_spaces_the_next(self):
        transport = _SlowTransport(delays=[0.15], fail={1})
        scraper = _spaced(transport)
        get = lambda: scraper.session.get(CATALOGUE, timeout=5, allow_redirects=False)  # noqa: E731
        results = _run_together([get] * 4)
        assert sum(isinstance(r, requests.ConnectionError) for r in results) == 1
        assert sum(getattr(r, "status_code", None) == 200 for r in results) == 3
        assert transport.max_active == 1
        _assert_spaced(transport.spans)
        assert not fs._SpacedAdapter._lock.locked()

    def test_the_gap_counts_from_the_end_of_the_body(self):
        transport = _SlowTransport(delays=[0.05], slow_body=True)
        scraper = _spaced(transport)
        _run_together([lambda: scraper._request(CATALOGUE)] * 3)
        starts = sorted(start for start, _ in transport.spans)
        ends = sorted(transport.body_ends)
        assert len(starts) == len(ends) == 3
        for body_end, next_start in zip(ends, starts[1:]):
            assert next_start >= body_end + GAP - 0.01


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "01.png"
        site = _site({PAGES[1]: dict(content=PNG)})
        assert site.download_image(PAGES[1], target) is True
        assert target.read_bytes() == PNG
        assert site.session.calls == [(PAGES[1], {
            "allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=PNG),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "01.png"
        target.write_bytes(b"older")
        assert _site({PAGES[1]: answer}).download_image(PAGES[1], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"{SITE}/assets/images/logo_furyosociety_head_new.png",
        "https://furyosquad.com/content/comics/a/b/1.png",
        PAGES[1].replace("https:", "http:"),
        None,
    ])
    def test_a_url_off_the_image_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "01.png"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
