"""HTML-fixture tests for the OGImageMetaScraper template family.

Powers ~30 single-manga sites that host on Blogger / Comic Easel and
expose images via og:image meta tags or img tags. We exercise the
template with a frieren-manga-like config + spot-check the registry.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.templates import OGImageMetaScraper
from memanga.scrapers import get_scraper


def _make_scraper(**overrides):
    cls = type("TestOG", (OGImageMetaScraper,), {
        "base_url": "https://akiramanga.com",
        "manga_title": "Akira",
        "chapter_link_pattern": r'chapter-?\d+',
        "image_cdn_filters": ["blogger.googleusercontent.com"],
        "cover_url": "https://akiramanga.com/cover.jpg",
        "normalize_blogger": True,
        **overrides,
    })
    return cls()


class TestSearch:
    def test_returns_single_configured_manga(self):
        s = _make_scraper()
        results = s.search("anything goes")
        assert len(results) == 1
        assert results[0].title == "Akira"
        assert results[0].url.startswith("https://akiramanga.com")
        assert results[0].cover_url == "https://akiramanga.com/cover.jpg"


class TestGetChapters:
    def test_extracts_chapters_with_dedup_and_sort(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("og_image_meta", "homepage.html"))
        chapters = s.get_chapters("https://akiramanga.com/")

        numbers = [c.number for c in chapters]
        # Sorted descending (newest first)
        assert numbers == sorted(numbers, key=float, reverse=True)
        # Dedup
        assert len(set(numbers)) == len(numbers)
        # Empty-text and non-chapter links are skipped
        assert all("about" not in c.url for c in chapters)
        # Relative URL got absolutized
        assert all(c.url.startswith("http") for c in chapters)

    def test_no_chapters_returns_empty(self, patch_html):
        s = _make_scraper()
        patch_html(s, "<html><body></body></html>")
        assert s.get_chapters("https://akiramanga.com/") == []


class TestGetPages:
    def test_primary_extraction_from_img_tags(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("og_image_meta", "chapter_blogger.html"))
        pages = s.get_pages("https://akiramanga.com/chapter-1/")
        assert len(pages) == 3
        # Blogger URLs got normalized to /s1600/
        assert all("/s1600/" in p for p in pages)
        # data: scheme and non-CDN images excluded
        assert all("blogger.googleusercontent.com" in p for p in pages)

    def test_fallback_to_meta_tags_when_no_imgs(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("og_image_meta", "chapter_meta_only.html"))
        pages = s.get_pages("https://akiramanga.com/chapter-1/")
        assert len(pages) == 2
        # Both meta URLs normalized
        assert all("/s1600/" in p for p in pages)

    def test_blogger_normalization_disabled(self, patch_html, load_fixture):
        s = _make_scraper(normalize_blogger=False)
        patch_html(s, load_fixture("og_image_meta", "chapter_blogger.html"))
        pages = s.get_pages("https://akiramanga.com/chapter-1/")
        # Should keep original resolutions like /s320/
        assert any("/s320/" in p or "/w320-h480/" in p or "/s640/" in p
                    for p in pages)


class TestCDNFilter:
    def test_data_scheme_excluded(self):
        s = _make_scraper()
        assert not s._is_cdn_image("data:image/png;base64,AAAA")

    def test_no_filters_means_nothing_passes(self):
        s = _make_scraper(image_cdn_filters=[])
        assert not s._is_cdn_image("https://anything.com/foo.jpg")

    def test_case_insensitive_match(self):
        s = _make_scraper(image_cdn_filters=["BLOGGER"])
        assert s._is_cdn_image("https://blogger.googleusercontent.com/x.jpg")


class TestDownloadImage:
    def test_short_content_treated_as_failure(self, monkeypatch, tmp_path, fake_response):
        s = _make_scraper()
        monkeypatch.setattr(s.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 100))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is False

    def test_writes_to_disk(self, monkeypatch, tmp_path, fake_response):
        s = _make_scraper()
        monkeypatch.setattr(s.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 4096))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").exists()


# ──────────────────────────────────────────────────────────────────────
# Registry wiring spot-checks
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain,title", [
    ("akiramanga.com", "Akira"),
    ("trigunmanga.com", "Trigun"),
    ("beckmanga.com", "Beck: Mongolian Chop Squad"),
    ("readclaymore.com", "Claymore"),
])
def test_og_image_meta_registry(domain, title):
    s = get_scraper(domain)
    assert isinstance(s, OGImageMetaScraper)
    assert s.manga_title == title
