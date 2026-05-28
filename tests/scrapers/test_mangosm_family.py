"""HTML-fixture tests for MangosmScraper template family.

Powers 7+ single-manga sites that use the Mangosm WordPress theme.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.templates import MangosmScraper
from memanga.scrapers import get_scraper


def _make_scraper(**overrides):
    cls = type("TestMangosm", (MangosmScraper,), {
        "base_url": "https://hxhmanga.com",
        "manga_title": "Hunter x Hunter",
        "manga_slug": "hunter-x-hunter",
        "cdn_domains": ["images.mangafreak.me"],
        "cdn_referer": "https://mangafreak.me/",
        **overrides,
    })
    return cls()


class TestSearch:
    def test_returns_single_manga(self):
        s = _make_scraper()
        results = s.search("anything")
        assert len(results) == 1
        assert results[0].title == "Hunter x Hunter"
        assert results[0].url.endswith("/")


class TestGetChapters:
    def test_dropdown_first(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("mangosm", "homepage_dropdown.html"))
        chapters = s.get_chapters("https://hxhmanga.com/")
        # 3 chapters; '#' filtered
        assert len(chapters) == 3
        assert any(c.number == "12.5" for c in chapters)
        # Newest first
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums, reverse=True)

    def test_link_fallback(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("mangosm", "homepage_links.html"))
        chapters = s.get_chapters("https://hxhmanga.com/")
        # 3 abs chapters + 1 relative = 4
        assert len(chapters) == 4
        assert all(c.url.startswith("http") for c in chapters)


class TestGetPages:
    def test_extracts_cdn_and_uploads_fallback(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("mangosm", "chapter.html"))
        pages = s.get_pages("https://hxhmanga.com/hunter-x-hunter-chapter-1/")
        # 3 CDN images + 1 wp-content/uploads fallback (logo skipped, otherhost skipped)
        assert len(pages) == 4
        # Logo filtered
        assert not any("logo" in p.lower() for p in pages)
        # No host outside cdn or wp-content
        assert all("mangafreak.me" in p or "wp-content/uploads" in p
                    for p in pages)


@pytest.mark.parametrize("domain", [
    "readblacklagoon.com", "hxhmanga.com", "jujutsukaisenmodulo.org",
    "kagurabachi-manga.com",
])
def test_mangosm_registry(domain):
    s = get_scraper(domain)
    assert isinstance(s, MangosmScraper)
