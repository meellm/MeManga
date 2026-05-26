"""JSON-fixture tests for MangaDex's official-API scraper."""

from __future__ import annotations

import pytest

from memanga.scrapers.mangadex import MangaDexScraper


@pytest.fixture
def scraper():
    return MangaDexScraper()


class TestExtractIDs:
    def test_manga_id(self, scraper):
        assert scraper._extract_manga_id(
            "https://mangadex.org/title/abc-123/manga-name"
        ) == "abc-123"

    def test_manga_id_missing(self, scraper):
        assert scraper._extract_manga_id("https://mangadex.org/foo/x") is None

    def test_chapter_id(self, scraper):
        assert scraper._extract_chapter_id(
            "https://mangadex.org/chapter/deadbeef-1234"
        ) == "deadbeef-1234"


class TestSearch:
    def test_returns_manga_with_cover_and_description(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "search.json")
        patch_json(scraper, payload)

        results = scraper.search("chainsaw")
        assert len(results) == 2

        first = results[0]
        assert first.title == "Chainsaw Man"
        assert first.url == "https://mangadex.org/title/11111111-1111-1111-1111-111111111111"
        assert first.cover_url and first.cover_url.endswith("cover.jpg.256.jpg")
        assert "chainsaw devil" in first.description.lower()

    def test_falls_back_to_romaji_when_no_english(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "search.json")
        patch_json(scraper, payload)

        results = scraper.search("anything")
        second = results[1]
        assert second.title == "Romaji Only Title"


class TestGetChapters:
    def test_paginates_skips_external_and_dedupes(self, monkeypatch, scraper,
                                                    load_json_fixture):
        feed = load_json_fixture("mangadex", "feed.json")

        # First call returns the feed; subsequent calls return empty.
        calls = {"n": 0}
        def fake_json(url, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return feed
            return {"data": []}
        monkeypatch.setattr(scraper, "_get_json", fake_json)

        chapters = scraper.get_chapters(
            "https://mangadex.org/title/11111111-1111-1111-1111-111111111111"
        )
        # 1 + 2 (external skipped, ch-dup deduped to one entry for "1")
        assert len(chapters) == 2
        numbers = sorted(c.number for c in chapters)
        assert numbers == ["1", "2"]

    def test_invalid_manga_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters("https://mangadex.org/foo/x")


class TestGetPages:
    def test_builds_high_quality_urls(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "server.json")
        patch_json(scraper, payload)

        pages = scraper.get_pages("https://mangadex.org/chapter/deadbeef-1234")
        assert len(pages) == 3
        assert pages[0] == "https://uploads.mangadex.org/data/abc123hash/1-page.png"
        assert all("/data/abc123hash/" in p for p in pages)

    def test_invalid_chapter_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_pages("https://mangadex.org/x/y")
