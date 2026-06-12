"""Unit tests for the shared search engine (memanga.search).

Everything network-shaped is faked — scrapers are stubs returning
canned Manga objects, no requests leave the process.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import Manga
from memanga.search import (
    SearchResult,
    compute_search_sources,
    fetch_chapter_count,
    probe_chapter_counts,
    result_matches_query,
    sweep,
)


class FakeScraper:
    def __init__(self, results=None, chapters=0, search_error=None,
                 chapters_error=None):
        self._results = results or []
        self._chapters = chapters
        self._search_error = search_error
        self._chapters_error = chapters_error
        self.search_calls = []
        self.get_chapters_calls = []

    def search(self, query):
        self.search_calls.append(query)
        if self._search_error:
            raise self._search_error
        return self._results

    def get_chapters(self, url):
        self.get_chapters_calls.append(url)
        if self._chapters_error:
            raise self._chapters_error
        return [object()] * self._chapters


def _patch_scrapers(monkeypatch, by_domain):
    """Point memanga.search.get_scraper at a dict of fakes."""
    def _get(domain):
        if domain not in by_domain:
            raise ValueError(f"No scraper available for: {domain}")
        return by_domain[domain]
    monkeypatch.setattr("memanga.search.get_scraper", _get)


class FakeConfig:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


# ─────────────────────────────────────────────────────────────────────────
# sweep
# ─────────────────────────────────────────────────────────────────────────


class TestSweep:
    def test_results_sorted_by_source_popularity(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "zzz-unranked.com": FakeScraper(
                [Manga(title="Blue Lock", url="https://zzz-unranked.com/bl")]),
            "mangadex.org": FakeScraper(
                [Manga(title="Blue Lock", url="https://mangadex.org/bl")]),
        })
        results, failures = sweep("Blue Lock",
                                  ["zzz-unranked.com", "mangadex.org"])
        assert not failures
        assert [r.source for r in results] == ["mangadex.org",
                                               "zzz-unranked.com"]

    def test_irrelevant_titles_filtered(self, monkeypatch):
        # Single-manga sites return their one manga for any query.
        _patch_scrapers(monkeypatch, {
            "beastars.example": FakeScraper(
                [Manga(title="Beastars", url="https://beastars.example/b")]),
            "mangadex.org": FakeScraper(
                [Manga(title="Blue Lock", url="https://mangadex.org/bl")]),
        })
        results, failures = sweep("Blue Lock",
                                  ["beastars.example", "mangadex.org"])
        assert not failures
        assert [r.title for r in results] == ["Blue Lock"]

    def test_per_source_limit(self, monkeypatch):
        many = [Manga(title=f"Blue Lock {i}", url=f"https://x.test/{i}")
                for i in range(10)]
        _patch_scrapers(monkeypatch, {"x.test": FakeScraper(many)})
        results, _ = sweep("Blue Lock", ["x.test"], limit=3)
        assert len(results) == 3

    def test_source_failure_collected_and_reported(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "broken.test": FakeScraper(search_error=RuntimeError("HTTP 502")),
            "mangadex.org": FakeScraper(
                [Manga(title="Blue Lock", url="https://mangadex.org/bl")]),
        })
        failed_calls = []
        results, failures = sweep(
            "Blue Lock", ["broken.test", "mangadex.org"],
            on_source_failed=lambda src, err: failed_calls.append((src, err)),
        )
        assert len(results) == 1
        assert len(failures) == 1
        assert failures[0].source == "broken.test"
        assert "HTTP 502" in failures[0].error
        assert failed_calls == [("broken.test", failures[0].error)]

    def test_unknown_source_is_a_failure_not_a_crash(self, monkeypatch):
        _patch_scrapers(monkeypatch, {})
        results, failures = sweep("Blue Lock", ["nope.test"])
        assert results == []
        assert len(failures) == 1

    def test_dict_results_tolerated(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "dicty.test": FakeScraper(
                [{"title": "Blue Lock", "url": "https://dicty.test/bl",
                  "cover_url": "https://dicty.test/c.jpg"}]),
        })
        results, _ = sweep("Blue Lock", ["dicty.test"])
        assert len(results) == 1
        assert results[0].cover_url == "https://dicty.test/c.jpg"

    def test_on_source_done_callback(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "mangadex.org": FakeScraper(
                [Manga(title="Blue Lock", url="https://mangadex.org/bl")]),
        })
        done = []
        sweep("Blue Lock", ["mangadex.org"],
              on_source_done=lambda src, count: done.append((src, count)))
        assert done == [("mangadex.org", 1)]

    def test_empty_source_list(self):
        results, failures = sweep("Blue Lock", [])
        assert results == []
        assert failures == []


# ─────────────────────────────────────────────────────────────────────────
# chapter counts
# ─────────────────────────────────────────────────────────────────────────


class TestChapterCounts:
    def test_fetch_count(self, monkeypatch):
        _patch_scrapers(monkeypatch, {"x.test": FakeScraper(chapters=42)})
        assert fetch_chapter_count("x.test", "https://x.test/m") == 42

    def test_fetch_count_failure_is_none(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "x.test": FakeScraper(chapters_error=RuntimeError("boom")),
        })
        assert fetch_chapter_count("x.test", "https://x.test/m") is None

    def test_probe_fills_in_place(self, monkeypatch):
        _patch_scrapers(monkeypatch, {
            "ok.test": FakeScraper(chapters=7),
            "bad.test": FakeScraper(chapters_error=RuntimeError("boom")),
        })
        results = [
            SearchResult(title="A", url="https://ok.test/a", source="ok.test"),
            SearchResult(title="B", url="https://bad.test/b", source="bad.test"),
        ]
        probe_chapter_counts(results)
        assert results[0].chapter_count == 7
        assert results[1].chapter_count is None


# ─────────────────────────────────────────────────────────────────────────
# source selection
# ─────────────────────────────────────────────────────────────────────────


class TestComputeSearchSources:
    def test_includes_aggregators_excludes_broken(self):
        sources = compute_search_sources(FakeConfig())
        assert "mangadex.org" in sources
        assert "mangapill.com" in sources
        # Known-dead sites never make the sweep list.
        assert "mangasee123.com" not in sources
        assert "manganato.com" not in sources

    def test_disabled_sources_removed(self):
        sources = compute_search_sources(FakeConfig({
            "sources.disabled": ["mangadex.org"],
        }))
        assert "mangadex.org" not in sources
        assert "mangapill.com" in sources

    def test_template_single_manga_sites_excluded_by_default(self):
        from memanga.scrapers.registry import TEMPLATE_SCRAPERS
        sources = set(compute_search_sources(FakeConfig()))
        overlap = sources & set(TEMPLATE_SCRAPERS.keys())
        assert not overlap

    def test_library_string_sources_do_not_crash(self):
        # Legacy configs can store plain URL strings under "sources".
        sources = compute_search_sources(FakeConfig({
            "manga": [{"title": "X",
                       "sources": ["https://mangadex.org/title/abc"]}],
        }))
        assert "mangadex.org" in sources


# ─────────────────────────────────────────────────────────────────────────
# relevance filter (canonical home; GUI re-exports it)
# ─────────────────────────────────────────────────────────────────────────


class TestRelevanceFilter:
    def test_exact_and_superset_match(self):
        assert result_matches_query("Blue Lock", "blue lock")
        assert result_matches_query("Blue Lock - Episode Nagi", "blue lock")

    def test_unrelated_title_dropped(self):
        assert not result_matches_query("Beastars", "blue lock")
        assert not result_matches_query("Tokyo Ghoul", "blue lock")

    def test_empty_query_passes_everything(self):
        assert result_matches_query("Anything", "")
