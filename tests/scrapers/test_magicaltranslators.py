"""Offline tests for Magical Translators: English-only catalogue series,
search, the chapter listing and its group choice, pages built from the
served slug, folder, group and file names (cache queries kept), and
download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's guya API answers (``/api/get_all_series/`` and
``/api/series/<slug>/``).
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import magicaltranslators as mt
from memanga.scrapers.magicaltranslators import (MagicalTranslatorsScraper,
                                                 MagicalTranslatorsSourceError,
                                                 MagicalTranslatorsUnsupportedError)

PARSER_TESTS = {"MagicalTranslatorsScraper": ("search", "chapters", "pages")}

SITE = "https://mahoushoujobu.com"
CATALOGUE = f"{SITE}/api/get_all_series/"
SERIES_API = f"{SITE}/api/series/After-School-Mate/"
SERIES = f"{SITE}/reader/series/After-School-Mate/"
CHAPTER = f"{SITE}/read/manga/After-School-Mate/13-5/1/"
MEDIA = f"{SITE}/media/manga/After-School-Mate/chapters"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
GROUPS = {"1": "Magical Translators", "12": "ElPsyKongroo & Magical Translators",
          "13": "haibane"}


def _entry(slug, cover=None):
    return {"author": "Umino Kuon", "artist": "Umino Kuon", "description": "",
            "slug": slug, "cover": cover or f"/media/manga/{slug}/volume_covers/1/00001.jpeg",
            "groups": GROUPS, "last_updated": 1703198402}


def _catalogue(**extra):
    data = {
        "After School Mate": _entry("After-School-Mate"),
        "Bro Girl": _entry("Bro-Girl"),
        "Bro Girl (en español/in Spanish)": _entry("Bro-Girl-ES"),
        "Magical Trans! (po polsku/in Polish)": _entry("Magical-Trans-PL"),
        "I Got Genderswapped (♂→♀), So I Tried To Seduce My Classmate":
            _entry("Classmate-GB", "/media/manga/Classmate-GB/volume_covers/1/Evi_AM5UYAEaXQW.jpeg"),
    }
    data.update(extra)
    return data


def _files(count, last="_w", ext="png", query=""):
    names = [f"{n:02d}.{ext}{query}" for n in range(1, count)]
    return names + [f"{count:02d}{last}.{ext}{query}"]


def _chapter(folder, files, group="12", released=1696436168, title=""):
    return {"volume": "2", "title": title, "folder": folder, "groups": {group: files},
            "release_date": {group: released}}


def _series(chapters=None, slug="After-School-Mate", preferred=None):
    chapters = {
        "1": _chapter("0001_jmjnwk8z", _files(33, ext="jpg"), group="13", released=1655931253),
        "6.5": _chapter("0006-5_24dncbsk", _files(10), released=1660517038),
        "13": _chapter("0013_hvh3s8o1", _files(38, query="?v2"), released=1696360199),
        "13.5": _chapter("0013-5_klv3ygl7", _files(13)),
    } if chapters is None else chapters
    return {"slug": slug, "title": "After School Mate", "description": "A coming-of-age drama.",
            "author": "Umino Kuon", "artist": "Umino Kuon",
            "groups": {"13": "haibane", "12": "ElPsyKongroo & Magical Translators"},
            "cover": "/media/manga/After-School-Mate/volume_covers/1/00001.jpeg",
            "preferred_sort": [] if preferred is None else preferred, "chapters": chapters,
            "next_release_page": False, "next_release_time": None, "next_release_html": ""}


class _Response:
    def __init__(self, url, status=200, data=None, content=None, text=None):
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
    scraper = MagicalTranslatorsScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


def _api(series=None, catalogue=None):
    return {CATALOGUE: dict(data=_catalogue() if catalogue is None else catalogue),
            SERIES_API: dict(data=_series() if series is None else series)}


def _urls(site):
    return [url for url, _ in site.session.calls]


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = MagicalTranslatorsScraper()
        assert (scraper.name, scraper.base_url, scraper.engine) == (
            "magicaltranslators", SITE, "api")
        assert scraper.content_language == "en"
        assert scraper.nsfw is True
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = MagicalTranslatorsScraper()
        cookie = create_cookie("sessionid", "x", domain="mahoushoujobu.com")
        request = MockRequest(requests.Request("GET", CATALOGUE).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [
        SERIES, f"{SITE}/reader/series/After-School-Mate",
        f"{SITE}/read/manga/After-School-Mate/"])
    def test_series_links(self, url):
        assert MagicalTranslatorsScraper()._series_slug(url) == "After-School-Mate"

    def test_gb_is_not_a_language(self):
        assert MagicalTranslatorsScraper()._series_slug(
            f"{SITE}/reader/series/Classmate-GB/") == "Classmate-GB"

    @pytest.mark.parametrize("slug", ["Bro-Girl-ES", "Magical-Trans-PL"])
    def test_other_languages_are_refused_before_a_request(self, slug):
        site = _site({})
        with pytest.raises(MagicalTranslatorsUnsupportedError, match="not in English"):
            site.get_chapters(f"{SITE}/reader/series/{slug}/")
        with pytest.raises(MagicalTranslatorsUnsupportedError, match="not in English"):
            site.get_pages(f"{SITE}/read/manga/{slug}/1/1/")
        assert site.session.calls == []

    @pytest.mark.parametrize("url", [
        "http://mahoushoujobu.com/reader/series/After-School-Mate/",
        "https://www.mahoushoujobu.com/reader/series/After-School-Mate/",
        f"{SITE}/reader/series/After-School-Mate/?x=1",
        f"{SITE}/reader/series/After_School_Mate/",
        f"{SITE}/series/After-School-Mate/",
        f"{SITE}/read/manga/After-School-Mate/13-5/1/",
        f"{SITE}/torawase/",
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(MagicalTranslatorsUnsupportedError):
            MagicalTranslatorsScraper()._series_slug(url)

    @pytest.mark.parametrize("url, ref", [
        (CHAPTER, ("After-School-Mate", "13.5")),
        (f"{SITE}/read/manga/After-School-Mate/13/1", ("After-School-Mate", "13")),
    ])
    def test_chapter_links(self, url, ref):
        assert MagicalTranslatorsScraper()._chapter_ref(url) == ref

    @pytest.mark.parametrize("url", [
        f"{SITE}/read/manga/After-School-Mate/13-5/2/",
        f"{SITE}/read/manga/After-School-Mate/13.5/1/",
        f"{SITE}/read/manga/After-School-Mate/013/1/",
        f"{SITE}/read/manga/After-School-Mate/13-5/",
        SERIES,
    ])
    def test_a_chapter_form_not_read_is_refused(self, url):
        with pytest.raises(MagicalTranslatorsUnsupportedError):
            MagicalTranslatorsScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    @pytest.mark.parametrize("query", ["After School Mate", "  after   SCHOOL ", "school"])
    def test_a_series_is_found_by_its_title(self, query):
        site = _site(_api())
        results = site.search(query)
        assert [(m.title, m.url, m.cover_url) for m in results] == [(
            "After School Mate", SERIES,
            f"{SITE}/media/manga/After-School-Mate/volume_covers/1/00001.jpeg")]
        assert site.session.calls == [(CATALOGUE, {"allow_redirects": False})]

    def test_a_term_with_no_match_is_empty(self):
        assert _site(_api()).search("zzqxjkvwpyd") == []

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    def test_other_language_entries_are_left_out(self):
        results = _site(_api()).search("Bro Girl")
        assert [m.url for m in results] == [f"{SITE}/reader/series/Bro-Girl/"]

    def test_the_gb_entry_is_english(self):
        results = _site(_api()).search("Seduce My Classmate")
        assert [m.url for m in results] == [f"{SITE}/reader/series/Classmate-GB/"]
        assert results[0].cover_url.endswith("/Classmate-GB/volume_covers/1/Evi_AM5UYAEaXQW.jpeg")

    def test_a_cover_off_the_media_path_is_not_kept(self):
        catalogue = _catalogue(**{"After School Mate": _entry(
            "After-School-Mate", "https://proxy.f-ck.me/cover.jpg")})
        assert _site(_api(catalogue=catalogue)).search("After")[0].cover_url is None

    @pytest.mark.parametrize("catalogue", [
        {},
        {"After School Mate": {"slug": "After School Mate"}},
        {"After School Mate": _entry("After-School-Mate"), "Again": _entry("After-School-Mate")},
        {"After School Mate": ["After-School-Mate"]},
    ])
    def test_a_catalogue_this_source_cannot_read_raises(self, catalogue):
        with pytest.raises(MagicalTranslatorsSourceError):
            _site(_api(catalogue=catalogue)).search("After")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_chapters_newest_first_with_their_dates(self):
        site = _site(_api())
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url, c.date, c.title) for c in chapters] == [
            ("13.5", CHAPTER, "2023-10-04", None),
            ("13", f"{SITE}/read/manga/After-School-Mate/13/1/", "2023-10-03", None),
            ("6.5", f"{SITE}/read/manga/After-School-Mate/6-5/1/", "2022-08-14", None),
            ("1", f"{SITE}/read/manga/After-School-Mate/1/1/", "2022-06-22", None),
        ]
        assert site.session.calls == [(CATALOGUE, {"allow_redirects": False}),
                                      (SERIES_API, {"allow_redirects": False})]

    def test_a_served_chapter_title_is_kept(self):
        series = _series({"2": _chapter("0002_enbb8wd7", _files(3), title="  The Rain  ")})
        assert _site(_api(series=series)).get_chapters(SERIES)[0].title == "The Rain"

    def test_a_series_outside_the_catalogue_is_refused(self):
        site = _site({CATALOGUE: dict(data=_catalogue())})
        with pytest.raises(MagicalTranslatorsSourceError, match="not in the site's catalogue"):
            site.get_chapters(f"{SITE}/reader/series/Torawase/")
        assert _urls(site) == [CATALOGUE]

    def test_a_chapter_from_several_groups_without_a_preference_is_left_out(self, caplog):
        both = {"volume": "1", "title": "", "folder": "0002_enbb8wd7",
                "groups": {"12": _files(3), "13": _files(4)},
                "release_date": {"12": 1660517038, "13": 1660517039}}
        series = _series({"2": both, "13.5": _chapter("0013-5_klv3ygl7", _files(13))})
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _site(_api(series=series)).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["13.5"]
        assert "1 chapter(s) are offered by several groups" in caplog.text

    def test_the_served_preferred_group_is_used(self):
        both = {"volume": "1", "title": "", "folder": "0002_enbb8wd7",
                "groups": {"12": _files(3), "13": _files(4)},
                "release_date": {"12": 1660517038, "13": 1655931253}}
        site = _site(_api(series=_series({"2": both}, preferred=["13", "12"])))
        assert site.get_chapters(SERIES)[0].date == "2022-06-22"
        site = _site(_api(series=_series({"2": both}, preferred=["13", "12"])))
        assert site.get_pages(f"{SITE}/read/manga/After-School-Mate/2/1/") == [
            f"{MEDIA}/0002_enbb8wd7/13/{name}" for name in _files(4)]

    def test_a_chapter_not_released_yet_is_left_out(self, caplog):
        series = _series({"14": _chapter("0014_aaaaaaaa", _files(3), released=4102444800),
                          "13.5": _chapter("0013-5_klv3ygl7", _files(13))})
        with caplog.at_level(logging.WARNING, logger=mt.logger.name):
            chapters = _site(_api(series=series)).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["13.5"]
        assert "not released yet" in caplog.text

    @pytest.mark.parametrize("chapters", [
        {"13,5": _chapter("0013-5_klv3ygl7", _files(13))},
        {"13.5": _chapter("../x", _files(13))},
        {"13.5": dict(_chapter("0013-5_klv3ygl7", _files(13)), folder=None)},
        {"13.5": dict(_chapter("0013-5_klv3ygl7", _files(13)), release_date={"12": "2023"})},
        {"13.5": dict(_chapter("0013-5_klv3ygl7", _files(13)), release_date=[1696436168])},
        {"13.5": "0013-5_klv3ygl7"},
    ])
    def test_a_chapter_this_source_cannot_read_raises(self, chapters):
        with pytest.raises(MagicalTranslatorsSourceError):
            _site(_api(series=_series(chapters))).get_chapters(SERIES)

    @pytest.mark.parametrize("answer", [
        dict(data=_series(slug="Bro-Girl")),
        dict(data=dict(_series(), chapters=[])),
        dict(status=301, text=""),
        dict(text="<html>not json</html>"),
    ])
    def test_a_series_answer_that_is_not_this_series_raises(self, answer):
        routes = _api()
        routes[SERIES_API] = answer
        with pytest.raises(MagicalTranslatorsSourceError):
            _site(routes).get_chapters(SERIES)

    def test_a_refusal_is_not_retried(self):
        site = _site({CATALOGUE: dict(status=403)})
        with pytest.raises(requests.HTTPError):
            site.get_chapters(SERIES)
        assert len(site.session.calls) == 1


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_built_from_the_served_parts_in_order(self):
        site = _site(_api())
        pages = site.get_pages(CHAPTER)
        assert pages == [f"{MEDIA}/0013-5_klv3ygl7/12/{n:02d}.png" for n in range(1, 13)] + [
            f"{MEDIA}/0013-5_klv3ygl7/12/13_w.png"]
        assert pages[6].endswith("/12/07.png")
        assert _urls(site) == [CATALOGUE, SERIES_API]

    def test_a_served_cache_query_is_kept(self):
        pages = _site(_api()).get_pages(f"{SITE}/read/manga/After-School-Mate/13/1/")
        assert len(pages) == 38
        assert pages[18] == f"{MEDIA}/0013_hvh3s8o1/12/19.png?v2"
        assert pages[-1] == f"{MEDIA}/0013_hvh3s8o1/12/38_w.png?v2"

    def test_another_groups_chapter_uses_its_group_and_folder(self):
        pages = _site(_api()).get_pages(f"{SITE}/read/manga/After-School-Mate/1/1/")
        assert pages[0] == f"{MEDIA}/0001_jmjnwk8z/13/01.jpg" and len(pages) == 33

    def test_a_chapter_left_out_of_the_listing_raises(self):
        series = _series({"14": _chapter("0014_aaaaaaaa", _files(3), released=4102444800)})
        with pytest.raises(MagicalTranslatorsSourceError, match="no readable chapter 14"):
            _site(_api(series=series)).get_pages(f"{SITE}/read/manga/After-School-Mate/14/1/")

    @pytest.mark.parametrize("files", [
        [],
        ["01.png", "01.png"],
        ["../01.png"],
        ["01.png?v2&x=1"],
        ["01.svg"],
        ["https://proxy.f-ck.me/01.png"],
        [1],
    ])
    def test_a_page_list_this_source_cannot_read_raises(self, files):
        series = _series({"13.5": _chapter("0013-5_klv3ygl7", files)})
        with pytest.raises(MagicalTranslatorsSourceError, match="no readable page list"):
            _site(_api(series=series)).get_pages(CHAPTER)

    def test_a_group_id_this_source_does_not_read_raises(self):
        series = _series({"13.5": _chapter("0013-5_klv3ygl7", _files(13), group="x1")})
        with pytest.raises(MagicalTranslatorsSourceError):
            _site(_api(series=series)).get_pages(CHAPTER)

    def test_no_cover_is_read_when_adding(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [
        f"{MEDIA}/0013-5_klv3ygl7/12/07.png",
        f"{MEDIA}/0013_hvh3s8o1/12/19.png?v2",
        f"{SITE}/media/manga/After-School-Mate/volume_covers/1/00001.jpeg",
    ])
    def test_a_media_file_is_saved_with_the_site_as_referer(self, url, tmp_path):
        target = tmp_path / "pages" / "07.png"
        site = _site({url: dict(content=PNG)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == PNG
        assert site.session.calls == [(url, {"allow_redirects": False,
                                             "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=PNG),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        url = f"{MEDIA}/0013-5_klv3ygl7/12/07.png"
        target = tmp_path / "07.png"
        target.write_bytes(b"older")
        assert _site({url: answer}).download_image(url, target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://proxy.f-ck.me/media/manga/After-School-Mate/chapters/0013-5_klv3ygl7/12/07.png",
        f"{MEDIA}/0013-5_klv3ygl7/12/07.png".replace("https:", "http:"),
        f"{MEDIA}/0013-5_klv3ygl7/12/../07.png",
        f"{MEDIA}/0013-5_klv3ygl7/12/07.png?v2&x=1",
        f"{SITE}/static/img/logo.png",
        None,
    ])
    def test_a_url_off_the_media_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "07.png"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
