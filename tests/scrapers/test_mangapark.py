"""HTML/JSON-fixture tests for MangaParkScraper (mangapark1.com)."""

from __future__ import annotations

import pytest

from memanga.scrapers.mangapark import MangaParkScraper


@pytest.fixture
def scraper():
    return MangaParkScraper()


class TestSearch:
    def test_parses_units_and_dedupes(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "search.html"))
        results = scraper.search("one piece")
        # 3 unique manga URLs after dedup of the repeated one-piece card
        assert len(results) == 3
        by_url = {r.url: r for r in results}
        assert "https://mangapark1.com/manga/one-piece" in by_url
        assert by_url["https://mangapark1.com/manga/one-piece"].title == "One Piece"
        assert by_url["https://mangapark1.com/manga/one-piece"].cover_url == \
            "https://cdn2.holdingyouclose.xyz/thumb/one-piece.webp"

    def test_title_falls_back_to_img_alt(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "search.html"))
        results = scraper.search("chopper")
        titles = [r.title for r in results]
        # Card with no info-block text link uses the cover alt text
        assert "Chopperman - Yuke Yuke! Minna no Chopper-sensei" in titles

    def test_no_results(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.search("nothing") == []


class TestGetChapters:
    def test_uses_json_endpoint(self, scraper, patch_json, load_json_fixture):
        patch_json(scraper, load_json_fixture("mangapark", "chapter_list.json"))
        chapters = scraper.get_chapters("https://mangapark1.com/manga/one-piece")
        # 4 unique chapters after dedup of the repeated chapter-1 entry
        assert len(chapters) == 4
        # Sorted ascending
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Integer-valued floats normalised: 1.0 -> "1"
        assert chapters[0].number == "1"
        # Decimal chapters preserved
        assert any(c.number == "10.5" for c in chapters)
        # URLs built from slug + chapter_slug
        assert chapters[-1].url == \
            "https://mangapark1.com/read/one-piece/chapter-1187"
        assert chapters[-1].date == "2026-07-03 03:21:33"

    def test_falls_back_to_html_when_endpoint_fails(
            self, scraper, monkeypatch, patch_html, load_fixture):
        def boom(*a, **k):
            raise IOError("endpoint down")
        monkeypatch.setattr(scraper, "_get_json", boom)
        patch_html(scraper, load_fixture("mangapark", "manga.html"))
        chapters = scraper.get_chapters("https://mangapark1.com/manga/one-piece")
        assert len(chapters) == 3
        assert any(c.number == "10.5" for c in chapters)
        assert all("/read/one-piece/" in c.url for c in chapters)

    def test_rejects_non_manga_url(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters("https://mangapark1.com/blog")


class TestGetPages:
    def test_extracts_cdn_urls_skips_placeholders(
            self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "chapter.html"))
        pages = scraper.get_pages(
            "https://mangapark1.com/read/one-piece/chapter-1")
        # 3 unique pages: duplicate and /assets/ placeholder excluded
        assert pages == [
            "https://cdn2.holdingyouclose.xyz/one-piece/1/0.webp",
            "https://cdn2.holdingyouclose.xyz/one-piece/1/1.webp",
            "https://cdn2.holdingyouclose.xyz/one-piece/1/2.webp",
        ]

    def test_no_pages(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.get_pages("https://mangapark1.com/read/x/chapter-1") == []


class TestDownloadImage:
    def test_sends_referer_and_writes_file(
            self, monkeypatch, scraper, tmp_path, fake_response):
        captured = {}

        def fake_request(url, **kwargs):
            captured.update(kwargs)
            return fake_response(content=b"imgdata" * 100)

        monkeypatch.setattr(scraper, "_request", fake_request)
        ok = scraper.download_image(
            "https://cdn2.holdingyouclose.xyz/one-piece/1/0.webp",
            tmp_path / "p.webp")
        assert ok is True
        assert (tmp_path / "p.webp").read_bytes() == b"imgdata" * 100
        assert captured["headers"]["Referer"] == "https://mangapark1.com/"

    def test_failure_returns_false(self, monkeypatch, scraper, tmp_path):
        def boom(*a, **k):
            raise IOError("nope")
        monkeypatch.setattr(scraper, "_request", boom)
        assert scraper.download_image("https://x", tmp_path / "p.webp") is False


class TestRegistry:
    def test_domain_resolves_to_scraper(self):
        from memanga.scrapers import get_scraper
        s = get_scraper("mangapark1.com")
        assert isinstance(s, MangaParkScraper)

    def test_www_prefix_resolves(self):
        from memanga.scrapers import get_scraper
        s = get_scraper("www.mangapark1.com")
        assert isinstance(s, MangaParkScraper)
