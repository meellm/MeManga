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

    def test_extracts_comizy_next_data(self, buddy, patch_html, load_fixture):
        # Issue #173: mangabuddy.com redirects to comizy.io, which ships
        # results in #__NEXT_DATA__ (props.pageProps.ssrItems).
        patch_html(buddy, load_fixture("playwright_html", "mangabuddy_search_next.html"))
        results = buddy.search("one piece")
        assert [r.title for r in results] == [
            "One Piece", "One Piece Academy", "One Piece Party",
        ]
        first = results[0]
        assert first.url == "https://mangabuddy.com/one-piece"
        assert first.cover_url == "https://rx.comizy.io/covers/475200263dfc.webp"
        assert "Pirate King" in first.description
        # Falls back to slug when url is missing; empty cover -> None
        assert results[2].url == "https://mangabuddy.com/one-piece-party"
        assert results[2].cover_url is None

    def test_next_data_capped_at_10(self, buddy, patch_html):
        items = ",".join(
            f'{{"url":"/series-{i}","name":"Series {i}"}}' for i in range(24)
        )
        patch_html(buddy, (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            f'{{"props":{{"pageProps":{{"ssrItems":[{items}]}}}}}}'
            "</script></body></html>"
        ))
        assert len(buddy.search("series")) == 10

    def test_empty_next_data_falls_back_to_legacy_cards(self, buddy, patch_html):
        patch_html(buddy, (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"ssrItems":[]}}}</script>'
            '<div class="book-item"><a href="/naruto"><img></a><h3>Naruto</h3></div>'
            "</body></html>"
        ))
        results = buddy.search("naruto")
        assert [r.title for r in results] == ["Naruto"]

    def test_query_is_url_encoded(self, buddy, monkeypatch):
        seen = []
        monkeypatch.setattr(buddy, "_get_html", lambda url: seen.append(url) or "<html></html>")
        assert buddy.search("fate/zero & more") == []
        assert seen == ["https://mangabuddy.com/search?q=fate%2Fzero+%26+more"]


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


class TestMangaBuddyNextPages:
    # Issue #173: chapter pages redirect to comizy.io, which embeds the
    # image URLs in #__NEXT_DATA__ (props.pageProps.initialChapter).
    @staticmethod
    def _html(chapter_json: str) -> str:
        return (
            '<html><body><img src="/logo.png">'
            '<script id="__NEXT_DATA__" type="application/json">'
            f'{{"props":{{"pageProps":{{"initialChapter":{chapter_json}}}}}}}'
            "</script></body></html>"
        )

    def test_reads_images_list(self, buddy):
        html = self._html(
            '{"images":["https://x9.cmzcdn.org/a/1.webp",'
            '"https://x9.cmzcdn.org/a/2.webp","https://x9.cmzcdn.org/a/1.webp"]}'
        )
        assert buddy._parse_next_pages(html) == [
            "https://x9.cmzcdn.org/a/1.webp",
            "https://x9.cmzcdn.org/a/2.webp",
        ]

    def test_falls_back_to_pages_url(self, buddy):
        html = self._html(
            '{"images":[],"pages":[{"url":"https://x9.cmzcdn.org/b/p1.webp"},'
            '{"url":"//x9.cmzcdn.org/b/p2.webp"},{"url":""},{"index":3}]}'
        )
        assert buddy._parse_next_pages(html) == [
            "https://x9.cmzcdn.org/b/p1.webp",
            "https://x9.cmzcdn.org/b/p2.webp",
        ]

    def test_missing_next_data_returns_empty(self, buddy):
        assert buddy._parse_next_pages("<html><body><img src='/1.jpg'></body></html>") == []
        assert buddy._parse_next_pages(self._html("null")) == []


class TestMangaBuddyDownload:
    def test_writes_file(self, monkeypatch, buddy, tmp_path, fake_response):
        monkeypatch.setattr(buddy.session, "get",
                             lambda *a, **k: fake_response(content=b"x" * 4096))
        ok = buddy.download_image("https://x", tmp_path / "p.jpg")
        assert ok is True

    def test_retries_with_comizy_referer(self, monkeypatch, buddy, tmp_path, fake_response):
        referers = []

        def get(url, headers=None, **k):
            referers.append(headers["Referer"])
            if headers["Referer"] != "https://comizy.io/":
                raise IOError("403")
            return fake_response(content=b"x" * 4096)

        monkeypatch.setattr(buddy.session, "get", get)
        assert buddy.download_image("https://x9.cmzcdn.org/p.webp", tmp_path / "p.webp") is True
        assert referers == ["https://mangabuddy.com/", "https://comizy.io/"]

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
