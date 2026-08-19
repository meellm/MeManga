"""Tests for the MangaTaro scraper.

MangaTaro's reader is JS-driven: the ordered page list comes from a JSON
endpoint (``/auth/chapter-content?chapter_id=<id>``) rather than the static
HTML, which only carries the first page. These tests exercise the pure
parsing/URL layer with payloads shaped after the live responses - the
network-facing helpers (``_get_json`` / ``_get_html`` / ``session.get``) are
patched, never called.

Regression focus (issue #152): ``get_pages`` used to rewrite every CDN host
to a stale ``bx1.mangapeak.me`` and enumerate by HEAD, which returned 0 pages
against the current site. It must now use the API host verbatim.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.mangataro import MangaTaroScraper


CHAPTER_URL = "https://mangataro.org/read/koi-to-yobu-ni-wa-kimochi-warui/ch1-547229"

# Shaped after the live /auth/chapter-content response: absolute CDN URLs
# on a host that is NOT the site domain and NOT the old mangapeak CDN.
API_PAYLOAD = {
    "success": True,
    "chapter_id": 547229,
    "chapter_type": "media",
    "images": [
        "https://mangataro.yachts/storage/chapters/7689b1e6b813f55210c2eb9d714eddea/001.webp",
        "https://mangataro.yachts/storage/chapters/7689b1e6b813f55210c2eb9d714eddea/002.webp",
        "https://mangataro.yachts/storage/chapters/7689b1e6b813f55210c2eb9d714eddea/003.webp",
    ],
    "total": 3,
}


@pytest.fixture
def mt():
    return MangaTaroScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("mangataro.org")
    assert isinstance(s, MangaTaroScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))

    # The stale, hard-coded CDN that broke page extraction is gone.
    assert not hasattr(MangaTaroScraper, "cdn_base")


# URL / id helpers


class TestChapterId:
    def test_extract_from_reader_url(self):
        assert MangaTaroScraper._extract_chapter_id(CHAPTER_URL) == "547229"

    def test_extract_decimal_chapter_with_query(self):
        url = "https://mangataro.org/read/x/ch10.5-999888?page=2#top"
        assert MangaTaroScraper._extract_chapter_id(url) == "999888"

    def test_extract_dashed_point_chapter(self):
        # Live URLs encode e.g. chapter 56.5 as "ch56-5-<id>"; the id is the
        # final numeric segment, not the "5" in the number.
        url = "https://mangataro.org/read/koi-to-yobu-ni-wa-kimochi-warui/ch56-5-547486"
        assert MangaTaroScraper._extract_chapter_id(url) == "547486"

    def test_extract_missing_returns_none(self):
        assert MangaTaroScraper._extract_chapter_id(
            "https://mangataro.org/manga/koi-to-yobu") is None
        assert MangaTaroScraper._extract_chapter_id("") is None

    def test_recover_id_from_body_markup(self):
        html = '<body data-chapter-id="547229" data-manga-id="547225">x</body>'
        assert MangaTaroScraper._chapter_id_from_html(html) == "547229"

    def test_recover_id_from_markup_missing(self):
        assert MangaTaroScraper._chapter_id_from_html("<body></body>") is None


class TestPageNumber:
    def test_zero_padded(self):
        assert MangaTaroScraper._page_number("https://h/storage/chapters/ab/007.webp") == 7

    def test_with_query(self):
        assert MangaTaroScraper._page_number("https://h/storage/chapters/ab/012.jpg?v=1") == 12

    def test_unparseable(self):
        assert MangaTaroScraper._page_number("https://h/no-page-here") == 0


# Pages via the API (the fix)


class TestPagesFromApi:
    def test_returns_urls_verbatim_in_order(self, mt):
        assert mt._pages_from_api_payload(API_PAYLOAD) == API_PAYLOAD["images"]

    def test_deduplicates_preserving_order(self, mt):
        payload = {
            "success": True,
            "images": [
                "https://mangataro.yachts/storage/chapters/ab/001.webp",
                "https://mangataro.yachts/storage/chapters/ab/002.webp",
                "https://mangataro.yachts/storage/chapters/ab/001.webp",  # dup
            ],
        }
        assert mt._pages_from_api_payload(payload) == [
            "https://mangataro.yachts/storage/chapters/ab/001.webp",
            "https://mangataro.yachts/storage/chapters/ab/002.webp",
        ]

    @pytest.mark.parametrize("payload", [
        {"success": False, "images": ["https://x/storage/chapters/ab/001.webp"]},
        {"success": True},                       # no images key
        {"success": True, "images": "nope"},     # images not a list
        {"success": True, "images": []},         # text/empty chapter
        {},
        None,
        "garbage",
    ])
    def test_bad_payloads_return_empty(self, mt, payload):
        assert mt._pages_from_api_payload(payload) == []

    def test_get_pages_calls_api_with_correct_id_no_rewrite(self, monkeypatch, mt):
        captured = {}

        def fake_get_json(url, *a, **k):
            captured["url"] = url
            captured["headers"] = k.get("headers")
            return API_PAYLOAD

        # If the API path works, the HTML fallback must never run.
        def boom_html(url, *a, **k):
            raise AssertionError("HTML fallback should not be reached")

        monkeypatch.setattr(mt, "_get_json", fake_get_json)
        monkeypatch.setattr(mt, "_get_html", boom_html)

        pages = mt.get_pages(CHAPTER_URL)

        assert "/auth/chapter-content?chapter_id=547229" in captured["url"]
        assert captured["url"].startswith("https://mangataro.org/")
        # URLs are returned exactly as served - no host rewriting.
        assert pages == API_PAYLOAD["images"]
        assert all(p.startswith("https://mangataro.yachts/") for p in pages)
        # The bug: everything got rewritten to the dead mangapeak CDN.
        assert not any("mangapeak" in p for p in pages)


# Fallback: reader HTML when the API yields nothing


FALLBACK_HTML = """
<html><head>
<meta property='og:image' content='https://mangataro.yachts/storage/chapters/abcdef/001.webp'>
<script type="application/ld+json">
{"@type":"ListItem","image":"https://mangataro.org/storage/chapters/abcdef/001.webp"}
</script>
</head><body data-chapter-id="547229">
<img src="https://mangataro.yachts/storage/chapters/abcdef/002.webp">
<img src="https://mangataro.yachts/storage/chapters/abcdef/003.webp">
</body></html>
"""


class TestPagesFromHtmlFallback:
    def test_prefers_cdn_host_and_orders(self, mt):
        pages = mt._pages_from_html(FALLBACK_HTML)
        # page 001 appears on both the (404-ing) site domain and the CDN;
        # the CDN host wins, and pages come out in numeric order.
        assert pages == [
            "https://mangataro.yachts/storage/chapters/abcdef/001.webp",
            "https://mangataro.yachts/storage/chapters/abcdef/002.webp",
            "https://mangataro.yachts/storage/chapters/abcdef/003.webp",
        ]
        assert not any("mangapeak" in p for p in pages)

    def test_get_pages_falls_back_when_api_empty(self, monkeypatch, mt):
        monkeypatch.setattr(mt, "_get_json", lambda *a, **k: {"success": False})
        monkeypatch.setattr(mt, "_get_html", lambda url, *a, **k: FALLBACK_HTML)

        pages = mt.get_pages(CHAPTER_URL)
        assert pages[0] == "https://mangataro.yachts/storage/chapters/abcdef/001.webp"
        assert len(pages) == 3

    def test_get_pages_recovers_id_from_html_then_uses_api(self, monkeypatch, mt):
        calls = []

        def fake_get_json(url, *a, **k):
            calls.append(url)
            if "chapter_id=547229" in url:
                return API_PAYLOAD
            return {"success": False}

        # URL has no /chN-<id> segment, so the id must come from the markup.
        monkeypatch.setattr(mt, "_get_json", fake_get_json)
        monkeypatch.setattr(mt, "_get_html",
                            lambda url, *a, **k: '<body data-chapter-id="547229"></body>')

        pages = mt.get_pages("https://mangataro.org/read/no-id-here/")
        assert pages == API_PAYLOAD["images"]
        assert any("chapter_id=547229" in u for u in calls)

    def test_get_pages_empty_when_nothing_anywhere(self, monkeypatch, mt):
        monkeypatch.setattr(mt, "_get_json", lambda *a, **k: {"success": False})
        monkeypatch.setattr(mt, "_get_html", lambda url, *a, **k: "<html></html>")
        assert mt.get_pages(CHAPTER_URL) == []


# Adjacent flow: chapter discovery (guards the reader dropdown parse)


MANGA_HTML = """
<html><body>
<a href="/read/koi-to-yobu-ni-wa-kimochi-warui/ch1-547229">Read Chapter 1</a>
</body></html>
"""

READER_HTML = """
<html><body>
<select class="chapter-select">
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch1-547229">Chapter 1</option>
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch2-547233">Chapter 2</option>
</select>
</body></html>
"""

# Live site encodes decimal chapters with a dash in the URL (ch7-5-<id> ==
# chapter 7.5) while the option text shows a clean "Ch. 7.5".
READER_HTML_DECIMAL = """
<html><body>
<select class="chapter-select">
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch7-547252">Ch. 7</option>
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch7-5-547254">Ch. 7.5</option>
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch14-5-547286">Ch. 14.5</option>
  <option value="/read/koi-to-yobu-ni-wa-kimochi-warui/ch56-5-547486">Ch. 56.5</option>
</select>
</body></html>
"""

# Fallback path: bare chapter links on the manga page. Text here has no
# decimal, so the number must come from the dashed-decimal URL shape.
MANGA_HTML_DECIMAL = """
<html><body>
<a href="/read/koi-to-yobu-ni-wa-kimochi-warui/ch7-547252">Read</a>
<a href="/read/koi-to-yobu-ni-wa-kimochi-warui/ch7-5-547254">Read</a>
<a href="/read/koi-to-yobu-ni-wa-kimochi-warui/ch14-5-547286">Read</a>
<a href="/read/koi-to-yobu-ni-wa-kimochi-warui/ch56-5-547486">Read</a>
</body></html>
"""


class TestChapterNumber:
    @pytest.mark.parametrize("url,expected", [
        ("/read/x/ch1-547229", "1"),
        ("/read/x/ch10-547229", "10"),
        ("/read/x/ch10.5-999888", "10.5"),        # dotted decimal
        ("/read/x/ch7-5-547254", "7.5"),          # dashed decimal
        ("/read/x/ch14-5-547286", "14.5"),
        ("/read/x/ch56-5-547486", "56.5"),
        ("/read/x/ch10.5-999888?page=2#top", "10.5"),
    ])
    def test_number_from_url(self, url, expected):
        assert MangaTaroScraper._chapter_number_from_url(url) == expected

    def test_number_from_url_missing(self):
        assert MangaTaroScraper._chapter_number_from_url(
            "https://mangataro.org/manga/koi-to-yobu") is None

    def test_prefers_clear_decimal_in_text(self):
        # Even for a dashed URL, a clean "Ch. 7.5" in the text is honoured.
        assert MangaTaroScraper._parse_chapter_number(
            "/read/x/ch7-5-547254", "Ch. 7.5") == "7.5"

    def test_falls_back_to_url_when_text_has_no_number(self):
        assert MangaTaroScraper._parse_chapter_number(
            "/read/x/ch56-5-547486", "Read") == "56.5"

    def test_defaults_to_zero(self):
        assert MangaTaroScraper._parse_chapter_number("/no-chapter", "Read") == "0"


class TestChapters:
    def test_parses_reader_dropdown(self, patch_html, mt):
        patch_html(mt, {"/manga/": MANGA_HTML, "/read/": READER_HTML})
        chapters = mt.get_chapters("https://mangataro.org/manga/koi-to-yobu")
        assert [c.number for c in chapters] == ["1", "2"]
        assert chapters[0].url == \
            "https://mangataro.org/read/koi-to-yobu-ni-wa-kimochi-warui/ch1-547229"
        # Chapter ids extracted here must feed get_pages' API call.
        assert MangaTaroScraper._extract_chapter_id(chapters[1].url) == "547233"

    def test_dropdown_parses_dashed_decimal_chapters(self, patch_html, mt):
        # Regression: ch7-5-<id> used to parse as chapter 7 (the "5" was
        # mistaken for the id), corrupting sort order and new-chapter checks.
        patch_html(mt, {"/manga/": MANGA_HTML, "/read/": READER_HTML_DECIMAL})
        chapters = mt.get_chapters("https://mangataro.org/manga/koi-to-yobu")
        assert [c.number for c in chapters] == ["7", "7.5", "14.5", "56.5"]
        # 7.5 sorts between 7 and 14.5, and the id is still the trailing segment.
        assert [c.numeric for c in chapters] == [7.0, 7.5, 14.5, 56.5]
        assert MangaTaroScraper._extract_chapter_id(chapters[1].url) == "547254"

    def test_fallback_direct_links_parse_dashed_decimal(self, patch_html, mt):
        # No <select> on the reader page -> direct-link fallback path.
        patch_html(mt, {"/manga/": MANGA_HTML_DECIMAL,
                        "/read/": "<html><body>no dropdown</body></html>"})
        chapters = mt.get_chapters("https://mangataro.org/manga/koi-to-yobu")
        assert [c.number for c in chapters] == ["7", "7.5", "14.5", "56.5"]


# Adjacent flow: search title parsing (direct-URL construction path)


class _FakeSearchResponse:
    def __init__(self, text, url, status=200):
        self.text = text
        self.url = url
        self.status_code = status


class TestSearch:
    def test_direct_url_parses_title(self, monkeypatch, mt):
        title_html = (
            "<html><head><title>Koi to Yobu ni wa Kimochi Warui "
            "Manga | Read Online Free at MangaTaro</title></head>"
            "<body><img src='https://mangataro.org/content/media/172533l.webp'></body></html>"
        )

        def fake_get(url, *a, **k):
            # Direct-URL hit resolves to a /manga/ page; the browse API
            # returns nothing extra here.
            return _FakeSearchResponse(title_html, url)

        monkeypatch.setattr(mt.session, "get", fake_get)
        results = mt.search("koi to yobu")
        assert results, "expected at least the direct-URL result"
        assert results[0].title == "Koi to Yobu ni wa Kimochi Warui"
        assert results[0].url == "https://mangataro.org/manga/koi-to-yobu"
