"""HTML-fixture tests for WordPressMadaraScraper template family.

Biggest family — powers ~40 domains. Covers both single-manga and
aggregator modes, AJAX and HTML chapter loading, optional CDN filter,
and the no-filter "looks like an image" fallback.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.templates import WordPressMadaraScraper
from memanga.scrapers import get_scraper


def _make_scraper(**overrides):
    cls = type("TestMadara", (WordPressMadaraScraper,), {
        "base_url": "https://hiperdex.com",
        "manga_title": "",
        "manga_slug": "",
        "is_single_manga": False,
        "image_cdn_filters": ["img.spoilerhat.com"],
        "uses_cloudscraper": False,
        "uses_ajax": False,
        **overrides,
    })
    return cls()


class TestSearch:
    def test_aggregator_search(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("wp_madara", "search.html"))
        results = s.search("solo")
        # Two unique /manga/ URLs (dup dropped, about/ ignored)
        assert len(results) == 3
        titles = [r.title for r in results]
        assert "Solo Leveling" in titles
        assert "Tower of God" in titles
        # Relative href absolutized
        assert all(r.url.startswith("http") for r in results)

    def test_single_manga_short_circuits(self):
        s = _make_scraper(is_single_manga=True,
                           manga_title="Spy x Family",
                           manga_slug="spy-x-family")
        results = s.search("anything")
        assert len(results) == 1
        assert results[0].title == "Spy x Family"
        assert results[0].url.endswith("/manga/spy-x-family/")

    def test_search_capped_at_10(self, patch_html):
        s = _make_scraper()
        # Build a fixture with > 10 manga results
        items = "\n".join(
            f'<div class="post-title"><a href="/manga/series-{i}/">Series {i}</a></div>'
            for i in range(20)
        )
        html = f"<html><body>{items}</body></html>"
        patch_html(s, html)
        assert len(s.search("series")) == 10


class TestGetChaptersHTML:
    def test_parses_chapter_list(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("wp_madara", "manga_chapters.html"))
        chapters = s.get_chapters("https://hiperdex.com/manga/solo-leveling/")

        # Dedup
        urls = [c.url for c in chapters]
        assert len(urls) == len(set(urls))
        # Sorted newest-first
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums, reverse=True)
        # Numeric parsing
        assert any(c.number == "10.5" for c in chapters)
        # Relative URL absolutized
        assert all(c.url.startswith("http") for c in chapters)

    def test_uses_ajax_when_configured(self, monkeypatch, load_fixture, fake_response):
        s = _make_scraper(uses_ajax=True)
        ajax_html = load_fixture("wp_madara", "manga_chapters.html")
        monkeypatch.setattr(s.session, "post",
                             lambda *a, **k: fake_response(text=ajax_html))
        # Make sure HTML fallback wouldn't accidentally also fire
        monkeypatch.setattr(s, "_get_html", lambda *a, **k: "<html></html>")

        chapters = s.get_chapters("https://hiperdex.com/manga/solo-leveling/")
        assert len(chapters) >= 1

    def test_ajax_failure_falls_back_to_html(self, monkeypatch, patch_html,
                                              load_fixture, fake_response):
        s = _make_scraper(uses_ajax=True)
        # ajax POST returns non-200
        monkeypatch.setattr(s.session, "post",
                             lambda *a, **k: fake_response(text="", status=500))
        # HTML path returns fixture
        patch_html(s, load_fixture("wp_madara", "manga_chapters.html"))
        chapters = s.get_chapters("https://hiperdex.com/manga/solo-leveling/")
        assert chapters

    def test_no_chapters_returns_empty(self, patch_html):
        s = _make_scraper()
        patch_html(s, "<html><body></body></html>")
        assert s.get_chapters("https://hiperdex.com/manga/x/") == []


class TestGetPages:
    def test_extracts_with_cdn_filter(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("wp_madara", "chapter_reader.html"))
        pages = s.get_pages("https://hiperdex.com/manga/solo-leveling/chapter-1/")
        # Only img.spoilerhat.com images that have proper extensions
        # Logo (not in CDN filter) excluded, .svg excluded
        assert len(pages) == 3
        # Protocol-relative '//img.spoilerhat.com/...' got https: prefix
        assert all(p.startswith("https://") for p in pages)

    def test_no_filter_falls_back_to_image_extension(self, patch_html, load_fixture):
        s = _make_scraper(image_cdn_filters=[])
        patch_html(s, load_fixture("wp_madara", "chapter_reader_no_filter.html"))
        pages = s.get_pages("https://hiperdex.com/chapter-1/")
        # p1.jpg + p2.webp + p3.gif; favicon + avatar excluded
        assert len(pages) == 3
        assert all(any(ext in p for ext in (".jpg", ".webp", ".gif")) for p in pages)


# ──────────────────────────────────────────────────────────────────────
# Registry wiring spot-checks
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain", [
    "hiperdex.com", "mangaread.org", "manga18fx.com", "azmanga.com",
    "sxfmanga.net", "mashlemanga.net", "gutsberserk.com",
])
def test_madara_registry(domain):
    s = get_scraper(domain)
    assert isinstance(s, WordPressMadaraScraper)
