"""HTML-fixture tests for the Lector Manga scraper.

The network-facing helper (``_request``) is replaced with a fake here -
these tests exercise only the parsing and URL handling, using markup
trimmed from the live ``lector-mangas.lat`` series/reader pages and the
``cdn.zerocomics.net`` search fragment.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.lectormanga import LectorMangaScraper


@pytest.fixture
def lm():
    return LectorMangaScraper()


class FakeResponse:
    def __init__(self, body: str):
        # Encoded as UTF-8 bytes; the real search host sends no charset.
        self.content = body.encode("utf-8")


def _fake_request(lm, monkeypatch, body):
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(body)

    monkeypatch.setattr(lm, "_request", fake)
    return calls


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("lector-mangas.lat")
    assert isinstance(s, LectorMangaScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


@pytest.mark.parametrize("domain", [
    "lectormangass.net", "www.lectormangass.net", "www.lector-mangas.lat",
])
def test_old_and_www_hosts_resolve(domain):
    assert isinstance(get_scraper(domain), LectorMangaScraper)


# URL helpers


class TestUrlHelpers:
    def test_parse_series_url(self):
        assert LectorMangaScraper._parse_series_url(
            "https://lector-mangas.lat/comics/jinx"
        ) == "jinx"
        assert LectorMangaScraper._parse_series_url(
            "https://lector-mangas.lat/comics/jinx/capitulo-103"
        ) == "jinx"
        assert LectorMangaScraper._parse_series_url("/comics/love-jinx?x=1") == "love-jinx"

    def test_parse_series_url_rejects_non_series(self):
        assert LectorMangaScraper._parse_series_url("https://lector-mangas.lat/") is None
        assert LectorMangaScraper._parse_series_url(
            "https://lector-mangas.lat/comics?q=jinx"
        ) is None
        assert LectorMangaScraper._parse_series_url("/comics/genre/boys-love") is None

    def test_parse_chapter_url(self):
        assert LectorMangaScraper._parse_chapter_url(
            "https://lector-mangas.lat/comics/jinx/capitulo-103"
        ) == ("jinx", "103")
        assert LectorMangaScraper._parse_chapter_url(
            "/comics/jinx/capitulo-90.5"
        ) == ("jinx", "90.5")

    def test_parse_chapter_url_missing(self):
        assert LectorMangaScraper._parse_chapter_url(
            "https://lector-mangas.lat/comics/jinx"
        ) == (None, None)
        # SEO "first chapter" alias is not a reader URL we build.
        assert LectorMangaScraper._parse_chapter_url(
            "/comics/jinx/chapter-1"
        ) == (None, None)

    def test_builds_site_urls(self, lm):
        assert lm._series_url("jinx") == "https://lector-mangas.lat/comics/jinx"
        assert lm._chapter_url("jinx", "90.5") == \
            "https://lector-mangas.lat/comics/jinx/capitulo-90.5"


# Search


def _card(slug, title, cover):
    return f"""
<div class="col-md-6 col-lg-6 col-xl-4 col-12">
  <div class="mobile-stats"><div class="text-caption">108 Capítulos</div></div>
  <div class="d-flex rounded zs-bg-3 elevation-2 card-body">
    <div class="relative card-cover-wrap">
      <a href="/comics/{slug}" title="{title}" class="card-cover-link">
        <img src="{cover}" alt="Portada de {title}" class="card-cover-img">
      </a>
    </div>
    <div class="py-4 card-info">
      <a href="/comics/{slug}">{title}</a>
      <div class="px-1"><a href="/comics/{slug}">Leer</a></div>
    </div>
  </div>
</div>"""


SEARCH_HTML = f"""
<html><body>
<section class="recommend--slide">
  <ul class="rankings-slider-track">
    <li class="rankings-slide"><a href="/comics/emdr">4 10.2K EMDR</a></li>
  </ul>
</section>
<div class="container" id="directory-results">
  <div class="row manga-grid">
    {_card("jinx", "Jinx", "https://api.zerocomics.net/storage/series/portadas/A.webp")}
    {_card("seleccion-mutua", "Selección mutua", "https://api.zerocomics.net/storage/series/portadas/B.webp")}
    {_card("jinx", "Jinx", "https://api.zerocomics.net/storage/series/portadas/A.webp")}
  </div>
</div>
<div class="v-pagination"><a href="/comics?page=2">2</a></div>
</body></html>
"""


class TestSearch:
    def test_parses_grid_cards_only(self, lm):
        results = lm._parse_search(SEARCH_HTML)
        assert [r.title for r in results] == ["Jinx", "Selección mutua"]
        assert results[0].url == "https://lector-mangas.lat/comics/jinx"
        assert results[0].cover_url == \
            "https://api.zerocomics.net/storage/series/portadas/A.webp"

    def test_falls_back_to_card_info_title(self, lm):
        html = """<div class="manga-grid"><div>
          <a class="card-cover-link" href="/comics/no-moral"><img src="/x.webp"></a>
          <div class="card-info"><a href="/comics/no-moral">No Moral</a></div>
        </div></div>"""
        results = lm._parse_search(html)
        assert [r.title for r in results] == ["No Moral"]
        # Relative covers are not usable download URLs.
        assert results[0].cover_url is None

    def test_no_grid_or_empty_grid(self, lm):
        assert lm._parse_search("<html><body>nothing</body></html>") == []
        assert lm._parse_search('<div class="manga-grid"></div>') == []
        assert lm._parse_search(None) == []

    def test_search_hits_live_search_endpoint_and_decodes_utf8(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, SEARCH_HTML)
        results = lm.search("  jinx ")
        assert results[1].title == "Selección mutua"
        url, kwargs = calls[0]
        assert url == "https://cdn.zerocomics.net/comics"
        assert kwargs["params"] == {"search": "jinx", "page": 1}

    def test_short_query_skips_request(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, SEARCH_HTML)
        assert lm.search("j") == []
        assert lm.search("   ") == []
        assert calls == []


# Chapters


def _chapter_row(num):
    return f"""
<div class="col-md-6 col-12" data-chapter-num="{num}">
  <a href="/comics/jinx/capitulo-{num}" class="v-card v-card--link">
    <div>Capítulo <span class="font-weight-bold">{num}</span></div>
    <div class="text-caption"><div>hace 3 meses</div></div>
  </a>
</div>"""


SERIES_HTML = f"""
<html><body>
<div class="sidebar">
  <div class="d-flex align-center mt-5"><a href="/comics/jinx/chapter-1">Capítulo 1</a></div>
</div>
<div id="content_area">
  <div class="row pa-4" id="chapters-list">
    {_chapter_row("103")}
    {_chapter_row("90.5")}
    {_chapter_row("53.1")}
    {_chapter_row("2")}
    {_chapter_row("1")}
    <div class="col-md-6 col-12" data-chapter-num="2">
      <a href="/comics/jinx/capitulo-2">duplicate</a>
    </div>
    <div class="col-md-6 col-12"><a href="/comics/other/capitulo-7">other series</a></div>
  </div>
  <section class="serie-seo-block"><p><a href="/comics/jinx/chapter-1">Capítulo 1</a></p></section>
</div>
</body></html>
"""


class TestChapters:
    def test_parses_sorts_and_dedupes(self, lm):
        chapters = lm._parse_chapters(SERIES_HTML, "jinx")
        assert [c.number for c in chapters] == ["1", "2", "53.1", "90.5", "103"]
        assert chapters[0].url == "https://lector-mangas.lat/comics/jinx/capitulo-1"
        assert chapters[3].url == "https://lector-mangas.lat/comics/jinx/capitulo-90.5"
        assert chapters[0].title == "Chapter 1"

    def test_url_keeps_site_number_and_number_is_normalised(self, lm):
        html = """<div id="chapters-list"><div data-chapter-num="12.0">
          <a href="/comics/jinx/capitulo-12.0">Capítulo 12</a></div></div>"""
        [chapter] = lm._parse_chapters(html, "jinx")
        assert chapter.number == "12"
        assert chapter.url.endswith("/comics/jinx/capitulo-12.0")

    def test_falls_back_to_href_number_without_container(self, lm):
        html = """<a href="/comics/jinx/capitulo-5">5</a>
                  <a href="/comics/jinx/capitulo-4">4</a>"""
        assert [c.number for c in lm._parse_chapters(html, "jinx")] == ["4", "5"]

    def test_get_chapters_uses_current_host_for_old_urls(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, SERIES_HTML)
        chapters = lm.get_chapters("https://lectormangass.net/comics/jinx")
        assert len(chapters) == 5
        assert calls[0][0] == "https://lector-mangas.lat/comics/jinx"
        assert all(c.url.startswith("https://lector-mangas.lat/") for c in chapters)

    def test_get_chapters_bad_url(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, SERIES_HTML)
        assert lm.get_chapters("https://lector-mangas.lat/") == []
        assert calls == []


# Pages


PAGE = "https://media.ikigaicomics.lat/capitulos/12/01KVDDJJJ1V05QWGSAQ6W7NRH3/page_{:03d}.webp"

READER_HTML = f"""
<html><body>
<a class="flex items-center gap-2"><figure>
  <img src="https://api.zerocomics.net/storage/series/portadas/A.webp" alt="Portada de Jinx">
</figure></a>
<div class="reader-pages flex flex-col w-full" data-adult-gate-content>
  <div class="w-full reader-page-wrap"><img src="{PAGE.format(1)}" class="reader-page-img"></div>
  <div class="w-full reader-page-wrap"><img src="{PAGE.format(2)}" loading="lazy" class="reader-page-img"></div>
  <div class="w-full reader-page-wrap"><img src="{PAGE.format(3)}" loading="lazy" class="reader-page-img"></div>
  <div class="w-full reader-page-wrap"><img src="{PAGE.format(3)}" loading="lazy" class="reader-page-img"></div>
</div>
<noscript><a><img src="//sstatic1.histats.com/0.gif?5031162&101" alt="contador"></a></noscript>
</body></html>
"""


class TestPages:
    def test_parses_reader_images_in_order(self, lm):
        assert lm._parse_pages(READER_HTML) == [PAGE.format(i) for i in (1, 2, 3)]

    def test_falls_back_to_reader_container(self, lm):
        html = f"""<div class="reader-pages"><img data-src="{PAGE.format(1)}"></div>
                   <img src="https://api.zerocomics.net/storage/cover.webp">"""
        assert lm._parse_pages(html) == [PAGE.format(1)]

    def test_no_reader(self, lm):
        assert lm._parse_pages("<html></html>") == []

    def test_get_pages_rebuilds_url_on_current_host(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, READER_HTML)
        pages = lm.get_pages("https://lectormangass.net/comics/jinx/capitulo-90.5")
        assert len(pages) == 3
        assert calls[0][0] == "https://lector-mangas.lat/comics/jinx/capitulo-90.5"

    def test_get_pages_bad_url(self, monkeypatch, lm):
        calls = _fake_request(lm, monkeypatch, READER_HTML)
        assert lm.get_pages("https://lector-mangas.lat/comics/jinx") == []
        assert calls == []
