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
from memanga.scrapers.batoto import BatoToScraper
from memanga.scrapers.wto import WTOScraper, _is_cf_challenge
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
# WTO (wto.to) - Bato mirror. Parsing is inherited from BatoToScraper;
# only the transport differs (Playwright, for the Cloudflare managed
# challenge). Tests inject fixture HTML through _get_html, so they
# exercise the exact parser wto.to relies on.
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def wto():
    return WTOScraper()


class TestWTORegistry:
    def test_wto_domain_resolves_to_wto_scraper(self):
        s = get_scraper("wto.to")
        assert isinstance(s, WTOScraper)
        assert s.base_url == "https://wto.to"

    def test_wto_reuses_bato_parser(self):
        assert issubclass(WTOScraper, BatoToScraper)

    def test_bato_domains_unaffected(self):
        # Mirror registration must not reroute or re-base the originals.
        for domain in ("bato.to", "batoto.to"):
            s = get_scraper(domain)
            assert type(s) is BatoToScraper
            assert s.base_url == "https://bato.to"


class TestWTOSearch:
    def test_parses_bato_series_cards(self, wto, patch_html, load_fixture):
        patch_html(wto, load_fixture("playwright_html", "wto_search.html"))
        results = wto.search("one piece")
        titles = [r.title for r in results]
        assert "One Piece" in titles
        assert "Naruto" in titles
        # Relative /series/ hrefs absolutized against the MIRROR domain
        assert all(r.url.startswith("https://wto.to/series/") for r in results)
        # Non-series links filtered out
        assert not any("/browse" in r.url for r in results)

    def test_dedupes_cover_and_text_links(self, wto, patch_html, load_fixture):
        patch_html(wto, load_fixture("playwright_html", "wto_search.html"))
        results = wto.search("one piece")
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls))
        assert len(results) == 3


class TestWTOChapters:
    def test_dedupes_and_sorts(self, wto, patch_html, load_fixture):
        patch_html(wto, load_fixture("playwright_html", "wto_manga.html"))
        chapters = wto.get_chapters("https://wto.to/series/72315/one-piece")
        urls = [c.url for c in chapters]
        assert len(urls) == len(set(urls))
        assert len(chapters) == 3
        # Ascending numeric order, decimal preserved
        assert [c.number for c in chapters] == ["1099", "1099.5", "1100"]
        # Relative /chapter/ hrefs absolutized against the mirror
        assert all(u.startswith("https://wto.to/chapter/") for u in urls)


class TestWTOPages:
    def test_extracts_image_urls_from_script(self, wto, patch_html):
        html = """
        <html><body>
        <script>
        const imgList = ["https://xfs-n01.xfsbb.com/comic/7002/chapter-1100/001.webp",
                         "https://xfs-n01.xfsbb.com/comic/7002/chapter-1100/002.png"];
        </script>
        </body></html>
        """
        patch_html(wto, html)
        pages = wto.get_pages("https://wto.to/chapter/2600003")
        assert len(pages) == 2
        assert all(p.startswith("https://") for p in pages)


class TestWTOCloudflareFallback:
    CHALLENGE = "<html><head><title>Just a moment...</title></head></html>"
    MANAGED = """
    <html><body>
    <h1>Performing security verification</h1>
    <div class="cf-turnstile"></div>
    <p>Ray ID: abc123</p>
    </body></html>
    """
    REAL = "<html><body><div class='item-text'></div></body></html>"

    def test_detects_challenge_markup(self):
        assert _is_cf_challenge(self.CHALLENGE) is True
        assert _is_cf_challenge(self.MANAGED) is True
        assert _is_cf_challenge(self.REAL) is False

    def test_retries_once_with_longer_wait(self, monkeypatch, wto):
        calls = []
        def fake_fetch(url, wait_time=0, **kwargs):
            calls.append(wait_time)
            return self.CHALLENGE if len(calls) == 1 else self.REAL
        monkeypatch.setattr(wto, "_get_page_content", fake_fetch)
        html = wto._get_html("https://wto.to/search?word=x")
        assert html == self.REAL
        assert len(calls) == 2
        assert calls[1] > calls[0]

    def test_persistent_challenge_degrades_to_empty_results(
            self, monkeypatch, wto):
        monkeypatch.setattr(wto, "_get_page_content",
                             lambda *a, **k: self.CHALLENGE)
        # No crash; parsers just find nothing in the interstitial.
        assert wto.search("one piece") == []


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
    "wto.to",
]


@pytest.mark.parametrize("domain", PLAYWRIGHT_DOMAINS)
def test_playwright_scraper_instantiates_and_has_required_api(domain):
    s = get_scraper(domain)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method)), f"{domain} missing {method}"
