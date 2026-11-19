"""HTML-fixture tests for the Manganato scraper.

The fixtures live under fixtures/manganato_kakalot/, named after the
site family the scraper was written for.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.manganato import ManganatoScraper


# ──────────────────────────────────────────────────────────────────────
# Manganato
# ──────────────────────────────────────────────────────────────────────


class TestManganatoSearch:
    def test_extracts_title_url_cover(self, patch_html, load_fixture):
        s = ManganatoScraper()
        patch_html(s, load_fixture("manganato_kakalot", "manganato_search.html"))
        results = s.search("one piece")
        assert len(results) >= 1
        op = next((r for r in results if r.title == "One Piece"), None)
        assert op is not None
        assert op.url == "https://manganato.com/manga-aa12345"
        assert op.cover_url and "avt.mkklcdnv6.com" in op.cover_url

    def test_title_fallback_uses_link_title_attr(self, patch_html, load_fixture):
        s = ManganatoScraper()
        patch_html(s, load_fixture("manganato_kakalot", "manganato_search.html"))
        results = s.search("naruto")
        assert any(r.title == "Naruto" for r in results)


class TestManganatoChapters:
    def test_extracts_chapter_numbers(self, patch_html, load_fixture):
        s = ManganatoScraper()
        patch_html(s, load_fixture("manganato_kakalot", "manganato_manga.html"))
        chapters = s.get_chapters("https://manganato.com/manga-aa12345")
        # 4 chapters, "Not a chapter" excluded
        assert len(chapters) == 4
        # Decimal chapter
        assert any(c.number == "10.5" for c in chapters)
        # Sorted ascending
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)


class TestManganatoPages:
    def test_only_image_extensions_and_dedup(self, patch_html, load_fixture):
        s = ManganatoScraper()
        patch_html(s, load_fixture("manganato_kakalot", "manganato_chapter.html"))
        pages = s.get_pages("https://chapmanganato.to/x/chapter-1")
        # SVG excluded → 3 pages
        assert len(pages) == 3
        # All accepted extensions
        assert all(p.endswith((".jpg", ".png", ".webp")) for p in pages)
        # No duplicates
        assert len(pages) == len(set(pages))


class TestManganatoDownload:
    def test_success(self, monkeypatch, tmp_path, fake_response):
        s = ManganatoScraper()
        monkeypatch.setattr(s.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 8192))
        assert s.download_image("https://x", tmp_path / "p.jpg") is True

    def test_failure(self, monkeypatch, tmp_path):
        s = ManganatoScraper()
        monkeypatch.setattr(s.session, "get",
                             lambda *a, **k: (_ for _ in ()).throw(IOError("x")))
        assert s.download_image("https://x", tmp_path / "p.jpg") is False
