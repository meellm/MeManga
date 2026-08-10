"""HTML-fixture tests for VyMangaScraper."""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.vymanga import VyMangaScraper


@pytest.fixture
def scraper():
    return VyMangaScraper()


class TestSearch:
    def test_extracts_dedupes_and_reads_cover(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        # 2 unique manga after de-dup (duplicate /manga/naruto-bc8 collapsed)
        assert len(results) == 2
        first = results[0]
        assert first.title == "Naruto"
        assert first.url == "https://mangavyvy.net/manga/naruto-bc8"
        assert first.cover_url == "https://cdnxyz.xyz/web/cover/841/thumbnail.png"

    def test_relative_urls_are_absolutised(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        assert all(r.url.startswith("https://mangavyvy.net/manga/") for r in results)

    def test_title_falls_back_to_img_alt(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        # The third fixture entry has no .comic-title, only img alt.
        assert any(r.title == "Boruto: Naruto Next Generations" for r in results)

    def test_no_results(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.search("nothing") == []


class TestGetChapters:
    def test_numbers_from_id_sorted_ascending_and_deduped(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        # 3 unique chapters (the duplicate chapter-1 href is collapsed)
        assert len(chapters) == 3
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Number comes from id="chapter-<num>", ignoring the "Vol.72" prefix text.
        assert [c.number for c in chapters] == ["1", "700", "700.5"]

    def test_decimal_chapter_detected(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        assert any(c.number == "700.5" for c in chapters)

    def test_chapter_url_is_the_redirect_href(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        assert all("aovheroes.com" in c.url for c in chapters)


class TestGetPages:
    def test_reads_carousel_and_skips_loading_and_related(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "chapter.html"))
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        # 3 reader pages; loading.gif skipped and the related-manga
        # collection thumbnail (outside #carousel) excluded.
        assert len(pages) == 3
        assert all("drive-storage" in p for p in pages)
        assert not any("loading" in p.lower() for p in pages)
        assert not any("collections" in p for p in pages)

    def test_preserves_page_order(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "chapter.html"))
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        assert pages == [
            "https://2.bp.blogspot.com/drive-storage/PAGE-001=w700",
            "https://2.bp.blogspot.com/drive-storage/PAGE-002=w700",
            "https://2.bp.blogspot.com/drive-storage/PAGE-003=w700",
        ]


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


class TestRegistry:
    @pytest.mark.parametrize("domain", ["mangavyvy.net", "vymanga.net", "www.vymanga.net"])
    def test_domains_resolve(self, domain):
        assert isinstance(get_scraper(domain), VyMangaScraper)
