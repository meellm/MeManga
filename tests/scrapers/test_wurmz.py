"""HTML-fixture tests for the Wurmz scraper.

The network-facing helper (``_request``) is replaced with a fake here -
these tests exercise only the parsing and URL handling, using markup
trimmed from the live ``wurmz.net`` search, series and reader pages.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.wurmz import WurmzScraper


@pytest.fixture
def wz():
    return WurmzScraper()


class FakeResponse:
    def __init__(self, body: str):
        self.text = body


def _fake_request(wz, monkeypatch, body):
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(body)

    monkeypatch.setattr(wz, "_request", fake)
    return calls


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("wurmz.net")
    assert isinstance(s, WurmzScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


def test_www_host_resolves():
    assert isinstance(get_scraper("www.wurmz.net"), WurmzScraper)


# URL helpers


class TestUrlHelpers:
    def test_parse_series_url(self):
        assert WurmzScraper._parse_series_url(
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo"
        ) == ("manhwa", "pendekar-pedang-solo")
        assert WurmzScraper._parse_series_url(
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/20"
        ) == ("manhwa", "pendekar-pedang-solo")
        assert WurmzScraper._parse_series_url(
            "/detail/manga/solois-dalam-sangkar?x=1"
        ) == ("manga", "solois-dalam-sangkar")

    def test_parse_series_url_rejects_non_series(self):
        assert WurmzScraper._parse_series_url("https://wurmz.net/") == (None, None)
        assert WurmzScraper._parse_series_url(
            "https://wurmz.net/semua-komik?q=solo"
        ) == (None, None)
        assert WurmzScraper._parse_series_url("/detail/manhwa") == (None, None)

    def test_parse_chapter_url(self):
        assert WurmzScraper._parse_chapter_url(
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/1"
        ) == ("manhwa", "pendekar-pedang-solo", "1")
        assert WurmzScraper._parse_chapter_url(
            "/detail/manhwa/naik-lepel-sendirian-xv2/chapter/179.8"
        ) == ("manhwa", "naik-lepel-sendirian-xv2", "179.8")
        assert WurmzScraper._parse_chapter_url(
            "/detail/manhwa/pemain-tunggal/chapter/0"
        ) == ("manhwa", "pemain-tunggal", "0")

    def test_parse_chapter_url_missing(self):
        assert WurmzScraper._parse_chapter_url(
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo"
        ) == (None, None, None)

    def test_builds_site_urls(self, wz):
        assert wz._series_url("manhua", "x") == "https://wurmz.net/detail/manhua/x"
        assert wz._chapter_url("manhwa", "x", "50.5") == \
            "https://wurmz.net/detail/manhwa/x/chapter/50.5"


# Search


def _card(kind, slug, title, latest):
    return f"""
<article class="comic-card group">
  <a aria-label="{title}" class="block" href="/detail/{kind}/{slug}">
    <div class="cover-frame">
      <img alt="{title}" loading="lazy" src="/covers/{kind}__{slug}.webp">
      <span class="type-badge">Manhwa</span>
    </div>
  </a>
  <a class="block" href="/detail/{kind}/{slug}"><h2 class="comic-title line-clamp-2">{title}</h2></a>
  <a class="ch-row" href="/detail/{kind}/{slug}/chapter/{latest}">
    <span class="ch-num">Ch. <!-- -->{latest}</span><span class="ch-time">1 hari lalu</span>
  </a>
</article>"""


SEARCH_HTML = f"""
<html><body>
<nav><a href="/semua-komik">Semua Komik</a><a href="/?type=manhwa">Manhwa</a></nav>
<div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3 md:gap-4">
  {_card("manhwa", "hanya-aku-yang-memiliki-panggilan-kelas-ex", "Solo EX-Rank Summoner", "41")}
  {_card("manhwa", "pendekar-pedang-solo", "Solo Swordmaster", "20")}
  {_card("manga", "solois-dalam-sangkar", "Soloist in a Cage", "2")}
  {_card("manhwa", "pendekar-pedang-solo", "Solo Swordmaster", "20")}
</div>
</body></html>
"""


class TestSearch:
    def test_parses_cards_and_dedupes(self, wz):
        results = wz._parse_search(SEARCH_HTML)
        assert [r.title for r in results] == [
            "Solo EX-Rank Summoner", "Solo Swordmaster", "Soloist in a Cage",
        ]
        assert results[1].url == "https://wurmz.net/detail/manhwa/pendekar-pedang-solo"
        assert results[2].url == "https://wurmz.net/detail/manga/solois-dalam-sangkar"
        # Relative /covers/ paths are made absolute on the site host.
        assert results[1].cover_url == \
            "https://wurmz.net/covers/manhwa__pendekar-pedang-solo.webp"

    def test_falls_back_to_aria_label_title(self, wz):
        html = """<article class="comic-card">
          <a aria-label="Solo Smurf" href="/detail/manhwa/solo-smurf"><img src="/c.webp"></a>
        </article>"""
        [result] = wz._parse_search(html)
        assert result.title == "Solo Smurf"
        assert result.url == "https://wurmz.net/detail/manhwa/solo-smurf"

    def test_no_cards(self, wz):
        assert wz._parse_search("<html><body>Tidak ada komik</body></html>") == []
        assert wz._parse_search(None) == []

    def test_search_hits_catalogue_filter(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, SEARCH_HTML)
        results = wz.search("  solo ")
        assert len(results) == 3
        url, kwargs = calls[0]
        assert url == "https://wurmz.net/semua-komik"
        assert kwargs["params"] == dict(q="solo")

    def test_blank_query_skips_request(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, SEARCH_HTML)
        assert wz.search("   ") == []
        assert calls == []


# Chapters


def _cell(num):
    return (f'<a class="chap-cell" href="/detail/manhwa/pendekar-pedang-solo/chapter/{num}"'
            f' title="Chapter {num}">Ch. <!-- -->{num}</a>')


SERIES_HTML = f"""
<html><body>
<h1>Solo Swordmaster Bahasa Indonesia</h1>
<a href="/detail/manhwa/pendekar-pedang-solo/chapter/1">Baca Chapter 1</a>
<section class="mt-7"><div>
  <div class="grid grid-cols-3 gap-1.5 max-h-[520px] overflow-y-auto">
    {_cell("20")}
    {_cell("19.5")}
    {_cell("12.0")}
    {_cell("2")}
    {_cell("1")}
    {_cell("0")}
    {_cell("2")}
  </div>
</div></section>
<aside>
  <a class="ch-row" href="/detail/manhwa/romansa-pemberontak/chapter/27">
    <span class="ch-num">Ch. 27</span></a>
  <a class="ch-row" href="/detail/manga/pendekar-pedang-solo/chapter/99">
    <span class="ch-num">Ch. 99</span></a>
</aside>
</body></html>
"""


class TestChapters:
    def test_parses_sorts_and_dedupes(self, wz):
        chapters = wz._parse_chapters(SERIES_HTML, "manhwa", "pendekar-pedang-solo")
        assert [c.number for c in chapters] == ["0", "1", "2", "12", "19.5", "20"]
        assert chapters[0].title == "Chapter 0"
        assert chapters[-1].url == \
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/20"

    def test_url_keeps_site_number(self, wz):
        chapters = wz._parse_chapters(SERIES_HTML, "manhwa", "pendekar-pedang-solo")
        twelve = [c for c in chapters if c.number == "12"][0]
        assert twelve.url.endswith("/pendekar-pedang-solo/chapter/12.0")

    def test_falls_back_to_all_links_without_grid(self, wz):
        html = """<a href="/detail/manhwa/x/chapter/5">5</a>
                  <a href="/detail/manhwa/x/chapter/4">4</a>
                  <a href="/detail/manhwa/y/chapter/9">other</a>"""
        assert [c.number for c in wz._parse_chapters(html, "manhwa", "x")] == ["4", "5"]

    def test_get_chapters_accepts_reader_and_www_urls(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, SERIES_HTML)
        chapters = wz.get_chapters(
            "https://www.wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/3"
        )
        assert len(chapters) == 6
        assert calls[0][0] == "https://wurmz.net/detail/manhwa/pendekar-pedang-solo"

    def test_get_chapters_bad_url(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, SERIES_HTML)
        assert wz.get_chapters("https://wurmz.net/semua-komik") == []
        assert calls == []


# Pages


PAGE = "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEpage{}/s1600/{}.jpg"

READER_HTML = f"""
<html><body>
<header><img src="/icon-192.png" alt="Wurmz"></header>
<div class="reader-canvas"><div class="mx-auto max-w-[900px]">
  <div class="reader-page"><img alt="halaman 1" class="w-full h-auto reader-image"
    loading="eager" referrerpolicy="no-referrer" src="{PAGE.format(1, 1)}"></div>
  <div class="reader-page"><img alt="halaman 2" class="w-full h-auto reader-image"
    loading="lazy" referrerpolicy="no-referrer" src="{PAGE.format(2, 2)}"></div>
  <div class="reader-page"><img alt="halaman 3" class="w-full h-auto reader-image"
    loading="lazy" referrerpolicy="no-referrer" src="{PAGE.format(3, 3)}"></div>
  <div class="reader-page"><img alt="halaman 3" class="w-full h-auto reader-image"
    loading="lazy" referrerpolicy="no-referrer" src="{PAGE.format(3, 3)}"></div>
</div></div>
<a href="/detail/manhwa/pendekar-pedang-solo/chapter/2">Next</a>
</body></html>
"""


class TestPages:
    def test_parses_reader_images_in_order(self, wz):
        assert wz._parse_pages(READER_HTML) == [PAGE.format(i, i) for i in (1, 2, 3)]

    def test_falls_back_to_reader_canvas(self, wz):
        html = f"""<div class="reader-canvas"><img data-src="{PAGE.format(1, 1)}"></div>
                   <img src="https://wurmz.net/covers/x.webp">"""
        assert wz._parse_pages(html) == [PAGE.format(1, 1)]

    def test_no_reader(self, wz):
        assert wz._parse_pages("<html></html>") == []

    def test_get_pages_fetches_reader_url(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, READER_HTML)
        pages = wz.get_pages(
            "https://www.wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/1"
        )
        assert len(pages) == 3
        assert calls[0][0] == \
            "https://wurmz.net/detail/manhwa/pendekar-pedang-solo/chapter/1"

    def test_get_pages_bad_url(self, monkeypatch, wz):
        calls = _fake_request(wz, monkeypatch, READER_HTML)
        assert wz.get_pages("https://wurmz.net/detail/manhwa/pendekar-pedang-solo") == []
        assert calls == []
