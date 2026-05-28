"""HTML-fixture tests for the Manganato + Mangakakalot family.

These two share nearly identical HTML structure (same network), so we
test them in one file with shared fixtures.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.manganato import ManganatoScraper
from memanga.scrapers.mangakakalot import MangakakalotScraper


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


# ──────────────────────────────────────────────────────────────────────
# Mangakakalot
# ──────────────────────────────────────────────────────────────────────


class TestKakalotSearch:
    def test_absolutizes_relative_urls(self, patch_html, load_fixture):
        s = MangakakalotScraper()
        patch_html(s, load_fixture("manganato_kakalot", "kakalot_search.html"))
        results = s.search("piece")
        # Two unique mangas
        assert len(results) == 2
        # Relative href got absolutized
        rel = next((r for r in results if "Relative" in r.title), None)
        assert rel and rel.url.startswith("https://mangakakalot.com")


class TestKakalotChapters:
    def test_extracts_chapters_with_absolute_urls(self, patch_html, load_fixture):
        s = MangakakalotScraper()
        patch_html(s, load_fixture("manganato_kakalot", "kakalot_manga.html"))
        chapters = s.get_chapters("https://mangakakalot.com/manga/one_piece")
        # 4 chapters
        assert len(chapters) == 4
        assert all(c.url.startswith("https://mangakakalot.com") for c in chapters)
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)


class TestKakalotPages:
    def test_absolutizes_relative_image_paths(self, patch_html, load_fixture):
        s = MangakakalotScraper()
        patch_html(s, load_fixture("manganato_kakalot", "kakalot_chapter.html"))
        pages = s.get_pages("https://mangakakalot.com/chapter/one_piece/chapter_1")
        # 3 images, including relative one that got absolutized
        assert len(pages) == 3
        assert any(p.startswith("https://mangakakalot.com/relative-page") for p in pages)
