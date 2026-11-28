"""Offline tests for FMTEAM: URL identity, search, the series and chapter
JSON, refusals, pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the fields the site's API serves.
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import fmteam as fm
from memanga.scrapers.fmteam import FMTeamScraper, FMTeamSourceError, FMTeamUnsupportedError

SITE = "https://fmteam.fr"
SERIES = f"{SITE}/manga/batuque"
SERIES_API = f"{SITE}/api/comics/batuque"
CHAPTER = f"{SITE}/read/batuque/fr/ch/157"
CHAPTER_API = f"{SITE}/api/read/batuque/fr/ch/157"
SEARCH = f"{SITE}/api/search/Batuque"
EMPTY = f"{SITE}/api/search/zzqxjkvwpyd"
FOLDER = (f"{SITE}/storage/comics/batuque_olx7weGtwqkSHNdE/"
          "fr-N-157-N-la-vraie-liberte_MTPam6S3iSWq6wuI")
PAGES = [f"{FOLDER}/01.png?v=1778342090", f"{FOLDER}/01a.jpg?v=1778342091",
         f"{FOLDER}/02.png?v=1778342091", f"{FOLDER}/27-28.png?v=1778342095",
         f"{FOLDER}/36.png?v=1778342099"]
TEAMS = [{"name": "FMTEAM", "url": "http://fmteam.fr"}, None]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


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
    scraper = FMTeamScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _row(number, **extra):
    row = {
        "id": None, "full_title": f"Chapitre {number} : Un titre", "title": "Un titre",
        "volume": None, "chapter": number, "subchapter": None,
        "full_chapter": f"[FR] Ch.{number}", "download_link": None, "language": "fr",
        "teams": TEAMS, "updated_at": "2026-07-06T21:31:50.000000Z",
        "published_on": "2026-05-09T15:54:00.000000Z", "hidden": 0, "licensed": 0,
        "slug_lang_vol_ch_sub": f"fr-N-{number}-N", "url": f"/read/batuque/fr/ch/{number}",
        "chapter_download": f"/download/batuque/fr/ch/{number}", "pdf": None,
    }
    row.update(extra)
    return row


ONESHOT = _row(None, full_title="Oneshot", title=None, url="/read/batuque/fr",
               slug_lang_vol_ch_sub="fr-N-N-N")


def _comic(slug="batuque", title="Batuque", chapters=None, **extra):
    comic = {
        "id": None, "title": title, "thumbnail": f"{SITE}/storage/comics/x/c.jpg?v=1",
        "author": "Sako Toshio", "artist": None, "target": "Seinen",
        "genres": [{"name": "Action - Science-fiction - Drame", "slug": "action"}],
        "status": "Terminé", "adult": 0, "hidden": 0, "url": f"/comics/{slug}",
        "slug": slug, "updated_at": "2026-07-17T20:37:35.000000Z",
    }
    if chapters is not None:
        comic["chapters"] = chapters
    comic.update(extra)
    return comic


_SERVED = object()  # "the served pages"; None is a real, invalid value


def _reader(pages=_SERVED, chapter=None, comic=None):
    chapter = dict(_row(157), pages=PAGES if pages is _SERVED else pages,
                   updated_at="2026-07-06 21:31:50", previous=_row(156), next=None,
                   vote_id=1330) if chapter is None else chapter
    return {"comic": _comic(chapters=[_row(157), _row(156)]) if comic is None else comic,
            "chapter": chapter}


THREE = [_row(157), _row(156), _row(1)]


# ── Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_metadata(self):
        scraper = FMTeamScraper()
        assert scraper.name == "fmteam"
        assert scraper.base_url == SITE
        assert scraper.engine == "api"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is False

    def test_no_cookie_is_kept(self):
        scraper = FMTeamScraper()
        cookie = create_cookie("site_session", "x", domain="fmteam.fr")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_series_url(self, url):
        assert FMTeamScraper()._series_slug(url) == "batuque"

    @pytest.mark.parametrize("url", [
        "http://fmteam.fr/manga/batuque",
        "https://www.fmteam.fr/manga/batuque",
        "https://evil.example/manga/batuque",
        "https://fmteam.fr:8443/manga/batuque",
        "https://u@fmteam.fr/manga/batuque",
        f"{SITE}/comics/batuque",
        f"{SITE}/api/comics/batuque",
        f"{SERIES}?x=1",
        f"{SERIES}#top",
        f"{SITE}/manga",
        f"{SITE}/manga/Batuque",
        f"{SITE}/manga/..",
        CHAPTER,
        "/manga/batuque",
        None,
    ])
    def test_other_series_urls_are_refused(self, url):
        with pytest.raises(FMTeamUnsupportedError):
            FMTeamScraper()._series_slug(url)

    def test_chapter_url(self):
        assert FMTeamScraper()._chapter_ref(CHAPTER) == ("batuque", "157")

    @pytest.mark.parametrize("url", [
        f"{SITE}/read/batuque/fr",
        f"{SITE}/read/batuque/fr/vol/15/ch/91",
        f"{SITE}/read/batuque/fr/ch/79/sub/1",
        f"{SITE}/read/batuque/en/ch/157",
        f"{SITE}/read/batuque/fr/ch/0157",
        f"{SITE}/read/batuque/fr/ch/157.5",
        f"{CHAPTER}#1",
        f"{SITE}/api/read/batuque/fr/ch/157",
        "https://evil.example/read/batuque/fr/ch/157",
    ])
    def test_other_chapter_urls_are_refused(self, url):
        with pytest.raises(FMTeamUnsupportedError):
            FMTeamScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_are_the_served_series(self):
        site = _site({SEARCH: dict(data={"comics": [_comic()]})})
        results = site.search("Batuque")
        assert [(m.title, m.url) for m in results] == [("Batuque", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_the_query_is_one_encoded_path_segment(self):
        url = f"{SITE}/api/search/Blue%20Lock%2F2"
        site = _site({url: dict(data={"comics": []})})
        site.search("  Blue   Lock/2 ")
        assert site.session.calls[0][0] == url

    def test_a_blank_query_sends_nothing(self):
        site = _site({})
        assert site.search("  ") == []
        assert site.session.calls == []

    def test_the_site_empty_answer_is_no_results(self):
        assert _site({EMPTY: dict(data={"comics": []})}).search("zzqxjkvwpyd") == []

    def test_the_same_series_twice_is_one_result(self):
        site = _site({SEARCH: dict(data={"comics": [_comic(), _comic()]})})
        assert len(site.search("Batuque")) == 1

    @pytest.mark.parametrize("extra", [
        {"adult": 1}, {"hidden": 1}, {"status": "Licencié"}, {"status": "Licenziato"},
    ])
    def test_a_refused_series_is_left_out_with_a_warning(self, extra, caplog):
        comics = [_comic(), _comic("berserk", "Berserk", **extra)]
        site = _site({SEARCH: dict(data={"comics": comics})})
        with caplog.at_level(logging.WARNING, logger=fm.logger.name):
            assert [m.url for m in site.search("Batuque")] == [SERIES]
        assert "1 search result(s)" in caplog.text

    @pytest.mark.parametrize("data", [
        {}, {"comics": None}, {"comics": ["x"]}, [],
        {"comics": [_comic(url="/comics/other")]},
        {"comics": [_comic(slug="Batuque")]},
        {"comics": [_comic(title=" ")]},
        {"comics": [_comic(title=None)]},
    ])
    def test_an_unreadable_answer_raises(self, data):
        with pytest.raises(FMTeamSourceError):
            _site({SEARCH: dict(data=data)}).search("Batuque")

    def test_html_where_json_is_expected_raises(self):
        with pytest.raises(FMTeamSourceError, match="not JSON"):
            _site({SEARCH: dict(text="<html>Just a moment</html>")}).search("Batuque")

    def test_a_redirect_raises(self):
        with pytest.raises(FMTeamSourceError):
            _site({SEARCH: dict(status=302)}).search("Batuque")

    def test_a_refusal_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("Batuque")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_numbered_chapters_newest_first(self):
        rows = [_row(1), _row(157), _row(156)]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == ["157", "156", "1"]
        assert chapters[0].url == CHAPTER
        assert chapters[0].title == "Chapitre 157 : Un titre"
        assert chapters[0].date == "2026-05-09"
        assert site.session.calls == [(SERIES_API, {"allow_redirects": False})]

    def test_a_date_that_is_not_an_iso_instant_is_not_kept(self):
        rows = [_row(2, published_on="2026-07-06 21:31:50"), _row(1, published_on=None)]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        assert [c.date for c in site.get_chapters(SERIES)] == [None, None]

    def test_a_oneshot_is_left_out_with_a_warning(self, caplog):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=THREE + [ONESHOT])})})
        with caplog.at_level(logging.WARNING, logger=fm.logger.name):
            assert [c.number for c in site.get_chapters(SERIES)] == ["157", "156", "1"]
        assert "1 unnumbered one-shot(s)" in caplog.text

    def test_a_series_that_is_only_a_oneshot_raises(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[ONESHOT])})})
        with pytest.raises(FMTeamSourceError, match="no numbered chapter"):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("extra", [{"hidden": 1}, {"licensed": 1}])
    def test_a_marked_chapter_is_left_out_with_a_warning(self, extra, caplog):
        rows = [_row(157, **extra), _row(156)]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        with caplog.at_level(logging.WARNING, logger=fm.logger.name):
            assert [c.number for c in site.get_chapters(SERIES)] == ["156"]
        assert "1 chapter(s) marked hidden or licensed" in caplog.text

    @pytest.mark.parametrize("row", [
        _row(91, volume=15, url="/read/batuque/fr/vol/15/ch/91"),
        _row(79, subchapter=1, url="/read/batuque/fr/ch/79/sub/1"),
        _row(157, language="en"),
        _row(157, language=None),
        _row(157, url="/read/other/fr/ch/157"),
        _row(157, url="/read/batuque/fr/ch/156"),
        _row(True, url="/read/batuque/fr/ch/True"),
        _row(-1, url="/read/batuque/fr/ch/-1"),
        _row("157"),
        _row(None, url="/read/batuque/fr/ch/None"),
        "not a row",
    ])
    def test_a_row_form_it_does_not_know_raises(self, row):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[_row(1), row])})})
        with pytest.raises(FMTeamSourceError):
            site.get_chapters(SERIES)

    def test_a_repeated_number_raises(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[_row(1), _row(1)])})})
        with pytest.raises(FMTeamSourceError, match="twice"):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("comic", [
        None,
        _comic(chapters=THREE, url="/comics/berserk"),
        _comic(chapters=THREE, slug="berserk"),
        _comic(chapters=THREE, adult=1),
        _comic(chapters=THREE, hidden=1),
        _comic(chapters=THREE, status="Licencié"),
        _comic(chapters=[]),
        _comic(),
    ])
    def test_a_series_it_cannot_read_raises(self, comic):
        site = _site({SERIES_API: dict(data={"comic": comic})})
        with pytest.raises(FMTeamSourceError):
            site.get_chapters(SERIES)

    def test_a_redirect_raises(self):
        with pytest.raises(FMTeamSourceError):
            _site({SERIES_API: dict(status=302)}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_served_order_with_its_query(self):
        site = _site({CHAPTER_API: dict(data=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(CHAPTER_API, {"allow_redirects": False})]

    @pytest.mark.parametrize("answer", [
        _reader(comic=_comic(url="/comics/berserk", slug="berserk")),
        _reader(comic=_comic(adult=1)),
        _reader(comic=_comic(status="Licencié")),
        {"chapter": _reader()["chapter"]},
        _reader(chapter=dict(_row(156), pages=PAGES)),
        _reader(chapter=dict(_row(157, url="/read/batuque/fr/ch/156"), pages=PAGES)),
        _reader(chapter=dict(_row(157, subchapter=1), pages=PAGES)),
        _reader(chapter=dict(_row(157, volume=2), pages=PAGES)),
        _reader(chapter=dict(_row(157, language="en"), pages=PAGES)),
        _reader(chapter=dict(_row(157, hidden=1), pages=PAGES)),
        _reader(chapter=dict(_row(157, licensed=1), pages=PAGES)),
        {"comic": _comic(), "chapter": None},
    ])
    def test_an_answer_for_another_or_refused_chapter_raises(self, answer):
        with pytest.raises(FMTeamSourceError):
            _site({CHAPTER_API: dict(data=answer)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("pages", [
        [],
        None,
        [PAGES[0], 7],
        [PAGES[0].replace("https:", "http:")],
        [PAGES[0].replace("fmteam.fr", "cdn.example")],
        [f"{SITE}/storage/other/a/01.png"],
        [f"{FOLDER}/01.png?v=1&x=2"],
        [f"{FOLDER}/01.txt"],
        [f"{SITE}/storage/comics/x/../01.png"],
        ["data:image/png;base64,AAAA"],
        [PAGES[0], PAGES[0]],
        [PAGES[0], f"{SITE}/storage/comics/batuque_x/other/02.png"],
    ])
    def test_a_page_list_it_cannot_trust_raises(self, pages):
        with pytest.raises(FMTeamSourceError):
            _site({CHAPTER_API: dict(data=_reader(pages=pages))}).get_pages(CHAPTER)

    def test_a_reader_without_its_page_list_raises(self):
        answer = _reader()
        del answer["chapter"]["pages"]
        with pytest.raises(FMTeamSourceError, match="no page images"):
            _site({CHAPTER_API: dict(data=answer)}).get_pages(CHAPTER)

    def test_no_cover_request_is_made(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "01.png"
        site = _site({PAGES[0]: dict(content=PNG)})
        assert site.download_image(PAGES[0], target) is True
        assert target.read_bytes() == PNG
        assert site.session.calls == [(PAGES[0], {
            "allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=PNG),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "01.png"
        target.write_bytes(b"older")
        assert _site({PAGES[0]: answer}).download_image(PAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"{SITE}/storage/other/a/01.png",
        PAGES[0].replace("fmteam.fr", "cdn.example"),
        PAGES[0].replace("https:", "http:"),
        None,
    ])
    def test_a_url_off_the_storage_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "01.png"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
