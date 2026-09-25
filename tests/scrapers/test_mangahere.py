"""Tests for the MangaHere scraper.

MangaHere runs the dm5 reader: the chapter HTML carries no page image,
only a loading.gif placeholder, and the real URLs arrive from
``chapterfun.ashx`` as P.A.C.K.E.R.-packed JavaScript (two pages per
call). These tests exercise the parsing layer against payloads captured
from the live site - the network helpers (``_get_html``, ``_request``,
``session.get``) are patched, never called.

Regression focus (issue #174): ``get_pages`` used to hand back reader
page URLs (``.../c001/2.html``) when it found no images, and
``download_image`` saved whatever came back - so a "downloaded" chapter
was HTML posing as JPEGs.
"""

from __future__ import annotations

import re

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.mangahere import MangaHereScraper, _unpack


MANGA_URL = "https://www.mangahere.cc/manga/one_piece_green/"
CHAPTER_URL = "https://www.mangahere.cc/manga/one_piece_green/c001/1.html"
CDN = "https://zjcdn.mangahere.org/store/manga/8602/001.0/compressed"
READER_KEY = "4e2b2e0e3bba6e00"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
BLOCK_PAGE = b"<!DOCTYPE html><html><body>Forbidden</body></html>"

# Sidebar ("hot manga") links point at chapters of OTHER series; only
# the ones under this manga's own slug may become chapters.
MANGA_HTML = (
    "<html><body>"
    '<div class="detail-main-list"><ul>'
    '<li><a href="/manga/one_piece_green/c002/1.html" title="Ch.002">Ch.002</a></li>'
    '<li><a href="/manga/one_piece_green/v01/c001/1.html" title="Ch.001">Ch.001</a></li>'
    "</ul></div>"
    '<div class="manga-list-1">'
    '<a href="/manga/the_great_mage_returns_after_4000_years/c275/1.html">Ch.275</a>'
    '<a href="/manga/battle_angel_alita/v09/c054/1.html">Ch.054</a>'
    "</div></body></html>"
)


@pytest.fixture
def mh():
    return MangaHereScraper()


@pytest.fixture
def chapter_html(load_fixture):
    """Chapter page shaped after the live reader: no image, just the
    reader variables and the packed script holding dm5_key."""
    key_js = load_fixture("mangahere", "reader_key.js")

    def _build(image_count=4):
        return (
            "<html><body>"
            '<img class="reader-main-img" '
            'src="//static.mangahere.cc/mangahere/images/loading.gif">'
            "<script>var comicid = 8602; var chapterid =122372;"
            " var imagepage=1; var imagecount=" + str(image_count) + ";</script>"
            "<script>" + key_js + "</script>"
            "</body></html>"
        )

    return _build


@pytest.fixture
def ashx(load_fixture, fake_response, monkeypatch):
    """Patch _request with a canned chapterfun.ashx, keyed by ?page=."""
    def _bind(scraper, bodies=None, boom=False):
        pages = bodies if bodies is not None else {
            1: load_fixture("mangahere", "chapterfun_page1.js"),
            3: load_fixture("mangahere", "chapterfun_page3.js"),
        }
        calls = []

        def _fake(url, **kwargs):
            calls.append((url, kwargs))
            if boom:
                raise IOError("endpoint down")
            page = int(re.search(r"page=(\d+)", url).group(1))
            return fake_response(text=pages.get(page, ""))

        monkeypatch.setattr(scraper, "_request", _fake)
        return calls

    return _bind


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("mangahere.cc")
    assert isinstance(s, MangaHereScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


# Packed-script decoding


class TestUnpack:
    def test_decodes_chapterfun_payload(self, load_fixture):
        js = _unpack(load_fixture("mangahere", "chapterfun_page1.js"))
        assert 'pix="//zjcdn.mangahere.org/store/manga/8602/001.0/compressed"' in js
        assert '"/u1.01.jpg","/u1.02.jpg"' in js

    def test_plain_script_decodes_to_empty(self):
        assert _unpack('var pvalue=["/u1.01.jpg"];') == ""


class TestReaderKey:
    def test_extracts_key_spelled_out_in_packed_script(self, chapter_html):
        assert MangaHereScraper._reader_key(chapter_html()) == READER_KEY

    def test_absent_key_is_not_fatal(self):
        assert MangaHereScraper._reader_key(
            "<html><script>var a=1;</script></html>") == ""


# get_pages


class TestGetPages:
    def test_returns_cdn_images_in_page_order(self, mh, patch_html,
                                               chapter_html, ashx):
        patch_html(mh, chapter_html())
        ashx(mh)
        assert mh.get_pages(CHAPTER_URL) == [
            CDN + "/u1.01.jpg", CDN + "/u1.02.jpg",
            CDN + "/u1.03.jpg", CDN + "/u1.04.jpg",
        ]

    def test_never_returns_reader_page_urls(self, mh, patch_html,
                                             chapter_html, ashx):
        # Issue #174: reader .html URLs were downloaded as if they were
        # images, filling the archive with markup.
        patch_html(mh, chapter_html())
        ashx(mh)
        pages = mh.get_pages(CHAPTER_URL)
        assert pages
        assert not any(p.endswith(".html") for p in pages)
        assert all(p.startswith("https://zjcdn.mangahere.org/") for p in pages)

    def test_requests_carry_chapter_id_key_and_referer(self, mh, patch_html,
                                                        chapter_html, ashx):
        patch_html(mh, chapter_html())
        calls = ashx(mh)
        mh.get_pages(CHAPTER_URL)
        url, kwargs = calls[0]
        assert url.startswith("https://www.mangahere.cc/manga/"
                               "one_piece_green/c001/chapterfun.ashx")
        assert "cid=122372" in url and "page=1" in url
        assert "key=" + READER_KEY in url
        assert kwargs["headers"]["Referer"] == CHAPTER_URL
        # Two images per call: 4 pages means calls for page 1 and page 3.
        assert [re.search(r"page=(\d+)", u).group(1) for u, _ in calls] == ["1", "3"]

    def test_directory_style_chapter_url_hits_the_same_endpoint(
            self, mh, patch_html, chapter_html, ashx):
        patch_html(mh, chapter_html())
        calls = ashx(mh)
        mh.get_pages("https://www.mangahere.cc/manga/one_piece_green/c001/")
        assert calls[0][0].startswith("https://www.mangahere.cc/manga/"
                                       "one_piece_green/c001/chapterfun.ashx")

    def test_trims_to_imagecount(self, mh, patch_html, chapter_html, ashx):
        patch_html(mh, chapter_html(image_count=3))
        ashx(mh)
        assert mh.get_pages(CHAPTER_URL) == [
            CDN + "/u1.01.jpg", CDN + "/u1.02.jpg", CDN + "/u1.03.jpg",
        ]

    def test_stops_when_endpoint_repeats_itself(self, mh, patch_html,
                                                 chapter_html, ashx,
                                                 load_fixture):
        repeat = load_fixture("mangahere", "chapterfun_page1.js")
        patch_html(mh, chapter_html(image_count=40))
        calls = ashx(mh, bodies={1: repeat, 3: repeat})
        assert mh.get_pages(CHAPTER_URL) == [CDN + "/u1.01.jpg", CDN + "/u1.02.jpg"]
        assert len(calls) == 2

    def test_missing_chapter_id_returns_no_pages(self, mh, patch_html, ashx):
        patch_html(mh, "<html><body>nothing to read here</body></html>")
        calls = ashx(mh)
        assert mh.get_pages(CHAPTER_URL) == []
        assert calls == []

    def test_endpoint_failure_returns_no_pages(self, mh, patch_html,
                                                chapter_html, ashx):
        patch_html(mh, chapter_html())
        ashx(mh, boom=True)
        assert mh.get_pages(CHAPTER_URL) == []

    def test_unreachable_chapter_returns_no_pages(self, mh, monkeypatch):
        def _boom(*a, **k):
            raise IOError("offline")
        monkeypatch.setattr(mh, "_get_html", _boom)
        assert mh.get_pages(CHAPTER_URL) == []


# get_chapters


class TestGetChapters:
    def test_ignores_chapters_of_other_series(self, mh, patch_html):
        patch_html(mh, MANGA_HTML)
        chapters = mh.get_chapters(MANGA_URL)
        assert [c.number for c in chapters] == ["002", "001"]
        assert all("/manga/one_piece_green/" in c.url for c in chapters)

    def test_keeps_volume_scoped_chapters(self, mh, patch_html):
        patch_html(mh, MANGA_HTML)
        urls = [c.url for c in mh.get_chapters(MANGA_URL)]
        assert MANGA_URL + "v01/c001/1.html" in urls

    @pytest.mark.parametrize("url,expected", [
        (MANGA_URL, "/manga/one_piece_green"),
        (CHAPTER_URL, "/manga/one_piece_green"),
        ("/manga/battle_angel_alita/v09/c054/1.html", "/manga/battle_angel_alita"),
        # No trailing slash / query / fragment: all still name the manga,
        # so sidebar filtering must stay switched on for them.
        ("https://www.mangahere.cc/manga/one_piece_green",
         "/manga/one_piece_green"),
        ("https://www.mangahere.cc/manga/one_piece_green?waring=1",
         "/manga/one_piece_green"),
        ("https://www.mangahere.cc/manga/one_piece_green#chapters",
         "/manga/one_piece_green"),
        ("https://www.mangahere.cc/latest/", ""),
        ("https://www.mangahere.cc/manga/", ""),
    ])
    def test_manga_path(self, url, expected):
        assert MangaHereScraper._manga_path(url) == expected

    def test_filters_sidebar_for_slug_without_trailing_slash(self, mh,
                                                             patch_html):
        # A manga URL with no trailing slash used to yield an empty
        # prefix, which turned the sidebar filter off entirely.
        patch_html(mh, MANGA_HTML)
        chapters = mh.get_chapters("https://www.mangahere.cc/manga/one_piece_green")
        assert [c.number for c in chapters] == ["002", "001"]


# download_image


class TestDownloadImage:
    def _patch_session(self, mh, monkeypatch, fake_response, *, content,
                        content_type, status=200):
        seen = dict()

        def _fake_get(url, headers=None, **kwargs):
            seen["url"] = url
            seen["headers"] = headers or dict()
            return fake_response(content=content, status=status,
                                  headers={"Content-Type": content_type})

        monkeypatch.setattr(mh.session, "get", _fake_get)
        return seen

    def test_writes_image_and_sends_referer(self, mh, monkeypatch, tmp_path,
                                             fake_response):
        seen = self._patch_session(mh, monkeypatch, fake_response,
                                    content=JPEG, content_type="image/jpeg")
        path = tmp_path / "sub" / "page.jpg"
        assert mh.download_image(CDN + "/u1.01.jpg", path) is True
        assert path.read_bytes() == JPEG
        assert seen["headers"]["Referer"] == "https://www.mangahere.cc/"

    def test_refuses_to_save_html_block_page(self, mh, monkeypatch, tmp_path,
                                              fake_response):
        # Issue #174: the CDN answers a request without the site Referer
        # with a block page; writing it produced an archive full of markup.
        self._patch_session(mh, monkeypatch, fake_response, content=BLOCK_PAGE,
                             content_type="text/html; charset=UTF-8")
        path = tmp_path / "page.jpg"
        assert mh.download_image(CDN + "/u1.01.jpg", path) is False
        assert not path.exists()

    def test_http_error_returns_false(self, mh, monkeypatch, tmp_path,
                                       fake_response):
        self._patch_session(mh, monkeypatch, fake_response, content=BLOCK_PAGE,
                             content_type="text/html", status=403)
        path = tmp_path / "page.jpg"
        assert mh.download_image(CDN + "/u1.01.jpg", path) is False
        assert not path.exists()
