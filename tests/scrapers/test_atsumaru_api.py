"""JSON-fixture tests for Atsumaru's API-driven scraper.

The network-facing helpers (``_get_json``) are never invoked here - these tests
exercise only the pure parsing/normalisation layer, using payloads shaped after
the live Typesense and REST API responses.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.atsumaru import AtsumaruScraper


@pytest.fixture
def scraper():
    return AtsumaruScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("atsu.moe")
    assert isinstance(s, AtsumaruScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


# URL helpers


class TestUrlHelpers:
    def test_extract_manga_id(self):
        assert AtsumaruScraper._extract_manga_id(
            "https://atsu.moe/manga/sVC2A"
        ) == "sVC2A"

    def test_extract_manga_id_missing(self):
        assert AtsumaruScraper._extract_manga_id("https://atsu.moe/foo/bar") is None

    def test_extract_manga_id_with_trailing_path(self):
        assert AtsumaruScraper._extract_manga_id(
            "https://atsu.moe/manga/sVC2A/chapters"
        ) == "sVC2A"

    def test_extract_manga_id_with_query_string(self):
        assert AtsumaruScraper._extract_manga_id(
            "https://atsu.moe/manga/sVC2A?ref=home"
        ) == "sVC2A"

    def test_extract_manga_id_allows_dash_and_underscore(self):
        # IDs are nanoid-style identifiers whose alphabet may include "-"/"_".
        assert AtsumaruScraper._extract_manga_id(
            "https://atsu.moe/manga/9L8-2j_efe"
        ) == "9L8-2j_efe"

    def test_extract_read_ids(self):
        manga_id, chapter_id = AtsumaruScraper._extract_read_ids(
            "https://atsu.moe/read/sVC2A/Nd6vV"
        )
        assert manga_id == "sVC2A"
        assert chapter_id == "Nd6vV"

    def test_extract_read_ids_allows_dash_and_underscore(self):
        manga_id, chapter_id = AtsumaruScraper._extract_read_ids(
            "https://atsu.moe/read/sV-C2A/Nd_6vV"
        )
        assert manga_id == "sV-C2A"
        assert chapter_id == "Nd_6vV"

    def test_extract_read_ids_missing(self):
        manga_id, chapter_id = AtsumaruScraper._extract_read_ids(
            "https://atsu.moe/manga/sVC2A"
        )
        assert manga_id is None
        assert chapter_id is None

    def test_abs_static_url(self, scraper):
        path = "/static/pages/abc123/Nd6vV/0.webp"
        assert scraper._abs_static_url(path) == "https://cdn.atsu.moe" + path

    def test_abs_static_url_already_absolute(self, scraper):
        url = "https://cdn.atsu.moe/static/pages/abc123/Nd6vV/0.webp"
        assert scraper._abs_static_url(url) == url

    def test_abs_static_url_no_leading_slash(self, scraper):
        path = "static/pages/abc123/Nd6vV/0.webp"
        assert scraper._abs_static_url(path) == "https://cdn.atsu.moe/static/pages/abc123/Nd6vV/0.webp"


# Search


SEARCH_PAYLOAD = {
    "found": 2,
    "hits": [
        {
            "document": {
                "id": "sVC2A",
                "title": "One Piece",
                "otherNames": ["OP", "Wan Piisu"],
                "chapterCount": 1189,
                "poster": "/static/posters/sVC2A/poster.webp",
                "posterMedium": "/static/posters/sVC2A/poster_medium.webp",
                "posterSmall": "/static/posters/sVC2A/poster_small.webp",
                "synopsis": "Monkey D. Luffy sets off on an adventure...",
            }
        },
        {
            "document": {
                "id": "xYZ12",
                "title": "One Punch Man",
                "otherNames": ["OPM"],
                "chapterCount": 200,
                "poster": "/static/posters/xYZ12/poster.webp",
                "synopsis": "Saitama is a hero who defeats everyone...",
            }
        },
        # Duplicate ID should be dropped
        {
            "document": {
                "id": "sVC2A",
                "title": "One Piece (Duplicate)",
            }
        },
        # Missing title should be dropped
        {
            "document": {
                "id": "noTitle",
                "title": "",
            }
        },
    ],
}


class TestSearch:
    def test_parses_manga_with_covers(self, scraper):
        results = scraper._parse_search(SEARCH_PAYLOAD)
        assert len(results) == 2
        assert results[0].title == "One Piece"
        assert results[0].url == "https://atsu.moe/manga/sVC2A"
        assert results[0].cover_url == "https://cdn.atsu.moe/static/posters/sVC2A/poster_medium.webp"
        assert results[0].description == "Monkey D. Luffy sets off on an adventure..."

    def test_deduplicates_manga_ids(self, scraper):
        results = scraper._parse_search(SEARCH_PAYLOAD)
        ids = [r.url.split("/")[-1] for r in results]
        assert ids == ["sVC2A", "xYZ12"]

    def test_empty_response_returns_empty(self, scraper):
        assert scraper._parse_search({}) == []
        assert scraper._parse_search({"hits": []}) == []
        assert scraper._parse_search(None) == []

    def test_search_calls_api_and_parses(self, monkeypatch, scraper):
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return SEARCH_PAYLOAD

        monkeypatch.setattr(scraper, "_get_json", fake_get_json)
        results = scraper.search("one piece")
        assert "q=one+piece" in captured["url"]
        assert "query_by=title" in captured["url"]
        assert "otherNames" in captured["url"]
        assert "per_page=20" in captured["url"]
        assert len(results) == 2

    def test_search_encodes_special_characters(self, monkeypatch, scraper):
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return {"hits": []}

        monkeypatch.setattr(scraper, "_get_json", fake_get_json)
        scraper.search("kaguya-sama & love is war")
        assert "q=kaguya-sama+%26+love+is+war" in captured["url"]
        assert "query_by=title" in captured["url"]
        assert "otherNames" in captured["url"]
        assert "per_page=20" in captured["url"]


# Chapters


CHAPTERS_PAYLOAD = {
    "chapters": [
        {
            "id": "zSZfP",
            "title": "Chapter 1189",
            "number": 1189,
            "createdAt": 1722880800000,  # 2024-08-05T18:00:00Z
            "index": 1188,
            "pageCount": 15,
            "scanlationMangaId": "sVC2A",
        },
        {
            "id": "Nd6vV",
            "title": "Chapter 1188",
            "number": 1188,
            "createdAt": 1722276000000,  # 2024-07-29T18:00:00Z
            "index": 1187,
            "pageCount": 18,
            "scanlationMangaId": "sVC2A",
        },
        {
            "id": "abc12",
            "title": "Chapter 1",
            "number": 1,
            "createdAt": 1600000000000,
            "index": 0,
            "pageCount": 20,
            "scanlationMangaId": "sVC2A",
        },
        # Half chapter
        {
            "id": "half1",
            "title": "Chapter 1.5",
            "number": 1.5,
            "createdAt": 1600100000000,
            "index": 1,
            "pageCount": 10,
        },
    ]
}


class TestChapters:
    def test_parses_chapters_sorted_ascending(self, scraper):
        chapters = scraper._parse_chapters(CHAPTERS_PAYLOAD, "sVC2A")
        assert [c.number for c in chapters] == ["1", "1.5", "1188", "1189"]

    def test_chapter_urls_include_both_ids(self, scraper):
        chapters = scraper._parse_chapters(CHAPTERS_PAYLOAD, "sVC2A")
        first = chapters[0]
        assert first.url == "https://atsu.moe/read/sVC2A/abc12"

    def test_chapter_dates_parsed(self, scraper):
        chapters = scraper._parse_chapters(CHAPTERS_PAYLOAD, "sVC2A")
        latest = chapters[-1]
        assert latest.date == "2024-08-05"

    def test_empty_response_returns_empty(self, scraper):
        assert scraper._parse_chapters({}, "sVC2A") == []
        assert scraper._parse_chapters({"chapters": []}, "sVC2A") == []

    def test_get_chapters_invalid_url_returns_empty(self, scraper):
        assert scraper.get_chapters("https://atsu.moe/unknown/path") == []

    def test_chapter_number_extraction(self):
        assert AtsumaruScraper._chapter_number({"number": 42}) == "42"
        assert AtsumaruScraper._chapter_number({"number": 42.5}) == "42.5"
        assert AtsumaruScraper._chapter_number({"index": 9}) == "10"
        assert AtsumaruScraper._chapter_number({"title": "Ch. 100"}) == "100"
        assert AtsumaruScraper._chapter_number({}) == "0"


# Pages


PAGES_PAYLOAD = {
    "readChapter": {
        "id": "Nd6vV",
        "mangaId": "sVC2A",
        "pages": [
            {"number": 0, "image": "/static/pages/cmgzkjxs70k8hm191srm4qxf9/Nd6vV/0.webp", "width": 784, "height": 1145},
            {"number": 1, "image": "/static/pages/cmgzkjxs70k8hm191srm4qxf9/Nd6vV/1.webp", "width": 784, "height": 1145},
            {"number": 2, "image": "/static/pages/cmgzkjxs70k8hm191srm4qxf9/Nd6vV/2.avif", "width": 784, "height": 1145},
        ],
    }
}


class TestPages:
    def test_extracts_ordered_pages(self, scraper):
        pages = scraper._parse_pages(PAGES_PAYLOAD)
        assert len(pages) == 3
        assert pages[0] == "https://cdn.atsu.moe/static/pages/cmgzkjxs70k8hm191srm4qxf9/Nd6vV/0.webp"
        assert pages[1].endswith("/1.webp")
        assert pages[2].endswith("/2.avif")  # AVIF preserved

    def test_pages_sorted_by_number(self, scraper):
        data = {
            "readChapter": {
                "pages": [
                    {"number": 2, "image": "/static/page2.webp"},
                    {"number": 0, "image": "/static/page0.webp"},
                    {"number": 1, "image": "/static/page1.webp"},
                ]
            }
        }
        pages = scraper._parse_pages(data)
        assert [p.split("/")[-1] for p in pages] == ["page0.webp", "page1.webp", "page2.webp"]

    def test_empty_response_returns_empty(self, scraper):
        assert scraper._parse_pages({}) == []
        assert scraper._parse_pages({"readChapter": {}}) == []
        assert scraper._parse_pages({"readChapter": {"pages": []}}) == []

    def test_get_pages_from_read_url(self, monkeypatch, scraper):
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return PAGES_PAYLOAD

        monkeypatch.setattr(scraper, "_get_json", fake_get_json)
        pages = scraper.get_pages("https://atsu.moe/read/sVC2A/Nd6vV")
        assert "mangaId=sVC2A" in captured["url"]
        assert "chapterId=Nd6vV" in captured["url"]
        assert len(pages) == 3

    def test_get_pages_from_api_query_url(self, monkeypatch, scraper):
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return PAGES_PAYLOAD

        monkeypatch.setattr(scraper, "_get_json", fake_get_json)
        pages = scraper.get_pages(
            "https://atsu.moe/api/read/chapter?mangaId=sVC2A&chapterId=Nd6vV"
        )
        assert "mangaId=sVC2A" in captured["url"]
        assert "chapterId=Nd6vV" in captured["url"]
        assert len(pages) == 3

    def test_get_pages_invalid_url_returns_empty(self, scraper):
        assert scraper.get_pages("https://atsu.moe/unknown/path") == []
