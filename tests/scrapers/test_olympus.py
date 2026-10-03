"""JSON/HTML-fixture tests for the Olympus Scanlation scraper.

The network-facing helpers (``_get_json`` / ``_get_html``) are replaced with
fakes here - these tests exercise only the parsing, URL handling and
pagination logic, using payloads shaped after the live ``olympusxyz.com``
catalogue, panel chapter-list and reader responses.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.olympus import OlympusScraper


@pytest.fixture
def ol():
    return OlympusScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("olympusxyz.com")
    assert isinstance(s, OlympusScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


def test_panel_subdomain_resolves():
    assert isinstance(get_scraper("panel.olympusxyz.com"), OlympusScraper)


# URL helpers


class TestUrlHelpers:
    def test_parse_series_url(self):
        assert OlympusScraper._parse_series_url(
            "https://olympusxyz.com/series/comic-solo-swordmaster"
        ) == ("comic", "solo-swordmaster")
        assert OlympusScraper._parse_series_url(
            "https://olympusxyz.com/series/novela-muchas-torres-novela"
        ) == ("novela", "muchas-torres-novela")

    def test_parse_series_url_missing(self):
        assert OlympusScraper._parse_series_url("https://olympusxyz.com/") == (None, None)

    def test_parse_chapter_url(self):
        assert OlympusScraper._parse_chapter_url(
            "https://olympusxyz.com/capitulo/133779/comic-solo-swordmaster"
        ) == ("133779", "solo-swordmaster")

    def test_parse_chapter_url_missing(self):
        assert OlympusScraper._parse_chapter_url(
            "https://olympusxyz.com/series/comic-solo-swordmaster"
        ) == (None, None)

    def test_builds_site_urls(self, ol):
        assert ol._series_url("solo-swordmaster") == \
            "https://olympusxyz.com/series/comic-solo-swordmaster"
        assert ol._chapter_url("solo-swordmaster", 133779) == \
            "https://olympusxyz.com/capitulo/133779/comic-solo-swordmaster"


# Search


CATALOGUE = [
    {"id": 5, "name": "Muchas Torres (Novela)", "slug": "muchas-torres-novela",
     "cover": "https://media.imagesolymp.xyz/novels/covers/5/a-sm.webp", "type": "novel"},
    {"id": 1800, "name": "Regresión del Espadachín", "slug": "regresion-del-espadachin",
     "cover": "https://media.imagesolymp.xyz/comics/covers/1800/b-sm.webp", "type": "comic"},
    {"id": 1777, "name": "Solo Swordmaster", "slug": "solo-swordmaster",
     "cover": "https://media.imagesolymp.xyz/comics/covers/1777/c-sm.webp", "type": "comic"},
    {"id": 1901, "name": "Los Gemelos Baek", "slug": "los-gemelos-baek-20260930-080317806",
     "cover": "https://media.imagesolymp.xyz/comics/covers/1901/d-sm.webp", "type": "comic"},
    # Same title as a comic entry, but a novel -> never returned.
    {"id": 6, "name": "Solo Swordmaster (Novela)", "slug": "solo-swordmaster-novela",
     "cover": None, "type": "novel"},
    # Malformed rows are skipped.
    {"id": 7, "name": "", "slug": "no-name", "type": "comic"},
    "not-a-dict",
]


class TestSearch:
    def test_filters_comics_by_every_query_word(self, ol):
        results = ol._parse_search(CATALOGUE, "solo swordmaster")
        assert [r.title for r in results] == ["Solo Swordmaster"]
        assert results[0].url == "https://olympusxyz.com/series/comic-solo-swordmaster"
        assert results[0].cover_url == \
            "https://media.imagesolymp.xyz/comics/covers/1777/c-sm.webp"

    def test_novels_are_excluded(self, ol):
        assert ol._parse_search(CATALOGUE, "muchas torres") == []

    def test_accent_insensitive_match(self, ol):
        results = ol._parse_search(CATALOGUE, "regresion espadachin")
        assert [r.title for r in results] == ["Regresión del Espadachín"]

    def test_matches_on_slug(self, ol):
        results = ol._parse_search(CATALOGUE, "gemelos-baek")
        assert results[0].url == \
            "https://olympusxyz.com/series/comic-los-gemelos-baek-20260930-080317806"

    def test_exact_and_prefix_matches_rank_first(self, ol):
        catalogue = [
            {"name": "The Swordmaster Returns", "slug": "the-swordmaster-returns", "type": "comic"},
            {"name": "Swordmaster Chronicles", "slug": "swordmaster-chronicles", "type": "comic"},
            {"name": "Swordmaster", "slug": "swordmaster", "type": "comic"},
        ]
        assert [r.title for r in ol._parse_search(catalogue, "swordmaster")] == [
            "Swordmaster", "Swordmaster Chronicles", "The Swordmaster Returns",
        ]

    def test_blank_query_or_bad_payload(self, ol):
        assert ol._parse_search(CATALOGUE, "  ") == []
        assert ol._parse_search(None, "solo") == []

    def test_search_fetches_catalogue_once(self, monkeypatch, ol):
        calls = []

        def fake_get_json(url, *a, **k):
            calls.append(url)
            return {"data": CATALOGUE}

        monkeypatch.setattr(ol, "_get_json", fake_get_json)
        assert len(ol.search("solo swordmaster")) == 1
        assert len(ol.search("gemelos")) == 1
        assert calls == ["https://olympusxyz.com/api/series/list"]


# Chapters


def _row(cid, name, published="2026-09-30T17:20:46.000000Z"):
    return {"name": name, "id": cid, "published_at": published,
            "team": {"id": 1, "name": "Olympus "}, "read_by_auth": False}


def _chapter_page(rows, page, last_page):
    return {"data": rows, "meta": {"current_page": page, "last_page": last_page,
                                   "per_page": 40}}


class TestChapters:
    def test_parses_sorts_and_dedupes(self, ol):
        rows = [_row(3, "2"), _row(1, "1"), _row(9, "22.05"), _row(4, "2.0"),
                {"id": None, "name": "5"}, "junk"]
        chapters = ol._parse_chapters(rows, "solo-swordmaster")
        assert [c.number for c in chapters] == ["1", "2", "22.05"]
        assert chapters[0].url == \
            "https://olympusxyz.com/capitulo/1/comic-solo-swordmaster"
        # The first release listed wins for a repeated number.
        assert chapters[1].url.endswith("/capitulo/3/comic-solo-swordmaster")
        assert chapters[0].title == "Chapter 1"
        assert chapters[0].date == "2026-09-30"

    def test_chapter_number(self):
        assert OlympusScraper._chapter_number("12") == "12"
        assert OlympusScraper._chapter_number("12.0") == "12"
        assert OlympusScraper._chapter_number("22.05") == "22.05"
        assert OlympusScraper._chapter_number(7) == "7"
        assert OlympusScraper._chapter_number("Extra") == "Extra"
        assert OlympusScraper._chapter_number(None) == "0"

    def test_walks_every_panel_page(self, monkeypatch, ol):
        pages = {
            1: _chapter_page([_row(i, str(i)) for i in range(1, 41)], 1, 2),
            2: _chapter_page([_row(i, str(i)) for i in range(41, 46)], 2, 2),
        }
        calls = []

        def fake_get_json(url, *a, **k):
            calls.append(url)
            return pages[int(url.split("page=")[1].split("&")[0])]

        monkeypatch.setattr(ol, "_get_json", fake_get_json)
        chapters = ol.get_chapters("https://olympusxyz.com/series/comic-los-gemelos-baek")
        assert calls == [
            "https://panel.olympusxyz.com/api/series/los-gemelos-baek/chapters?page=1&direction=asc",
            "https://panel.olympusxyz.com/api/series/los-gemelos-baek/chapters?page=2&direction=asc",
        ]
        assert len(chapters) == 45
        assert chapters[-1].number == "45"

    def test_novel_and_invalid_urls_return_empty(self, monkeypatch, ol):
        def boom(*a, **k):
            raise AssertionError("no request expected")

        monkeypatch.setattr(ol, "_get_json", boom)
        assert ol.get_chapters("https://olympusxyz.com/series/novela-muchas-torres-novela") == []
        assert ol.get_chapters("https://olympusxyz.com/") == []


# Pages


CHAPTER_URL = "https://olympusxyz.com/capitulo/133779/comic-solo-swordmaster"
MEDIA = "https://media.imagesolymp.xyz/comics/1777/133779"

READER_PAYLOAD = {
    "chapter": {
        "id": 133779, "name": "4", "title": None,
        "pages": [f"{MEDIA}/1_01.webp", f"{MEDIA}/1_02.webp", "", None, f"{MEDIA}/2_01.webp"],
    },
}

READER_HTML = f"""
<html><body>
  <img src="https://media.imagesolymp.xyz/comics/covers/1777/c-xl.webp"/>
  <img src="https://media.imagesolymp.xyz/teams/originals/logo5.png"/>
  <section>
    <img src="{MEDIA}/1_01.webp"/>
    <img src="{MEDIA}/1_02.webp"/>
    <img src="{MEDIA}/1_01.webp"/>
  </section>
</body></html>
"""


class TestPages:
    def test_parses_reader_payload(self, ol):
        assert ol._parse_pages(READER_PAYLOAD) == [
            f"{MEDIA}/1_01.webp", f"{MEDIA}/1_02.webp", f"{MEDIA}/2_01.webp",
        ]

    def test_bad_payloads(self, ol):
        assert ol._parse_pages(None) == []
        assert ol._parse_pages({}) == []
        assert ol._parse_pages({"chapter": {"pages": []}}) == []

    def test_html_fallback_keeps_only_chapter_images(self, ol):
        assert ol._parse_pages_html(READER_HTML, "133779") == [
            f"{MEDIA}/1_01.webp", f"{MEDIA}/1_02.webp",
        ]

    def test_get_pages_uses_reader_api(self, monkeypatch, ol):
        calls = []

        def fake_get_json(url, *a, **k):
            calls.append(url)
            return READER_PAYLOAD

        monkeypatch.setattr(ol, "_get_json", fake_get_json)
        pages = ol.get_pages(CHAPTER_URL)
        assert calls == ["https://olympusxyz.com/api/capitulo/solo-swordmaster/133779"]
        assert len(pages) == 3

    def test_get_pages_falls_back_to_reader_html(self, monkeypatch, ol):
        seen = {}

        def fake_get_html(url, *a, **k):
            seen["url"] = url
            return READER_HTML

        monkeypatch.setattr(ol, "_get_json", lambda *a, **k: {"unexpected": True})
        monkeypatch.setattr(ol, "_get_html", fake_get_html)
        assert ol.get_pages(CHAPTER_URL) == [f"{MEDIA}/1_01.webp", f"{MEDIA}/1_02.webp"]
        assert seen["url"] == CHAPTER_URL

    def test_get_pages_invalid_url_returns_empty(self, ol):
        assert ol.get_pages("https://olympusxyz.com/series/comic-solo-swordmaster") == []


# Cover


def test_get_cover_url_uses_series_api(monkeypatch, ol):
    seen = {}

    def fake_get_json(url, *a, **k):
        seen["url"] = url
        return {"data": {"cover": "https://media.imagesolymp.xyz/comics/covers/1777/c-xl.webp"}}

    monkeypatch.setattr(ol, "_get_json", fake_get_json)
    assert ol.get_cover_url("https://olympusxyz.com/series/comic-solo-swordmaster") == \
        "https://media.imagesolymp.xyz/comics/covers/1777/c-xl.webp"
    assert seen["url"] == "https://olympusxyz.com/api/series/solo-swordmaster"
