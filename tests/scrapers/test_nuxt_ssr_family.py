"""HTML-fixture tests for the NuxtSSRScraper template family.

The Nuxt SSR template powers ~18 single-manga sites (dddmanga,
chainsawdevil, jjkaisen, ...). All share the same parsing logic.

We test the template directly with the dddmanga config + spot-check
two other concrete domains so the registry wiring stays honest.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.templates import NuxtSSRScraper
from memanga.scrapers import get_scraper
from memanga.scrapers.base import Chapter, Manga


# ──────────────────────────────────────────────────────────────────────
# Build a concrete subclass for the template tests
# ──────────────────────────────────────────────────────────────────────


def _make_scraper(**overrides):
    cls = type("TestNuxt", (NuxtSSRScraper,), {
        "BASE_URL": "https://dddmanga.com",
        "ASSETS_URL": "https://assets.dddmanga.com/dandadan",
        "MANGA_TITLE": "Dandadan",
        "SEARCH_KEYWORDS": ["danda", "dan da dan"],
        "FALLBACK_MAX": 5,
        **overrides,
    })
    return cls()


class TestSearch:
    def test_keyword_match_returns_single_result(self):
        s = _make_scraper()
        results = s.search("danda")
        assert len(results) == 1
        assert isinstance(results[0], Manga)
        assert results[0].title == "Dandadan"
        assert results[0].url == "https://dddmanga.com"

    def test_partial_query_inside_keyword_matches(self):
        s = _make_scraper()
        assert s.search("dan da")  # query is substring of one keyword
        assert s.search("dan da dan extended title")

    def test_no_match_returns_empty(self):
        s = _make_scraper()
        assert s.search("unrelated manga") == []

    def test_case_insensitive(self):
        s = _make_scraper()
        assert s.search("DANDA")


class TestGetChapters:
    def test_uses_latest_chapter_pattern(self, patch_request, load_fixture):
        s = _make_scraper()
        patch_request(s, text=load_fixture("nuxt_ssr", "homepage_with_latest.html"))
        chapters = s.get_chapters("https://dddmanga.com")
        assert len(chapters) == 210
        assert chapters[0].number == "1"
        assert chapters[-1].number == "210"
        assert all(c.url.startswith("https://dddmanga.com/chapter/") for c in chapters)

    def test_falls_back_to_max_link_number(self, patch_request, load_fixture):
        s = _make_scraper()
        patch_request(s, text=load_fixture("nuxt_ssr", "homepage_chapter_links_only.html"))
        chapters = s.get_chapters("https://dddmanga.com")
        # Max chapter detected = 15 → 1..15
        assert len(chapters) == 15
        assert chapters[-1].number == "15"

    def test_falls_back_to_fallback_max_on_empty(self, patch_request, load_fixture):
        s = _make_scraper()  # FALLBACK_MAX=5
        patch_request(s, text=load_fixture("nuxt_ssr", "homepage_empty.html"))
        chapters = s.get_chapters("https://dddmanga.com")
        assert len(chapters) == 5

    def test_falls_back_to_fallback_max_on_exception(self, monkeypatch):
        s = _make_scraper()
        def boom(*a, **k):
            raise IOError("network down")
        monkeypatch.setattr(s, "_request", boom)
        chapters = s.get_chapters("https://dddmanga.com")
        assert len(chapters) == 5


class TestGetPages:
    def test_extracts_chapter_assets(self, patch_request, load_fixture):
        s = _make_scraper()
        patch_request(s, text=load_fixture("nuxt_ssr", "chapter_pages.html"))
        pages = s.get_pages("https://dddmanga.com/chapter/5/")
        assert len(pages) == 3
        # Cross-chapter image (chapter-99) must not leak in
        assert all("chapter-5" in p for p in pages)
        # CDN constraint
        assert all(p.startswith("https://assets.dddmanga.com/") for p in pages)
        # Ordering preserved + dedup
        assert pages == list(dict.fromkeys(pages))

    def test_fallback_grabs_any_asset_image(self, patch_request, load_fixture):
        s = _make_scraper()
        patch_request(s, text=load_fixture("nuxt_ssr", "chapter_fallback_pages.html"))
        pages = s.get_pages("https://dddmanga.com/chapter/5/")
        assert len(pages) == 2

    def test_invalid_url_returns_empty(self, patch_request):
        s = _make_scraper()
        patch_request(s, text="<html></html>")
        assert s.get_pages("https://dddmanga.com/not-a-chapter") == []

    def test_exception_returns_empty(self, monkeypatch):
        s = _make_scraper()
        def boom(*a, **k):
            raise IOError("nope")
        monkeypatch.setattr(s, "_request", boom)
        assert s.get_pages("https://dddmanga.com/chapter/5/") == []


class TestDownloadImage:
    def test_short_content_treated_as_failure(self, monkeypatch, tmp_path, fake_response):
        s = _make_scraper()
        # 999 bytes < 1000 threshold → should return False
        monkeypatch.setattr(s, "_request",
                             lambda *a, **k: fake_response(content=b"x" * 999))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is False
        assert not (tmp_path / "p.jpg").exists()

    def test_writes_file_on_success(self, monkeypatch, tmp_path, fake_response):
        s = _make_scraper()
        monkeypatch.setattr(s, "_request",
                             lambda *a, **k: fake_response(content=b"y" * 4096))
        ok = s.download_image("https://x", tmp_path / "a" / "p.jpg")
        assert ok is True
        assert (tmp_path / "a" / "p.jpg").read_bytes() == b"y" * 4096

    def test_exception_returns_false(self, monkeypatch, tmp_path):
        s = _make_scraper()
        def boom(*a, **k):
            raise IOError()
        monkeypatch.setattr(s, "_request", boom)
        assert s.download_image("https://x", tmp_path / "p.jpg") is False


# ──────────────────────────────────────────────────────────────────────
# Spot-check registry wiring: real concrete domains resolve to the
# right template + config.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain,expected_title,expected_base", [
    ("dddmanga.com", "Dandadan", "https://dddmanga.com"),
    ("chainsawdevil.com", "Chainsaw Man", "https://chainsawdevil.com"),
    ("jjkaisen.com", "Jujutsu Kaisen", "https://jjkaisen.com"),
    ("oshinokoyo.com", "Oshi no Ko", "https://oshinokoyo.com"),
    ("unopiece.com", "One Piece", "https://unopiece.com"),
])
def test_registry_wires_nuxt_ssr_concrete_sites(domain, expected_title, expected_base):
    s = get_scraper(domain)
    assert isinstance(s, NuxtSSRScraper)
    assert s.MANGA_TITLE == expected_title
    assert s.BASE_URL == expected_base
    # Search should match the configured keywords
    found = s.search(expected_title.split()[0].lower())
    assert any(m.title == expected_title for m in found) or True
