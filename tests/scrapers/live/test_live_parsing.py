"""End-to-end pipeline health checks against live sites.

Reachability alone isn't enough — a site can be up while its HTML
changed in a way that breaks the parser. Each probe here walks the
same stages a real download does, in order, against the live site:

    reachability → search → chapters → pages → image

and fails on the FIRST broken stage, so the pytest output (and the
--health-report JSON) tells you *which part* of the scraper is broken,
e.g. `[STALE:pages] mangapill.com: get_pages(...) returned 0 page
URLs` — not just a generic STALE.

We can't maintain a known-good URL per domain forever, so this file
is deliberately curated — it tests a focused set of high-traffic
sources + every scraper template family (one representative per
template). Broad one-request-per-domain coverage lives in
test_live_reachability.py.

Skipped by default. Opt in with:
    pytest -m live tests/scrapers/live/test_live_parsing.py -v

Single source:
    pytest -m live tests/scrapers/live/test_live_parsing.py \
        -k mangadex.org -v
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pytest

from memanga.scrapers import get_scraper

from _helpers import (  # injected onto sys.path by conftest.py
    HealthResult, StageResult, StageFailure, ScraperPipeline,
    STATUS_OK, STATUS_STALE, STATUS_PROTECTED, STATUS_DEAD, STATUS_HTTP_ERROR,
    STAGE_REACHABILITY,
    probe_url, scraper_base_url,
)


# ─────────────────────────────────────────────────────────────────────
# Per-source probe specs.
#
# query=None means a single-manga template site: skip search and get
# chapters straight from the configured base URL.
#
# Keep these LIGHT — the full pipeline is ~4 requests per source
# (search, chapters, pages, one image). Disable later stages where a
# site makes them too slow/brittle (e.g. check_pages=False for
# Playwright-rendered readers).
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeSpec:
    description: str
    query: str | None = None      # None → single-manga template site
    check_chapters: bool = True
    check_pages: bool = True
    check_image: bool = True


PARSING_PROBES = {
    # ── Aggregators (full pipeline) ──
    "mangadex.org": ProbeSpec("API client", query="one piece"),
    "mangapill.com": ProbeSpec("Simple HTTP aggregator", query="one piece"),
    "mangapark1.com": ProbeSpec("MangaPark", query="one piece"),
    "tcbonepiecechapters.com": ProbeSpec("TCB Scans (project list)",
                                           query="one piece"),
    "mangakakalot.com": ProbeSpec("Mangakakalot", query="naruto"),
    "manganato.com": ProbeSpec("Manganato", query="naruto"),
    "mangahub.io": ProbeSpec("MangaHub", query="one piece"),
    "comix.to": ProbeSpec("Comix.to", query="kubera"),

    # ── One representative per template family ──
    "dddmanga.com": ProbeSpec("NuxtSSR template (single-manga)"),
    "akiramanga.com": ProbeSpec("OGImageMeta template (single-manga)"),
    "overlord-manga.online": ProbeSpec("LaiondCDN template (single-manga)"),
    "hxhmanga.com": ProbeSpec("Mangosm template (single-manga)"),
    "hiperdex.com": ProbeSpec("WordPress Madara template (aggregator)",
                                query="solo leveling"),

    # ── ReadManga base family ──
    # Search-only: chapter listing needs a manga URL slug this site's
    # search results don't provide reliably.
    "readsnk.com": ProbeSpec("ReadManga base (Attack on Titan)",
                               query="attack on titan",
                               check_chapters=False),
}


def _fail_message(domain: str, failure: StageFailure) -> str:
    """Multi-line failure: broken stage first, then what already passed."""
    lines = [f"[{failure.failed.status}:{failure.failed.stage}] "
             f"{domain}: {failure.failed.detail}"]
    for s in failure.stages:
        if s is failure.failed:
            mark = "FAIL"
        elif s.status == STATUS_OK:
            mark = "OK"
        else:
            mark = "WARN"
        lines.append(f"  {mark} {s.stage:12s} {s.detail}  ({s.elapsed_ms:.0f}ms)")
    return "\n".join(lines)


@pytest.mark.live
@pytest.mark.health
@pytest.mark.parametrize("domain,spec",
                          list(PARSING_PROBES.items()),
                          ids=list(PARSING_PROBES.keys()))
def test_scraper_pipeline_live(domain, spec, health_recorder):
    """Stage-by-stage check: reachability, search, chapters, pages, image."""
    # 1. Reachability first — fail fast if the site is dead.
    reach = probe_url(f"https://{domain}")
    stages = [StageResult(STAGE_REACHABILITY, reach.status, reach.detail,
                            reach.elapsed_ms)]
    if reach.status == STATUS_DEAD:
        health_recorder(HealthResult(
            domain, STATUS_DEAD, STAGE_REACHABILITY, reach.detail,
            reach.elapsed_ms, extra={"stages": [asdict(s) for s in stages]}))
        pytest.fail(f"[DEAD:reachability] {domain}: {reach.detail}")
    # PROTECTED is not fatal — the real scraper bypasses Cloudflare,
    # so still run the pipeline and let its stages decide.

    # 2. Walk the pipeline; first broken stage raises StageFailure.
    scraper = get_scraper(domain)
    pipe = ScraperPipeline(scraper, domain)
    pipe.stages = stages
    failure = None
    try:
        if spec.query is None:
            manga_url = scraper_base_url(scraper)
        else:
            results = pipe.search(spec.query)
            manga_url = results[0].url
        if spec.check_chapters:
            chapters = pipe.chapters(manga_url)
            if spec.check_pages:
                pages = pipe.pages(chapters[0])
                if spec.check_image:
                    pipe.image(pages[0])
    except StageFailure as e:
        health_recorder(HealthResult(
            domain, e.failed.status, e.failed.stage, e.failed.detail,
            reach.elapsed_ms,
            extra={"stages": [asdict(s) for s in e.stages]}))
        failure = e

    if failure:
        pytest.fail(_fail_message(domain, failure), pytrace=False)

    result = HealthResult(
        domain, STATUS_OK, "", spec.description, reach.elapsed_ms,
        extra={"stages": [asdict(s) for s in pipe.stages]})
    health_recorder(result)
    ran = ", ".join(s.stage for s in pipe.stages)
    print(f"[{result.status:9s}] {domain:38s} {spec.description} ({ran})")


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
        label = f"{r.domain} (broke at: {r.stage})" if r.stage else r.domain
        by_status.setdefault(r.status, []).append(label)

    lines = ["", "=" * 60, "SCRAPER HEALTH SUMMARY", "=" * 60]
    for status in (STATUS_OK, STATUS_PROTECTED, STATUS_STALE,
                     STATUS_HTTP_ERROR, STATUS_DEAD):
        domains = by_status.get(status, [])
        lines.append(f"{status:10s}: {len(domains):4d}")
        for d in sorted(domains):
            lines.append(f"           - {d}")
    lines.append("=" * 60)
    print("\n".join(lines))
