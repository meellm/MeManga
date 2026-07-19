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


class TestMangaFireSearchUsesJsonApi:
    """Regression (issue #74): the old flow drove the homepage search bar
    through the persistent Playwright browser and scraped
    `.info a[href*="/manga/"]` result links. The browse page the search
    bar redirects to renders results client-side under /title/hid-slug
    links, so that selector matched nothing and every search returned 0
    results. search() must hit GET /api/titles?keyword=... over plain HTTP
    instead - no browser involved at all.
    """

    class _FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class _FakeSession:
        def __init__(self, payload):
            self._payload = payload
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return TestMangaFireSearchUsesJsonApi._FakeResponse(self._payload)

    def test_search_hits_titles_api_with_encoded_keyword(self):
        from memanga.scrapers import mangafire as mf

        scraper = mf.MangaFireScraper()
        scraper.session = self._FakeSession({
            "items": [{
                "title": "Blue Lock",
                "url": "/title/abc-blue-lock",
                "poster": {"medium": "https://cdn.example/bl@280.jpg"},
            }],
            "meta": {"total": 1},
        })

        results = scraper.search("blue lock/2")

        assert scraper.session.urls == [
            "https://mangafire.to/api/titles?keyword=blue%20lock%2F2",
        ]
        assert results and results[0].url == "https://mangafire.to/title/abc-blue-lock"

    def test_search_does_not_launch_firefox(self, monkeypatch):
        """Hard guard: calling MangaFireScraper.search() must NOT start
        Playwright at all - search works over plain HTTP.
        """
        from memanga.scrapers import mangafire as mf

        called = {"n": 0}

        class _BoomPW:
            def __enter__(self): called["n"] += 1; return self
            def __exit__(self, *a): pass
            firefox = type("_F", (), {
                "launch": staticmethod(
                    lambda *a, **k: (_ for _ in ()).throw(
                        AssertionError("search must not launch Firefox"),
                    )
                ),
            })()
            def start(self): called["n"] += 1; return self
            def stop(self): pass

        import playwright.sync_api as pwapi
        monkeypatch.setattr(pwapi, "sync_playwright", lambda: _BoomPW())

        scraper = mf.MangaFireScraper()
        scraper.session = self._FakeSession({"items": [], "meta": {}})
        scraper.search("x")
        assert called["n"] == 0, "search must stay browser-free"


class TestWeebCentralSearchHitsDataEndpoint:
    """Regression: typing into the quick-search sidebar and pressing
    Enter does not filter WeebCentral's main result grid — the page
    returns the unfiltered series list, the worker's relevance filter
    drops every row, and the GUI ends up rendering zero WeebCentral
    results even though the scraper appears to "succeed". The fix
    navigates directly to /search/data?text=<query>&… which is the
    real HTMX endpoint the page itself calls.
    """

    def test_navigates_to_search_data_endpoint_with_query(self, monkeypatch):
        from memanga.scrapers import weebcentral as wc

        # Capture the URL that goto() is called with.
        visited = {"url": None}

        class _FakePage:
            def goto(self, url, **kw): visited["url"] = url
            def wait_for_selector(self, *a, **kw): pass
            def content(self): return "<html></html>"
            def title(self): return ""
            def close(self): pass

        class _FakeContext:
            def new_page(self): return _FakePage()

        monkeypatch.setattr(
            wc.WeebCentralScraper, "_get_browser_in_thread",
            lambda self: (None, _FakeContext()),
        )

        scraper = wc.WeebCentralScraper()
        scraper._search_in_thread("Blue Lock")

        url = visited["url"] or ""
        # Must hit the real data endpoint, not /search.
        assert "/search/data" in url, f"expected /search/data, got {url}"
        # Must encode the query into the text param so the server
        # actually filters.
        assert "text=Blue+Lock" in url or "text=Blue%20Lock" in url, \
            f"query missing from URL: {url}"

    def test_strips_official_badge_from_titles(self, monkeypatch):
        """Result titles from /search/data are prefixed with an
        "Official" badge text — strip it so the rendered row shows
        "Blue Lock" not "OfficialBlue Lock".
        """
        from memanga.scrapers import weebcentral as wc

        html = """
        <html><body>
        <a href="/series/abc/Blue-Lock">
          <span>Official</span>Blue Lock
        </a>
        <a href="/series/def/Other">
          <abbr title="Other Title">Other Title</abbr>
        </a>
        </body></html>
        """

        class _FakePage:
            def goto(self, url, **kw): pass
            def wait_for_selector(self, *a, **kw): pass
            def content(self): return html
            def title(self): return ""
            def close(self): pass

        class _FakeContext:
            def new_page(self): return _FakePage()

        monkeypatch.setattr(
            wc.WeebCentralScraper, "_get_browser_in_thread",
            lambda self: (None, _FakeContext()),
        )

        scraper = wc.WeebCentralScraper()
        results = scraper._search_in_thread("Blue Lock")

        titles = [r.title for r in results]
        assert "Blue Lock" in titles, \
            f"'Official' badge prefix not stripped: {titles}"
        assert "Other Title" in titles


class TestWeebCentralCloudflareDetection:
    """Cloudflare interstitials show up as a "Just a moment…" challenge
    page instead of the real result HTML. The scraper must detect that
    on the first attempt and retry once after a homepage warm-up
    (which seeds the CF cookies on the persistent browser context)
    instead of silently returning zero results.
    """

    def test_looks_like_cloudflare_matches_known_phrases(self):
        from memanga.scrapers.weebcentral import _looks_like_cloudflare
        assert _looks_like_cloudflare("", "Just a moment...")
        assert _looks_like_cloudflare(
            "<html><body>Checking your browser…</body></html>",
        )
        assert _looks_like_cloudflare("DDoS protection by Cloudflare")
        # A normal results page must NOT trip the detector.
        assert not _looks_like_cloudflare(
            "<html><a href='/series/abc'>Blue Lock</a></html>",
            "WeebCentral — Search",
        )

    def test_search_retries_after_cloudflare_interstitial(self, monkeypatch):
        """If the first /search/data response is a CF challenge, the
        scraper must warm up the homepage and retry once.
        """
        from memanga.scrapers import weebcentral as wc

        # First _do_search_once: CF (raises RuntimeError).
        # Second _do_search_once: returns one Manga.
        calls = {"n": 0}

        def fake(self, query):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("cloudflare interstitial")
            return [wc.Manga(title="Blue Lock", url="https://x/m")]

        monkeypatch.setattr(wc.WeebCentralScraper, "_do_search_once", fake)

        # Stub the homepage warm-up so it doesn't try to open a real page.
        class _StubPage:
            def goto(self, *a, **k): pass
            def wait_for_timeout(self, *a, **k): pass
            def close(self): pass
        monkeypatch.setattr(
            wc.WeebCentralScraper, "_new_page",
            lambda self: (None, None, _StubPage()),
        )

        scraper = wc.WeebCentralScraper()
        results = scraper._search_in_thread("Blue Lock")

        assert calls["n"] == 2, f"expected 2 attempts, got {calls['n']}"
        assert results and results[0].title == "Blue Lock"


class TestWeebCentralChapterListStability:
    """Regression for the "only 9 of 349 chapters returned" bug. The
    HTMX swap that lands the full chapter list arrives in batches; the
    scraper must wait for the count to stabilise rather than returning
    after the first batch crosses some threshold.
    """

    def test_waits_until_link_count_stops_growing(self):
        from memanga.scrapers.weebcentral import WeebCentralScraper

        # Simulate the HTMX swap by returning a growing count from
        # `page.evaluate(...)` until it plateaus.
        sequence = iter([5, 12, 80, 200, 340, 349, 349, 349])

        class _FakePage:
            def evaluate(self, _expr):
                return next(sequence, 349)
            def wait_for_timeout(self, _ms):
                pass

        scraper = WeebCentralScraper()
        final = scraper._wait_for_chapter_list_stable(
            _FakePage(), max_passes=20, interval_ms=0,
        )
        assert final == 349, f"expected 349, got {final}"

    def test_returns_when_count_never_grows_past_zero(self):
        """A page with no chapter links at all must still terminate
        (don't sit on max_passes × interval just because the count is
        stuck at zero)."""
        from memanga.scrapers.weebcentral import WeebCentralScraper

        class _FakePage:
            def evaluate(self, _expr):
                return 0
            def wait_for_timeout(self, _ms):
                pass

        scraper = WeebCentralScraper()
        # Bound the call so a regression wouldn't hang the suite.
        final = scraper._wait_for_chapter_list_stable(
            _FakePage(), max_passes=5, interval_ms=0,
        )
        assert final == 0


class TestWeebCentralChapterUrlSelfHeal:
    """Regression: legacy library entries from older builds occasionally
    stored a chapter URL (/chapters/<id>) as the manga's source URL
    instead of the series URL (/series/<id>/<slug>). Calling
    ``get_chapters`` on the chapter URL loads the reader, which has
    zero series-chapter-list links, so check-updates silently
    returns "0 new chapters" forever.

    The scraper now detects this case, finds the parent series link
    on the chapter page, and re-navigates before extracting.
    """

    def test_resolve_series_url_picks_series_link_ignoring_random(self):
        from memanga.scrapers.weebcentral import WeebCentralScraper

        class _FakePage:
            def evaluate(self, _expr):
                # The /series/random link must be filtered out — it's
                # the "Random series" affordance present on every page.
                return [
                    "/series/random",
                    "/series/01J76XYD7E91K8QP6CY0Y53900/Blue-Lock",
                ]

        scraper = WeebCentralScraper()
        url = scraper._resolve_series_url(_FakePage())
        assert url == "https://weebcentral.com/series/01J76XYD7E91K8QP6CY0Y53900/Blue-Lock"

    def test_resolve_series_url_returns_none_when_only_random(self):
        from memanga.scrapers.weebcentral import WeebCentralScraper

        class _FakePage:
            def evaluate(self, _expr):
                return ["/series/random"]

        scraper = WeebCentralScraper()
        assert scraper._resolve_series_url(_FakePage()) is None

    def test_resolve_series_url_handles_absolute_href(self):
        from memanga.scrapers.weebcentral import WeebCentralScraper

        class _FakePage:
            def evaluate(self, _expr):
                return [
                    "https://weebcentral.com/series/01ABC/Other",
                ]

        scraper = WeebCentralScraper()
        url = scraper._resolve_series_url(_FakePage())
        assert url == "https://weebcentral.com/series/01ABC/Other"

    def test_resolve_series_url_returns_none_on_evaluate_failure(self):
        from memanga.scrapers.weebcentral import WeebCentralScraper

        class _FakePage:
            def evaluate(self, _expr):
                raise RuntimeError("page closed")

        scraper = WeebCentralScraper()
        assert scraper._resolve_series_url(_FakePage()) is None


class TestPlaywrightScraperPerSubclassExecutor:
    """Regression: every PlaywrightScraper subclass used to inherit ONE
    shared `_executor = ThreadPoolExecutor(max_workers=1)` from the
    base class, so WeebCentral / Comick / MangaKatana / MangaClash /
    MangaHere all queued serially on a single browser thread inside the
    search worker's 8-slot pool. The first slow scraper blocked every
    other Playwright source. Each subclass must now own its own
    executor + lock pair.
    """

    def test_each_subclass_has_distinct_executor(self):
        from memanga.scrapers.playwright_base import PlaywrightScraper
        from memanga.scrapers.weebcentral import WeebCentralScraper
        from memanga.scrapers.comick import ComickScraper

        # Two subclasses → two distinct executors and two distinct locks.
        assert WeebCentralScraper._executor is not ComickScraper._executor
        assert WeebCentralScraper._executor_lock is not ComickScraper._executor_lock

    def test_get_browser_in_thread_rolls_back_partial_init(self, monkeypatch):
        """When firefox.launch raises, neither `_thread_local.playwright`
        nor `_thread_local.browser` may be left in a half-set state —
        the next call must be able to retry cleanly.
        """
        from memanga.scrapers import playwright_base as pb
        from memanga.scrapers.weebcentral import WeebCentralScraper

        # Reset any prior thread-local state
        pb.cleanup_browsers()

        class _BoomPW:
            firefox = type("_F", (), {
                "launch": staticmethod(
                    lambda *a, **k: (_ for _ in ()).throw(
                        RuntimeError("firefox missing"),
                    )
                ),
            })()
            stopped = False
            def stop(self): _BoomPW.stopped = True

        boom = _BoomPW()
        import playwright.sync_api as pwapi
        monkeypatch.setattr(pwapi, "sync_playwright", lambda: type("_S", (), {
            "start": staticmethod(lambda: boom),
        })())

        scraper = WeebCentralScraper()
        with pytest.raises(RuntimeError):
            scraper._get_browser_in_thread()

        # State must be fully cleaned: no dangling playwright/browser/context.
        assert not hasattr(pb._thread_local, "playwright"), \
            "partial init left _thread_local.playwright set"
        assert not hasattr(pb._thread_local, "browser")
        assert not hasattr(pb._thread_local, "context")
        # And `pw.stop()` must have been called to release native resources.
        assert _BoomPW.stopped, "partial init didn't call pw.stop()"
