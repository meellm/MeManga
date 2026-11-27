"""Offline tests for Blue Solo: URL identity, search, the series and chapter
JSON (volumes and subchapters), adult refusal by flag and genre, the
API-confirmed cover, pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the fields the site's API serves.
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import bluesolo as bs
from memanga.scrapers.bluesolo import (BlueSoloScraper, BlueSoloSourceError,
                                       BlueSoloUnsupportedError)

SITE = "https://bluesolo.org"
SLUG = "aishiteru-game-wo-owarasetai"
SERIES = f"{SITE}/comics/{SLUG}"
SERIES_API = f"{SITE}/api/comics/{SLUG}"
SEARCH = f"{SITE}/api/search/Aishiteru"
EMPTY = f"{SITE}/api/search/zzqxjkvwpyd"
COVER = (f"{SITE}/storage/comics/{SLUG}_3DxZ7ruztClu63eH/"
         "20f124a3-4bdf-40a1-a6c4-b0125677eafe.png?v=1779402607")
FOLDER = f"{SITE}/storage/comics/{SLUG}_3DxZ7ruztClu63eH/fr-10-71-N-titre_Kq2Lw9xYzA1bC3dE"
PAGES = [f"{FOLDER}/01.png?v=1790872859", f"{FOLDER}/01a.png?v=1790872859",
         f"{FOLDER}/01b.png?v=1790872860", f"{FOLDER}/02.png?v=1790872860",
         f"{FOLDER}/36a.png?v=1790872875"]
TEAMS = [{"name": "Unnamed Era", "url": "https://example.org"}, None]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_SERVED = object()  # "the served value"; None is a real, invalid value


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
    scraper = BlueSoloScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _path(chapter, volume=10, sub=None, slug=SLUG):
    path = f"/read/{slug}/fr"
    if volume is not None:
        path += f"/vol/{volume}"
    path += f"/ch/{chapter}"
    if sub is not None:
        path += f"/sub/{sub}"
    return path


def _row(chapter, volume=10, sub=None, **extra):
    number = chapter if sub is None else f"{chapter}.{sub}"
    row = {
        "id": None, "full_title": f"Chapitre {number}", "title": None,
        "volume": volume, "chapter": chapter, "subchapter": sub,
        "full_chapter": "[FR]" + (f" Vol.{volume}" if volume is not None else "")
                        + f" Ch.{number}",
        "views": 10, "rating": None, "download_link": None, "language": "fr",
        "teams": TEAMS, "updated_at": "2026-10-01T16:40:35.000000Z",
        "published_on": "2026-10-01T16:40:00.000000Z", "hidden": 0, "licensed": 0,
        "slug_lang_vol_ch_sub": f"fr-{volume or 'N'}-{chapter}-{sub or 'N'}",
        "url": _path(chapter, volume, sub), "chapter_download": None,
        "volume_download": None, "pdf": None,
    }
    row.update(extra)
    return row


UNNUMBERED = _row(None, volume=None, full_chapter="[FR] ", full_title="Oneshot",
                  url=f"/read/{SLUG}/fr")


def _comic(slug=SLUG, title="Aishiteru Game wo Owarasetai", chapters=None, **extra):
    comic = {
        "id": None, "title": title, "thumbnail": COVER, "author": "Domoto Yuki",
        "artist": "Domoto Yuki", "target": "Shonen",
        "genres": [{"name": "Comédie", "slug": "comedie"}, {"name": "Romance", "slug": "romance"}],
        "status": "En Cours", "format_id": 1, "adult": 0, "hidden": 0,
        "url": f"/comics/{slug}", "slug": slug, "volume_downloads": [],
    }
    if chapters is not None:
        comic["chapters"] = chapters
    comic.update(extra)
    return comic


MATURE = [{"name": "Drame", "slug": "drame"}, {"name": "Mature", "slug": "mature"}]
SERVED_ROWS = [_row(71), _row(60, volume=8, sub=5), _row(60, volume=8),
               _row(15, volume=2, sub=1), _row(15, volume=2), _row(1, volume=1)]


def _reader(pages=_SERVED, chapter=None, comic=None, row=None):
    if chapter is None:
        chapter = dict(row or _row(71), updated_at="2026-10-01 16:40:35",
                       previous=_row(70), next=None, vote_id=7)
        if pages is not _SERVED:
            chapter["pages"] = pages
        else:
            chapter["pages"] = PAGES
    return {"chapter": chapter,
            "comic": _comic(chapters=SERVED_ROWS) if comic is None else comic}


def _api(path):
    return f"{SITE}/api{path}"


# ── Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_metadata(self):
        scraper = BlueSoloScraper()
        assert scraper.name == "bluesolo"
        assert scraper.base_url == SITE
        assert scraper.engine == "api"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is True

    def test_no_cookie_is_kept(self):
        scraper = BlueSoloScraper()
        cookie = create_cookie("site_session", "x", domain="bluesolo.org")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_series_url(self, url):
        assert BlueSoloScraper()._series_slug(url) == SLUG

    @pytest.mark.parametrize("url", [
        f"{SITE}/manga/{SLUG}",
        f"{SITE}/api/comics/{SLUG}",
        f"http://bluesolo.org/comics/{SLUG}",
        f"https://www.bluesolo.org/comics/{SLUG}",
        f"https://bluesolo.org:8443/comics/{SLUG}",
        f"https://u@bluesolo.org/comics/{SLUG}",
        f"{SERIES}?x=1",
        f"{SERIES}#top",
        f"{SITE}/comics",
        f"{SITE}/comics/Aishiteru",
        f"{SITE}/comics/..",
        f"/comics/{SLUG}",
        None,
    ])
    def test_other_series_urls_are_refused(self, url):
        with pytest.raises(BlueSoloUnsupportedError):
            BlueSoloScraper()._series_slug(url)

    @pytest.mark.parametrize("path, expected", [
        (_path(71), (SLUG, 10, 71, None)),
        (_path(60, 8, 5), (SLUG, 8, 60, 5)),
        (_path(5, None), (SLUG, None, 5, None)),
        (_path(5, None, 2), (SLUG, None, 5, 2)),
    ])
    def test_chapter_url_keeps_volume_and_subchapter(self, path, expected):
        assert BlueSoloScraper()._chapter_ref(f"{SITE}{path}") == expected

    @pytest.mark.parametrize("url", [
        f"{SITE}/read/{SLUG}/fr",
        f"{SITE}/read/{SLUG}/fr/vol/10",
        f"{SITE}{_path(60, 8)}/sub/0",
        f"{SITE}{_path(60, 8)}/sub/10",
        f"{SITE}/read/{SLUG}/fr/ch/60/vol/8",
        f"{SITE}/read/{SLUG}/fr/sub/5/ch/60",
        f"{SITE}/read/{SLUG}/en/vol/10/ch/71",
        f"{SITE}/read/{SLUG}/fr/vol/10/ch/071",
        f"{SITE}/read/{SLUG}/fr/vol/10/ch/71.5",
        f"{SITE}{_path(71)}/extra",
        f"{SITE}{_path(71)}#1",
        f"{SITE}/api{_path(71)}",
        f"https://evil.example{_path(71)}",
    ])
    def test_other_chapter_urls_are_refused(self, url):
        with pytest.raises(BlueSoloUnsupportedError):
            BlueSoloScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_are_the_served_series(self):
        site = _site({SEARCH: dict(data={"comics": [_comic()]})})
        results = site.search("Aishiteru")
        assert [(m.title, m.url) for m in results] == [("Aishiteru Game wo Owarasetai", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_the_query_is_one_encoded_path_segment(self):
        url = f"{SITE}/api/search/Blue%20Lock%2F2"
        site = _site({url: dict(data={"comics": []})})
        site.search("  Blue   Lock/2 ")
        assert site.session.calls[0][0] == url

    def test_a_blank_query_sends_nothing(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    def test_the_site_empty_answer_is_no_results(self):
        assert _site({EMPTY: dict(data={"comics": []})}).search("zzqxjkvwpyd") == []

    def test_a_series_without_a_status_is_kept(self):
        site = _site({SEARCH: dict(data={"comics": [_comic(status=None)]})})
        assert [m.url for m in site.search("Aishiteru")] == [SERIES]

    @pytest.mark.parametrize("extra", [
        {"adult": 1}, {"hidden": 1}, {"status": "Licencié"},
        {"genres": MATURE}, {"genres": [{"name": " adulte ", "slug": "adulte"}]},
        {"genres": "Mature"}, {"genres": [None]},
    ])
    def test_a_refused_series_is_left_out_with_a_warning(self, extra, caplog):
        comics = [_comic(), _comic("nezumi-no-hatsukoi", "Nezumi no Hatsukoi", **extra)]
        site = _site({SEARCH: dict(data={"comics": comics})})
        with caplog.at_level(logging.WARNING, logger=bs.logger.name):
            assert [m.url for m in site.search("Aishiteru")] == [SERIES]
        assert "1 search result(s)" in caplog.text

    @pytest.mark.parametrize("data", [
        {}, {"comics": None}, {"comics": ["x"]}, [],
        {"comics": [_comic(url="/comics/other")]},
        {"comics": [_comic(slug="Aishiteru")]},
        {"comics": [_comic(title="")]},
    ])
    def test_an_unreadable_answer_raises(self, data):
        with pytest.raises(BlueSoloSourceError):
            _site({SEARCH: dict(data=data)}).search("Aishiteru")

    def test_html_where_json_is_expected_raises(self):
        with pytest.raises(BlueSoloSourceError, match="not JSON"):
            _site({SEARCH: dict(text="<html>Chargement</html>")}).search("Aishiteru")

    def test_a_redirect_raises(self):
        with pytest.raises(BlueSoloSourceError):
            _site({SEARCH: dict(status=302)}).search("Aishiteru")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_volumes_and_subchapters_are_listed_by_their_served_labels(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=SERVED_ROWS)})})
        chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == ["71", "60.5", "60", "15.1", "15", "1"]
        assert [c.url for c in chapters] == [
            f"{SITE}{_path(71)}", f"{SITE}{_path(60, 8, 5)}", f"{SITE}{_path(60, 8)}",
            f"{SITE}{_path(15, 2, 1)}", f"{SITE}{_path(15, 2)}", f"{SITE}{_path(1, 1)}"]
        assert chapters[0].title == "Chapitre 71"
        assert chapters[0].date == "2026-10-01"
        assert site.session.calls == [(SERIES_API, {"allow_redirects": False})]

    def test_rows_without_a_volume_are_read(self):
        rows = [_row(5, volume=None), _row(4, volume=None, sub=2)]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url) for c in chapters] == [
            ("5", f"{SITE}{_path(5, None)}"), ("4.2", f"{SITE}{_path(4, None, 2)}")]

    def test_a_series_without_a_status_is_read(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[_row(1)], status=None)})})
        assert [c.number for c in site.get_chapters(SERIES)] == ["1"]

    def test_an_unnumbered_row_is_left_out_with_a_warning(self, caplog):
        rows = SERVED_ROWS + [UNNUMBERED]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        with caplog.at_level(logging.WARNING, logger=bs.logger.name):
            assert len(site.get_chapters(SERIES)) == 6
        assert "1 unnumbered chapter row(s)" in caplog.text

    def test_a_series_with_only_unnumbered_rows_raises(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[UNNUMBERED])})})
        with pytest.raises(BlueSoloSourceError, match="no numbered chapter"):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("extra", [{"hidden": 1}, {"licensed": 1}])
    def test_a_marked_chapter_is_left_out_with_a_warning(self, extra, caplog):
        rows = [_row(71, **extra), _row(70)]
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        with caplog.at_level(logging.WARNING, logger=bs.logger.name):
            assert [c.number for c in site.get_chapters(SERIES)] == ["70"]
        assert "1 chapter(s) marked hidden or licensed" in caplog.text

    @pytest.mark.parametrize("row", [
        _row(60, volume=8, sub=5, full_chapter="[FR] Vol.8 Ch.60"),
        _row(60, volume=8, sub=5, full_chapter=None),
        _row(60, volume=8, sub=10, url=_path(60, 8) + "/sub/10"),
        _row(60, volume=8, sub=0, url=_path(60, 8) + "/sub/0"),
        _row(60, volume=8, sub=True, url=_path(60, 8) + "/sub/True"),
        _row(71, url=_path(71, 9)),
        _row(71, url=_path(71, None)),
        _row(71, volume=None, url=_path(71)),
        _row(71, url=_path(71, 10, None, "other")),
        _row(True, url=_path("True")),
        _row("71", url=_path(71)),
        _row(-1, url=_path(-1)),
        _row(None, volume=3, url=f"/read/{SLUG}/fr/vol/3"),
        _row(71, language="en"),
        _row(71, language=None),
        "not a row",
    ])
    def test_a_row_form_it_cannot_place_raises(self, row):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=[_row(1), row])})})
        with pytest.raises(BlueSoloSourceError):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("rows", [
        [_row(60, volume=8), _row(60, volume=9)],
        [_row(60, volume=8, sub=5), _row(60, volume=9, sub=5)],
        [_row(1), _row(1)],
    ])
    def test_two_rows_with_one_number_raise(self, rows):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=rows)})})
        with pytest.raises(BlueSoloSourceError, match="twice"):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("comic", [
        None,
        _comic(chapters=SERVED_ROWS, url="/comics/other"),
        _comic(chapters=SERVED_ROWS, slug="other"),
        _comic(chapters=SERVED_ROWS, title=None),
        _comic(chapters=SERVED_ROWS, adult=1),
        _comic(chapters=SERVED_ROWS, hidden=1),
        _comic(chapters=SERVED_ROWS, status="Licensed"),
        _comic(chapters=SERVED_ROWS, genres=MATURE),
        _comic(chapters=[]),
        _comic(),
    ])
    def test_a_series_it_cannot_read_raises(self, comic):
        site = _site({SERIES_API: dict(data={"comic": comic})})
        with pytest.raises(BlueSoloSourceError):
            site.get_chapters(SERIES)

    def test_an_unknown_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES_API: dict(status=404)}).get_chapters(SERIES)

    def test_a_redirect_raises(self):
        with pytest.raises(BlueSoloSourceError):
            _site({SERIES_API: dict(status=302)}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_served_order_with_its_query(self):
        site = _site({_api(_path(71)): dict(data=_reader())})
        assert site.get_pages(f"{SITE}{_path(71)}") == PAGES
        assert site.session.calls == [(_api(_path(71)), {"allow_redirects": False})]

    def test_a_subchapter_is_read_from_its_own_link(self):
        path = _path(60, 8, 5)
        site = _site({_api(path): dict(data=_reader(row=_row(60, volume=8, sub=5)))})
        assert site.get_pages(f"{SITE}{path}") == PAGES
        assert site.session.calls[0][0] == _api(path)

    @pytest.mark.parametrize("answer", [
        _reader(comic=_comic(url="/comics/other", slug="other")),
        _reader(comic=_comic(genres=MATURE)),
        _reader(comic=_comic(adult=1)),
        {"chapter": _reader()["chapter"]},
        {"comic": _comic(), "chapter": None},
        _reader(row=_row(70)),
        _reader(row=_row(71, url=_path(70))),
        _reader(row=_row(71, volume=9)),
        _reader(row=_row(71, volume=None)),
        _reader(row=_row(71, volume=True)),
        _reader(row=_row(71, sub=5)),
        _reader(row=_row(71, language="en")),
        _reader(row=_row(71, hidden=1)),
        _reader(row=_row(71, licensed=1)),
    ])
    def test_an_answer_for_another_or_refused_chapter_raises(self, answer):
        with pytest.raises(BlueSoloSourceError):
            _site({_api(_path(71)): dict(data=answer)}).get_pages(f"{SITE}{_path(71)}")

    @pytest.mark.parametrize("pages", [
        [],
        None,
        [PAGES[0], 7],
        [PAGES[0].replace("https:", "http:")],
        [PAGES[0].replace("bluesolo.org", "cdn.example")],
        [f"{SITE}/storage/other/a/01.png"],
        [f"{FOLDER}/01.png?v=1&x=2"],
        [f"{FOLDER}/01.txt"],
        [f"{SITE}/storage/comics/x/../01.png"],
        ["data:image/png;base64,AAAA"],
        [PAGES[0], PAGES[0]],
        [PAGES[0], f"{SITE}/storage/comics/{SLUG}_x/other/02.png"],
    ])
    def test_a_page_list_it_cannot_trust_raises(self, pages):
        answer = _reader(pages=pages)
        assert answer["chapter"]["pages"] == pages
        with pytest.raises(BlueSoloSourceError):
            _site({_api(_path(71)): dict(data=answer)}).get_pages(f"{SITE}{_path(71)}")

    def test_a_reader_without_its_page_list_raises(self):
        answer = _reader()
        del answer["chapter"]["pages"]
        with pytest.raises(BlueSoloSourceError, match="no page images"):
            _site({_api(_path(71)): dict(data=answer)}).get_pages(f"{SITE}{_path(71)}")


# ── Cover (what adding a series confirms) ───────────────────────────

class TestCover:
    def test_the_cover_comes_from_the_series_api_answer(self):
        site = _site({SERIES_API: dict(data={"comic": _comic(chapters=SERVED_ROWS)})})
        assert site.get_cover_url(SERIES) == COVER
        assert site.session.calls == [(SERIES_API, {"allow_redirects": False})]

    @pytest.mark.parametrize("answer", [
        dict(status=404),
        dict(status=302),
        dict(text="<html>Chargement</html>"),
        dict(data={"comic": None}),
        dict(data={"comic": _comic(url="/comics/other", slug="other")}),
        dict(data={"comic": _comic(genres=MATURE)}),
    ])
    def test_a_series_the_api_does_not_confirm_gives_no_cover(self, answer, caplog):
        with caplog.at_level(logging.WARNING, logger=bs.logger.name):
            assert _site({SERIES_API: answer}).get_cover_url(SERIES) is None
        assert caplog.text

    @pytest.mark.parametrize("thumbnail", [
        None, "", COVER.replace("bluesolo.org", "cdn.example"), f"{SITE}/storage/x.png",
    ])
    def test_a_cover_off_the_site_storage_is_not_returned(self, thumbnail):
        site = _site({SERIES_API: dict(data={"comic": _comic(thumbnail=thumbnail)})})
        assert site.get_cover_url(SERIES) is None

    def test_a_url_that_is_not_a_series_sends_nothing(self, caplog):
        site = _site({})
        with caplog.at_level(logging.WARNING, logger=bs.logger.name):
            assert site.get_cover_url(f"{SITE}/manga/{SLUG}") is None
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
        PAGES[0].replace("bluesolo.org", "cdn.example"),
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
