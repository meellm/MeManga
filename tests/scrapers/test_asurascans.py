"""Tests for the Asura Scans scraper (issue #177).

Asura runs an Astro frontend backed by a public JSON API on
api.asurascans.com. These tests drive the parsing layer with payloads
shaped after the live responses; the network helpers (``_get_json`` /
``_get_html``) are patched, never called.

Regression focus: the old scraper fetched
``asuracomic.net/series?name=<query>`` through Playwright. That domain
now redirects to the asurascans.com homepage and drops the query
string, so search always came back empty - and asurascans.com was
parked in ``BROKEN_SEARCH_SOURCES`` and missing from the curated
default source set, so the multi-source sweep skipped it outright.
All three halves are covered below, along with the early-access
chapters the site lists but won't serve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from memanga.scrapers import (
    DEFAULT_ENABLED_SOURCES, SCRAPERS, get_scraper,
)
from memanga.scrapers.asurascans import AsuraScansScraper
from memanga.scrapers.playwright_base import PlaywrightScraper
from memanga.scrapers.registry import TEMPLATE_SCRAPERS
from memanga.search import BROKEN_SEARCH_SOURCES, compute_search_sources


def _iso(offset: timedelta) -> str:
    """API-shaped timestamp `offset` away from now (trailing "Z")."""
    stamp = datetime.now(timezone.utc) + offset
    return stamp.isoformat().replace("+00:00", "Z")


SERIES_URL = "https://asurascans.com/comics/nano-machine-05c7df14"
CHAPTER_URL = SERIES_URL + "/chapter/330"
# Shapes library entries still carry from the retired domains.
LEGACY_SERIES_URL = "https://asuracomic.net/series/nano-machine-05c7df14"
MADARA_SERIES_URL = "https://asuratoon.com/manga/nano-machine/"

CDN = "https://cdn.asurascans.com/asura-images"

SEARCH_PAYLOAD = {
    "data": [
        {
            "id": 6091,
            "slug": "the-academy-s-weapon-replicator",
            "title": "The Academy Weapon Replicator",
            "cover": CDN + "/covers/the-academy-s-weapon-replicator.2096c2.webp",
            "chapter_count": 14,
            "public_url": "/comics/the-academy-s-weapon-replicator-05c7df14",
            "source_url": "/s/6091",
        },
        {
            "id": 2017,
            "slug": "nano-machine",
            "title": "Nano Machine",
            "cover": CDN + "/covers/nano-machine.e31bdb.webp",
            "chapter_count": 331,
            "public_url": "/comics/nano-machine-05c7df14",
            "source_url": "/s/2017",
        },
    ],
    "meta": {"total": 2, "per_page": 20},
}

# The API answers a no-match query with `data: null`, not an empty list.
EMPTY_SEARCH_PAYLOAD = {"data": None, "meta": {"per_page": 20}}

CHAPTERS_PAYLOAD = {
    "data": [
        {
            "id": 261518,
            "series_id": 2017,
            "number": 330,
            "title": "107: Special Forces",
            "slug": "chapter-330",
            "page_count": 12,
            "is_premium": False,
            "published_at": "2026-09-16T21:15:32.384188Z",
            "series_slug": "nano-machine",
        },
        {
            "id": 261361,
            "series_id": 2017,
            "number": 329,
            "title": "107. Special Forces",
            "slug": "chapter-329",
            "page_count": 16,
            "is_premium": False,
            "published_at": "2026-09-09T19:53:21.634208Z",
            "series_slug": "nano-machine",
        },
        {
            # Older chapters carry a UUID slug and no title.
            "id": 152280,
            "series_id": 2017,
            "number": 1,
            "slug": "ac158a3a-7e87-4492-b792-cf36c9ef9dd5",
            "page_count": 24,
            "is_premium": False,
            "published_at": "2023-12-25T10:11:49Z",
            "series_slug": "nano-machine",
        },
        {
            # Early access: listed by the site, but the chapter detail
            # comes back `is_locked` with zero pages until the window
            # closes (issue #177 - Nano Machine 331).
            "id": 261700,
            "series_id": 2017,
            "number": 331,
            "title": "108: Early Access",
            "slug": "chapter-331",
            "page_count": 0,
            "is_premium": True,
            "early_access_until": _iso(timedelta(days=3)),
            "published_at": "2026-09-23T21:15:32.384188Z",
            "series_slug": "nano-machine",
        },
    ]
}

PAGE_URLS = [
    CDN + "/chapters/nano-machine/330/30f200.webp?v=1789693664",
    CDN + "/chapters/nano-machine/330/1e0c97.webp?v=1789693664",
    CDN + "/chapters/nano-machine/330/8c5a75.webp?v=1789693664",
]

CHAPTER_PAYLOAD = {
    "data": {
        "access_gate": "",
        "is_locked": False,
        "chapter": {
            "id": 261518,
            "series_id": 2017,
            "number": 330,
            "title": "107: Special Forces",
            "slug": "chapter-330",
            "pages": [{"url": u} for u in PAGE_URLS],
            "page_count": 3,
            "is_premium": False,
        },
    }
}

# Early-access chapter: listed by the site, metadata only, no pages.
LOCKED_CHAPTER_PAYLOAD = {
    "data": {
        "access_gate": "",
        "is_locked": True,
        "unlock_time": "2026-09-23T22:43:34.410042Z",
        "chapter": {
            "id": 261700,
            "number": 331,
            "slug": "chapter-331",
            "pages": [],
            "page_count": 0,
            "is_premium": True,
        },
    }
}

SERIES_PAYLOAD = {
    "series": {
        "id": 2017,
        "slug": "nano-machine",
        "title": "Nano Machine",
        "cover": CDN + "/covers/nano-machine.e31bdb.webp",
        "chapter_count": 331,
        "public_url": "/comics/nano-machine-05c7df14",
    },
    "recommended_series": [],
}

# The reader page embeds the same CDN URLs inside an HTML-escaped Astro
# island payload, each one twice (preload link + reader image).
CHAPTER_HTML = "<html><body><script>" + "".join(
    "[0,{&quot;url&quot;:[0,&quot;" + u + "&quot;]}],"
    for u in PAGE_URLS + PAGE_URLS
) + "</script></body></html>"


class FakeConfig:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


class RecordingJson:
    """Stand-in for ``_get_json`` that routes on URL substring."""

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for needle, payload in self._routes.items():
            if needle in url:
                return payload
        raise AssertionError("unexpected URL fetched: " + repr(url))


@pytest.fixture
def asura():
    return AsuraScansScraper()


def _boom(*args, **kwargs):
    raise AssertionError("network call should not happen")


# ----------------------------------------------------------------------
# Registration / wiring
# ----------------------------------------------------------------------


class TestRegistration:
    def test_scraper_is_api_based_not_playwright(self):
        s = get_scraper("asurascans.com")
        assert isinstance(s, AsuraScansScraper)
        assert not isinstance(s, PlaywrightScraper)
        for method in ("search", "get_chapters", "get_pages", "download_image"):
            assert callable(getattr(s, method))

    def test_base_url_points_at_the_live_domain(self):
        assert AsuraScansScraper.base_url == "https://asurascans.com"
        assert AsuraScansScraper.api_url == "https://api.asurascans.com/api"

    def test_retired_domains_still_map_to_the_scraper(self):
        # Library entries saved against the old domains must keep working.
        for domain in ("asuracomic.net", "asuratoon.com"):
            assert SCRAPERS[domain] is AsuraScansScraper

    def test_asurascans_is_no_longer_skipped_in_search(self):
        assert "asurascans.com" not in BROKEN_SEARCH_SOURCES
        sources = compute_search_sources(FakeConfig())
        assert [d for d in sources if "asura" in d] == ["asurascans.com"]

    def test_retired_aliases_stay_out_of_the_sweep(self):
        # Same scraper class - probing all three would triple the work.
        assert "asuracomic.net" in BROKEN_SEARCH_SOURCES
        assert "asuratoon.com" in BROKEN_SEARCH_SOURCES

    def test_only_the_canonical_domain_is_curated(self):
        # Aliases in the curated set would be seeded enabled and then
        # dropped by BROKEN_SEARCH_SOURCES anyway - just noise.
        assert "asurascans.com" in DEFAULT_ENABLED_SOURCES
        assert "asuracomic.net" not in DEFAULT_ENABLED_SOURCES
        assert "asuratoon.com" not in DEFAULT_ENABLED_SOURCES

    def test_first_run_config_still_sweeps_asura(self):
        # Clearing BROKEN_SEARCH_SOURCES isn't enough on its own: the GUI
        # seeds a fresh config by disabling every non-template source
        # outside the curated list, so a source that isn't curated never
        # reaches the sweep for a new user. Reproduce that seeding.
        enabled = set(DEFAULT_ENABLED_SOURCES)
        templates = set(TEMPLATE_SCRAPERS.keys())
        disabled = sorted(d for d in SCRAPERS
                          if d not in enabled and d not in templates)
        assert "asuracomic.net" in disabled and "asuratoon.com" in disabled

        sources = compute_search_sources(
            FakeConfig({"sources.disabled": disabled}))

        assert [d for d in sources if "asura" in d] == ["asurascans.com"]


# ----------------------------------------------------------------------
# URL / number helpers
# ----------------------------------------------------------------------


class TestSeriesSlug:
    def test_public_comics_url(self, asura):
        assert asura._series_slug(SERIES_URL) == "nano-machine-05c7df14"

    def test_legacy_series_url(self, asura):
        assert asura._series_slug(LEGACY_SERIES_URL) == "nano-machine-05c7df14"

    def test_legacy_madara_manga_url(self, asura):
        # asuratoon.com ran a Madara theme: /manga/<slug>/ with a
        # trailing slash and no routing suffix.
        assert asura._series_slug(MADARA_SERIES_URL) == "nano-machine"

    def test_chapter_url_yields_the_series_slug(self, asura):
        assert asura._series_slug(CHAPTER_URL) == "nano-machine-05c7df14"

    def test_query_and_fragment_are_stripped(self, asura):
        assert asura._series_slug(SERIES_URL + "?tab=chapters#top") == \
            "nano-machine-05c7df14"

    def test_unrecognised_url(self, asura):
        assert asura._series_slug("https://example.com/foo") is None
        assert asura._series_slug("") is None


class TestFormatNumber:
    def test_integer_keeps_no_decimal_point(self):
        assert AsuraScansScraper._format_number(330) == "330"
        assert AsuraScansScraper._format_number(100.0) == "100"

    def test_decimal_chapter(self):
        assert AsuraScansScraper._format_number(100.5) == "100.5"

    def test_unparseable(self):
        assert AsuraScansScraper._format_number(None) is None
        assert AsuraScansScraper._format_number("extra") is None


# ----------------------------------------------------------------------
# Search - the fix for #177
# ----------------------------------------------------------------------


class TestSearch:
    def test_queries_the_search_param_not_name(self, asura, monkeypatch):
        # The endpoint accepts ?name= but ignores it and returns the whole
        # catalogue; ?search= is the parameter that actually filters.
        fake = RecordingJson({"/api/series": SEARCH_PAYLOAD})
        monkeypatch.setattr(asura, "_get_json", fake)

        asura.search("nano machine")

        url, kwargs = fake.calls[0]
        assert url == "https://api.asurascans.com/api/series"
        assert kwargs["params"] == {"search": "nano machine"}

    def test_parses_titles_urls_and_covers(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/api/series": SEARCH_PAYLOAD}))

        results = asura.search("nano machine")

        assert [m.title for m in results] == ["Nano Machine",
                                              "The Academy Weapon Replicator"]
        assert results[0].url == SERIES_URL
        assert results[0].cover_url == CDN + "/covers/nano-machine.e31bdb.webp"

    def test_title_match_outranks_a_fuzzy_hit(self, asura, monkeypatch):
        # The API matches alt titles and descriptions too, so the exact
        # title can come back behind unrelated series.
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/api/series": SEARCH_PAYLOAD}))
        assert asura.search("nano machine")[0].title == "Nano Machine"

    def test_no_match_returns_empty_list(self, asura, monkeypatch):
        monkeypatch.setattr(
            asura, "_get_json",
            RecordingJson({"/api/series": EMPTY_SEARCH_PAYLOAD}))
        assert asura.search("no such series") == []

    def test_results_are_capped_at_ten(self, asura, monkeypatch):
        payload = {"data": [
            {"slug": "series-" + str(i), "title": "Series " + str(i),
             "public_url": "/comics/series-" + str(i)}
            for i in range(25)
        ]}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/api/series": payload}))
        assert len(asura.search("series")) == 10

    def test_entries_without_a_slug_are_skipped(self, asura, monkeypatch):
        payload = {"data": [
            {"title": "No Slug"},
            {"slug": "ok", "title": "Ok", "public_url": "/comics/ok-1234"},
        ]}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/api/series": payload}))
        results = asura.search("ok")
        assert [m.title for m in results] == ["Ok"]
        assert results[0].url == "https://asurascans.com/comics/ok-1234"


# ----------------------------------------------------------------------
# Chapters
# ----------------------------------------------------------------------


class TestChapters:
    def test_parses_and_sorts_ascending(self, asura, monkeypatch):
        fake = RecordingJson({"/chapters": CHAPTERS_PAYLOAD})
        monkeypatch.setattr(asura, "_get_json", fake)

        chapters = asura.get_chapters(SERIES_URL)

        assert [c.number for c in chapters] == ["1", "329", "330"]
        assert fake.calls[0][0] == (
            "https://api.asurascans.com/api/series/"
            "nano-machine-05c7df14/chapters")

    def test_chapter_fields(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": CHAPTERS_PAYLOAD}))

        latest = asura.get_chapters(SERIES_URL)[-1]

        assert latest.url == CHAPTER_URL
        assert latest.title == "107: Special Forces"
        assert latest.date == "2026-09-16"

    def test_untitled_chapter_keeps_title_none(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": CHAPTERS_PAYLOAD}))
        assert asura.get_chapters(SERIES_URL)[0].title is None

    def test_legacy_url_yields_links_on_the_live_domain(self, asura,
                                                        monkeypatch):
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": CHAPTERS_PAYLOAD}))

        chapters = asura.get_chapters(LEGACY_SERIES_URL)

        assert all(c.url.startswith("https://asurascans.com/comics/")
                   for c in chapters)

    def test_decimal_chapter_number_in_url(self, asura, monkeypatch):
        payload = {"data": [{"number": 100.5, "slug": "chapter-100-5"}]}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": payload}))

        chapter = asura.get_chapters(SERIES_URL)[0]

        assert chapter.number == "100.5"
        assert chapter.url.endswith("/chapter/100.5")

    def test_duplicate_numbers_collapse(self, asura, monkeypatch):
        payload = {"data": [
            {"number": 5, "slug": "chapter-5"},
            {"number": 5, "slug": "chapter-5-dupe"},
        ]}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": payload}))
        assert len(asura.get_chapters(SERIES_URL)) == 1

    def test_foreign_url_returns_empty_without_a_request(self, asura,
                                                         monkeypatch):
        monkeypatch.setattr(asura, "_get_json", _boom)
        assert asura.get_chapters("https://example.com/foo") == []


class TestEarlyAccessChapters:
    """Premium rows are listed by the site but return zero pages until
    their window closes (issue #177 - Nano Machine 331). Listing them
    hands the downloader a chapter it can never fetch."""

    def test_locked_chapter_is_not_listed(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters": CHAPTERS_PAYLOAD}))

        numbers = [c.number for c in asura.get_chapters(SERIES_URL)]

        assert "331" not in numbers
        assert numbers == ["1", "329", "330"]

    def test_premium_row_is_listed_once_the_window_closed(self):
        row = {"number": 331, "is_premium": True,
               "early_access_until": _iso(timedelta(days=-1))}
        assert AsuraScansScraper._is_early_access(row) is False

    def test_premium_row_without_an_unlock_time_stays_hidden(self):
        # No timestamp to go on - treat it as still paywalled rather
        # than offering a chapter that downloads to nothing.
        assert AsuraScansScraper._is_early_access({"is_premium": True}) is True

    def test_free_row_is_never_early_access(self):
        assert AsuraScansScraper._is_early_access({"is_premium": False}) is False
        assert AsuraScansScraper._is_early_access({"number": 5}) is False

    def test_alternate_unlock_key_is_honoured(self):
        row = {"is_premium": True, "unlock_time": _iso(timedelta(hours=6))}
        assert AsuraScansScraper._is_early_access(row) is True

    def test_unparseable_unlock_time_falls_back_to_hidden(self):
        row = {"is_premium": True, "early_access_until": "soon"}
        assert AsuraScansScraper._is_early_access(row) is True


class TestParseTimestamp:
    def test_trailing_z_is_utc(self):
        stamp = AsuraScansScraper._parse_timestamp("2026-09-23T22:43:34Z")
        assert stamp is not None
        assert stamp.utcoffset().total_seconds() == 0

    def test_sub_second_precision(self):
        assert AsuraScansScraper._parse_timestamp(
            "2026-09-23T22:43:34.410042Z") is not None

    def test_explicit_offset(self):
        assert AsuraScansScraper._parse_timestamp(
            "2026-09-23T22:43:34+02:00") is not None

    def test_naive_timestamp_is_assumed_utc(self):
        stamp = AsuraScansScraper._parse_timestamp("2026-09-23T22:43:34")
        assert stamp is not None and stamp.tzinfo is not None

    def test_junk_and_missing_values(self):
        for raw in ("", "   ", "soon", None, 1789693664, {}):
            assert AsuraScansScraper._parse_timestamp(raw) is None


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------


class TestPages:
    def test_parses_page_urls_in_order(self, asura, monkeypatch):
        fake = RecordingJson({"/chapters/330": CHAPTER_PAYLOAD})
        monkeypatch.setattr(asura, "_get_json", fake)
        monkeypatch.setattr(asura, "_get_html", _boom)

        assert asura.get_pages(CHAPTER_URL) == PAGE_URLS
        assert fake.calls[0][0] == (
            "https://api.asurascans.com/api/series/"
            "nano-machine-05c7df14/chapters/330")

    def test_decimal_chapter_url(self, asura, monkeypatch):
        fake = RecordingJson({"/chapters/100.5": CHAPTER_PAYLOAD})
        monkeypatch.setattr(asura, "_get_json", fake)

        asura.get_pages(SERIES_URL + "/chapter/100.5")

        assert fake.calls[0][0].endswith("/chapters/100.5")

    def test_locked_chapter_yields_no_pages_and_no_html_fetch(self, asura,
                                                              monkeypatch):
        # Early access: the chapter is real but paywalled. Falling back to
        # the reader HTML would just burn a request for the same nothing.
        monkeypatch.setattr(
            asura, "_get_json",
            RecordingJson({"/chapters/331": LOCKED_CHAPTER_PAYLOAD}))
        monkeypatch.setattr(asura, "_get_html", _boom)

        assert asura.get_pages(SERIES_URL + "/chapter/331") == []

    def test_falls_back_to_reader_html_when_api_returns_no_pages(
            self, asura, monkeypatch):
        empty = {"data": {"is_locked": False, "chapter": {"pages": []}}}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters/330": empty}))
        monkeypatch.setattr(asura, "_get_html", lambda url: CHAPTER_HTML)

        # Each URL appears twice in the markup; order and uniqueness hold.
        assert asura.get_pages(CHAPTER_URL) == PAGE_URLS

    def test_html_fallback_fetches_the_live_domain_for_a_legacy_url(
            self, asura, monkeypatch):
        # A library entry saved on a retired domain would otherwise fall
        # back to a URL that redirects to the homepage, which carries no
        # reader images - rebuild the reader URL on asurascans.com.
        empty = {"data": {"is_locked": False, "chapter": {"pages": []}}}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters/330": empty}))
        fetched = []

        def _record(url):
            fetched.append(url)
            return CHAPTER_HTML

        monkeypatch.setattr(asura, "_get_html", _record)

        pages = asura.get_pages(LEGACY_SERIES_URL + "/chapter/330")

        assert pages == PAGE_URLS
        assert fetched == [CHAPTER_URL]

    def test_html_fallback_rebuilds_a_madara_url_on_the_live_domain(
            self, asura, monkeypatch):
        empty = {"data": {"is_locked": False, "chapter": {"pages": []}}}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters/100.5": empty}))
        fetched = []
        monkeypatch.setattr(asura, "_get_html",
                            lambda url: fetched.append(url) or CHAPTER_HTML)

        asura.get_pages(MADARA_SERIES_URL + "chapter/100.5")

        assert fetched == [
            "https://asurascans.com/comics/nano-machine/chapter/100.5"]

    def test_html_fallback_failure_is_swallowed(self, asura, monkeypatch):
        empty = {"data": {"is_locked": False, "chapter": {"pages": []}}}
        monkeypatch.setattr(asura, "_get_json",
                            RecordingJson({"/chapters/330": empty}))

        def _raise(url):
            raise RuntimeError("503")

        monkeypatch.setattr(asura, "_get_html", _raise)
        assert asura.get_pages(CHAPTER_URL) == []

    def test_series_url_without_a_chapter_segment(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json", _boom)
        assert asura.get_pages(SERIES_URL) == []

    def test_foreign_url(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json", _boom)
        assert asura.get_pages("https://example.com/chapter/1") == []


# ----------------------------------------------------------------------
# Cover
# ----------------------------------------------------------------------


class TestCoverUrl:
    def test_reads_cover_from_the_series_api(self, asura, monkeypatch):
        fake = RecordingJson({"/api/series/": SERIES_PAYLOAD})
        monkeypatch.setattr(asura, "_get_json", fake)

        assert asura.get_cover_url(SERIES_URL) == \
            CDN + "/covers/nano-machine.e31bdb.webp"
        assert fake.calls[0][0] == (
            "https://api.asurascans.com/api/series/nano-machine-05c7df14")

    def test_missing_cover(self, asura, monkeypatch):
        monkeypatch.setattr(
            asura, "_get_json",
            RecordingJson({"/api/series/": {"series": {}}}))
        assert asura.get_cover_url(SERIES_URL) is None

    def test_request_failure_returns_none(self, asura, monkeypatch):
        def _raise(url, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(asura, "_get_json", _raise)
        assert asura.get_cover_url(SERIES_URL) is None

    def test_foreign_url(self, asura, monkeypatch):
        monkeypatch.setattr(asura, "_get_json", _boom)
        assert asura.get_cover_url("https://example.com/foo") is None
