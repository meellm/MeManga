"""JSON/HTML-fixture tests for MangaBall's API-driven scraper.

The network-facing helpers (``_api_post`` / ``_get_html``) are never invoked
here - these tests exercise only the pure parsing/normalisation layer, using
payloads shaped after the live ``/api/v1`` responses and reader pages.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.mangaball import MangaBallScraper


@pytest.fixture
def mb():
    return MangaBallScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("mangaball.net")
    assert isinstance(s, MangaBallScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


# URL helpers


class TestUrlHelpers:
    def test_extract_title_id(self):
        assert MangaBallScraper._extract_title_id(
            "https://mangaball.net/title-detail/kubera-official-6889f402e00aa4d41d07e044/"
        ) == "6889f402e00aa4d41d07e044"

    def test_extract_title_id_missing(self):
        assert MangaBallScraper._extract_title_id("https://mangaball.net/foo/bar") is None

    def test_extract_title_id_ignores_earlier_hex_run(self):
        # A slug containing an earlier 24-hex-looking run must not shadow the
        # real trailing title id.
        url = (
            "https://mangaball.net/title-detail/"
            "deadbeefcafebabefacefeed0042-6889f402e00aa4d41d07e044/"
        )
        assert MangaBallScraper._extract_title_id(url) == "6889f402e00aa4d41d07e044"

    def test_extract_title_id_with_query_and_fragment(self):
        url = "https://mangaball.net/title-detail/x-6889f402e00aa4d41d07e044?a=1#top"
        assert MangaBallScraper._extract_title_id(url) == "6889f402e00aa4d41d07e044"

    def test_abs_url_relative(self, mb):
        assert mb._abs_url("/title-detail/x-abc/") == \
            "https://mangaball.net/title-detail/x-abc/"

    def test_abs_url_forces_https(self, mb):
        # The chapter API hands back http:// links.
        assert mb._abs_url("http://mangaball.net/chapter-detail/deadbeef/") == \
            "https://mangaball.net/chapter-detail/deadbeef/"


# Search


SEARCH_PAYLOAD = {
    "code": 200,
    "message": "Search smart success",
    "data": {
        "manga": [
            {
                "img": "https://cdn.poke-black-and-white.net/covers/a/cover.jpg",
                "title": "Kubera (Official)",
                "url": "/title-detail/kubera-official-6889f402e00aa4d41d07e044/",
            },
            {
                "img": "https://cdn.poke-black-and-white.net/covers/b/cover.jpg",
                "title": "KubeRag Arena",
                "url": "/title-detail/kuberag-arena-68525476048c12fa14c40b6c/",
            },
            # Duplicate URL + a blank-title row must be dropped.
            {"img": None, "title": "dup", "url": "/title-detail/kubera-official-6889f402e00aa4d41d07e044/"},
            {"img": None, "title": "", "url": "/title-detail/nameless-000000000000000000000000/"},
        ],
        "authors": "",
        "tags": "",
    },
}


class TestSearch:
    def test_parses_manga_with_covers(self, mb):
        results = mb._parse_search(SEARCH_PAYLOAD)
        assert [r.title for r in results] == ["Kubera (Official)", "KubeRag Arena"]
        assert results[0].url == \
            "https://mangaball.net/title-detail/kubera-official-6889f402e00aa4d41d07e044/"
        assert results[0].cover_url.endswith("cover.jpg")

    def test_non_200_returns_empty(self, mb):
        assert mb._parse_search({"code": 419, "message": "expired"}) == []
        assert mb._parse_search({}) == []

    def test_search_calls_api_and_parses(self, monkeypatch, mb):
        captured = {}

        def fake_post(path, data):
            captured["path"] = path
            captured["data"] = data
            return SEARCH_PAYLOAD

        monkeypatch.setattr(mb, "_api_post", fake_post)
        results = mb.search("kubera")
        assert captured["path"] == "/api/v1/smart-search/search/"
        assert captured["data"] == {"search_input": "kubera"}
        assert len(results) == 2


# Chapters


def _translation(url, language="en", date="2026-08-03 05:07:13"):
    return {"url": url, "language": language, "languageName": language, "date": date}


CHAPTERS_PAYLOAD = {
    "code": 200,
    "ALL_CHAPTERS": [
        {
            "number": "Ch. 726",
            "number_float": 726,
            "title": "Ch. 726",
            "translations": [
                _translation("http://mangaball.net/chapter-detail/en726a/"),
                _translation("http://mangaball.net/chapter-detail/en726b/"),
            ],
        },
        {
            "number": "Ch. 725.5",
            "number_float": 725.5,
            "title": "Ch. 725.5",
            "translations": [
                # No English -> fall back to first usable translation.
                _translation("http://mangaball.net/chapter-detail/fr7255/", language="fr"),
            ],
        },
        {
            "number": "Ch. 10",
            "number_float": 10,
            "title": "Ch. 10",
            "translations": [_translation("http://mangaball.net/chapter-detail/en10/")],
        },
        # Entry with no usable translation is skipped entirely.
        {"number": "Ch. 9", "number_float": 9, "title": "Ch. 9", "translations": [{"language": "en"}]},
    ],
}


class TestChapters:
    def test_prefers_english_sorts_and_normalises(self, mb):
        chapters = mb._parse_chapters(CHAPTERS_PAYLOAD)
        # 3 entries yield chapters (the translation-less one is dropped).
        assert [c.number for c in chapters] == ["10", "725.5", "726"]
        # English translation chosen for 726 (first en URL, not the fr one).
        top = chapters[-1]
        assert top.url == "https://mangaball.net/chapter-detail/en726a/"
        # http -> https normalisation applied.
        assert all(c.url.startswith("https://") for c in chapters)
        # Non-English chapter still resolved via fallback.
        mid = next(c for c in chapters if c.number == "725.5")
        assert mid.url.endswith("/fr7255/")
        assert mid.date == "2026-08-03 05:07:13"

    def test_non_200_returns_empty(self, mb):
        assert mb._parse_chapters({"code": 500}) == []

    def test_pick_translation_prefers_english(self):
        picked = MangaBallScraper._pick_translation([
            _translation("u1", language="es"),
            _translation("u2", language="en"),
        ])
        assert picked["url"] == "u2"

    def test_pick_translation_none_when_no_urls(self):
        assert MangaBallScraper._pick_translation([{"language": "en"}]) is None

    def test_chapter_number_from_float_and_text(self):
        assert MangaBallScraper._chapter_number({"number_float": 726}) == "726"
        assert MangaBallScraper._chapter_number({"number_float": 725.5}) == "725.5"
        assert MangaBallScraper._chapter_number({"number": "Ch. 42"}) == "42"
        assert MangaBallScraper._chapter_number({}) == "0"

    def test_get_chapters_invalid_url_returns_empty(self, mb):
        assert mb.get_chapters("https://mangaball.net/no-id-here/") == []


# Pages


READER_HTML = """
<html><head><meta name="csrf-token" content="abc"></head><body>
<script>
    const chapterImages = JSON.parse(`["https://jigglypuff.poke-black-and-white.net/storage/x/0/726/en/aa-001.jpg","https://jigglypuff.poke-black-and-white.net/storage/x/0/726/en/aa-002.jpg"]`);
</script>
</body></html>
"""

READER_HTML_FALLBACK = """
<html><body>
<img src="https://mangaball.net/public/logo.png">
<img data-src="https://jigglypuff.poke-black-and-white.net/storage/x/0/1/en/bb-001.jpg">
<img src="https://jigglypuff.poke-black-and-white.net/storage/x/0/1/en/bb-002.jpg">
</body></html>
"""


class TestPages:
    def test_extracts_embedded_json(self, mb):
        pages = mb._parse_pages(READER_HTML)
        assert len(pages) == 2
        assert pages[0].endswith("aa-001.jpg")
        assert all("poke-black-and-white.net" in p for p in pages)

    def test_embedded_json_normalises_http_to_https(self, mb):
        html = (
            "<script>const chapterImages = JSON.parse(`"
            '["http://jigglypuff.poke-black-and-white.net/storage/x/0/726/en/aa-001.jpg"]'
            "`);</script>"
        )
        pages = mb._parse_pages(html)
        assert pages == [
            "https://jigglypuff.poke-black-and-white.net/storage/x/0/726/en/aa-001.jpg"
        ]

    def test_falls_back_to_cdn_img_tags(self, mb):
        pages = mb._parse_pages(READER_HTML_FALLBACK)
        assert pages == [
            "https://jigglypuff.poke-black-and-white.net/storage/x/0/1/en/bb-001.jpg",
            "https://jigglypuff.poke-black-and-white.net/storage/x/0/1/en/bb-002.jpg",
        ]

    def test_get_pages_fetches_normalised_url(self, monkeypatch, mb):
        seen = {}

        def fake_get_html(url, *a, **k):
            seen["url"] = url
            return READER_HTML

        monkeypatch.setattr(mb, "_get_html", fake_get_html)
        pages = mb.get_pages("http://mangaball.net/chapter-detail/en726a/")
        assert seen["url"] == "https://mangaball.net/chapter-detail/en726a/"
        assert len(pages) == 2
