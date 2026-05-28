"""HTML-fixture tests for LaiondCDNScraper template family.

Powers ~16 single-manga sites that use laiond.com / loinew.com CDNs.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.templates import LaiondCDNScraper
from memanga.scrapers import get_scraper


def _make_scraper(**overrides):
    cls = type("TestLaiond", (LaiondCDNScraper,), {
        "base_url": "https://overlord-manga.online",
        "manga_title": "Overlord",
        "chapter_link_pattern": r'chapter-?\d+',
        "cdn_domains": ["laiond.com"],
        "uses_cloudscraper": False,
        "url_path_prefix": "comic",
        **overrides,
    })
    return cls()


class TestSearch:
    def test_returns_single_manga(self):
        s = _make_scraper()
        results = s.search("anything")
        assert len(results) == 1
        assert results[0].title == "Overlord"
        assert results[0].url == "https://overlord-manga.online/"


class TestGetChapters:
    def test_uses_dropdown_when_present(self, patch_html, load_fixture):
        s = _make_scraper(base_url="https://detective-conan-manga.online",
                          manga_title="Detective Conan")
        patch_html(s, load_fixture("laiond_cdn", "homepage_dropdown.html"))
        chapters = s.get_chapters("https://detective-conan-manga.online/")
        # 3 real chapters + 1 relative-URL chapter = 4
        assert len(chapters) == 4
        # '#' and the non-chapter "about" entry must be filtered out
        assert all("/about" not in c.url for c in chapters)
        # Newest first
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums, reverse=True)
        # Relative URL absolutized
        assert all(c.url.startswith("http") for c in chapters)

    def test_falls_back_to_link_extraction(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("laiond_cdn", "homepage_links.html"))
        chapters = s.get_chapters("https://overlord-manga.online/")
        # 3 chapters with text (empty-text and about/ filtered out)
        assert len(chapters) == 3
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums, reverse=True)
        assert chapters[0].number == "50"


class TestGetPages:
    def test_filters_to_cdn_and_skips_thumbnails(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("laiond_cdn", "chapter.html"))
        pages = s.get_pages("https://overlord-manga.online/chapter-1/")
        # 3 real pages; 2 thumbnails + non-CDN + data: scheme excluded
        assert len(pages) == 3
        assert all("laiond.com" in p for p in pages)
        # No thumbnail sizes
        assert not any("32x32" in p or "192x192" in p for p in pages)

    def test_custom_cdn_domains(self, patch_html):
        s = _make_scraper(cdn_domains=["loinew.com"])
        html = """<html><body>
            <img src="https://cdn.loinew.com/1.jpg">
            <img src="https://cdn.laiond.com/2.jpg">
        </body></html>"""
        patch_html(s, html)
        pages = s.get_pages("x")
        assert len(pages) == 1
        assert "loinew.com" in pages[0]


@pytest.mark.parametrize("domain", [
    "overlord-manga.online", "rezero-manga.online", "goblin-slayer-manga.online",
    "witch-hat-atelier.online", "detective-conan-manga.online",
])
def test_laiond_registry(domain):
    s = get_scraper(domain)
    assert isinstance(s, LaiondCDNScraper)
