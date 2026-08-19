"""HTML/JSON-fixture tests for the Mangadot scraper.

The network-facing helpers (``_get_html`` / ``_get_json`` / ``_get_json_optional``)
are never invoked here - these tests exercise only the pure parsing and
normalisation layer, using payloads shaped after the live ``mangadot.net``
search page and ``/api`` responses.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.mangadot import MangadotScraper


@pytest.fixture
def md():
    return MangadotScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("mangadot.net")
    assert isinstance(s, MangadotScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


# URL helpers


class TestUrlHelpers:
    def test_manga_id(self):
        assert MangadotScraper._manga_id("https://mangadot.net/manga/25867") == "25867"
        assert MangadotScraper._manga_id("/manga/41") == "41"

    def test_manga_id_missing(self):
        assert MangadotScraper._manga_id("https://mangadot.net/search?search=x") is None

    def test_chapter_id(self):
        assert MangadotScraper._chapter_id("https://mangadot.net/chapter/1263396") == "1263396"

    def test_chapter_id_missing(self):
        assert MangadotScraper._chapter_id("https://mangadot.net/manga/41") is None

    def test_abs_url_relative(self, md):
        assert md._abs_url("/uploads/thumbs/320/a.webp") == \
            "https://mangadot.net/uploads/thumbs/320/a.webp"

    def test_abs_url_absolute_passthrough(self, md):
        assert md._abs_url("https://mangadot.net/chapters/manga_41/x/001.jpg") == \
            "https://mangadot.net/chapters/manga_41/x/001.jpg"


# Search


SEARCH_HTML = """
<html><body>
  <a class="group flex flex-col" href="/manga/41">
    <div class="relative">
      <img src="/uploads/thumbs/320/onepiece.webp.webp"/>
      <span>Manga</span><span>&#9733; 9.3</span>
    </div>
    <div class="line-clamp-2 text-[12px]">ONE PIECE</div>
  </a>
  <a class="group flex flex-col" href="/manga/37534">
    <div class="relative"><img src="/uploads/thumbs/320/side.jpg.webp"/></div>
    <div class="line-clamp-2">One Piece: Mugiwara Daigekijou</div>
  </a>
  <!-- Duplicate manga id must be dropped. -->
  <a href="/manga/41"><div class="line-clamp-2">One Piece (dup)</div></a>
  <!-- Card without a title div is ignored (e.g. a nav/section link). -->
  <a href="/manga/999"><img src="/uploads/x.webp"/></a>
</body></html>
"""


class TestSearch:
    def test_parses_cards_with_titles_and_covers(self, md):
        results = md._parse_search(SEARCH_HTML)
        assert [r.title for r in results] == [
            "ONE PIECE",
            "One Piece: Mugiwara Daigekijou",
        ]
        assert results[0].url == "https://mangadot.net/manga/41"
        # Cover made absolute.
        assert results[0].cover_url == \
            "https://mangadot.net/uploads/thumbs/320/onepiece.webp.webp"

    def test_empty_page_returns_empty(self, md):
        assert md._parse_search("<html><body></body></html>") == []

    def test_search_fetches_query_url(self, monkeypatch, md):
        seen = {}

        def fake_get_html(url, *a, **k):
            seen["url"] = url
            return SEARCH_HTML

        monkeypatch.setattr(md, "_get_html", fake_get_html)
        results = md.search("one piece")
        assert seen["url"] == "https://mangadot.net/search?search=one+piece"
        assert len(results) == 2


# Chapters


def _entry(cid, number, language="en", title=None, date="2026-08-10 14:31:28.120232+00"):
    return {
        "id": cid,
        "chapter_number": number,
        "chapter_title": title if title is not None else f"Chapter {number}",
        "language": language,
        "group_id": 14972,
        "page_count": 12,
        "source": "user",
        "date_added": date,
    }


CHAPTERS_DATA = [
    # Chapter 1 exists in French then English -> English release wins.
    _entry(500, 1, language="fr", title="Ch 1 FR"),
    _entry(501, 1, language="en", title="Ch 1 EN"),
    # A decimal chapter, English only.
    _entry(510, "1.5"),
    # Chapter 2 has no English release -> the sole French release is kept.
    _entry(520, 2, language="fr", title="Ch 2 FR"),
    # Rows with missing id / number are dropped.
    {"id": None, "chapter_number": 3},
    {"id": 530, "chapter_number": None},
]


class TestChapters:
    def test_dedupes_prefers_english_sorts_and_normalises(self, md):
        chapters = md._parse_chapters(CHAPTERS_DATA)
        # One chapter per number, sorted ascending.
        assert [c.number for c in chapters] == ["1", "1.5", "2"]
        # English release chosen for chapter 1 (id 501, not the French 500).
        first = chapters[0]
        assert first.url == "https://mangadot.net/chapter/501"
        assert first.title == "Ch 1 EN"
        # Chapter 2 falls back to the only (French) release.
        two = next(c for c in chapters if c.number == "2")
        assert two.url == "https://mangadot.net/chapter/520"
        # Date trimmed to YYYY-MM-DD.
        assert first.date == "2026-08-10"

    def test_non_list_returns_empty(self, md):
        assert md._parse_chapters({"error": "nope"}) == []
        assert md._parse_chapters(None) == []

    def test_chapter_number_from_int_float_and_text(self):
        assert MangadotScraper._chapter_number({"chapter_number": 0}) == "0"
        assert MangadotScraper._chapter_number({"chapter_number": 726}) == "726"
        assert MangadotScraper._chapter_number({"chapter_number": "11.0"}) == "11"
        assert MangadotScraper._chapter_number({"chapter_number": 725.5}) == "725.5"
        assert MangadotScraper._chapter_number({"chapter_number": "Vol 2 Ch 42"}) == "2"
        assert MangadotScraper._chapter_number({"chapter_number": None}) == "0"

    def test_clean_date(self):
        assert MangadotScraper._clean_date("2026-08-10 14:31:28.120232+00") == "2026-08-10"
        assert MangadotScraper._clean_date("") is None
        assert MangadotScraper._clean_date(None) is None

    def test_get_chapters_invalid_url_returns_empty(self, md):
        assert md.get_chapters("https://mangadot.net/search?search=x") == []

    def test_get_chapters_fetches_list_endpoint(self, monkeypatch, md):
        seen = {}

        def fake_get_json(url, *a, **k):
            seen["url"] = url
            return CHAPTERS_DATA

        monkeypatch.setattr(md, "_get_json", fake_get_json)
        chapters = md.get_chapters("https://mangadot.net/manga/25867")
        assert seen["url"] == "https://mangadot.net/api/manga/25867/chapters/list"
        assert len(chapters) == 3


# Pages


IMAGES_PAYLOAD = {
    "chapter": {"id": 121126, "manga_id": 46, "page_count": 3},
    "images": [
        {"url": "/chapters/manga_46/chapter_232_g10712/001.jpg", "w": 0, "h": 0},
        {"url": "/chapters/manga_46/chapter_232_g10712/002.jpg", "w": 0, "h": 0},
        {"url": "/chapters/manga_41/user_8_ch1190_en_abc/003.webp", "w": 0, "h": 0},
    ],
}


class TestPages:
    def test_parses_images_to_absolute_urls(self, md):
        pages = md._parse_pages(IMAGES_PAYLOAD)
        assert pages == [
            "https://mangadot.net/chapters/manga_46/chapter_232_g10712/001.jpg",
            "https://mangadot.net/chapters/manga_46/chapter_232_g10712/002.jpg",
            "https://mangadot.net/chapters/manga_41/user_8_ch1190_en_abc/003.webp",
        ]

    def test_empty_or_missing_images(self, md):
        assert md._parse_pages(None) == []
        assert md._parse_pages({}) == []
        assert md._parse_pages({"images": []}) == []

    def test_skips_malformed_image_entries(self, md):
        payload = {"images": [{"url": ""}, {"nope": 1}, {"url": "/a/001.jpg"}]}
        assert md._parse_pages(payload) == ["https://mangadot.net/a/001.jpg"]

    def test_get_pages_invalid_url_returns_empty(self, md):
        assert md.get_pages("https://mangadot.net/manga/46") == []

    def test_get_pages_uses_upload_endpoint_first(self, monkeypatch, md):
        calls = []

        def fake_optional(url):
            calls.append(url)
            if url.endswith("/api/uploads/121126/images"):
                return IMAGES_PAYLOAD
            raise AssertionError("should not reach the chapters endpoint")

        monkeypatch.setattr(md, "_get_json_optional", fake_optional)
        pages = md.get_pages("https://mangadot.net/chapter/121126")
        assert calls == ["https://mangadot.net/api/uploads/121126/images"]
        assert len(pages) == 3

    def test_get_pages_falls_back_to_chapters_endpoint(self, monkeypatch, md):
        calls = []

        def fake_optional(url):
            calls.append(url)
            # Upload endpoint doesn't apply (404 -> None); chapters one does.
            if url.endswith("/api/uploads/26329/images"):
                return None
            return IMAGES_PAYLOAD

        monkeypatch.setattr(md, "_get_json_optional", fake_optional)
        pages = md.get_pages("https://mangadot.net/chapter/26329")
        assert calls == [
            "https://mangadot.net/api/uploads/26329/images",
            "https://mangadot.net/api/chapters/26329/images",
        ]
        assert len(pages) == 3
