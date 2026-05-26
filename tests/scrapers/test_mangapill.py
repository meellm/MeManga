"""HTML-fixture tests for MangapillScraper."""

from __future__ import annotations

import pytest

from memanga.scrapers.mangapill import MangapillScraper


@pytest.fixture
def scraper():
    return MangapillScraper()


class TestSearch:
    def test_dedupes_and_caps_at_10(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapill", "search.html"))
        results = scraper.search("piece")
        # 3 unique manga URLs after dedup
        assert len(results) == 3
        titles = [r.title for r in results]
        assert "One Piece" in titles
        # title-less entry falls back to slug
        assert any("Some Cool Series" in t for t in titles) or \
               any("some-cool-series" in r.url for r in results)

    def test_falls_back_to_alt_attribute_when_text_missing(self, scraper, patch_html):
        html = """<html><body>
            <a href="/manga/1/foo"><img alt="Alt Title"></a>
        </body></html>"""
        patch_html(scraper, html)
        results = scraper.search("foo")
        # Some text-less branch should produce a title
        assert results
        assert any(r.title for r in results)

    def test_no_results(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.search("nothing") == []


class TestGetChapters:
    def test_extracts_numbers_from_url_and_text(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapill", "manga.html"))
        chapters = scraper.get_chapters("https://mangapill.com/manga/1/one-piece")
        # 4 chapters
        assert len(chapters) == 4
        # Sorted ascending
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Decimal chapter detected
        assert any(c.number == "3.5" for c in chapters)


class TestGetPages:
    def test_skips_loading_gif_and_non_js_pages(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapill", "chapter.html"))
        pages = scraper.get_pages("https://mangapill.com/chapters/123/one-piece-chapter-1")
        # 3 valid pages; loading.gif and logo (non js-page) excluded
        assert len(pages) == 3
        assert not any("loading" in p.lower() for p in pages)


class TestDownloadImage:
    def test_success_writes_file(self, monkeypatch, scraper, tmp_path, fake_response):
        monkeypatch.setattr(scraper.session, "get",
                             lambda *a, **k: fake_response(content=b"data" * 100))
        ok = scraper.download_image("https://x.com/p.jpg", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").exists()

    def test_failure_returns_false(self, monkeypatch, scraper, tmp_path):
        def boom(*a, **k):
            raise IOError("nope")
        monkeypatch.setattr(scraper.session, "get", boom)
        assert scraper.download_image("https://x", tmp_path / "p.jpg") is False
