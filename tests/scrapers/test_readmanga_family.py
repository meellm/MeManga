"""HTML-fixture tests for the ReadManga base + its 10+ subclasses.

The ReadMangaBaseScraper powers ReadSNK, ReadBerserk, ReadHaikyuu,
ReadJujutsuKaisen, ReadChainsawMan, ReadOnePiece, ReadNaruto, ReadMHA,
ReadFairyTail, ReadBlackClover.

We exercise the base methods + spot-check that the subclasses inherit
correctly and stay reachable from get_scraper().
"""

from __future__ import annotations

import pytest

from memanga.scrapers.readmanga_base import ReadMangaBaseScraper
from memanga.scrapers import get_scraper


def _make_scraper(**overrides):
    cls = type("TestReadManga", (ReadMangaBaseScraper,), {
        "base_url": "https://readsnk.com",
        "cdn_pattern": "",
        **overrides,
    })
    return cls()


class TestMakeAbsolute:
    def test_returns_input_when_absolute(self):
        s = _make_scraper()
        assert s._make_absolute("https://x.com/path") == "https://x.com/path"

    def test_prepends_base_for_root_relative(self):
        s = _make_scraper()
        assert s._make_absolute("/foo/bar") == "https://readsnk.com/foo/bar"

    def test_prepends_base_for_bare_relative(self):
        s = _make_scraper()
        assert s._make_absolute("foo/bar") == "https://readsnk.com/foo/bar"

    def test_empty_returns_empty(self):
        s = _make_scraper()
        assert s._make_absolute("") == ""


class TestSearch:
    def test_extracts_manga_links_dedupes_and_caps(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("readmanga", "search.html"))
        results = s.search("snk")
        # 2 unique manga results (about page excluded)
        assert len(results) == 2
        assert all("/manga/" in r.url for r in results)
        # Both URLs absolutized
        assert all(r.url.startswith("http") for r in results)


class TestGetChapters:
    def test_dedupes_and_sorts_descending(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("readmanga", "manga.html"))
        chapters = s.get_chapters("https://readsnk.com/manga/snk")
        # 4 unique chapters (ch 2 dup deduped)
        urls = [c.url for c in chapters]
        assert len(urls) == len(set(urls))
        # Sorted descending (newest first)
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums, reverse=True)
        # Decimal chapter handled
        assert any(c.number == "100.5" for c in chapters)


class TestGetPages:
    def test_filters_cdn_patterns(self, patch_html, load_fixture):
        s = _make_scraper()
        patch_html(s, load_fixture("readmanga", "chapter.html"))
        pages = s.get_pages("https://readsnk.com/chapter/snk-chapter-1/")
        # Only CDN-matching images: cdn.readsnk.com/file, cdn.readmanga/mangap,
        # AnimeRleases. Random example.com excluded.
        assert len(pages) >= 3
        assert not any("example.com/random" in p for p in pages)

    def test_custom_cdn_pattern_is_used(self, patch_html):
        s = _make_scraper(cdn_pattern=r"images\.bespoke\.com")
        html = """<html><body>
            <img src="https://images.bespoke.com/p1.jpg">
            <img src="https://otherhost.com/p2.jpg">
        </body></html>"""
        patch_html(s, html)
        pages = s.get_pages("x")
        assert len(pages) == 1
        assert "images.bespoke.com" in pages[0]


class TestIsMangaImage:
    @pytest.mark.parametrize("url,expected", [
        ("", False),
        ("https://cdn.readsnk.com/file/x.jpg", True),
        ("https://cdn.manga.example/x.jpg", True),
        ("https://example.com/mangap/x.jpg", True),
        ("https://example.com/foo.jpg", False),
        ("https://AnimeRleases.com/x.png", True),
    ])
    def test_pattern_recognition(self, url, expected):
        s = _make_scraper()
        assert s._is_manga_image(url) is expected


class TestDownloadImage:
    def test_writes_file_on_success(self, monkeypatch, tmp_path, fake_response):
        s = _make_scraper()
        monkeypatch.setattr(s.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 4096))
        ok = s.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").exists()

    def test_failure_returns_false(self, monkeypatch, tmp_path):
        s = _make_scraper()
        def boom(*a, **k):
            raise IOError()
        monkeypatch.setattr(s.session, "get", boom)
        assert s.download_image("https://x", tmp_path / "p.jpg") is False


# ──────────────────────────────────────────────────────────────────────
# Subclass coverage — every ReadXxx scraper resolves and inherits the
# base. Catches typos in subclass declarations + registry wiring.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain", [
    "readsnk.com",
    "readberserk.com",
    "readhaikyuu.com",
    "readjujutsukaisen.com",
    "readchainsawman.com",
    "readonepiece.com",
    "readnaruto.com",
    "readmha.com",
    "readfairytail.com",
    "readblackclover.com",
])
def test_readmanga_subclass_wiring(domain):
    s = get_scraper(domain)
    assert isinstance(s, ReadMangaBaseScraper)
    assert s.base_url.startswith("http")
