"""
Shared multi-source search engine.

Both the CLI (`memanga search`) and the GUI Search page run the same
sweep: fan a query out to many scrapers in parallel, filter the
returned titles for relevance, and order results by source
popularity. The GUI drives it through `BackgroundWorker.search_manga`
(event-bus based, cancellable); the CLI uses the synchronous
:func:`sweep` below. The building blocks live here so the two
surfaces can't drift apart.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

from .scrapers import POPULAR_SOURCES, get_scraper


# ─────────────────────────────────────────────────────────────────────
# Relevance filter — many "single-manga" scrapers in the registry
# (BeastarsManga, TGManga, AjimeNoIppo, …) hard-code `search()` to
# return their one manga regardless of the query string. Without this
# filter, searching "Blue Lock" returns Beastars, Tokyo Ghoul, Hajime
# no Ippo, etc. We compare the returned title against the query tokens
# and drop everything that's obviously unrelated. Cheap and idempotent
# — scrapers that already do server-side search (MangaDex API, etc.)
# pass through unchanged.
# ─────────────────────────────────────────────────────────────────────


_WORD_RE = re.compile(r"[a-z0-9]+")


def result_matches_query(title: str, query: str) -> bool:
    """Decide whether `title` is a plausible match for `query`.

    Rules:
      - Empty query → everything passes.
      - Whole query substring in title → pass.
      - Tokenise both, drop common stopwords. Short queries (1-2
        tokens) require ALL tokens to be present in the title. Longer
        queries require ≥ 60% of tokens.
    """
    if not query:
        return True
    title_l = (title or "").lower()
    query_l = query.lower().strip()
    if not title_l:
        return False
    if query_l in title_l:
        return True
    q_tokens = [t for t in _WORD_RE.findall(query_l) if len(t) >= 2]
    if not q_tokens:
        return True
    t_tokens = set(_WORD_RE.findall(title_l))
    matched = sum(1 for t in q_tokens if t in t_tokens or t in title_l)
    if len(q_tokens) <= 2:
        return matched == len(q_tokens)
    return matched / len(q_tokens) >= 0.6


# ─────────────────────────────────────────────────────────────────────
# Popularity ranking — sources we hit first (and present first in the
# results list). Earlier in POPULAR_SOURCES = more popular / more
# trusted. Anything not listed gets rank=999 (shown after the named
# ones, stable alphabetical order between them).
# ─────────────────────────────────────────────────────────────────────


_POPULARITY_RANK = {d: i for i, d in enumerate(POPULAR_SOURCES)}


def source_rank(domain: str) -> int:
    """Lower = more popular. Unranked sources sort after named ones."""
    return _POPULARITY_RANK.get(domain, 999)


def sort_sources_by_popularity(sources: List[str]) -> List[str]:
    """Return `sources` ordered most-popular-first, then alphabetical."""
    return sorted(sources, key=lambda d: (source_rank(d), d))


# Sources known to be broken or dead — skipped in search so a worker
# slot doesn't wait out the full timeout. Re-run tests/scrapers/live/
# against a candidate domain before re-enabling it here.
#
# Reasons:
#   - SHUTDOWN:     site shows a "shutdown" page (mangasee123)
#   - DEAD_DNS:     domain resolves nowhere, every request times out
#   - REPLACED:     domain forwards to an unrelated site (mangakakalot →
#                   spinzywheel.com gambling page)
#   - NEEDS_JS_API: site has an SPA + client-side search API that the
#                   plain HTML doesn't expose (asurascans, mgeko.cc)
BROKEN_SEARCH_SOURCES = {
    # SHUTDOWN
    "mangasee123.com",            # serves a "shutdown" image
    # DEAD_DNS / unreachable
    "mangareader.to",
    "chapmanganato.to",
    "readmanganato.com",
    "manganato.com",
    "mangakakalot.com",           # → spinzywheel.com
    "mangakakalot.to",
    "manga4life.com",             # ex-mangasee mirror, also dead
    "mangalife.us",
    # REPLACED / regional block / chronic timeout
    "mangatown.com", "www.mangatown.com",
    "manhwa18.cc",
    "mangafreak.me", "mangafreak.ws", "ww2.mangafreak.me",
    "bato.to", "batoto.to",
    # NEEDS_JS_API — static HTML returns 0 hits, real search is client-side
    "asuracomic.net", "asurascans.com", "asuratoon.com",
    "mgeko.cc",
    "mangabolt.com",
    "truemanga.com", "mangamonk.com",
    "mangahub.us",                # search endpoint requires headless JS
    "hivetoons.org", "hivetoon.com",
    "isekaiscan.com",
    "zinmanga.com",
    "kunmanga.com",
    "flamecomics.xyz",            # SPA, search via API only
    # Strong Cloudflare interactive challenge — even cloudscraper gets a
    # 403. Would need a real headless browser. Drops them from search;
    # user can still add manga from these by URL.
    "manhuafast.com",
    "manhuaus.org",
    # WTO (Bato mirror) - Cloudflare managed challenge that stays stuck
    # on "Just a moment..." even for headless Firefox + stealth in
    # probes. Its Playwright scraper is registered for add-by-URL, but
    # a sweep slot would just burn its 60s budget on the challenge.
    "wto.to",
    # Manganato.gg also serves the Cloudflare "Just a moment..." page
    # to plain requests + Playwright without a deep wait. Its existing
    # Playwright scraper times out at the 60s mark in practice.
    "manganato.gg",
}


def compute_search_sources(config) -> List[str]:
    """Build the source list for a multi-source sweep.

    Searching every supported source (~290) would mostly hit
    template-based single-manga sites (dddmanga.com, chainsawdevil.com,
    …) whose `search()` is hard-wired to their one manga's keywords —
    pure wasted network for any other query. We restrict to:

      1. Real aggregators (anything in SCRAPERS that's not a
         template-based single-manga site).
      2. Every source the user has in their library — they've proven
         useful for this user already.
      3. Minus anything disabled on the Sources page
         (`sources.disabled` in config).
      4. Minus sites that are known dead / not searchable from plain
         HTML (BROKEN_SEARCH_SOURCES — verified against the live
         probe; updating that set is the supported way to re-enable a
         source once its scraper is fixed).
    """
    from .scrapers import SCRAPERS
    try:
        from .scrapers.registry import TEMPLATE_SCRAPERS
    except Exception:
        TEMPLATE_SCRAPERS = {}

    disabled = set(config.get("sources.disabled", []) or [])
    library: set = set()
    for m in config.get("manga", []):
        for s in m.get("sources", []) or []:
            if isinstance(s, dict):
                d = s.get("source", "")
                if not d and s.get("url"):
                    d = urlparse(s["url"]).netloc.replace("www.", "")
                if d:
                    library.add(d)
            elif isinstance(s, str):
                d = urlparse(s).netloc.replace("www.", "")
                if d:
                    library.add(d)
        d = m.get("source", "")
        if d:
            library.add(d)

    # Real aggregators: anything in SCRAPERS that's NOT a template-based
    # single-manga site. Template scrapers' search() only matches their
    # configured keywords, so we'd just be probing the network for no
    # reason.
    template_domains = set(TEMPLATE_SCRAPERS.keys())
    aggregators = {d for d in SCRAPERS.keys() if d not in template_domains}

    # De-dupe canonical hostnames — many aliases map to the same scraper
    # class (e.g. tcbscans.com / tcbscans.me / tcbonepiecechapters.com
    # all hit the same TCBScansScraper). We can just collapse via
    # set-of-classes lookup keyed on identity.
    canonical: dict = {}
    for d in (library | aggregators):
        if d in disabled:
            continue
        if d in BROKEN_SEARCH_SOURCES:
            continue
        cls = SCRAPERS.get(d)
        if cls is None:
            continue
        key = id(cls)
        # Prefer library domains, then popular canonical domains, over
        # less user-facing aliases such as api.mangadex.org.
        current = canonical.get(key)
        if (
            current is None
            or (d in library and current not in library)
            or (
                (d in library) == (current in library)
                and source_rank(d) < source_rank(current)
            )
        ):
            canonical[key] = d
    return sorted(canonical.values())


# ─────────────────────────────────────────────────────────────────────
# Synchronous sweep — used by the CLI. The GUI keeps its own
# event-bus/cancellation wrapper in gui/workers.py but shares the
# filter, ranking and source selection above.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """One manga hit from one source."""
    title: str
    url: str
    source: str
    cover_url: Optional[str] = None
    description: Optional[str] = None
    chapter_count: Optional[int] = None


@dataclass
class SourceFailure:
    """A source whose search() raised — kept so callers can report
    partial coverage instead of silently hiding broken sources."""
    source: str
    error: str


def _search_one_source(query: str, domain: str,
                       limit: Optional[int]) -> List[SearchResult]:
    scraper = get_scraper(domain)
    found = scraper.search(query) or []
    out: List[SearchResult] = []
    for m in found:
        # Tolerate both Manga dataclass (the contract) and plain dict
        # (older scrapers / future variants).
        if hasattr(m, "title") and hasattr(m, "url"):
            title = getattr(m, "title", "") or ""
            url = getattr(m, "url", "") or ""
            cover = getattr(m, "cover_url", None)
            desc = getattr(m, "description", None)
        elif isinstance(m, dict):
            title = m.get("title", "") or ""
            url = m.get("url", "") or ""
            cover = m.get("cover_url")
            desc = m.get("description")
        else:
            continue
        if not title or not url:
            continue
        if not result_matches_query(title, query):
            # Single-manga site returned its manga for an unrelated
            # query — drop it silently.
            continue
        out.append(SearchResult(title=title, url=url, source=domain,
                                cover_url=cover, description=desc))
        if limit is not None and len(out) >= limit:
            break
    return out


def sweep(
    query: str,
    sources: List[str],
    *,
    limit: Optional[int] = None,
    max_workers: int = 8,
    on_source_done: Optional[Callable[[str, int], None]] = None,
    on_source_failed: Optional[Callable[[str, str], None]] = None,
) -> Tuple[List[SearchResult], List[SourceFailure]]:
    """Search `query` across `sources` in parallel.

    Blocks until every source has answered or failed. Results come
    back ordered by source popularity (then source name), with each
    source's own ordering preserved within that. `limit` caps results
    per source, not overall.

    Concurrency is capped at `max_workers` — hundreds of sources × 1
    thread each would saturate the network stack and spin up a flood
    of Playwright browsers.
    """
    ordered = sort_sources_by_popularity(sources)
    results: List[SearchResult] = []
    failures: List[SourceFailure] = []
    if not ordered:
        return results, failures

    with ThreadPoolExecutor(max_workers=max_workers,
                            thread_name_prefix="memanga-search") as pool:
        futures = {pool.submit(_search_one_source, query, d, limit): d
                   for d in ordered}
        for f in as_completed(futures):
            domain = futures[f]
            try:
                found = f.result()
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"[:160]
                failures.append(SourceFailure(source=domain, error=msg))
                if on_source_failed:
                    on_source_failed(domain, msg)
                continue
            results.extend(found)
            if on_source_done:
                on_source_done(domain, len(found))

    # Stable sort: per-source order is preserved, sources are ranked
    # by popularity so MangaDex / MangaPill hits lead the list.
    results.sort(key=lambda r: (source_rank(r.source), r.source))
    return results, failures


def fetch_chapter_count(source: str, url: str) -> Optional[int]:
    """Chapter count for one result, or None when the probe fails.
    One attempt only — callers wanting retries (the GUI chip probe)
    layer them on top."""
    try:
        scraper = get_scraper(source)
        chapters = scraper.get_chapters(url) or []
        return len(chapters)
    except Exception:
        return None


def probe_chapter_counts(results: List[SearchResult],
                         max_workers: int = 6) -> None:
    """Fill in `chapter_count` on each result in place, in parallel.
    Failed probes leave the field None."""
    if not results:
        return
    with ThreadPoolExecutor(max_workers=max_workers,
                            thread_name_prefix="chapter-count") as pool:
        futures = {pool.submit(fetch_chapter_count, r.source, r.url): r
                   for r in results}
        for f in as_completed(futures):
            futures[f].chapter_count = f.result()
