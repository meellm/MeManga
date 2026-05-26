"""HTML-fixture tests for TCBScansScraper."""

from __future__ import annotations

import pytest

from memanga.scrapers.tcbscans import TCBScansScraper


@pytest.fixture
def scraper():
    return TCBScansScraper()


class TestSearch:
    def test_filters_by_query_and_dedupes(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("tcbscans", "projects.html"))
        results = scraper.search("one piece")
        assert len(results) == 1
        assert results[0].title == "One Piece"
        assert results[0].url.startswith("https://tcbonepiecechapters.com/mangas/")

    def test_case_insensitive(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("tcbscans", "projects.html"))
        results = scraper.search("ONE")
        assert any(r.title == "One Piece" for r in results)

    def test_no_match_returns_empty(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("tcbscans", "projects.html"))
        assert scraper.search("frieren") == []


class TestGetChapters:
    def test_extracts_with_title_and_subtitle(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("tcbscans", "manga.html"))
        chapters = scraper.get_chapters("https://tcbonepiecechapters.com/mangas/5/one-piece")
        # 3 valid chapters; "Special" without a number skipped
        assert len(chapters) == 3
        # Subtitle composed when present
        assert any("Romance Dawn" in (c.title or "") for c in chapters)
        # Sorted ascending
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # URLs absolutized
        assert all(c.url.startswith("https://tcbonepiecechapters.com") for c in chapters)


class TestGetPages:
    def test_picture_and_chapter_content_with_logo_skip(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("tcbscans", "chapter.html"))
        pages = scraper.get_pages("https://tcbonepiecechapters.com/chapters/123/x")
        # 3 pages + 1 relative chapter-content page; logo skipped
        assert len(pages) == 4
        assert not any("logo" in p.lower() for p in pages)
        # Relative URL absolutized
        assert any(p.endswith("/relative/page-4.png") for p in pages)
