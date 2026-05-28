"""End-to-end parsing health checks against live sites.

Reachability alone isn't enough — a site can be up while its HTML
changed in a way that breaks the parser. This file actually invokes
each scraper's search() / get_chapters() / get_pages() against the
real site and fails when the parser returns zero results (likely
indicates the site's structure drifted).

We can't maintain a known-good URL per domain forever, so this file
is deliberately curated — it tests a focused set of high-traffic
sources + every scraper template family (one representative per
template).

Skipped by default. Opt in with:
    pytest -m live tests/scrapers/live/test_live_parsing.py -v

Single source:
    pytest -m live tests/scrapers/live/test_live_parsing.py \
        -k mangadex.org -v
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper

from _helpers import (  # injected onto sys.path by conftest.py
    HealthResult, STATUS_OK, STATUS_STALE, STATUS_PROTECTED, STATUS_DEAD,
    probe_url, assert_alive, assert_parsed_something, LIVE_TIMEOUT,
)


# ─────────────────────────────────────────────────────────────────────
# Per-source health probes.
#
# Each probe is a callable that takes the scraper instance and either:
#   - returns silently on success
#   - calls pytest.fail / pytest.skip with a classified message
#
# Keep these LIGHT — one search + one get_chapters per probe is plenty.
# Avoid get_pages on Playwright sites (too slow + brittle for CI).
# ─────────────────────────────────────────────────────────────────────


def _probe_search_then_chapters(scraper, query: str, *,
                                  expect_results: int = 1,
                                  expect_chapters: int = 1,
                                  do_chapters: bool = True):
    """search(query) → ≥1 result; first result's chapters → ≥1 chapter."""
    results = assert_parsed_something(scraper.search, query,
                                        min_items=expect_results)
    if not do_chapters:
        return
    first = results[0]
    assert_parsed_something(scraper.get_chapters, first.url,
                              min_items=expect_chapters)


def _probe_single_manga_chapters(scraper):
    """For single-manga template sites: chapters from the configured base."""
    base = getattr(scraper, "BASE_URL", None) or getattr(scraper, "base_url", "")
    assert_parsed_something(scraper.get_chapters, base, min_items=1)


# Domain → (description, probe-fn). Curated list of sites we test
# end-to-end. Easy to expand: just add another entry.
PARSING_PROBES = {
    # ── Aggregators (search + chapters) ──
    "mangadex.org": (
        "API client", lambda s: _probe_search_then_chapters(s, "one piece"),
    ),
    "mangapill.com": (
        "Simple HTTP aggregator",
        lambda s: _probe_search_then_chapters(s, "one piece"),
    ),
    "tcbonepiecechapters.com": (
        "TCB Scans (project list)",
        lambda s: _probe_search_then_chapters(s, "one piece"),
    ),
    "mangakakalot.com": (
        "Mangakakalot",
        lambda s: _probe_search_then_chapters(s, "naruto"),
    ),
    "manganato.com": (
        "Manganato",
        lambda s: _probe_search_then_chapters(s, "naruto"),
    ),
    "mangahub.io": (
        "MangaHub", lambda s: _probe_search_then_chapters(s, "one piece"),
    ),

    # ── One representative per template family ──
    "dddmanga.com": (
        "NuxtSSR template (single-manga)",
        _probe_single_manga_chapters,
    ),
    "akiramanga.com": (
        "OGImageMeta template (single-manga)",
        _probe_single_manga_chapters,
    ),
    "overlord-manga.online": (
        "LaiondCDN template (single-manga)",
        _probe_single_manga_chapters,
    ),
    "hxhmanga.com": (
        "Mangosm template (single-manga)",
        _probe_single_manga_chapters,
    ),
    "hiperdex.com": (
        "WordPress Madara template (aggregator)",
        lambda s: _probe_search_then_chapters(s, "solo leveling"),
    ),

    # ── ReadManga base family ──
    "readsnk.com": (
        "ReadManga base (Attack on Titan)",
        lambda s: _probe_search_then_chapters(s, "attack on titan",
                                                do_chapters=False),
    ),
}


@pytest.mark.live
@pytest.mark.health
@pytest.mark.parametrize("domain,description,probe",
                          [(d, desc, fn) for d, (desc, fn) in PARSING_PROBES.items()],
                          ids=list(PARSING_PROBES.keys()))
def test_scraper_parses_live_site(domain, description, probe, health_recorder):
    """Full end-to-end check: reachability + parser still extracts data."""
    # 1. Reachability first — fail fast if the site is dead.
    base = f"https://{domain}"
    reach = probe_url(base)
    if reach.status == STATUS_DEAD:
        health_recorder(reach)
        pytest.fail(f"[DEAD] {domain}: {reach.detail}")
    if reach.status == STATUS_PROTECTED:
        # Real scraper bypasses Cloudflare — still try the probe.
        pass

    # 2. Run the probe. Wraps any exception into STALE-style failure.
    scraper = get_scraper(domain)
    try:
        probe(scraper)
        result = HealthResult(domain, STATUS_OK, description,
                                reach.elapsed_ms)
    except pytest.skip.Exception:
        raise
    except (pytest.fail.Exception, AssertionError) as e:
        result = HealthResult(domain, STATUS_STALE, str(e), reach.elapsed_ms)
        health_recorder(result)
        raise
    except Exception as e:
        result = HealthResult(domain, STATUS_STALE,
                                f"{type(e).__name__}: {e}", reach.elapsed_ms)
        health_recorder(result)
        raise

    health_recorder(result)
    print(f"[{result.status:9s}] {domain:38s} {description}")


# ─────────────────────────────────────────────────────────────────────
# Summary test — runs LAST, prints a one-page status table covering
# everything probed in this run. Always passes (it's reporting, not
# validation). Useful in CI artifacts.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.live
@pytest.mark.health
def test_zzz_health_summary_report():  # name puts it last alphabetically
    """Always-pass summary so the run finishes with a report block.

    The actual data lives in tests/scrapers/live/conftest._RESULTS,
    accumulated by every parametrized test above. We print a digest
    here — JSON dump still goes via --health-report.
    """
    # Reach into the conftest module — its session-scoped accumulator
    # is the source of truth for the run.
    import sys
    conftest = sys.modules.get("conftest") or sys.modules.get(
        "tests.scrapers.live.conftest")
    _RESULTS = getattr(conftest, "_RESULTS", []) if conftest else []

    if not _RESULTS:
        pytest.skip("no results accumulated — were any live tests run?")

    by_status: dict[str, list[str]] = {}
    for r in _RESULTS:
        by_status.setdefault(r.status, []).append(r.domain)

    lines = ["", "=" * 60, "SCRAPER HEALTH SUMMARY", "=" * 60]
    for status in (STATUS_OK, STATUS_PROTECTED, STATUS_STALE, STATUS_DEAD):
        domains = by_status.get(status, [])
        lines.append(f"{status:10s}: {len(domains):4d}")
        for d in sorted(domains):
            lines.append(f"           - {d}")
    lines.append("=" * 60)
    print("\n".join(lines))
