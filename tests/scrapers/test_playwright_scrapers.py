"""HTML-fixture tests for Playwright-based scrapers.

Playwright itself is never invoked here — these tests only exercise
the HTML-parsing portions of each scraper (search + get_chapters,
which usually go through self._get_html) by injecting fixture HTML.

The browser-driven get_pages paths are NOT tested in this file
because they require a real Firefox install; we just confirm those
methods exist on each scraper.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.mangabuddy import MangaBuddyScraper
from memanga.scrapers.comix import ComixScraper
from memanga.scrapers import get_scraper


# ──────────────────────────────────────────────────────────────────────
# MangaBuddy — represents the largest single Playwright scraper.
# Search + chapters parse HTML (testable); pages uses Playwright (not
# tested here).
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def buddy():
    return MangaBuddyScraper()


class TestMangaBuddySearch:
    def test_extracts_items_with_covers(self, buddy, patch_html, load_fixture):
        patch_html(buddy, load_fixture("playwright_html", "mangabuddy_search.html"))
        results = buddy.search("one piece")
        assert len(results) == 3
        titles = [r.title for r in results]
        assert "One Piece" in titles
        assert "Naruto" in titles
        # Relative href absolutized
        assert all(r.url.startswith("http") for r in results)

    def test_capped_at_10(self, buddy, patch_html):
        items = "\n".join(
            f'<div class="book-item"><a href="/manga/x-{i}"><img></a><h3>Series {i}</h3></div>'
            for i in range(20)
        )
        patch_html(buddy, f"<html><body>{items}</body></html>")
        assert len(buddy.search("series")) == 10


class TestMangaBuddyChapters:
    def test_dedupes_and_sorts(self, buddy, patch_html, load_fixture):
        patch_html(buddy, load_fixture("playwright_html", "mangabuddy_manga.html"))
        chapters = buddy.get_chapters("https://mangabuddy.com/manga/one-piece")
        # 4 unique chapters (about/ filtered, chapter-1 dup removed)
        urls = [c.url for c in chapters]
        assert len(urls) == len(set(urls))
        # Sorted ascending by numeric
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Decimal preserved
        assert any(c.number == "15.5" for c in chapters)


class TestMangaBuddyDownload:
    def test_writes_file(self, monkeypatch, buddy, tmp_path, fake_response):
        monkeypatch.setattr(buddy.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 4096))
        ok = buddy.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True

    def test_failure_returns_false(self, monkeypatch, buddy, tmp_path):
        def boom(*a, **k):
            raise IOError()
        monkeypatch.setattr(buddy.session, "get", boom)
        assert buddy.download_image("https://x", tmp_path / "p.jpg") is False


# ──────────────────────────────────────────────────────────────────────
# Comix.to
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def comix():
    return ComixScraper()


class TestComixSearch:
    def test_extracts_rendered_title_links(self, comix):
        html = """
        <a href="/title/45nl-kubera"><img src="https://static.comix.to/k.jpg"></a>
        <a href="/title/45nl-kubera">Kubera</a>
        <a href="/title/793e-arelyn-is-sick-and-tired">Arelyn Is Sick and Tired</a>
        """
        results = comix._parse_search_html(html)
        assert [r.title for r in results] == [
            "Kubera",
            "Arelyn Is Sick and Tired",
        ]
        assert results[0].url == "https://comix.to/title/45nl-kubera"
        assert results[0].cover_url == "https://static.comix.to/k.jpg"


class TestComixChapters:
    def test_extracts_chapter_rows(self, comix):
        html = """
        <a class="mchap-row__primary"
           href="/title/45nl-kubera/10512172-chapter-705">Ch.705 S3-423</a>
        <a class="mchap-row__primary"
           href="/title/45nl-kubera/10308843-chapter-704">Ch.704 S3-422</a>
        """
        chapters = comix._parse_chapters_html(html)
        assert [c.number for c in chapters] == ["705", "704"]
        assert chapters[0].title == "S3-423"
        assert chapters[0].url == (
            "https://comix.to/title/45nl-kubera/10512172-chapter-705"
        )


# ──────────────────────────────────────────────────────────────────────
# Smoke tests: every Playwright-based scraper imports + instantiates +
# exposes the required methods. This catches typos and missing-import
# bugs without paying the cost of spinning up a browser.
# ──────────────────────────────────────────────────────────────────────


PLAYWRIGHT_DOMAINS = [
    "weebcentral.com",
    "asuracomic.net",
    "mangakatana.com",
    "mangafire.to",
    "mangasee123.com",
    "mangabuddy.com",
    "mangataro.org",
    "flamecomics.xyz",
    "luminousscans.com",
    "mangahere.cc",
    "mangaeffect.com",
    "manhuaplus.org",
    "manhwa18.cc",
    "mangahub.io",
    "mangatown.com",
    "manhuaus.org",
    "comick.io",
    "comix.to",
    "fanfox.net",
    "toonily.me",
    "omegascans.org",
    "hivetoons.org",
    "mangayy.org",
    "manga4life.com",
    "isekaiscan.com",
    "zinmanga.com",
    "zazamanga.com",
    "mangaball.net",
    "mangaclash.com",
    "kunmanga.com",
    "manytoon.com",
    "pururin.to",
    "hentairead.com",
    "manganato.gg",
    "mangahere.onl",
]


@pytest.mark.parametrize("domain", PLAYWRIGHT_DOMAINS)
def test_playwright_scraper_instantiates_and_has_required_api(domain):
    s = get_scraper(domain)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method)), f"{domain} missing {method}"
