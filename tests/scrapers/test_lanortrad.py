"""Offline tests for LanorTrad: the catalogue, chapter index and pages
files read as data, the series that are read or refused, search, chapters,
built page URLs, and the one image-host redirect of a download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the data files the site serves (comment lines, unquoted
keys, the ``expand`` index and the per-series pages file).
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import lanortrad as lt
from memanga.scrapers.lanortrad import (LanorTradScraper, LanorTradSourceError,
                                        LanorTradUnsupportedError)

PARSER_TESTS = {"LanorTradScraper": ("search", "chapters", "pages")}

SITE = "https://lanortrad.com"
SERIES_JS = f"{SITE}/js/data/series.js"
INDEX_JS = f"{SITE}/js/data/chapters.js"
PAGES_JS = f"{SITE}/js/data/pages/Tougen-Anki.js"
SERIES = f"{SITE}/manga.html?id=Tougen%20Anki"
CHAPTER = f"{SITE}/manga/tougen-anki/chapitre-256/"
FOLDER = "Tougen%20Anki/Chapitres/Chapitre%20256"
PAGES = [f"{SITE}/Manga/{FOLDER}/{n:03d}.webp" for n in range(1, 19)]
CDN = [p.replace("https://lanortrad.com/", "https://images.lanortrad.com/") for p in PAGES]
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8X" + b"\x00" * 8


def _entry(series_id, kind="manga", genres=("Action", "Drame"), demo="false", extra=""):
    genre_list = ", ".join(f'"{g}"' for g in genres)
    url = series_id.replace(" ", "%20")
    return (f'  {{\n    id: "{series_id}",\n    title: "{series_id}",\n    type: "{kind}",\n'
            f'    genres: [{genre_list}],\n    status: "En cours",\n    chapters: 256,\n'
            f'    rating: 4.8,\n    author: "Yura Urushibara",\n'
            f'    description:\n      "Shiki Ichinose : un simple ado ? Pas vraiment.",\n'
            f'    cover: "images/Cover/X.jpg",\n{extra}'
            f'    url: "manga.html?id={url}",\n    demo: {demo},\n    featured: true\n  }}')


TOUGEN = _entry("Tougen Anki", demo="true")
AO = _entry("Ao No Exorcist")
CATENACCIO = _entry(
    "Catenaccio", genres=("Sports", "Collaboration"), demo="true",
    extra=('    // Équipes partenaires (hors LanorTrad) qui collaborent sur cette série\n'
           '    partners: [\n      { name: "KaminaTrad", url: "https://x.com/KaminaTrad" }\n'
           '    ],\n'))
ONESHOT = _entry("Countdown", kind="oneshot", genres=("Surnaturel", "Oneshot"), demo="true")


def _catalogue(*entries):
    entries = entries or (TOUGEN, AO, ONESHOT)
    return ("// === LanorTrad - Source unique des metadonnees de series ===\r\n"
            "// demo      : true => chapitres reellement copies et lisibles dans cette version\r\n"
            "window.SERIES = [\r\n" + ",\r\n".join(entries) + "\r\n];\r\n")


EXPAND = """window.CHAPTERS = (function () {
  "use strict";
  function expand(D) {
    var out = {};
    for (var s in D) {
      var d = D[s], list = [];
      for (var i = 0; i < d.c.length; i++) {
        var c = d.c[i], o = c[2] || {};
        var folder = o.f !== undefined ? o.f : (o.p !== undefined ? o.p : d.p) + c[0];
        var e = { num: c[0], folder: folder, pages: c[1] };
        var w = o.w !== undefined ? o.w : d.w;
        var h = o.h !== undefined ? o.h : d.h;
        if (w) { e.w = w; e.h = h; }
        if (o.d) e.d = o.d;
        list.push(e);
      }
      out[s] = list;
    }
    return out;
  }
""".replace("\n", "\r\n")

TOUGEN_ROWS = [["256", 18, {"w": 836, "h": 1200, "d": "2026-10-17"}],
               ["255", 22, {"w": 836, "h": 1200, "d": "2026-10-17"}],
               ["246.5", 10, {"w": 836, "h": 1200}],
               ["9", 20, {"p": "Chapitres/Chapitre 0", "w": 1200, "h": 1800}],
               ["1", 54]]
PAGES_MAP = {"Ao No Exorcist": "js/data/pages/Ao-No-Exorcist.js",
             "Countdown": "js/data/pages/Countdown.js",
             "Tougen Anki": "js/data/pages/Tougen-Anki.js"}


def _index(data=None, pages=None, expand=EXPAND):
    data = {"Ao No Exorcist": {"p": "Chapitres/Chapitre ", "c": [["171", 34]]},
            "Countdown": {"p": "Chapitres/Chapitre ", "c": [["1", 40, {"f": "Oneshot"}]]},
            "Tougen Anki": {"p": "Chapitres/Chapitre ", "c": TOUGEN_ROWS,
                            "t": "001.webp", "w": 835, "h": 1200}} if data is None else data
    pages = PAGES_MAP if pages is None else pages
    return ("// Genere automatiquement par tools/build-data.py - NE PAS EDITER A LA MAIN\r\n"
            + expand + f"  return expand({json.dumps(data)});\r\n}})();\r\n"
            "// Ou trouver les pages de chaque serie (charge a la demande par le lecteur).\r\n"
            f"window.CHAPTER_PAGES = {json.dumps(pages, indent=1)};\r\n")


def _files(count):
    return [f"{n:03d}.webp" for n in range(1, count + 1)]


def _pages_file(chapters=None, series_id="Tougen Anki"):
    chapters = {"256": {"f": _files(18), "odd": {"5": [1644, 1200]}, "v": "644839a3"},
                "9": {"f": _files(20), "v": "0a2e5f6b"}} if chapters is None else chapters
    return ("// Genere automatiquement par tools/build-data.py - NE PAS EDITER A LA MAIN\n"
            "window.CHAPTER_FILES = window.CHAPTER_FILES || {};\n"
            f"window.CHAPTER_FILES[{json.dumps(series_id)}] = {json.dumps(chapters)};\n")


class _Response:
    def __init__(self, url, status=200, text="", content=None, headers=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode() if content is None else content
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})

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
    scraper = LanorTradScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


def _data(catalogue=None, index=None, pages=None):
    return {SERIES_JS: dict(text=_catalogue() if catalogue is None else catalogue),
            INDEX_JS: dict(text=_index() if index is None else index),
            PAGES_JS: dict(text=_pages_file() if pages is None else pages)}


def _urls(site):
    return [url for url, _ in site.session.calls]


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = LanorTradScraper()
        assert scraper.name == "lanortrad"
        assert scraper.base_url == SITE
        assert scraper.engine == "http"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = LanorTradScraper()
        cookie = create_cookie("site_session", "x", domain="lanortrad.com")
        request = MockRequest(requests.Request("GET", SERIES_JS).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url, ref", [
        (SERIES, ("id", "Tougen Anki")),
        (f"{SITE}/manga/tougen-anki/", ("slug", "tougen-anki")),
        (f"{SITE}/manga/tougen-anki", ("slug", "tougen-anki")),
    ])
    def test_series_links(self, url, ref):
        assert LanorTradScraper()._parse_series_url(url) == ref

    @pytest.mark.parametrize("url", [
        "http://lanortrad.com/manga.html?id=Tougen%20Anki",
        "https://www.lanortrad.com/manga.html?id=Tougen%20Anki",
        "https://images.lanortrad.com/manga/tougen-anki/",
        f"{SITE}/manga.html",
        f"{SITE}/manga.html?id=",
        f"{SITE}/manga.html?id=A&id=B",
        f"{SITE}/manga/Tougen Anki/",
        f"{SITE}/manga/tougen-anki/?x=1",
        f"{SITE}/manga/tougen-anki/chapitre-256/",
        f"{SITE}/reader.html?manga=Tougen%20Anki",
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(LanorTradUnsupportedError):
            LanorTradScraper()._parse_series_url(url)

    @pytest.mark.parametrize("url, ref", [
        (CHAPTER, ("tougen-anki", "256")),
        (f"{SITE}/manga/tougen-anki/chapitre-246.5", ("tougen-anki", "246.5")),
    ])
    def test_chapter_links(self, url, ref):
        assert LanorTradScraper()._chapter_ref(url) == ref

    @pytest.mark.parametrize("url", [
        f"{SITE}/manga/tougen-anki/lecture/",
        f"{SITE}/manga/tougen-anki/chapitre-0256/",
        f"{SITE}/manga/tougen-anki/chapitre-x/",
        f"{SITE}/manga/tougen-anki/chapitre-256/?v=1",
        "https://images.lanortrad.com/manga/tougen-anki/chapitre-256/",
    ])
    def test_a_chapter_form_not_read_is_refused(self, url):
        with pytest.raises(LanorTradUnsupportedError):
            LanorTradScraper()._chapter_ref(url)

    @pytest.mark.parametrize("text, slug", [
        ("Tougen Anki", "tougen-anki"), ("Ao No Exorcist", "ao-no-exorcist"),
        ("Mystère à l'école", "mystere-a-l-ecole")])
    def test_slugs_follow_the_site_links(self, text, slug):
        assert lt._slugify(text) == slug


# ── Data files ──────────────────────────────────────────────────────

class TestDataFiles:
    def test_the_catalogue_is_read_as_data(self):
        site = _site({SERIES_JS: dict(text=_catalogue(TOUGEN, CATENACCIO))})
        catalogue = site._catalogue()
        assert [e["id"] for e in catalogue] == ["Tougen Anki", "Catenaccio"]
        assert catalogue[0]["demo"] is True and catalogue[0]["rating"] == 4.8
        assert catalogue[0]["description"].startswith("Shiki Ichinose : un simple")
        assert catalogue[1]["partners"] == [{"name": "KaminaTrad",
                                             "url": "https://x.com/KaminaTrad"}]

    @pytest.mark.parametrize("text", [
        "window.SERIES = [];",
        "window.SERIES = [ { id: 'Tougen Anki', title: 'Tougen Anki' } ];",
        "window.SERIES = [ { id: \"A\", title: \"A\" }, { id: \"A\", title: \"A\" } ];",
        "window.SERIES = [ { id: \"A\" } ];",
        "window.SERIES = [ { id: \"A\", title: \"A\" } ]; window.SERIES.push(1);",
        "var SERIES = [ { id: \"A\", title: \"A\" } ];",
        "window.SERIES = [ { id: \"A\", title: \"A\" } ];\nwindow.SERIES = [];",
    ])
    def test_a_catalogue_this_source_cannot_read_raises(self, text):
        with pytest.raises(LanorTradSourceError):
            _site({SERIES_JS: dict(text=text)})._catalogue()

    def test_the_index_and_pages_map_are_read(self):
        index, pages = _site({INDEX_JS: dict(text=_index())})._index()
        assert index["Tougen Anki"]["c"][0] == ["256", 18, {"w": 836, "h": 1200,
                                                            "d": "2026-10-17"}]
        assert pages == PAGES_MAP

    @pytest.mark.parametrize("text", [
        _index(expand=EXPAND.replace("+ c[0];", "+ c[0] + \"-v2\";")),
        _index(expand=EXPAND.replace("pages: c[1]", "pages: c[1] * 2")),
        _index(pages={"Tougen Anki": "https://elsewhere.example/p.js"}),
        _index(pages={"Tougen Anki": "js/data/pages/../../x.js"}),
        _index().replace("return expand(", "return expand(window.X || "),
        _index().replace("window.CHAPTER_PAGES =", "window.PAGES ="),
    ])
    def test_an_index_this_source_cannot_read_raises(self, text):
        with pytest.raises(LanorTradSourceError):
            _site({INDEX_JS: dict(text=text)})._index()

    def test_a_data_file_that_is_not_served_raises(self):
        with pytest.raises(LanorTradSourceError, match="HTTP 301"):
            _site({SERIES_JS: dict(status=301)})._catalogue()

    def test_a_refusal_is_not_retried(self):
        site = _site({SERIES_JS: dict(status=403)})
        with pytest.raises(requests.HTTPError):
            site._catalogue()
        assert len(site.session.calls) == 1


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.parametrize("query", ["Tougen Anki", "  tougen   ANKI ", "tougen"])
    def test_a_readable_series_is_found_by_its_title(self, query):
        site = _site(_data())
        assert [(m.title, m.url) for m in site.search(query)] == [("Tougen Anki", SERIES)]
        assert site.session.calls == [(SERIES_JS, {"allow_redirects": False})]

    def test_a_term_with_no_match_is_empty(self):
        assert _site(_data()).search("zzqxjkvwpyd") == []

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("query, reason", [
        ("Ao No Exorcist", "demo"),
        ("Countdown", "one-shots are not read yet"),
    ])
    def test_a_series_not_read_is_left_out_with_a_warning(self, query, reason, caplog):
        with caplog.at_level(logging.WARNING, logger=lt.logger.name):
            assert _site(_data()).search(query) == []
        assert reason in caplog.text

    def test_a_served_link_that_does_not_name_its_series_raises(self):
        bad = TOUGEN.replace('url: "manga.html?id=Tougen%20Anki"', 'url: "manga.html?id=Other"')
        with pytest.raises(LanorTradSourceError, match="links to"):
            _site(_data(catalogue=_catalogue(bad))).search("Tougen")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_chapters_newest_first_with_their_dates(self):
        site = _site(_data())
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url, c.date, c.title) for c in chapters] == [
            ("256", f"{SITE}/manga/tougen-anki/chapitre-256/", "2026-10-17", None),
            ("255", f"{SITE}/manga/tougen-anki/chapitre-255/", "2026-10-17", None),
            ("246.5", f"{SITE}/manga/tougen-anki/chapitre-246.5/", None, None),
            ("9", f"{SITE}/manga/tougen-anki/chapitre-9/", None, None),
            ("1", f"{SITE}/manga/tougen-anki/chapitre-1/", None, None),
        ]
        assert _urls(site) == [SERIES_JS, INDEX_JS]

    def test_the_slug_link_reads_the_same_series(self):
        chapters = _site(_data()).get_chapters(f"{SITE}/manga/tougen-anki/")
        assert chapters[0].number == "256"

    @pytest.mark.parametrize("url, reason", [
        (f"{SITE}/manga.html?id=Ao%20No%20Exorcist", "demo"),
        (f"{SITE}/manga.html?id=Countdown", "one-shots"),
        (f"{SITE}/manga.html?id=Unknown", "0 series"),
    ])
    def test_a_series_not_read_raises_before_its_index(self, url, reason):
        site = _site(_data())
        with pytest.raises(LanorTradSourceError, match=reason):
            site.get_chapters(url)
        assert _urls(site) == [SERIES_JS]

    @pytest.mark.parametrize("entry, reason", [
        (_entry("Tougen Anki", genres=("Action", "Adulte"), demo="true"), "adult genre"),
        (_entry("Tougen Anki", kind="roman", demo="true"), "type 'roman'"),
        (_entry("Tougen Anki", demo="\"true\""), "demo"),
    ])
    def test_scope_is_read_from_the_served_fields(self, entry, reason):
        with pytest.raises(LanorTradSourceError, match=reason):
            _site(_data(catalogue=_catalogue(entry))).get_chapters(SERIES)

    @pytest.mark.parametrize("rows", [
        [["256", 18], ["256", 18]],
        [[256, 18]],
        [["256", 0]],
        [["256", "18"]],
        [["256"]],
        [["256", 18, {"f": "../x"}]],
        [["256", 18, {"f": "/Chapitres"}]],
        [["256", 18, []]],
        [["4,5", 18]],
        [],
    ])
    def test_an_index_row_this_source_cannot_read_raises(self, rows):
        data = {"Tougen Anki": {"p": "Chapitres/Chapitre ", "c": rows}}
        with pytest.raises(LanorTradSourceError):
            _site(_data(index=_index(data=data))).get_chapters(SERIES)

    def test_a_series_without_a_pages_file_raises(self):
        index = _index(pages={"Ao No Exorcist": "js/data/pages/Ao-No-Exorcist.js"})
        with pytest.raises(LanorTradSourceError, match="no pages file"):
            _site(_data(index=index)).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_built_from_the_served_parts_in_order(self):
        site = _site(_data())
        assert site.get_pages(CHAPTER) == PAGES
        assert _urls(site) == [SERIES_JS, INDEX_JS, PAGES_JS]

    def test_a_row_prefix_overrides_the_series_prefix(self):
        pages = _site(_data()).get_pages(f"{SITE}/manga/tougen-anki/chapitre-9/")
        assert pages[0] == f"{SITE}/Manga/Tougen%20Anki/Chapitres/Chapitre%2009/001.webp"
        assert len(pages) == 20

    def test_a_folder_override_is_used_as_served(self):
        data = {"Tougen Anki": {"p": "Chapitres/Chapitre ",
                                "c": [["256", 2, {"f": "Hors série/Spécial"}]]}}
        pages = _site(_data(index=_index(data=data),
                            pages=_pages_file({"256": {"f": ["01 a.webp", "02.jpg"]}}))
                      ).get_pages(CHAPTER)
        assert pages == [f"{SITE}/Manga/Tougen%20Anki/Hors%20s%C3%A9rie/Sp%C3%A9cial/01%20a.webp",
                         f"{SITE}/Manga/Tougen%20Anki/Hors%20s%C3%A9rie/Sp%C3%A9cial/02.jpg"]

    def test_a_chapter_of_a_series_not_read_raises_before_its_index(self):
        site = _site(_data())
        with pytest.raises(LanorTradSourceError, match="demo"):
            site.get_pages(f"{SITE}/manga/ao-no-exorcist/chapitre-171/")
        assert _urls(site) == [SERIES_JS]

    @pytest.mark.parametrize("chapters, series_id", [
        ({"256": {"f": _files(17)}}, "Tougen Anki"),
        ({"256": {"f": _files(17) + ["017.webp"]}}, "Tougen Anki"),
        ({"256": {"f": _files(17) + ["../018.webp"]}}, "Tougen Anki"),
        ({"256": {"f": _files(17) + ["018.svg"]}}, "Tougen Anki"),
        ({"256": {"f": []}}, "Tougen Anki"),
        ({"255": {"f": _files(18)}}, "Tougen Anki"),
        ({"256": {"f": _files(18)}}, "Ao No Exorcist"),
    ])
    def test_a_pages_list_this_source_cannot_read_raises(self, chapters, series_id):
        with pytest.raises(LanorTradSourceError):
            _site(_data(pages=_pages_file(chapters, series_id))).get_pages(CHAPTER)

    def test_a_chapter_missing_from_the_index_raises(self):
        with pytest.raises(LanorTradSourceError, match="no indexed chapter 300"):
            _site(_data()).get_pages(f"{SITE}/manga/tougen-anki/chapitre-300/")

    def test_no_cover_is_read(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

REFERER = {"Referer": f"{SITE}/"}


class TestDownload:
    def test_the_served_redirect_to_the_image_host_is_followed(self, tmp_path):
        target = tmp_path / "pages" / "009.webp"
        site = _site({PAGES[8]: dict(status=301, headers={"Location": CDN[8]}),
                      CDN[8]: dict(content=WEBP)})
        assert site.download_image(PAGES[8], target) is True
        assert target.read_bytes() == WEBP
        assert site.session.calls == [
            (PAGES[8], {"allow_redirects": False, "headers": REFERER}),
            (CDN[8], {"allow_redirects": False, "headers": REFERER})]

    def test_a_page_served_by_the_site_itself_is_saved(self, tmp_path):
        target = tmp_path / "018.webp"
        site = _site({PAGES[17]: dict(content=WEBP)})
        assert site.download_image(PAGES[17], target) is True
        assert len(site.session.calls) == 1

    def test_a_served_query_on_the_image_host_is_kept(self, tmp_path):
        location = CDN[0] + "?v=644839a3"
        site = _site({PAGES[0]: dict(status=302, headers={"Location": location}),
                      location: dict(content=WEBP)})
        assert site.download_image(PAGES[0], tmp_path / "001.webp") is True

    @pytest.mark.parametrize("location", [
        "https://elsewhere.example/Manga/Tougen%20Anki/Chapitres/Chapitre%20256/001.webp",
        CDN[0].replace("https:", "http:"),
        CDN[1],
        CDN[0].replace("/Manga/", "/manga/"),
        CDN[0] + "#x",
        "/Manga/Tougen%20Anki/Chapitres/Chapitre%20256/001.webp",
        "",
    ])
    def test_a_redirect_off_the_same_path_on_the_image_host_is_refused(self, location,
                                                                      tmp_path):
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        site = _site({PAGES[0]: dict(status=301, headers={"Location": location})})
        assert site.download_image(PAGES[0], target) is False
        assert len(site.session.calls) == 1
        assert not target.exists()

    @pytest.mark.parametrize("answer", [
        dict(status=301, headers={"Location": CDN[2]}),
        dict(content=b"<html>not an image</html>"),
        dict(status=403),
        dict(status=404),
    ])
    def test_a_failed_image_host_answer_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        site = _site({PAGES[0]: dict(status=301, headers={"Location": CDN[0]}), CDN[0]: answer})
        assert site.download_image(PAGES[0], target) is False
        assert len(site.session.calls) == 2
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        CDN[0],
        PAGES[0].replace("https:", "http:"),
        f"{SITE}/images/Cover/TougenAnki.jpg",
        PAGES[0] + "?v=1",
        f"{SITE}/Manga/Tougen Anki/Chapitres/Chapitre 256/001.webp",
        None,
    ])
    def test_a_url_off_the_page_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
