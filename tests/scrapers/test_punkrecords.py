"""Offline tests for Punk Records: URL identity, search and its single page,
the series list, reader binding by ids, the plain-edition rule, pages and
download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the fields the site's API serves.
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import punkrecords as pr
from memanga.scrapers.punkrecords import (PunkRecordsScraper, PunkRecordsSourceError,
                                          PunkRecordsUnsupportedError)

SITE = "https://punkrecordz.com"
SERIES = f"{SITE}/manga/naruto"
SERIES_API = f"{SITE}/api/mangas/naruto"
CHAPTER = f"{SITE}/naruto/700"
READER_API = f"{SITE}/api/mangas/naruto/chapters/700/reader"
SEARCH = f"{SITE}/api/search?q=Naruto&page=1&perPage=24"
EMPTY = f"{SITE}/api/search?q=zzqxjkvwpyd&page=1&perPage=24"
MANGA_ID = "81644914-a38f-48ba-ae6b-4ce712b18f00"
CHAPTER_ID = "32446fa4-f062-4548-a2e4-88b029054293"
OTHER_ID = "4f00fc34-0153-4389-bee3-1afb1a49cee1"
PAGE_IDS = ["c7ad7964-61ac-456e-9853-bc7f3c224b79", "98dccef4-0339-4c9f-933e-440146beaa4a",
            "b56feb9f-5137-4c0a-a0d0-43fd622ec2d8"]
COVER = f"https://s3-preprod3.punkrecordz.com/punk-records/mangas/{MANGA_ID}/cover/c.webp"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8
_SERVED = object()  # "the served value"; None is a real, invalid value


def _page_url(index, page_id=None, manga_id=MANGA_ID, chapter_id=CHAPTER_ID):
    page_id = PAGE_IDS[index] if page_id is None else page_id
    return (f"https://s3-preprod3.punkrecordz.com/punk-records/mangas/{manga_id}"
            f"/chapters/{chapter_id}/pages/{index:04d}-{page_id}.webp")


PAGES = [_page_url(i) for i in range(3)]


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
    scraper = PunkRecordsScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _item(slug="naruto", title="Naruto", item_id=MANGA_ID, **extra):
    item = {"id": item_id, "title": title, "slug": slug,
            "coverUrl": "/api/media/thumbnail?v=3", "firstPageUrl": "/api/media/thumbnail?v=3",
            "author": "Masashi Kishimoto", "updatedAt": "2026-09-16T20:50:16.445Z",
            "viewCount": 348448,
            "latestChapter": {"id": CHAPTER_ID, "number": 700, "title": "Chapitre 700"}}
    item.update(extra)
    return item


def _results(items, total=None, total_pages=1, page=1):
    return {"items": items, "total": len(items) if total is None else total,
            "page": page, "perPage": 24, "totalPages": total_pages}


def _row(number, row_id=None, **extra):
    row = {"id": row_id or f"00000000-0000-4000-8000-{number:012d}", "number": number,
           "title": f"Chapitre {number}", "slug": str(number),
           "publishedAt": "2026-08-22T14:48:36.850Z", "viewCount": 1223, "pageCount": 23,
           "firstPageUrl": "/api/media/thumbnail?v=4&variant=chapter",
           "firstPageWidth": 1013, "firstPageHeight": 1600}
    row.update(extra)
    return row


def _series(rows=None, count=_SERVED, **extra):
    rows = [_row(1), _row(2), _row(700, row_id=CHAPTER_ID)] if rows is None else rows
    manga = {"id": MANGA_ID, "title": "Naruto", "slug": "naruto", "altTitle": None,
             "description": "Dans le village caché de Konoha…", "author": "Masashi Kishimoto",
             "artist": None, "year": 1999, "genres": [], "tags": [], "viewCount": 348450,
             "favoriteCount": 28, "chapterCount": len(rows) if count is _SERVED else count,
             "coverUrl": "/api/media/thumbnail?v=3", "coverFullUrl": COVER}
    manga.update(extra)
    return {"manga": manga, "chapters": rows}


def _page(index, **extra):
    page = {"id": PAGE_IDS[index], "pageIndex": index, "url": PAGES[index], "coloredUrl": None,
            "width": 1013, "height": 1600, "coloredWidth": None, "coloredHeight": None,
            "mimeType": "image/webp"}
    page.update(extra)
    return page


def _reader(pages=_SERVED, chapter=None, manga=None):
    return {
        "chapter": chapter or {"id": CHAPTER_ID, "mangaId": MANGA_ID, "number": 700,
                               "title": "Chapitre 700", "slug": "700",
                               "publishedAt": "2026-08-22T14:48:36.850Z"},
        "manga": manga or {"id": MANGA_ID, "title": "Naruto", "slug": "naruto",
                           "coverUrl": "/api/media/thumbnail?v=3"},
        "pages": [_page(i) for i in range(3)] if pages is _SERVED else pages,
        "prev": {"id": OTHER_ID, "number": 699}, "next": None,
        "links": {"xUrl": "https://x.com/example", "discordUrl": "https://discord.com/invite/x",
                  "paypalUrl": "https://www.paypal.com/paypalme/example"},
    }


# ── Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_metadata(self):
        scraper = PunkRecordsScraper()
        assert scraper.name == "punkrecords"
        assert scraper.base_url == SITE
        assert scraper.engine == "api"
        assert scraper.content_language is None
        assert scraper.nsfw is True

    def test_no_cookie_is_kept(self):
        scraper = PunkRecordsScraper()
        cookie = create_cookie("site_session", "x", domain="punkrecordz.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_series_url(self, url):
        assert PunkRecordsScraper()._series_slug(url) == "naruto"

    @pytest.mark.parametrize("url", [
        CHAPTER,
        f"{SITE}/api/mangas/naruto",
        "http://punkrecordz.com/manga/naruto",
        "https://www.punkrecordz.com/manga/naruto",
        "https://punkrecordz.com:8443/manga/naruto",
        "https://u@punkrecordz.com/manga/naruto",
        f"{SERIES}?x=1",
        f"{SERIES}#top",
        f"{SITE}/manga/Naruto",
        f"{SITE}/manga/api",
        f"{SITE}/manga",
        "/manga/naruto",
        None,
    ])
    def test_other_series_urls_are_refused(self, url):
        with pytest.raises(PunkRecordsUnsupportedError):
            PunkRecordsScraper()._series_slug(url)

    def test_chapter_url(self):
        assert PunkRecordsScraper()._chapter_ref(CHAPTER) == ("naruto", "700")

    @pytest.mark.parametrize("url", [
        SERIES,
        f"{SITE}/manga/700",
        f"{SITE}/api/700",
        f"{SITE}/naruto/0700",
        f"{SITE}/naruto/700.5",
        f"{SITE}/naruto/abc",
        f"{SITE}/naruto/700/2",
        f"{CHAPTER}?page=2",
        f"{CHAPTER}#1",
        "https://evil.example/naruto/700",
    ])
    def test_other_chapter_urls_are_refused(self, url):
        with pytest.raises(PunkRecordsUnsupportedError):
            PunkRecordsScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_are_the_served_series(self):
        site = _site({SEARCH: dict(data=_results([_item()]))})
        assert [(m.title, m.url) for m in site.search("Naruto")] == [("Naruto", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_the_query_is_encoded_and_its_spacing_normalised(self):
        url = f"{SITE}/api/search?q=One+Piece%2F2&page=1&perPage=24"
        site = _site({url: dict(data=_results([]))})
        site.search("  One   Piece/2 ")
        assert site.session.calls[0][0] == url

    def test_a_blank_query_sends_nothing(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    def test_the_site_empty_answer_is_no_results(self):
        data = {"items": [], "total": 0, "page": 1, "perPage": 24, "totalPages": 1}
        assert _site({EMPTY: dict(data=data)}).search("zzqxjkvwpyd") == []

    @pytest.mark.parametrize("data", [
        _results([_item()], total_pages=2, total=30),
        _results([_item()], total=2),
        _results([], total_pages=0),
    ])
    def test_results_over_more_than_one_page_raise(self, data):
        with pytest.raises(PunkRecordsSourceError, match="single page"):
            _site({SEARCH: dict(data=data)}).search("Naruto")

    @pytest.mark.parametrize("extra", [{"adult": True}, {"hidden": 1}, {"isPremium": True},
                                       {"licensed": True}])
    def test_a_restricted_result_is_left_out_with_a_warning(self, extra, caplog):
        items = [_item(), _item("bleach", "Bleach", OTHER_ID, **extra)]
        site = _site({SEARCH: dict(data=_results(items))})
        with caplog.at_level(logging.WARNING, logger=pr.logger.name):
            assert [m.url for m in site.search("Naruto")] == [SERIES]
        assert "1 search result(s)" in caplog.text

    @pytest.mark.parametrize("data", [
        {}, [], {"items": None, "total": 0, "page": 1, "totalPages": 1},
        _results([_item()], page=2),
        {"items": [_item()], "page": 1, "totalPages": 1},
        _results(["x"]),
        _results([_item(slug="Naruto")]),
        _results([_item(slug="manga")]),
        _results([_item(item_id="81")]),
        _results([_item(title=" ")]),
    ])
    def test_an_unreadable_answer_raises(self, data):
        with pytest.raises(PunkRecordsSourceError):
            _site({SEARCH: dict(data=data)}).search("Naruto")

    def test_html_where_json_is_expected_raises(self):
        with pytest.raises(PunkRecordsSourceError, match="not JSON"):
            _site({SEARCH: dict(text="<html>404</html>")}).search("Naruto")

    def test_a_redirect_raises(self):
        with pytest.raises(PunkRecordsSourceError):
            _site({SEARCH: dict(status=302)}).search("Naruto")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_whole_chapters_newest_first(self):
        site = _site({SERIES_API: dict(data=_series())})
        chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == ["700", "2", "1"]
        assert chapters[0].url == CHAPTER
        assert chapters[0].title == "Chapitre 700"
        assert all(c.date is None for c in chapters)
        assert site.session.calls == [(SERIES_API, {"allow_redirects": False})]

    def test_null_genres_and_tags_are_read(self):
        site = _site({SERIES_API: dict(data=_series(genres=None, tags=None))})
        assert len(site.get_chapters(SERIES)) == 3

    @pytest.mark.parametrize("row", [
        dict(_row(5), number=5.5, slug="5.5"),
        _row(5, slug="05"),
        _row(5, slug="cinq"),
        dict(_row(5), number=True, slug="True"),
        dict(_row(5), number="5"),
        dict(_row(5), number=-1, slug="-1"),
        _row(5, id=None),
        _row(5, id="5"),
        _row(5, title=None),
        _row(5, locked=True),
        _row(5, isPremium=True),
        "not a row",
    ])
    def test_a_row_form_it_cannot_read_raises(self, row):
        site = _site({SERIES_API: dict(data=_series(rows=[_row(1), row]))})
        with pytest.raises(PunkRecordsSourceError):
            site.get_chapters(SERIES)

    @pytest.mark.parametrize("rows", [
        [_row(1), _row(1, row_id=OTHER_ID)],
        [_row(1), _row(2, row_id="00000000-0000-4000-8000-000000000001")],
    ])
    def test_a_repeated_chapter_raises(self, rows):
        with pytest.raises(PunkRecordsSourceError, match="twice"):
            _site({SERIES_API: dict(data=_series(rows=rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("count", [2, 4, None, _SERVED])
    def test_a_list_shorter_or_longer_than_its_count_raises(self, count):
        data = _series(count=count)
        if count is _SERVED:
            del data["manga"]["chapterCount"]
        with pytest.raises(PunkRecordsSourceError, match="counts"):
            _site({SERIES_API: dict(data=data)}).get_chapters(SERIES)

    @pytest.mark.parametrize("data", [
        _series(slug="bleach"),
        _series(id="81"),
        _series(title=None),
        _series(adult=True),
        _series(hidden=1),
        _series(genres=["Action", "Hentai"]),
        _series(tags=[" Mature "]),
        _series(genres="Action"),
        _series(tags=[1]),
        _series(rows=[]),
        {"chapters": [_row(1)]},
        {"manga": _series()["manga"]},
    ])
    def test_a_series_it_cannot_read_raises(self, data):
        with pytest.raises(PunkRecordsSourceError):
            _site({SERIES_API: dict(data=data)}).get_chapters(SERIES)

    def test_an_unknown_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES_API: dict(status=404)}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_plain_pages_in_page_index_order(self):
        site = _site({READER_API: dict(data=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(READER_API, {"allow_redirects": False})]

    def test_a_page_without_the_colored_key_is_read(self):
        pages = [_page(i) for i in range(3)]
        for page in pages:
            del page["coloredUrl"]
        assert _site({READER_API: dict(data=_reader(pages=pages))}).get_pages(CHAPTER) == PAGES

    def test_a_coloured_edition_raises_before_any_image(self):
        pages = [_page(0), _page(1, coloredUrl=PAGES[1].replace(".webp", "-c.webp")), _page(2)]
        site = _site({READER_API: dict(data=_reader(pages=pages))})
        with pytest.raises(PunkRecordsSourceError, match="coloured edition"):
            site.get_pages(CHAPTER)
        assert site.session.calls == [(READER_API, {"allow_redirects": False})]

    @pytest.mark.parametrize("answer", [
        _reader(manga={"id": MANGA_ID, "title": "Bleach", "slug": "bleach"}),
        _reader(manga={"id": OTHER_ID, "title": "Naruto", "slug": "naruto"}),
        _reader(chapter={"id": CHAPTER_ID, "mangaId": OTHER_ID, "number": 700, "slug": "700"}),
        _reader(chapter={"id": CHAPTER_ID, "mangaId": MANGA_ID, "number": 699, "slug": "699"}),
        _reader(chapter={"id": CHAPTER_ID, "mangaId": MANGA_ID, "number": 699, "slug": "700"}),
        _reader(chapter={"id": "700", "mangaId": MANGA_ID, "number": 700, "slug": "700"}),
        _reader(chapter={"id": CHAPTER_ID, "mangaId": MANGA_ID, "number": True, "slug": "700"}),
        _reader(chapter={"id": CHAPTER_ID, "mangaId": MANGA_ID, "number": 700, "slug": "700",
                         "locked": True}),
        _reader(manga={"id": MANGA_ID, "title": "Naruto", "slug": "naruto", "adult": True}),
        {"chapter": _reader()["chapter"], "pages": _reader()["pages"]},
        {"manga": _reader()["manga"], "pages": _reader()["pages"]},
    ])
    def test_a_reader_for_another_or_restricted_chapter_raises(self, answer):
        with pytest.raises(PunkRecordsSourceError):
            _site({READER_API: dict(data=answer)}).get_pages(CHAPTER)

    @pytest.mark.parametrize("pages, reason", [
        ([], "no page images"),
        (None, "no page images"),
        (["x"], "unreadable page"),
        ([_page(0), _page(1, pageIndex=2), _page(2)], "out of place"),
        ([_page(1, pageIndex=0)], "out of place"),
        ([_page(0, url=_page_url(0, manga_id=OTHER_ID))], "out of place"),
        ([_page(0, url=_page_url(0, chapter_id=OTHER_ID))], "out of place"),
        ([_page(0, url=_page_url(0, page_id=PAGE_IDS[1]))], "out of place"),
        ([_page(0, url=PAGES[0].replace("s3-preprod3.", "s3-prod."))], "out of place"),
        ([_page(0, url=PAGES[0].replace("https:", "http:"))], "out of place"),
        ([_page(0, url=f"{PAGES[0]}?v=1")], "out of place"),
        ([_page(0, url=PAGES[0].replace(".webp", ".png"))], "out of place"),
        ([_page(0, url=None)], "out of place"),
        ([_page(0, premium=True)], "restricted"),
        ([_page(0), _page(1, id=PAGE_IDS[0], url=_page_url(1, page_id=PAGE_IDS[0]))], "twice"),
    ])
    def test_a_page_list_it_cannot_trust_raises(self, pages, reason):
        answer = _reader(pages=pages)
        assert answer["pages"] == pages
        with pytest.raises(PunkRecordsSourceError, match=reason):
            _site({READER_API: dict(data=answer)}).get_pages(CHAPTER)

    def test_a_reader_without_its_page_list_raises(self):
        answer = _reader()
        del answer["pages"]
        with pytest.raises(PunkRecordsSourceError, match="no page images"):
            _site({READER_API: dict(data=answer)}).get_pages(CHAPTER)

    def test_no_cover_request_is_made(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "0000.webp"
        site = _site({PAGES[0]: dict(content=WEBP)})
        assert site.download_image(PAGES[0], target) is True
        assert target.read_bytes() == WEBP
        assert site.session.calls == [(PAGES[0], {
            "allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=WEBP),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "0000.webp"
        target.write_bytes(b"older")
        assert _site({PAGES[0]: answer}).download_image(PAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"{SITE}/api/media/thumbnail?v=3",
        PAGES[0].replace("s3-preprod3.", "s3-prod."),
        PAGES[0].replace("https:", "http:"),
        None,
    ])
    def test_a_url_off_the_image_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "0000.webp"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
