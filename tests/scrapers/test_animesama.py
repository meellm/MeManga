"""Offline tests for Anime-Sama scans: URL identity, search, the choice of
panel, the viewer's chapter list, page URLs and download.

The session is replaced with canned answers, so no network is used. The
pages follow markup the site serves, including its commented-out templates.
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import animesama as am
from memanga.scrapers.animesama import (AnimeSamaScraper, AnimeSamaSourceError,
                                        AnimeSamaUnsupportedError)

SITE = "https://anime-sama.to"
SERIES = f"{SITE}/catalogue/one-piece/"
PANEL = f"{SERIES}scan_noir-et-blanc/vf/"
SEARCH = f"{SITE}/catalogue/?type%5B%5D=Scans&search=one%20piece&page=1"
COUNT = f"{SITE}/s2/scans/get_nb_chap_et_img.php?oeuvre=One%20Piece%20"
LIVE_PANELS = [("Scans (couleur)", "scan/vf"), ("Scans (noir et blanc)", "scan_noir-et-blanc/vf")]
LIVE_LIST = 'resetListe();\n\t\t\tcreerListe(1, 1045);newSP("One Shot");\n\t\t\tfinirListe(1046);'
NOTICE = "Aucun résultat trouvé, vérifiez bien votre recherche."
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


class _Response:
    def __init__(self, url, status=200, text=None, content=None, data=None):
        self.url = url
        self.status_code = status
        self.text = json.dumps(data) if data is not None else (text or "")
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
    scraper = AnimeSamaScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _card(slug="one-piece", title="One Piece ", scans=True):
    badge = '<span class="as-badge as-badge-scan">Scans</span>' if scans else ""
    return (f'<div class="as-carte as-carte-oeuvre" data-url="/catalogue/{slug}/" '
            f'data-cat="oeuvre" data-nom="{title}"><a class="as-carte-lien" '
            f'href="{SITE}/catalogue/{slug}/" draggable="false"><div class="as-carte-badges">'
            f'<span class="as-badge as-badge-anime">Anime</span>{badge}</div>'
            f'<div class="as-carte-texte"><h3 class="as-carte-titre" title="{title}">{title}</h3>'
            f'</div></a></div>')


def _catalogue(inner):
    return (f'<html><body><div id="list_catalog" class="overflow-y-scroll">{inner}</div>'
            f'<div id="list_pagination"></div><p>Publicité</p></body></html>')


def _empty():
    return _catalogue(f'<p class="text-white font-bold text-2xl h-96 p-5">{NOTICE}</p>')


def _series(panels=None, live=None):
    panels = LIVE_PANELS if panels is None else panels
    calls = "\n".join(f'panneauScan("{label}", "{path}");' for label, path in panels)
    block = calls if live is None else live
    return (
        '<html><body><h1 id="titreOeuvre" class="oe-titre">One Piece </h1><script>\n'
        '/* Cartes des saisons / scans :\n'
        '   panneauAnime("nom", "saison1/vostfr"); panneauScan("nom", "scan/vf"); */\n'
        'var OE_BASE = "\\/catalogue\\/one-piece\\/";\n'
        'function oePanneau(nom, url, scan) { var lien = /^(https?:)?\\//.test(url); }\n'
        'function panneauAnime(nom, url) { oePanneau(nom, url, false); }\n'
        'function panneauScan(nom, url) { oePanneau(nom, url, true); }\n'
        '</script><script>\n'
        '/*panneauAnime("nom", "url"); -> on en met autant*/\n'
        'panneauAnime("Saga 1", "saison1/vostfr");\n'
        '</script><script>\n'
        '/*panneauScan("nom", "url"); -> on en met autant qu\'on veut*/\n'
        f'{block}\n'
        '</script></body></html>')


def _list_script(commands=LIVE_LIST):
    return ('<script>\n\t\t$(document).ready(function(){\n\t\t\t/*\n'
            '\t\t\tresetListe(); toujours au debut en premier\n'
            '\t\t\tcreerListe(debut, fin);newSP(special); on en met autant\n'
            '\t\t\tfinirListe(debut de la fin);\n\t\t\t*/\n'
            f'\t\t\t{commands}\n'
            '\t\t\t//$("#messagePage").html("Une page du chapitre 1180 est en anglais.");\t\n'
            '\t\t});\n\t\t</script>')


def _panel(script=None, heading="One Piece ", canonical=PANEL, viewer=True, select=True):
    script = _list_script() if script is None else script
    src = '<script defer src="/js/contenu/scans.js?v=1795228759"></script>' if viewer else ""
    box = '<select id="selectChapitres"></select>' if select else ""
    return (f'<html><head><link rel="canonical" href="{canonical}" />{src}</head><body>'
            f'<h1 id="titreOeuvre" class="ct-titre">{heading}</h1>{box}{script}</body></html>')


def _counts(highest=1200, pages=20, **overrides):
    data = {str(n): pages for n in range(1, highest + 1)}
    data.update(overrides)
    return data


def _routes(series=None, panel=None, counts=None, panel_url=PANEL, count_url=COUNT):
    return {SERIES: dict(text=_series() if series is None else series),
            panel_url: dict(text=_panel() if panel is None else panel),
            count_url: dict(data=_counts() if counts is None else counts)}


def _chapters(**kwargs):
    return _site(_routes(**kwargs)).get_chapters(SERIES)


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url", [
        SERIES, SERIES.rstrip("/"), "https://www.anime-sama.to/catalogue/one-piece/",
        "http://anime-sama.to/catalogue/one-piece/",
    ])
    def test_a_series_url_has_one_slug(self, url):
        assert AnimeSamaScraper()._series_slug(url) == "one-piece"

    @pytest.mark.parametrize("url", [
        "https://anime-sama.fr/catalogue/x/",
        "https://anime-sama.to.example.test/catalogue/x/",
        "https://u@anime-sama.to/catalogue/x/",
        "https://anime-sama.to:8443/catalogue/x/",
        "https://anime-sama.to/catalogue/x/?y=1",
        "https://anime-sama.to/catalogue/x/#top",
        "ftp://anime-sama.to/catalogue/x/",
        "/catalogue/x/",
        "https://anime-sama.to/catalogue/",
        "https://anime-sama.to/planning/x/",
        "https://anime-sama.to/catalogue/x/scan/vf/",
        "https://anime-sama.to/catalogue/../",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(AnimeSamaUnsupportedError):
            AnimeSamaScraper()._series_slug(url)

    @pytest.mark.parametrize("url, panel, folder", [
        (f"{PANEL}#dossier=1200", PANEL, 1200),
        (f"{SERIES}scan/vf/#dossier=1", f"{SERIES}scan/vf/", 1),
        ("https://www.anime-sama.to/catalogue/one-piece/scan/vf/#dossier=7",
         f"{SERIES}scan/vf/", 7),
    ])
    def test_a_chapter_is_a_panel_and_a_folder(self, url, panel, folder):
        assert AnimeSamaScraper()._chapter_ref(url) == (panel, folder)

    @pytest.mark.parametrize("url", [
        PANEL,
        SERIES,
        f"{PANEL}#dossier=0",
        f"{PANEL}#dossier=1.5",
        f"{PANEL}#dossier=x",
        f"{PANEL}#chapitre=1",
        f"{PANEL}?x=1#dossier=1",
        f"{PANEL.rstrip('/')}#dossier=1",
        f"{SERIES}saison1/vostfr/#dossier=1",
        f"{SERIES}scan/vostfr/#dossier=1",
        "https://example.test/catalogue/one-piece/scan/vf/#dossier=1",
    ])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site({})

        with pytest.raises(AnimeSamaUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (AnimeSamaScraper.engine, AnimeSamaScraper.content_language,
                AnimeSamaScraper.nsfw) == ("http", "fr", False)
        assert AnimeSamaScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = AnimeSamaScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("PHPSESSID", "x", domain=".anime-sama.to"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_a_served_card(self):
        scraper = _site({SEARCH: dict(text=_catalogue("<script>var a;</script>" + _card()))})

        results = scraper.search(" one piece ")

        assert [(m.title, m.url) for m in results] == [("One Piece", SERIES)]
        (url, kwargs), = scraper.session.calls
        assert url == SEARCH and kwargs["allow_redirects"] is False

    def test_a_query_is_sent_as_one_value(self):
        url = f"{SITE}/catalogue/?type%5B%5D=Scans&search=a%26b%3Dc%20d&page=1"

        assert _site({url: dict(text=_empty())}).search("a&b=c d") == []

    def test_a_blank_query_sends_nothing(self):
        scraper = _site({})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_the_sites_notice_is_no_results(self):
        assert _site({SEARCH: dict(text=_empty())}).search("one piece") == []

    @pytest.mark.parametrize("page, why", [
        ("<html><title>Just a moment...</title></html>", "did not serve a catalogue"),
        (_catalogue(""), "did not serve results"),
        (_catalogue("<p>Autre message</p>"), "did not serve results"),
        (_catalogue(f"<p>{NOTICE}</p><p>{NOTICE}</p>"), "did not serve results"),
        (_catalogue(f"<p>{NOTICE}</p>" + _card()), "results and no results"),
    ], ids=["challenge", "empty-list", "other-notice", "two-notices", "notice-and-card"])
    def test_any_other_page_is_an_error(self, page, why):
        with pytest.raises(AnimeSamaSourceError, match=why):
            _site({SEARCH: dict(text=page)}).search("one piece")

    def test_a_card_without_the_scans_badge_is_left_out(self):
        page = _catalogue(_card("anime-only", "Anime Only", scans=False) + _card())

        assert [m.url for m in _site({SEARCH: dict(text=page)}).search("one piece")] == [SERIES]

    @pytest.mark.parametrize("card", [
        '<div class="as-carte"><h3 class="as-carte-titre">X</h3></div>',
        f'<div class="as-carte"><a class="as-carte-lien" href="{SERIES}"></a></div>',
        f'<div class="as-carte"><a class="as-carte-lien" href="{SERIES}">'
        '<h3 class="as-carte-titre"> </h3></a></div>',
    ], ids=["no-link", "no-title", "blank-title"])
    def test_a_card_without_link_or_title_is_an_error(self, card):
        with pytest.raises(AnimeSamaSourceError, match="without its link or title"):
            _site({SEARCH: dict(text=_catalogue(card))}).search("one piece")

    def test_a_card_that_is_not_a_series_is_an_error(self):
        card = _card().replace(f'href="{SERIES}"', 'href="https://example.test/catalogue/x/"')

        with pytest.raises(AnimeSamaSourceError, match="not a series"):
            _site({SEARCH: dict(text=_catalogue(card))}).search("one piece")

    def test_a_repeated_card_is_listed_once(self):
        page = _catalogue(_card() + _card())

        assert len(_site({SEARCH: dict(text=page)}).search("one piece")) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(am, "_MAX_SEARCH_RESULTS", 2)
        page = _catalogue("".join(_card(f"s{n}", f"S{n}") for n in range(5)))

        assert len(_site({SEARCH: dict(text=page)}).search("one piece")) == 2

    def test_a_redirected_search_is_an_error(self):
        with pytest.raises(AnimeSamaSourceError, match="HTTP 301"):
            _site({SEARCH: dict(status=301)}).search("one piece")

    def test_a_refused_search_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("one piece")


# ── Panel choice ────────────────────────────────────────────────────

class TestPanels:
    def test_the_labelled_black_and_white_panel_is_read(self):
        scraper = _site(_routes())

        scraper.get_chapters(SERIES)

        assert [url for url, _ in scraper.session.calls] == [SERIES, PANEL, COUNT]
        assert all(kw["allow_redirects"] is False for _, kw in scraper.session.calls)

    def test_the_only_french_panel_is_read(self):
        panel = f"{SERIES}scan/vf/"
        routes = _routes(series=_series([("Scans", "scan/vf")]),
                         panel=_panel(canonical=panel), panel_url=panel)

        chapters = _site(routes).get_chapters(SERIES)

        assert chapters[0].url == f"{panel}#dossier=1200"

    def test_a_panel_in_another_language_is_not_a_choice(self):
        panel = f"{SERIES}scan/vf/"
        routes = _routes(series=_series([("Scans VO", "scan/vo"), ("Scans", "scan/vf")]),
                         panel=_panel(canonical=panel), panel_url=panel)

        assert _site(routes).get_chapters(SERIES)[0].url.startswith(panel)

    @pytest.mark.parametrize("panels", [
        [],
        [("Scans VO", "scan/vo")],
        [("Scans (couleur)", "scan/vf"), ("Scans 2", "scan2/vf")],
        [("Scans (noir et blanc)", "scan/vf"), ("Scans (noir et blanc)", "scan2/vf")],
        [("Scans", "autre/vf")],
    ], ids=["none", "no-french", "two-unlabelled", "two-labelled", "unknown-path"])
    def test_an_unclear_choice_is_an_error(self, panels):
        with pytest.raises(AnimeSamaSourceError, match="panel"):
            _site({SERIES: dict(text=_series(panels))}).get_chapters(SERIES)

    @pytest.mark.parametrize("live", [
        'panneauScan("Scans", "scan/vf"); autre();',
        "panneauScan('Scans', 'scan/vf');",
    ], ids=["other-statement", "other-quotes"])
    def test_a_panel_script_in_another_form_is_an_error(self, live):
        with pytest.raises(AnimeSamaSourceError, match="other statements"):
            _site({SERIES: dict(text=_series(live=live))}).get_chapters(SERIES)

    def test_a_page_that_is_not_a_series_is_an_error(self):
        with pytest.raises(AnimeSamaSourceError, match="not a series page"):
            _site({SERIES: dict(text="<html></html>")}).get_chapters(SERIES)

    @pytest.mark.parametrize("page", [
        _panel(canonical=f"{SERIES}scan/vf/"),
        _panel(viewer=False),
        _panel(select=False),
        _panel().replace('id="titreOeuvre"', 'id="autre"'),
        _panel() + '<h1 id="titreOeuvre">Autre</h1>',
    ], ids=["other-canonical", "no-viewer", "no-select", "no-title", "two-titles"])
    def test_a_page_that_is_not_the_viewer_is_an_error(self, page):
        with pytest.raises(AnimeSamaSourceError, match="not this panel's viewer"):
            _chapters(panel=page)


# ── Chapter list ────────────────────────────────────────────────────

class TestChapterList:
    def test_the_served_list_keeps_labels_and_folders_apart(self, caplog):
        with caplog.at_level(logging.WARNING, logger=am.logger.name):
            chapters = _chapters()

        by_folder = {int(c.url.rsplit("=", 1)[1]): c for c in chapters}
        assert len(chapters) == 1200
        assert chapters[0].url == f"{PANEL}#dossier=1200"
        assert (chapters[0].number, chapters[0].title) == ("1199", "Chapitre 1199")
        assert by_folder[1047].number == "1046"
        assert (by_folder[1046].number, by_folder[1046].title) == ("One Shot", "Chapitre One Shot")
        assert by_folder[1045].number == "1045"
        assert by_folder[1].number == "1"
        assert chapters[-1].url == f"{PANEL}#dossier=1"
        assert caplog.text == ""

    def test_no_list_commands_is_the_viewers_default_list(self):
        chapters = _chapters(panel=_panel(script=""), counts=_counts(3))

        assert [c.number for c in chapters] == ["3", "2", "1"]
        assert chapters[0].url == f"{PANEL}#dossier=3"

    def test_a_comment_template_is_not_a_command(self):
        chapters = _chapters(panel=_panel(script=_list_script("creerListe(1, 2);")),
                             counts=_counts(2))

        assert [c.number for c in chapters] == ["2", "1"]

    def test_a_folder_without_pages_is_left_out_with_a_warning(self, caplog):
        counts = _counts(5)
        del counts["3"]
        counts["4"] = 0

        with caplog.at_level(logging.WARNING, logger=am.logger.name):
            chapters = _chapters(panel=_panel(script=""), counts=counts)

        assert [c.number for c in chapters] == ["5", "2", "1"]
        assert "2 chapter position(s)" in caplog.text and "not listed" in caplog.text

    def test_a_folder_no_position_reaches_is_reported(self, caplog):
        script = _list_script("creerListe(1, 2);")

        with caplog.at_level(logging.WARNING, logger=am.logger.name):
            chapters = _chapters(panel=_panel(script=script), counts=_counts(4))

        assert [c.number for c in chapters] == ["2", "1"]
        assert "2 folder(s)" in caplog.text

    def test_a_special_shifts_the_labels_after_it(self):
        script = _list_script('creerListe(1, 1);newSP("Extra");finirListe(2);')

        chapters = _chapters(panel=_panel(script=script), counts=_counts(4))

        assert [c.number for c in chapters] == ["3", "2", "Extra", "1"]
        assert [c.url.rsplit("=", 1)[1] for c in chapters] == ["4", "3", "2", "1"]

    @pytest.mark.parametrize("commands", [
        'newSPF("Hors-série");',
        "newSP(12.5);",
        'newSP("12.5");',
        'newSP("Extra 2");',
        'newSP(" ");',
        "creerListe(1.5, 3);",
        "creerListe(1);",
        "finirListe();",
        "autreCommande();creerListe(1, 2);",
        '$("#messagePage").html("x");creerListe(1, 2);',
        "creerListe(1, 2)",
        "creerListe(1, 2); // fin",
    ], ids=["newspf", "decimal-special", "quoted-decimal", "special-with-number", "blank-special",
            "decimal-range", "short-range", "empty-rest", "other-command", "live-message",
            "no-semicolon", "trailing-comment"])
    def test_an_unknown_list_form_is_an_error(self, commands):
        with pytest.raises(AnimeSamaSourceError, match="unknown"):
            _chapters(panel=_panel(script=_list_script(commands)), counts=_counts(3))

    @pytest.mark.parametrize("script, why", [
        ("<script>creerListe(1, 2);</script>", "unknown form"),
        (_list_script() + _list_script(), "several"),
        (_list_script("creerListe(1, 2);creerListe(2, 3);"), "two list positions"),
    ], ids=["not-in-ready-block", "two-scripts", "duplicate-label"])
    def test_a_list_that_cannot_be_read_clearly_is_an_error(self, script, why):
        with pytest.raises(AnimeSamaSourceError, match=why):
            _chapters(panel=_panel(script=script), counts=_counts(3))

    def test_a_reset_clears_the_list_so_far(self):
        script = _list_script("creerListe(5, 6);resetListe();creerListe(1, 2);")

        assert [c.number for c in _chapters(panel=_panel(script=script),
                                            counts=_counts(2))] == ["2", "1"]

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(am, "_MAX_CHAPTERS", 2)

        with pytest.raises(AnimeSamaSourceError, match="more chapters"):
            _chapters(panel=_panel(script=_list_script("creerListe(1, 3);")), counts=_counts(2))

    @pytest.mark.parametrize("data", [
        [],
        {},
        {"1.5": 10},
        {"0": 10},
        {"x": 10},
        {"1": -1},
        {"1": True},
        {"1": "10"},
        {"1": 1.5},
        {"1": 999999},
    ], ids=["list", "empty", "decimal-key", "zero-key", "text-key", "negative", "bool", "text",
            "float", "too-many-pages"])
    def test_an_unreadable_count_map_is_an_error(self, data):
        routes = _routes()
        routes[COUNT] = dict(text=json.dumps(data))

        with pytest.raises(AnimeSamaSourceError, match="page count"):
            _site(routes).get_chapters(SERIES)

    def test_a_map_of_only_empty_folders_is_an_error(self):
        with pytest.raises(AnimeSamaSourceError, match="no chapter with pages"):
            _chapters(panel=_panel(script=""), counts={"1": 0})

    def test_a_count_answer_that_is_not_json_is_an_error(self):
        routes = _routes()
        routes[COUNT] = dict(text="<html></html>")

        with pytest.raises(AnimeSamaSourceError, match="not JSON"):
            _site(routes).get_chapters(SERIES)

    def test_a_redirected_panel_is_an_error(self):
        routes = _routes()
        routes[PANEL] = dict(status=301)

        with pytest.raises(AnimeSamaSourceError, match="HTTP 301"):
            _site(routes).get_chapters(SERIES)

    def test_a_refused_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES: dict(status=404)}).get_chapters(SERIES)


# ── Work title ──────────────────────────────────────────────────────

class TestWorkTitle:
    @pytest.mark.parametrize("heading, query, path", [
        ("One Piece ", "One%20Piece%20", "One%20Piece%20"),
        ("Foo &amp; Bar ", "Foo%20%26amp%3B%20Bar%20", "Foo%20&amp;%20Bar%20"),
        ("A&nbsp;B", "A%26nbsp%3BB", "A&nbsp;B"),
        ("Été", "%C3%89t%C3%A9", "%C3%89t%C3%A9"),
        ("L'Ami (2)", "L'Ami%20(2)", "L'Ami%20(2)"),
    ], ids=["trailing-space", "ampersand", "non-breaking-space", "accents", "punctuation"])
    def test_the_title_is_sent_as_the_viewer_reads_it(self, heading, query, path):
        count = f"{SITE}/s2/scans/get_nb_chap_et_img.php?oeuvre={query}"
        scraper = _site({PANEL: dict(text=_panel(script="", heading=heading)),
                         count: dict(data={"1": 2})})

        assert scraper.get_pages(f"{PANEL}#dossier=1") == [
            f"{SITE}/s2/scans/{path}/1/1.jpg", f"{SITE}/s2/scans/{path}/1/2.jpg"]

    @pytest.mark.parametrize("heading", [
        "", "   ", "A/B", "A?B", "A#B", "A%B", "A\\B", "One <b>Piece</b>", "One<!-- x -->Piece",
    ], ids=["empty", "blank", "slash", "question", "hash", "percent", "backslash", "child",
            "comment"])
    def test_a_title_that_cannot_be_sent_safely_is_an_error(self, heading):
        scraper = _site({PANEL: dict(text=_panel(script="", heading=heading))})

        with pytest.raises(AnimeSamaSourceError):
            scraper.get_pages(f"{PANEL}#dossier=1")
        assert len(scraper.session.calls) == 1


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def _pages(self, folder, counts):
        scraper = _site({PANEL: dict(text=_panel()), COUNT: dict(data=counts)})
        return scraper, scraper.get_pages(f"{PANEL}#dossier={folder}")

    def test_every_page_of_the_highest_folder(self):
        scraper, pages = self._pages(1200, _counts(**{"1200": 13}))

        assert pages == [f"{SITE}/s2/scans/One%20Piece%20/1200/{n}.jpg" for n in range(1, 14)]
        assert [url for url, _ in scraper.session.calls] == [PANEL, COUNT]

    def test_the_special_reads_its_own_folder(self):
        _, pages = self._pages(1046, _counts(**{"1046": 37}))

        assert len(pages) == 37
        assert pages[0] == f"{SITE}/s2/scans/One%20Piece%20/1046/1.jpg"

    def test_the_fragment_is_never_sent(self):
        scraper, _ = self._pages(1200, _counts())

        assert not any("#" in url or "dossier" in url for url, _ in scraper.session.calls)

    @pytest.mark.parametrize("folder", [1201, 5000], ids=["next", "far"])
    def test_a_folder_past_the_list_is_an_error(self, folder):
        with pytest.raises(AnimeSamaSourceError, match=f"in folder {folder}"):
            self._pages(folder, _counts())

    def test_a_folder_without_pages_is_an_error(self):
        counts = _counts()
        del counts["1199"]

        with pytest.raises(AnimeSamaSourceError, match="in folder 1199"):
            self._pages(1199, counts)

    def test_a_refused_panel_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({PANEL: dict(status=403)}).get_pages(f"{PANEL}#dossier=1")


# ── Download ────────────────────────────────────────────────────────

IMAGE = f"{SITE}/s2/scans/One%20Piece%20/1200/1.jpg"


class TestDownload:
    def test_webp_bytes_under_a_jpg_name_are_saved_as_served(self, tmp_path):
        scraper = _site({IMAGE: dict(content=WEBP)})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(IMAGE, target) is True
        assert target.read_bytes() == WEBP
        (sent, kwargs), = scraper.session.calls
        assert sent == IMAGE
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""),
        dict(status=302, content=b""), dict(status=403, content=b""),
    ], ids=["html", "empty", "redirect", "refused"])
    def test_a_failed_page_clears_an_older_file(self, answer, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")

        assert _site({IMAGE: answer}).download_image(IMAGE, target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://example.test/s2/scans/One%20Piece%20/1/1.jpg",
        "http://anime-sama.to/s2/scans/One%20Piece%20/1/1.jpg",
        "https://www.anime-sama.to/s2/scans/One%20Piece%20/1/1.jpg",
        f"{SITE}/s2/scans/One%20Piece%20/1/1.png",
        f"{SITE}/s2/scans/One%20Piece%20/x/1.jpg",
        f"{SITE}/s2/scans/One%20Piece%20/1/1.jpg?x=1",
        f"{SITE}/s2/scans/../1/1.jpg",
        f"{SITE}/autre/One%20Piece%20/1/1.jpg",
    ], ids=["other-site", "http", "www", "other-extension", "bad-folder", "query", "dot-dot",
            "other-path"])
    def test_a_url_off_the_viewers_form_is_not_requested(self, url, tmp_path):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper = _site({})

        assert scraper.download_image(url, target) is False
        assert scraper.session.calls == []
        assert not target.exists()
