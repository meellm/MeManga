"""Offline tests for OnePieceTubeScraper (onepiece.tube).

Every page here is a synthetic fixture and no request leaves the test.
Field shapes follow what the site's list and reader pages serve.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import requests
from PIL import Image

from memanga.downloader.formats.cbz import _manga_language
from memanga.scrapers import onepiecetube
from memanga.scrapers.onepiecetube import (
    OnePieceTubeScraper, OnePieceTubeSourceError, chapter_number, page_data)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"OnePieceTubeScraper": ("search", "chapters", "pages")}

BASE = "https://onepiece.tube"
LIST_URL = f"{BASE}/manga/kapitel-mangaliste"
MENU_URL = f"{BASE}/manga/spin-off-mangaliste"
CHAPTER_URL = f"{BASE}/manga/kapitel/1199/1"
MENU = [("Anime Comics", "anime-comic"), ("Artbooks", "artbook"),
        ("Cover-Stories", "cover-story"), ("Databooks", "databook"),
        ("Light Novels", "light-novel"), ("Manga Kapitel", "kapitel"), ("Omakes", "omake"),
        ("One Shots", "one-shot"), ("Sonderausgaben", "special"), ("Spin-Off's", "spin-off")]


def _row(number=1199, available=True, **changes):
    row = {"arc_id": 80, "category_id": 3, "date": "19.11.2026",
           "href": f"{BASE}/manga/kapitel/{number}/1", "id": number + 100,
           "is_available": available, "lang": "ger", "name": f"Kapitel {number}",
           "number": number, "pages": 12, "specials_id": 0}
    row.update(changes)
    return row


def _html(data):
    return ("<html><body><script>var other = 1;</script>"
            f"<script>window.__data = {json.dumps(data, ensure_ascii=False)};</script>"
            "</body></html>")


def _list(rows):
    return _html({"options": {}, "category": {"description": "x"},
                  "specials": [{"id": 22, "name": "One Piece Party"},
                               {"id": 23, "name": "Chopperman "}],
                  "arcs": [], "entries": rows})


def _image(name, ext="png", kind="image/png", width=1100, height=1606):
    return {"url": f"{BASE}/images/manga/kapitel/abcdefghi/{name}.{ext}", "type": kind,
            "width": width, "height": height}


def _reader(pages):
    return {"chapter": {"name": "Kapitel 1199", "pages": pages}, "currentPage": "1",
            "currentChapter": "1199", "currentChapterId": 1299, "currentChapterFormat": "x",
            "categoryEntries": [], "nextChapter": None, "prevChapter": "1198",
            "categoryHome": {}, "categoryLink": "x", "breadcrumbs": []}


def _menu(items=None):
    links = "".join(f'<a class="dropdown-item" href="{BASE}/manga/{slug}-mangaliste">{text}</a>'
                    for text, slug in (MENU if items is None else items))
    return f"<html><body><nav>{links}</nav></body></html>"


def _png():
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 12), (10, 20, 30, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Reply:
    def __init__(self, text="", status=200, content=b"", headers=None):
        self.text = text
        self.status_code = status
        self.headers = headers or {}
        self._content = content
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def close(self):
        self.closed = True


@pytest.fixture
def scraper():
    return OnePieceTubeScraper()


@pytest.fixture
def site(monkeypatch, scraper):
    """Serves replies by exact URL and records every request."""
    served, calls = {}, []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        if url not in served:
            raise AssertionError(f"unexpected request {url}")
        reply = served[url]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_request", fake_request)
    return served, calls


def _http_error(status):
    return requests.HTTPError(f"{status} error", response=_Reply(status=status))


# ── Page data ─────────────────────────────────────────────────────────


class TestPageData:
    @pytest.mark.parametrize("script", [
        'window.__data = {"a": 1};', 'window.__data={"a": 1}', '  window.__data  =  {"a": 1} ;  ',
    ])
    def test_a_strict_json_assignment(self, script):
        assert page_data(f"<script>{script}</script>") == {"a": 1}

    @pytest.mark.parametrize("html", ["", "<html></html>", "<script>var a = 1;</script>"])
    def test_a_page_without_data_is_none(self, html):
        assert page_data(html) is None

    @pytest.mark.parametrize("script", [
        "window.__data = {a: 1};", "window.__data = {'a': 1};", 'window.__data = {"a": NaN};',
        'window.__data = {"a": Infinity};', "window.__data = load();", "window.__data = [1];",
        "window.__data = 1;", 'window.__data = {"a": 1}; run();', 'window.__data = {"a": 1',
        'window.__data {"a": 1};', "window.__data",
    ])
    def test_anything_else_raises_and_nothing_runs(self, script):
        with pytest.raises(OnePieceTubeSourceError):
            page_data(f"<script>{script}</script>")

    def test_two_data_scripts_raise(self):
        script = '<script>window.__data = {"a": 1};</script>'
        with pytest.raises(OnePieceTubeSourceError, match="more than one"):
            page_data(script + script)


# ── URLs ──────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("url, number", [
        (CHAPTER_URL, 1199), (f"{BASE}/manga/kapitel/1/1", 1), (f"{BASE}/manga/kapitel/99/1", 99)])
    def test_a_chapter_url(self, url, number):
        assert chapter_number(url) == number

    @pytest.mark.parametrize("url", [
        "http://onepiece.tube/manga/kapitel/1199/1",
        "https://www.onepiece.tube/manga/kapitel/1199/1",
        "https://onepiece-tube.com/manga/kapitel/1199/1",
        "https://onepiece.tube:8443/manga/kapitel/1199/1",
        "https://user@onepiece.tube/manga/kapitel/1199/1",
        f"{CHAPTER_URL}?x=1", f"{CHAPTER_URL}#x", f"{CHAPTER_URL}/",
        f"{BASE}/manga/kapitel/1199/2", f"{BASE}/manga/kapitel/1199",
        f"{BASE}/manga/kapitel/0/1", f"{BASE}/manga/kapitel/01/1", f"{BASE}/manga/kapitel/x/1",
        f"{BASE}/manga/spin-off/party/1/1", LIST_URL, "", None, 7,
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_number(url)


# ── Search ────────────────────────────────────────────────────────────


class TestSearch:
    @pytest.mark.parametrize("query", [
        "One Piece", "one piece", "ONE   PIECE", "one-piece", "ＯＮＥ ＰＩＥＣＥ", "piece", "one"])
    def test_the_series_is_found_through_the_sites_menu(self, scraper, site, query):
        served, calls = site
        served[MENU_URL] = _Reply(_menu())
        found = scraper.search(query)
        assert [(m.title, m.url) for m in found] == [("One Piece [DE]", LIST_URL)]
        assert [c[0] for c in calls] == [MENU_URL]
        assert calls[0][1]["allow_redirects"] is False

    @pytest.mark.parametrize("query", [
        "Naruto", "piece one", "one piece party", "someone", "ワンピース", "", "   ", "!!!"])
    def test_any_other_query_is_empty_without_a_request(self, scraper, site, query):
        _, calls = site
        assert scraper.search(query) == []
        assert calls == []

    @pytest.mark.parametrize("reply", [
        _Reply(_menu([("Artbooks", "artbook")])),
        _Reply(_menu([("Manga Kapitel", "kapitel"), ("Manga Kapitel", "other")])),
        _Reply(_menu([("Manga Kapitel", "other")])),
        _Reply('<a class="dropdown-item" href="https://evil.example/manga/kapitel-mangaliste">'
               "Manga Kapitel</a>"),
        _Reply("<html></html>"),
        _Reply(status=302), _http_error(403), requests.ConnectionError("reset"),
        _Reply(_menu(), headers={"cf-mitigated": "challenge"}),
    ], ids=["no-item", "two-links", "other-link", "off-host", "no-menu", "redirect", "403",
            "transport", "challenge"])
    def test_a_menu_that_does_not_name_the_list_raises(self, scraper, site, reply):
        served, _ = site
        served[MENU_URL] = reply
        with pytest.raises(OnePieceTubeSourceError):
            scraper.search("One Piece")


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _chapters_from(self, scraper, site, rows):
        served, _ = site
        served[LIST_URL] = _Reply(_list(rows))
        return scraper.get_chapters(LIST_URL)

    def test_only_available_entries_are_listed_in_number_order(self, scraper, site):
        rows = [_row(1199, date="19.11.2026"), _row(420), _row(419, available=False), _row(1)]
        chapters = self._chapters_from(scraper, site, rows)
        assert [c.number for c in chapters] == ["1", "420", "1199"]
        assert chapters[2].url == CHAPTER_URL
        assert chapters[2].title == "Kapitel 1199"
        assert chapters[2].date == "2026-11-19"

    def test_the_served_link_is_kept(self, scraper, site):
        chapters = self._chapters_from(scraper, site, [_row(7)])
        assert chapters[0].url == f"{BASE}/manga/kapitel/7/1"

    def test_an_entry_in_another_language_is_not_listed(self, scraper, site):
        chapters = self._chapters_from(scraper, site, [_row(2), _row(3, lang="eng"), _row(4, lang="jp")])
        assert [c.number for c in chapters] == ["2"]

    def test_a_placeholder_name_is_no_title(self, scraper, site):
        assert self._chapters_from(scraper, site, [_row(5, name="-")])[0].title is None

    @pytest.mark.parametrize("served_date", ["00.00.0000", "31.02.2020", "01.13.2020"])
    def test_a_value_that_is_no_calendar_date_gives_no_date(self, scraper, site, served_date):
        assert self._chapters_from(scraper, site, [_row(5, date=served_date)])[0].date is None

    @pytest.mark.parametrize("change", [
        {"id": None}, {"id": True}, {"id": 0}, {"id": "5"},
        {"number": None}, {"number": True}, {"number": 0}, {"number": "1199"}, {"number": 1.5},
        {"is_available": None}, {"is_available": 1}, {"is_available": "true"},
        {"lang": None}, {"lang": ""}, {"lang": 1},
        {"name": None}, {"name": "  "}, {"name": 7},
        {"category_id": 4}, {"category_id": None}, {"category_id": "3"},
        {"specials_id": 22}, {"specials_id": None}, {"specials_id": False},
        {"href": None}, {"href": ""}, {"href": "/manga/kapitel/1199/1"},
        {"href": "http://onepiece.tube/manga/kapitel/1199/1"},
        {"href": "https://evil.example/manga/kapitel/1199/1"},
        {"href": "https://onepiece-tube.com/manga/kapitel/1199/1"},
        {"href": f"{BASE}/manga/kapitel/1199/2"}, {"href": f"{BASE}/manga/kapitel/1198/1"},
        {"date": None}, {"date": ""}, {"date": "2026-11-19"}, {"date": "19.11.26"}, {"date": 7},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_an_entry_with_an_unusable_field_raises(self, scraper, site, change):
        row = _row()
        row.update(change)
        with pytest.raises(OnePieceTubeSourceError):
            self._chapters_from(scraper, site, [_row(1), row])

    def test_an_unavailable_entry_is_still_checked(self, scraper, site):
        with pytest.raises(OnePieceTubeSourceError):
            self._chapters_from(scraper, site, [_row(1), _row(2, available=False, href="https://x.example/")])

    def test_a_row_that_is_not_an_object_raises(self, scraper, site):
        with pytest.raises(OnePieceTubeSourceError):
            self._chapters_from(scraper, site, [_row(1), "x"])

    def test_a_repeated_id_raises(self, scraper, site):
        with pytest.raises(OnePieceTubeSourceError, match="id is listed twice"):
            self._chapters_from(scraper, site, [_row(1, id=5), _row(2, id=5)])

    @pytest.mark.parametrize("second_available", [True, False])
    def test_a_repeated_number_raises(self, scraper, site, second_available):
        rows = [_row(3, id=5), _row(3, available=second_available, id=6)]
        with pytest.raises(OnePieceTubeSourceError, match="number is listed twice"):
            self._chapters_from(scraper, site, rows)

    def test_an_empty_list_raises(self, scraper, site):
        with pytest.raises(OnePieceTubeSourceError, match="no entries"):
            self._chapters_from(scraper, site, [])

    def test_a_list_with_nothing_available_raises(self, scraper, site):
        with pytest.raises(OnePieceTubeSourceError, match="no German chapter"):
            self._chapters_from(scraper, site, [_row(1, available=False), _row(2, lang="eng")])

    @pytest.mark.parametrize("reply", [
        _Reply("<html></html>"), _Reply(_html({"entries": {}})), _Reply(_html({})),
        _Reply('<script>window.__data = {bad};</script>'), _Reply(status=301), _http_error(404),
        requests.Timeout("slow"), _Reply(_list([_row()]), headers={"cf-mitigated": "challenge"}),
    ], ids=["no-data", "entries-object", "no-entries", "bad-json", "redirect", "404", "timeout",
            "challenge"])
    def test_a_failed_list_raises(self, scraper, site, reply):
        served, _ = site
        served[LIST_URL] = reply
        with pytest.raises(OnePieceTubeSourceError):
            scraper.get_chapters(LIST_URL)

    @pytest.mark.parametrize("url", [
        MENU_URL, f"{BASE}/manga/one-shot-mangaliste", CHAPTER_URL,
        "https://onepiece-tube.com/manga/kapitel-mangaliste", f"{LIST_URL}?x=1"])
    def test_any_other_url_sends_nothing(self, scraper, site, url):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_chapters(url)
        assert calls == []

    def test_a_trailing_slash_reads_the_same_list(self, scraper, site):
        served, calls = site
        served[LIST_URL] = _Reply(_list([_row(1)]))
        assert len(scraper.get_chapters(f"{LIST_URL}/")) == 1
        assert [c[0] for c in calls] == [LIST_URL]
        assert calls[0][1]["allow_redirects"] is False

    def test_the_listing_logs_its_scope(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.onepiecetube")
        self._chapters_from(scraper, site, [_row(1), _row(2, available=False)])
        assert "listing 1 of the 2 chapter(s)" in caplog.text
        assert "available in German" in caplog.text


def test_the_site_has_no_covers(scraper, site):
    _, calls = site
    assert scraper.get_cover_url(LIST_URL) is None
    assert calls == []


# ── Pages ─────────────────────────────────────────────────────────────


class TestPages:
    def test_pages_keep_the_served_order(self, scraper, site):
        served, calls = site
        pages = [_image("10"), _image("02"), _image("k3x9q", "jpg", "image/jpeg", 3288, 2400),
                 _image("01")]
        served[CHAPTER_URL] = _Reply(_html(_reader(pages)))
        assert scraper.get_pages(CHAPTER_URL) == [page["url"] for page in pages]
        assert [c[0] for c in calls] == [CHAPTER_URL]
        assert calls[0][1]["allow_redirects"] is False

    def test_all_twelve_pages_are_returned(self, scraper, site):
        served, _ = site
        pages = [_image(f"{n:02d}") for n in range(1, 13)]
        served[CHAPTER_URL] = _Reply(_html(_reader(pages)))
        assert len(scraper.get_pages(CHAPTER_URL)) == 12

    def test_a_stub_page_without_data_is_not_available(self, scraper, site):
        served, _ = site
        url = f"{BASE}/manga/kapitel/419/1"
        served[url] = _Reply("<html><body>Nicht verfügbar</body></html>")
        with pytest.raises(OnePieceTubeSourceError, match="chapter 419 is not available"):
            scraper.get_pages(url)

    @pytest.mark.parametrize("data, why", [
        ({"chapter": None}, "no page list"), ({"chapter": []}, "no page list"),
        ({"chapter": {"name": "x"}}, "no page list"), ({"chapter": {"pages": {}}}, "no page list"),
        ({"chapter": {"pages": []}}, "no pages"), ({}, "no page list"),
    ], ids=["null-chapter", "list-chapter", "no-pages-key", "pages-object", "empty", "no-chapter"])
    def test_a_reader_without_pages_raises(self, scraper, site, data, why):
        served, _ = site
        served[CHAPTER_URL] = _Reply(_html(data))
        with pytest.raises(OnePieceTubeSourceError, match=why):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        "x", None, {}, {"url": None}, {"url": 7}, {"url": ""}, {"url": "/images/1.png"},
        {"url": "http://onepiece.tube/images/1.png"},
        {"url": "https://evil.example/images/1.png"},
        {"url": "https://onepiece.tube.evil.example/images/1.png"},
        {"url": "https://www.onepiece.tube/images/1.png"},
        {"url": "https://onepiece-tube.com/images/1.png"},
        {"url": "https://onepiece.tube:8443/images/1.png"},
        {"url": "https://user@onepiece.tube/images/1.png"},
        {"url": "https://ONEPIECE.TUBE/images/1.png"},
        {"url": "https://onepiece.tube/images/1.png?sig=1"},
        {"url": "https://onepiece.tube/images/1.png#x"},
        {"url": "https://onepiece.tube/images/../1.png"},
        {"url": "https://onepiece.tube/images/"}, {"url": "https://onepiece.tube"},
        {"url": "https://onepiece.tube/images/a b.png"},
        {"url": "https://onepiece.tube\\@evil.example/1.png"},
    ])
    def test_an_unusable_page_raises(self, scraper, site, bad):
        served, _ = site
        served[CHAPTER_URL] = _Reply(_html(_reader([_image("01"), bad])))
        with pytest.raises(OnePieceTubeSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_a_repeated_page_raises(self, scraper, site):
        served, _ = site
        served[CHAPTER_URL] = _Reply(_html(_reader([_image("01"), _image("02"), _image("01")])))
        with pytest.raises(OnePieceTubeSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _Reply('<script>window.__data = {bad};</script>'), _http_error(403),
        requests.ConnectionError("reset"),
        _Reply(_html(_reader([_image("01")])), headers={"cf-mitigated": "challenge"}),
    ], ids=["redirect", "bad-json", "403", "transport", "challenge"])
    def test_a_failed_reader_raises(self, scraper, site, reply):
        served, _ = site
        served[CHAPTER_URL] = reply
        with pytest.raises(OnePieceTubeSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_a_url_that_is_not_a_chapter_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_pages(LIST_URL)
        assert calls == []


# ── Images ────────────────────────────────────────────────────────────


IMAGE_URL = f"{BASE}/images/manga/kapitel/abcdefghi/01.png"


class TestDownloadImage:
    def test_the_bytes_are_saved_as_served(self, scraper, site, tmp_path):
        served, calls = site
        picture = _png()
        reply = _Reply(content=picture)
        served[IMAGE_URL] = reply
        path = tmp_path / "out" / "001.png"
        assert scraper.download_image(IMAGE_URL, path) is True
        assert path.read_bytes() == picture
        kwargs = calls[0][1]
        assert kwargs["headers"]["Referer"] == f"{BASE}/"
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        assert reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(content=b"<html>blocked</html>"), _Reply(content=b""), _Reply(status=302),
        _Reply(status=206, content=b"partial"), _http_error(403), _http_error(503),
        requests.ConnectionError("reset"), requests.exceptions.ChunkedEncodingError("cut"),
    ], ids=["html", "empty", "redirect", "partial", "403", "503", "transport", "cut"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        served, _ = site
        served[IMAGE_URL] = reply
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(IMAGE_URL, path) is False
        assert not path.exists()

    def test_a_body_that_breaks_while_streaming_fails(self, scraper, site, tmp_path):
        served, _ = site

        class _Broken(_Reply):
            def iter_content(self, size):
                yield _png()[:4]
                raise requests.exceptions.ChunkedEncodingError("cut")

        reply = _Broken()
        served[IMAGE_URL] = reply
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(IMAGE_URL, path) is False
        assert not path.exists() and reply.closed

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        served, _ = site
        monkeypatch.setattr(onepiecetube, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(content=_png())
        served[IMAGE_URL] = reply
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(IMAGE_URL, path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        "https://evil.example/images/1.png", "http://onepiece.tube/images/1.png",
        "https://onepiece.tube/images/1.png?x=1", "https://onepiece-tube.com/images/1.png"])
    def test_an_off_host_page_fails_without_a_request(self, scraper, site, tmp_path, url):
        _, calls = site
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(url, path) is False
        assert calls == [] and not path.exists()


def test_source_metadata():
    assert OnePieceTubeScraper.name == "onepiecetube"
    assert OnePieceTubeScraper.base_url == BASE
    assert OnePieceTubeScraper.engine == "http"
    assert OnePieceTubeScraper.content_language == "de"
    assert OnePieceTubeScraper.nsfw is False
    assert OnePieceTubeScraper.reading_direction is None
    assert _manga_language({"title": "One Piece [DE]"}, OnePieceTubeScraper()) == "de"
