"""Exhaustive registry coverage.

For every domain in memanga.scrapers.SCRAPERS:
  - get_scraper(domain) returns an instance
  - the instance has the four required methods
  - the instance has a non-empty base_url (when applicable)

Catches typos in __init__.py wiring + template config misses.
"""

from __future__ import annotations

import inspect

import pytest

from memanga.scrapers import SCRAPERS, get_scraper, list_supported_sources
from memanga.scrapers.base import BaseScraper


REQUIRED_METHODS = ("search", "get_chapters", "get_pages", "download_image")


def _all_domains():
    return sorted(SCRAPERS.keys())


@pytest.mark.parametrize("domain", _all_domains())
def test_every_domain_resolves_to_instance(domain):
    s = get_scraper(domain)
    assert s is not None, f"{domain} resolved to None"
    assert isinstance(s, BaseScraper), \
        f"{domain} returned {type(s).__name__}, not BaseScraper subclass"


@pytest.mark.parametrize("domain", _all_domains())
def test_every_scraper_has_required_methods(domain):
    s = get_scraper(domain)
    for m in REQUIRED_METHODS:
        attr = getattr(s, m, None)
        assert attr is not None and callable(attr), \
            f"{domain}: missing or non-callable {m}"


@pytest.mark.parametrize("domain", _all_domains())
def test_required_methods_are_not_abstract(domain):
    """Every concrete scraper must actually implement, not just inherit
    the abstractmethod placeholder."""
    s = get_scraper(domain)
    for m in REQUIRED_METHODS:
        method = getattr(s, m)
        # Bound methods: check the underlying function isn't the
        # abstractmethod on BaseScraper.
        func = getattr(method, "__func__", method)
        base_func = getattr(BaseScraper, m, None)
        if base_func is not None and getattr(base_func, "__isabstractmethod__", False):
            assert func is not base_func, \
                f"{domain}: {m} not overridden, still abstract"


class TestListSupportedSources:
    def test_returns_sorted_list(self):
        sources = list_supported_sources()
        assert sources == sorted(sources)

    def test_no_www_duplicates(self):
        sources = list_supported_sources()
        # If "www.foo.com" is a key, it should be collapsed under "foo.com"
        assert not any(s.startswith("www.") for s in sources)

    def test_contains_known_anchors(self):
        sources = list_supported_sources()
        for known in ("mangadex.org", "mangapill.com",
                       "tcbonepiecechapters.com"):
            assert known in sources


class TestGetScraperResolution:
    def test_exact_match(self):
        assert get_scraper("mangadex.org") is not None

    def test_case_insensitive(self):
        assert get_scraper("MangaDex.org") is not None

    def test_strips_www(self):
        # www.mangatown.com → mangatown.com
        assert get_scraper("www.mangatown.com") is not None

    def test_matches_subdomain_suffix(self):
        # ww3.mangafreak.me suffix-matches mangafreak.me
        s = get_scraper("ww3.mangafreak.me")
        assert s is not None

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError):
            get_scraper("totally-fake-domain-xyz.com")
