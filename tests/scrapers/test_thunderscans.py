"""HTML-fixture tests for the Thunder Scans EN scraper.

The network-facing helper (``_get_html``) is replaced with fakes here - these
tests exercise only the parsing, URL handling and pagination logic, using
markup shaped after the live ``en-thunderscans.com`` search, series and
reader pages (WordPress MangaThemesia theme).
"""

from __future__ import annotations

import pytest
import requests

from memanga.scrapers import get_scraper
from memanga.scrapers.thunderscans import ThunderScansScraper

BASE = "https://en-thunderscans.com"


@pytest.fixture
def ts():
    return ThunderScansScraper()


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("en-thunderscans.com")
    assert isinstance(s, ThunderScansScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


def test_www_host_resolves():
    assert isinstance(get_scraper("www.en-thunderscans.com"), ThunderScansScraper)


def test_sends_site_referer(ts):
    assert ts.session.headers["Referer"] == BASE + "/"


# URL helpers


class TestSlugPrefix:
    def test_strips_series_prefix(self):
        assert ThunderScansScraper._strip_slug_prefix(
            f"{BASE}/comics/0086250808-i-got-the-weakest-class-dragon-tamer/"
        ) == f"{BASE}/comics/i-got-the-weakest-class-dragon-tamer/"

    def test_strips_chapter_prefix(self):
        assert ThunderScansScraper._strip_slug_prefix(
            f"{BASE}/1482765166-i-got-the-weakest-class-dragon-tamer-1/"
        ) == f"{BASE}/i-got-the-weakest-class-dragon-tamer-1/"

    def test_unprefixed_urls_return_none(self):
        assert ThunderScansScraper._strip_slug_prefix(
            f"{BASE}/comics/solo-swordmaster/"
        ) is None
        assert ThunderScansScraper._strip_slug_prefix(
            f"{BASE}/solo-swordmaster-chapter-19/"
        ) is None


# Search


def _card(url: str, title: str, cover: str = "") -> str:
    return f"""
    <div class="bs"><div class="bsx">
      <a href="{url}" title="{title}">
        <div class="limit"><img src="{cover}" class="ts-post-image"/></div>
        <div class="bigor"><div class="tt">{title}</div></div>
      </a>
    </div></div>"""


def _search_page(cards: str, next_url: str = "") -> str:
    pagination = ""
    if next_url:
        pagination = (
            '<div class="pagination">'
            '<span aria-current="page" class="page-numbers current">1</span>'
            f'<a class="next page-numbers" href="{next_url}">Next &raquo;</a>'
            "</div>"
        )
    return f"""<html><body>
    <div class="bixbox"><div class="releases"><h1>Search</h1></div>
      <div class="listupd">{cards}</div>
      {pagination}
    </div>
    <div class="serieslist"><a href="{BASE}/comics/sidebar-popular/">Popular</a></div>
    </body></html>"""


SEARCH_PAGE_1 = _search_page(
    _card(f"{BASE}/comics/solo-swordmaster/", "Solo Swordmaster",
          f"{BASE}/wp-content/uploads/2026/09/cover-210x300.jpg")
    + _card(f"{BASE}/comics/0086250808-solo-bug-player/",
            "I Really Don&#8217;t Want to Solo")
    # Not a series link -> ignored.
    + _card(f"{BASE}/genres/manga/", "Manga"),
    next_url=f"{BASE}/page/2/?s=solo",
)
SEARCH_PAGE_2 = _search_page(
    _card(f"{BASE}/comics/the-king-of-soloplay/", "The King of Soloplay")
    # Repeated across pages -> deduplicated.
    + _card(f"{BASE}/comics/solo-swordmaster/", "Solo Swordmaster"),
)


class TestSearch:
    def test_parses_result_cards(self, ts):
        results = ts._parse_search(SEARCH_PAGE_1)
        assert [m.title for m in results] == [
            "Solo Swordmaster",
            "I Really Don’t Want to Solo",
        ]
        assert results[0].url == f"{BASE}/comics/solo-swordmaster/"
        assert results[0].cover_url == f"{BASE}/wp-content/uploads/2026/09/cover-210x300.jpg"
        assert results[1].url == f"{BASE}/comics/0086250808-solo-bug-player/"

    def test_ignores_sidebar_links(self, ts):
        urls = [m.url for m in ts._parse_search(SEARCH_PAGE_1)]
        assert f"{BASE}/comics/sidebar-popular/" not in urls

    def test_follows_pagination_and_dedupes(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            return SEARCH_PAGE_1 if "/page/2/" not in url else SEARCH_PAGE_2

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        results = ts.search("solo sword")
        assert calls == [f"{BASE}/?s=solo+sword", f"{BASE}/page/2/?s=solo"]
        assert [m.title for m in results] == [
            "Solo Swordmaster",
            "I Really Don’t Want to Solo",
            "The King of Soloplay",
        ]

    def test_stops_at_page_cap(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            return SEARCH_PAGE_1  # always advertises a next page

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        ts.search("solo")
        assert len(calls) == ThunderScansScraper._MAX_SEARCH_PAGES

    def test_blank_query_skips_network(self, monkeypatch, ts):
        def boom(*a, **k):
            raise AssertionError("no request expected")

        monkeypatch.setattr(ts, "_get_html", boom)
        assert ts.search("   ") == []

    def test_no_results_page(self, ts):
        assert ts._parse_search(_search_page("")) == []


# Chapters


SERIES_PAGE = f"""<html><body>
<div class="lastend">
  <div class="inepcx"><a href="{BASE}/solo-swordmaster-chapter-20/">
    <span class="epcur epcurlast">Chapter 20</span></a></div>
  <div class="inepcx"><a href="#/"><span class="epcur epcurfirst">Chapter ?</span></a></div>
</div>
<div class="eplister" id="chapterlist"><style>.navbar {{ padding: 0; }}</style>
<ul>
  <li data-num="20">
    <a data-bs-toggle="modal" data-bs-target="#lockedChapterModal"
       data-id="689649" data-coin="50" data-title="Chapter 20">
      <div class="chbox"><div class="eph-num">
        <span class="chapternum">Chapter 20</span>
        <span class="chapterdate">September 30, 2026</span>
      </div><span class="text-gold">50</span></div>
    </a>
  </li>
  <li data-num="19">
    <a href="{BASE}/solo-swordmaster-chapter-19/">
      <div class="chbox"><div class="eph-num">
        <span class="chapternum">
          Chapter
          19</span>
        <span class="chapterdate">September 30, 2026</span>
      </div></div>
    </a>
  </li>
  <li data-num="2.5">
    <a href="{BASE}/solo-swordmaster-chapter-2-5/">
      <div class="chbox"><div class="eph-num">
        <span class="chapternum">Chapter 2.5</span>
        <span class="chapterdate">January 2, 2026</span>
      </div></div>
    </a>
  </li>
  <li data-num="">
    <a href="{BASE}/1482765166-solo-swordmaster-1/">
      <div class="chbox"><div class="eph-num">
        <span class="chapternum">Chapter 1</span>
        <span class="chapterdate">January 1, 2026</span>
      </div></div>
    </a>
  </li>
  <li data-num="19">
    <a href="{BASE}/solo-swordmaster-chapter-19/">duplicate row</a>
  </li>
</ul>
</div>
</body></html>"""


class TestChapters:
    def test_parses_unlocked_chapters_ascending(self, ts):
        chapters = ts._parse_chapters(SERIES_PAGE)
        assert [c.number for c in chapters] == ["1", "2.5", "19"]
        assert [c.url for c in chapters] == [
            f"{BASE}/1482765166-solo-swordmaster-1/",
            f"{BASE}/solo-swordmaster-chapter-2-5/",
            f"{BASE}/solo-swordmaster-chapter-19/",
        ]
        assert chapters[-1].title == "Chapter 19"
        assert chapters[-1].date == "September 30, 2026"

    def test_skips_coin_locked_chapters(self, ts):
        numbers = [c.number for c in ts._parse_chapters(SERIES_PAGE)]
        assert "20" not in numbers

    def test_ignores_first_last_shortcut_links(self, ts):
        urls = [c.url for c in ts._parse_chapters(SERIES_PAGE)]
        assert urls.count(f"{BASE}/solo-swordmaster-chapter-19/") == 1
        assert f"{BASE}/solo-swordmaster-chapter-20/" not in urls

    def test_chapter_number_fallbacks(self):
        number = ThunderScansScraper._chapter_number
        assert number("388.5", "Chapter 388.5", "") == "388.5"
        assert number("", "Chapter 12", "") == "12"
        assert number(None, "", f"{BASE}/demonic-emperor-chapter-150-1/") == "150.1"
        assert number(None, "", f"{BASE}/oneshot/") == "0"

    def test_get_chapters_fetches_series_page(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            return SERIES_PAGE

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        chapters = ts.get_chapters(f"{BASE}/comics/solo-swordmaster/")
        assert calls == [f"{BASE}/comics/solo-swordmaster/"]
        assert len(chapters) == 3

    def test_stale_slug_prefix_retries_unprefixed(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            if "0086250808-" in url:
                raise _http_error(404)
            return SERIES_PAGE

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        chapters = ts.get_chapters(f"{BASE}/comics/0086250808-solo-swordmaster/")
        assert calls == [
            f"{BASE}/comics/0086250808-solo-swordmaster/",
            f"{BASE}/comics/solo-swordmaster/",
        ]
        assert len(chapters) == 3

    def test_non_404_errors_are_not_retried(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            raise _http_error(503)

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        with pytest.raises(requests.HTTPError):
            ts.get_chapters(f"{BASE}/comics/0086250808-solo-swordmaster/")
        assert len(calls) == 1

    def test_unprefixed_404_is_raised(self, monkeypatch, ts):
        def fake_get_html(url, *a, **k):
            raise _http_error(404)

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        with pytest.raises(requests.HTTPError):
            ts.get_chapters(f"{BASE}/comics/does-not-exist/")


# Pages


IMG = f"{BASE}/wp-content/uploads/manga/806f031e239fa13c5db543f582b84b0c"

READER_PAGE = f"""<html><body>
<div id="readerarea"></div>
<div id="readerarea-loading"><img src="{BASE}/wp-content/themes/mangareader/assets/img/readerarea.svg" /></div>
<script>ts_reader.run({{"post_id":689648,"noimagehtml":"<center><h4>NO IMAGE YET<\\/h4><\\/center>","prevUrl":"{BASE}\\/solo-swordmaster-chapter-18\\/","nextUrl":"","mode":"full","sources":[{{"source":"Server 2","images":["https:\\/\\/mirror.example\\/0001.webp"]}},{{"source":"Server 1","images":["{IMG}\\/0001_dbcc1498.webp","{IMG}\\/0002_930e3b51.webp","{IMG}\\/0003_c14c3130.webp"]}}],"lazyload":false,"defaultSource":"Server 1","protected":false,"is_novel":false,"unlock_token":null}});</script>
</body></html>"""

READER_IMG_ONLY = f"""<html><body>
<div id="readerarea">
  <img src="{IMG}/0001.webp" />
  <img data-src="{IMG}/0002.webp" src="{BASE}/wp-content/themes/mangareader/assets/img/readerarea.svg" />
  <img src="{IMG}/0001.webp" />
</div>
<img src="{BASE}/wp-content/uploads/logo.png" />
</body></html>"""


class TestPages:
    def test_reads_default_source_from_ts_reader(self, ts):
        assert ts._parse_reader_payload(READER_PAGE) == [
            f"{IMG}/0001_dbcc1498.webp",
            f"{IMG}/0002_930e3b51.webp",
            f"{IMG}/0003_c14c3130.webp",
        ]

    def test_falls_back_to_first_non_empty_source(self, ts):
        html = READER_PAGE.replace('"defaultSource":"Server 1"', '"defaultSource":"Server 9"')
        assert ts._parse_reader_payload(html) == ["https://mirror.example/0001.webp"]

    def test_missing_or_broken_payload(self, ts):
        assert ts._parse_reader_payload("<html></html>") == []
        assert ts._parse_reader_payload("<script>ts_reader.run({broken);</script>") == []

    def test_reader_img_fallback(self, ts):
        assert ts._parse_reader_images(READER_IMG_ONLY) == [
            f"{IMG}/0001.webp",
            f"{IMG}/0002.webp",
        ]

    def test_get_pages_prefers_payload(self, monkeypatch, ts):
        monkeypatch.setattr(ts, "_get_html", lambda *a, **k: READER_PAGE)
        pages = ts.get_pages(f"{BASE}/solo-swordmaster-chapter-19/")
        assert len(pages) == 3
        assert pages[0] == f"{IMG}/0001_dbcc1498.webp"

    def test_get_pages_uses_img_fallback(self, monkeypatch, ts):
        monkeypatch.setattr(ts, "_get_html", lambda *a, **k: READER_IMG_ONLY)
        assert ts.get_pages(f"{BASE}/solo-swordmaster-chapter-19/") == [
            f"{IMG}/0001.webp",
            f"{IMG}/0002.webp",
        ]

    def test_get_pages_retries_stale_chapter_prefix(self, monkeypatch, ts):
        calls = []

        def fake_get_html(url, *a, **k):
            calls.append(url)
            if "1482765166-" in url:
                raise _http_error(404)
            return READER_PAGE

        monkeypatch.setattr(ts, "_get_html", fake_get_html)
        pages = ts.get_pages(f"{BASE}/1482765166-solo-swordmaster-1/")
        assert calls[-1] == f"{BASE}/solo-swordmaster-1/"
        assert len(pages) == 3
