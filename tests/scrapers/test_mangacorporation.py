"""Offline tests for Manga-Corporation: URL identity, search, the chapter
rows with their volume, chapter and subchapter forms, the rows left out,
reader binding, served page URLs and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's API answers (``/api/search/…``,
``/api/comics/<slug>`` and ``/api/read/…``).
"""

from __future__ import annotations

import hashlib
import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import mangacorporation as mc
from memanga.scrapers.mangacorporation import (MangaCorporationScraper,
                                               MangaCorporationSourceError,
                                               MangaCorporationUnsupportedError)

PARSER_TESTS = {"MangaCorporationScraper": ("search", "chapters", "pages")}

SITE = "https://manga-corporation.com"
SLUG = "alya-sometimes-hides-her-feelings-in-russian"
TITLE = "Alya Sometimes Hides Her Feelings in Russian"
SERIES = f"{SITE}/comics/{SLUG}"
SERIES_API = f"{SITE}/api/comics/{SLUG}"
PATH_80 = f"/read/{SLUG}/fr/vol/10/ch/80"
CHAPTER = f"{SITE}{PATH_80}"
READER_API = f"{SITE}/api{PATH_80}"
SEARCH = f"{SITE}/api/search/Alya%20Sometimes%20Hides%20Her%20Feelings%20in%20Russian"
EMPTY = f"{SITE}/api/search/zzqxjkvwpyd"
COVER = (f"{SITE}/storage/comics/{SLUG}_jaBPrLefusJ70OOi/cover-variants/"
         "79f6e2c25db7a2a0484b549bf020239a502c4724914f5693d5c8b3d921f64430-640-q78.webp")
PAGES = [f"https://images.manga-corporation.com/chapters/435/"
         f"{hashlib.sha256(str(i).encode()).hexdigest()}.jpg" for i in range(17)]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
TEAMS = [{"name": "Manga-Corporation", "url": "https://x.com/MangaCorp_"}, None]
_SERVED = object()  # "the served value"; None is a real value here


def _row(chapter, volume=_SERVED, sub=None, path=None, published="2026-11-05T14:25:00.000000Z",
         language="fr", slug=SLUG, **extra):
    volume = 10 if volume is _SERVED else volume
    if path is None:
        path = f"/read/{slug}/fr"
        if chapter is not None:
            path += (f"/vol/{volume}" if volume is not None else "") + f"/ch/{chapter}"
            path += f"/sub/{sub}" if sub is not None else ""
    row = {"id": None, "full_title": f"Vol.{volume} Ch.{chapter} - La Peur du Bouton (6)",
           "title": "La Peur du Bouton « Reset » (6)", "volume": volume, "chapter": chapter,
           "subchapter": sub, "full_chapter": f"[FR] Vol.{volume} Ch.{chapter}", "views": 83,
           "rating": None, "download_link": None, "language": language, "teams": TEAMS,
           "updated_at": "2026-11-05T14:10:38.000000Z", "published_on": published,
           "hidden": 0, "licensed": 0, "anime_resume": False,
           "slug_lang_vol_ch_sub": f"fr-{volume}-{chapter}-N", "url": path,
           "chapter_download": path.replace("/read/", "/download/"), "volume_download": None,
           "pdf": path.replace("/read/", "/pdf/"), "comments_count": 0}
    row.update(extra)
    return row


ROWS = [_row(80), _row(79, published="2026-11-05T14:20:00.000000Z"),
        _row(59, volume=8, published="2026-02-15T12:00:00.000000Z"),
        _row(0, volume=None, published="2026-04-26T15:30:00.000000Z", title="Spin off Isekai")]


def _comic(chapters=None, slug=SLUG, **extra):
    comic = {"id": None, "title": TITLE, "thumbnail": COVER, "description": "Dans sa nouvelle école…",
             "alt_titles": ["Tokidoki Bosotto Russiago de Dereru Tonari no Alya-san"],
             "author": "Orignal : Sunsunsun / Manga : Saho Tenamachi", "artist": None,
             "target": "Shōnen", "genres": [{"name": "Comedy", "slug": "comedy"},
                                            {"name": "Romance", "slug": "romance"}],
             "status": "En cours", "category": "ongoing", "format_id": 1, "adult": 0,
             "hidden": 0, "url": f"/comics/{slug}", "slug": slug,
             "last_chapter": ROWS[0], "chapters": ROWS if chapters is None else chapters}
    comic.update(extra)
    return comic


def _reader(pages=None, comic=None, **chapter):
    row = dict(_row(80), updated_at="2026-11-05 14:10:38",
               pages=PAGES if pages is None else pages, pages_landscape=[0] * 17,
               suggested_offset=True, vote_id=435, previous=_row(79), next=None)
    row.update(chapter)
    comic = dict(_comic(), chapters=[]) if comic is None else comic
    return {"chapter": row, "comic": comic}


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
    scraper = MangaCorporationScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


def _series(comic=None):
    return _site({SERIES_API: dict(data={"comic": _comic() if comic is None else comic})})


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = MangaCorporationScraper()
        assert (scraper.name, scraper.base_url, scraper.engine) == (
            "mangacorporation", SITE, "api")
        assert scraper.content_language == "fr"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = MangaCorporationScraper()
        cookie = create_cookie("mc_session_v2", "x", domain="manga-corporation.com")
        request = MockRequest(requests.Request("GET", SERIES_API).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_series_url(self, url):
        assert MangaCorporationScraper()._series_slug(url) == SLUG

    @pytest.mark.parametrize("url", [
        f"http://manga-corporation.com/comics/{SLUG}",
        f"https://www.manga-corporation.com/comics/{SLUG}",
        f"{SITE}/manga/{SLUG}",
        f"{SITE}/comics/{SLUG}?page=2",
        f"{SITE}/comics/Alya",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(MangaCorporationUnsupportedError):
            MangaCorporationScraper()._series_slug(url)

    @pytest.mark.parametrize("url, ref", [
        (CHAPTER, (PATH_80, SLUG, 10, 80, None)),
        (f"{SITE}/read/{SLUG}/fr/ch/0", (f"/read/{SLUG}/fr/ch/0", SLUG, None, 0, None)),
        (f"{SITE}/read/tomodachi-game/fr/ch/0/sub/3/",
         ("/read/tomodachi-game/fr/ch/0/sub/3", "tomodachi-game", None, 0, 3)),
    ])
    def test_numbered_chapter_links(self, url, ref):
        assert MangaCorporationScraper()._chapter_ref(url) == ref

    @pytest.mark.parametrize("url", [
        f"{SITE}/read/c-45510/fr",
        f"{SITE}/read/{SLUG}/en/vol/10/ch/80",
        f"{SITE}/read/{SLUG}/fr/vol/10/ch/080",
        f"{SITE}/read/{SLUG}/fr/ch/80/sub/x",
        f"{SITE}/download/{SLUG}/fr/vol/10/ch/80",
        f"{SITE}/pdf/{SLUG}/fr/vol/10/ch/80",
    ])
    def test_a_chapter_form_not_read_is_refused(self, url):
        with pytest.raises(MangaCorporationUnsupportedError):
            MangaCorporationScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_exact_title_finds_the_series_with_its_cover(self):
        site = _site({SEARCH: dict(data={"comics": [dict(_comic(), chapters=[])]})})
        results = site.search(TITLE)
        assert [(m.title, m.url, m.cover_url) for m in results] == [(TITLE, SERIES, COVER)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_the_empty_answer_is_no_results(self):
        assert _site({EMPTY: dict(data={"comics": []})}).search("zzqxjkvwpyd") == []

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search("   ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("extra", [{"adult": 1}, {"hidden": 1}, {"status": "Licencié"}])
    def test_a_refused_series_is_left_out_with_a_warning(self, extra, caplog):
        comics = [dict(_comic(), chapters=[], **extra)]
        with caplog.at_level(logging.WARNING, logger=mc.logger.name):
            assert _site({EMPTY: dict(data={"comics": comics})}).search("zzqxjkvwpyd") == []
        assert "1 search result(s)" in caplog.text

    def test_a_cover_off_its_served_path_is_not_kept(self):
        comic = dict(_comic(), chapters=[], thumbnail="https://elsewhere.example/c.jpg")
        assert _site({EMPTY: dict(data={"comics": [comic]})}).search("zzqxjkvwpyd")[0].cover_url is None

    @pytest.mark.parametrize("answer", [
        {"comics": [{"title": TITLE, "slug": SLUG, "url": f"/manga/{SLUG}"}]},
        {"comics": [{"title": " ", "slug": SLUG, "url": f"/comics/{SLUG}"}]},
        {"comics": {"slug": SLUG}},
    ])
    def test_an_unreadable_result_raises(self, answer):
        with pytest.raises(MangaCorporationSourceError):
            _site({EMPTY: dict(data=answer)}).search("zzqxjkvwpyd")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_chapters_newest_first_with_their_served_paths_and_dates(self):
        site = _series()
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.url, c.date) for c in chapters] == [
            ("80", CHAPTER, "2026-11-05"),
            ("79", f"{SITE}/read/{SLUG}/fr/vol/10/ch/79", "2026-11-05"),
            ("59", f"{SITE}/read/{SLUG}/fr/vol/8/ch/59", "2026-02-15"),
            ("0", f"{SITE}/read/{SLUG}/fr/ch/0", "2026-04-26"),
        ]
        assert chapters[-1].title == "Spin off Isekai"
        assert site.session.calls == [(SERIES_API, {"allow_redirects": False})]

    def test_a_subchapter_keeps_its_exact_number(self):
        rows = [_row(0, volume=None, sub=3, slug=SLUG), _row(0, volume=None, slug=SLUG)]
        chapters = _series(_comic(rows)).get_chapters(SERIES)
        assert [(c.number, c.url) for c in chapters] == [
            ("0.3", f"{SITE}/read/{SLUG}/fr/ch/0/sub/3"), ("0", f"{SITE}/read/{SLUG}/fr/ch/0")]

    @pytest.mark.parametrize("row, reason", [
        (_row(None, volume=None, path=f"/read/{SLUG}/fr"), "unnumbered"),
        (_row(81, language="en", path=f"/read/{SLUG}/en/vol/10/ch/81"), "another language"),
        (_row(81, hidden=1), "hidden or licensed"),
        (_row(81, licensed=1), "hidden or licensed"),
        (_row(81, published="2099-01-01T00:00:00.000000Z"), "not published yet"),
    ])
    def test_a_row_not_read_is_left_out_with_a_counted_warning(self, row, reason, caplog):
        with caplog.at_level(logging.WARNING, logger=mc.logger.name):
            chapters = _series(_comic([row] + ROWS)).get_chapters(SERIES)
        assert [c.number for c in chapters] == ["80", "79", "59", "0"]
        assert f"1 chapter row(s) left out ({reason})" in caplog.text

    def test_an_unreadable_date_is_left_empty(self):
        chapters = _series(_comic([_row(80, published="2026-11-05 14:25:00")])).get_chapters(SERIES)
        assert chapters[0].date is None

    @pytest.mark.parametrize("rows", [
        [_row(80), _row(80)],
        [_row(1, volume=None, sub=1), _row(1, volume=None, sub=10)],
        [_row(80, path=f"/read/{SLUG}/fr/vol/9/ch/80")],
        [_row(80, path=f"/read/other-series/fr/vol/10/ch/80")],
        [_row(80, path=f"/read/{SLUG}/fr/vol/10/ch/80/extra")],
        [_row("80")],
        [_row(80.5)],
        ["/read/x"],
    ])
    def test_a_row_this_source_cannot_read_raises(self, rows):
        with pytest.raises(MangaCorporationSourceError):
            _series(_comic(rows)).get_chapters(SERIES)

    @pytest.mark.parametrize("comic", [
        _comic(slug="other-series"),
        dict(_comic(), url="/manga/" + SLUG),
        dict(_comic(), adult=1),
        dict(_comic(), hidden=1),
        dict(_comic(), status="Licensed"),
        dict(_comic(), chapters=None),
    ])
    def test_a_series_answer_not_read_raises(self, comic):
        with pytest.raises(MangaCorporationSourceError):
            _series(comic).get_chapters(SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(MangaCorporationSourceError, match="HTTP 301"):
            _site({SERIES_API: dict(status=301, text="")}).get_chapters(SERIES)

    def test_a_refusal_is_not_retried(self):
        site = _site({SERIES_API: dict(status=403)})
        with pytest.raises(requests.HTTPError):
            site.get_chapters(SERIES)
        assert len(site.session.calls) == 1


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_read_as_served(self):
        site = _site({READER_API: dict(data=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(READER_API, {"allow_redirects": False})]

    def test_a_subchapter_reader_is_bound_by_its_numbers(self):
        path = f"/read/{SLUG}/fr/ch/0/sub/3"
        answer = _reader(url=path, volume=None, chapter=0, subchapter=3)
        site = _site({f"{SITE}/api{path}": dict(data=answer)})
        assert site.get_pages(f"{SITE}{path}") == PAGES

    @pytest.mark.parametrize("chapter", [
        {"url": f"/read/{SLUG}/fr/vol/10/ch/79"},
        {"chapter": 79},
        {"volume": 9},
        {"subchapter": 1},
        {"language": "en"},
        {"hidden": 1},
        {"licensed": 1},
    ])
    def test_a_reader_for_another_or_withheld_chapter_raises(self, chapter):
        with pytest.raises(MangaCorporationSourceError):
            _site({READER_API: dict(data=_reader(**chapter))}).get_pages(CHAPTER)

    def test_a_reader_for_another_series_raises(self):
        answer = _reader(comic=dict(_comic(slug="other-series"), chapters=[]))
        with pytest.raises(MangaCorporationSourceError, match="not this series"):
            _site({READER_API: dict(data=answer)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("pages", [
        [],
        PAGES[:3] + [PAGES[0]],
        [PAGES[0] + "?v=1"],
        [PAGES[0].replace("images.manga-corporation.com", "manga-corporation.com")],
        [PAGES[0].replace("https:", "http:")],
        ["https://images.manga-corporation.com/chapters/435/notahexname.jpg"],
        ["data:image/jpeg;base64,AAAA"],
        [None],
    ])
    def test_a_page_list_this_source_does_not_read_raises(self, pages):
        with pytest.raises(MangaCorporationSourceError):
            _site({READER_API: dict(data=_reader(pages=pages))}).get_pages(CHAPTER)

    def test_no_cover_is_read_when_adding(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [PAGES[8], COVER,
                                     f"{SITE}/storage/comics/{SLUG}_jaBPrLefusJ70OOi/"
                                     "cover%20t10.jpg?v=1790770838"])
    def test_a_served_image_is_saved_with_the_site_as_referer(self, url, tmp_path):
        target = tmp_path / "pages" / "009.jpg"
        site = _site({url: dict(content=JPEG)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == JPEG
        assert site.session.calls == [(url, {"allow_redirects": False,
                                             "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=JPEG),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "009.jpg"
        target.write_bytes(b"older")
        assert _site({PAGES[8]: answer}).download_image(PAGES[8], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        PAGES[8].replace("https:", "http:"),
        PAGES[8] + "?v=1",
        f"{SITE}/download/{SLUG}/fr/vol/10/ch/80",
        "https://elsewhere.example/chapters/435/" + "a" * 64 + ".jpg",
        None,
    ])
    def test_a_url_off_the_image_paths_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "009.jpg"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
