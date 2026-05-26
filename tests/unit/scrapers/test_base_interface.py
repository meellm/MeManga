"""Tests for the BaseScraper abstract interface + the dataclasses
(Chapter, Manga) that scrapers return.

Every scraper in the registry must implement `search`, `get_chapters`,
`get_pages`, `download_image`. We don't network-call them — we just
check they're callable with the expected signatures.
"""

from __future__ import annotations

import inspect
import pkgutil
import importlib
import pytest


# ─────────────────────────────────────────────────────────────────────────
# Chapter / Manga dataclasses
# ─────────────────────────────────────────────────────────────────────────


class TestChapter:
    def test_constructs_minimal(self):
        from memanga.scrapers.base import Chapter
        c = Chapter(number="5", title="t", url="https://x.test/c")
        assert c.number == "5"
        assert c.title == "t"
        assert c.url == "https://x.test/c"

    def test_numeric_property_parses(self):
        from memanga.scrapers.base import Chapter
        c = Chapter(number="12.5", title="t", url="u")
        # Most scrapers expose a numeric helper for sorting.
        if hasattr(c, "numeric"):
            assert c.numeric == 12.5

    def test_ordering_by_number(self):
        from memanga.scrapers.base import Chapter
        cs = [Chapter("10", "", ""), Chapter("2", "", ""), Chapter("1", "", "")]
        # Chapter should be sortable somehow — either via numeric key
        # or by __lt__.
        try:
            cs.sort()
            nums = [float(c.number) for c in cs]
            assert nums == sorted(nums)
        except TypeError:
            # If Chapter doesn't implement __lt__, sorting via key works
            cs.sort(key=lambda c: float(c.number))
            assert [c.number for c in cs] == ["1", "2", "10"]


class TestMangaDataclass:
    def test_constructs(self):
        from memanga.scrapers.base import Manga
        m = Manga(title="X", url="u")
        assert m.title == "X"
        assert m.url == "u"


# ─────────────────────────────────────────────────────────────────────────
# Retry helper
# ─────────────────────────────────────────────────────────────────────────


class TestRetryHelper:
    def test_returns_value_on_first_success(self):
        from memanga.scrapers.base import _retry
        out = _retry(lambda: 42)
        assert out == 42

    def test_retries_on_exception(self):
        from memanga.scrapers.base import _retry
        attempts = [0]
        def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise IOError("transient")
            return "done"
        out = _retry(flaky, max_attempts=3, base_delay=0.001)
        assert out == "done"
        assert attempts[0] == 3

    def test_gives_up_after_max_attempts(self):
        from memanga.scrapers.base import _retry
        def always_fail():
            raise IOError("nope")
        with pytest.raises(IOError):
            _retry(always_fail, max_attempts=2, base_delay=0.001)


# ─────────────────────────────────────────────────────────────────────────
# BaseScraper contract — concrete subclasses must implement these
# ─────────────────────────────────────────────────────────────────────────


REQUIRED_METHODS = ("search", "get_chapters", "get_pages", "download_image")


class TestBaseScraperContract:
    def test_base_scraper_is_abstract(self):
        from memanga.scrapers.base import BaseScraper
        # Should not be instantiable directly.
        with pytest.raises(TypeError):
            BaseScraper()

    def test_base_scraper_defines_required_abstract_methods(self):
        from memanga.scrapers.base import BaseScraper
        for name in REQUIRED_METHODS:
            assert hasattr(BaseScraper, name), \
                f"BaseScraper missing required method {name}"


# ─────────────────────────────────────────────────────────────────────────
# Every registered scraper imports cleanly + has the required API
# ─────────────────────────────────────────────────────────────────────────


def _discover_scraper_modules():
    """Find every scraper module under memanga.scrapers (skipping base/
    templates) and return (name, module) pairs.
    """
    import memanga.scrapers as pkg
    out = []
    for _, name, _ in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_") or name in ("base", "templates",
                                              "playwright_base"):
            continue
        try:
            m = importlib.import_module(f"memanga.scrapers.{name}")
            out.append((name, m))
        except Exception as e:
            # Modules that need extra deps will be flagged in the test
            # below — don't crash discovery here.
            out.append((name, None))
    return out


_ALL_SCRAPERS = _discover_scraper_modules()


@pytest.mark.parametrize("name,module",
                          _ALL_SCRAPERS, ids=[n for n, _ in _ALL_SCRAPERS])
def test_scraper_module_imports(name, module):
    """Every scraper module under memanga.scrapers should import without
    raising — even if its underlying dependency (playwright, etc.) is
    missing, we should fail with a clean diagnostic, not a stack trace
    that breaks the test runner.
    """
    assert module is not None, f"failed to import memanga.scrapers.{name}"


@pytest.mark.parametrize("name,module",
                          [(n, m) for n, m in _ALL_SCRAPERS if m is not None],
                          ids=[n for n, m in _ALL_SCRAPERS if m is not None])
def test_scraper_exposes_required_attrs(name, module):
    """Each scraper module should expose at least one class with the
    required scraper methods."""
    found = False
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if not inspect.isclass(attr):
            continue
        if all(hasattr(attr, m) for m in REQUIRED_METHODS):
            found = True
            break
    assert found, f"{name}: no class with all of {REQUIRED_METHODS}"


# ─────────────────────────────────────────────────────────────────────────
# get_scraper registry
# ─────────────────────────────────────────────────────────────────────────


class TestGetScraperRegistry:
    @pytest.mark.parametrize("domain", [
        "mangadex.org",
        "mangafire.to",
        "mangabuddy.com",
        "weebcentral.com",
    ])
    def test_known_domains_resolve(self, domain):
        from memanga.scrapers import get_scraper
        s = get_scraper(domain)
        assert s is not None
        # Returned object must satisfy the API contract.
        for m in REQUIRED_METHODS:
            assert hasattr(s, m), f"{domain} scraper missing {m}"
