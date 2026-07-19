# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

> This is the changelog for the **`cli` branch** — the GUI-free
> variant of MeManga. Desktop-app changes (PySide6 pages, themes,
> first-run install dialog, app icon, build scripts) land on `main`.
> Engine and scraper fixes land on both.

## [Unreleased]

## [0.3.3] - 2026-07-12

### Fixed
- #83 MangaDex API requests could fail with HTTP 400 because the shared
  scraper session claimed a browser user agent without the `Sec-Fetch-*`
  headers MangaDex expects. Default scraper headers now include those
  browser fetch metadata headers, restoring MangaDex search and chapter
  requests.

### Acknowledgements
- Special thanks to @Camponotus-vagus for the detailed issue diagnostics
  and follow-up testing that helped shape the fixes.

## [0.3.2] - 2026-07-08

### Added
- #77 Comix.to is now available as a supported source. Search runs
  through the rendered search flow, chapter discovery reads paginated
  chapter rows, and reader image extraction/downloads use the headers
  required by the site.
- #78 MangaPark is now available as a supported source through
  `mangapark1.com`, including search, chapter-list parsing, reader page
  extraction, CDN image downloads, and live scraper diagnostics.
- Live scraper diagnostics now include staged parsing probes that make
  source-specific breakage easier to confirm without running the full
  application workflow.

### Fixed
- #74 MangaFire search now reads the current `/api/titles` JSON payload
  instead of scraping the old browser search page, restoring title
  discovery for queries such as `one piece`, `ao no hako`, and
  `super no ura`.

## [0.3.1] - 2026-07-06

### Fixed
- #71 MangaFire changed its chapter and page endpoints, so saved
  MangaFire library entries could no longer fetch real chapter lists.
  MangaFire now reads the current `/api` chapter and page payloads,
  keeps old saved MangaFire URLs compatible, follows paginated chapter
  lists, and deduplicates repeated chapter numbers before update checks
  or downloads run.

## [0.3.0] - 2026-06-13

### Added
- #31 CLI-only users had no way to discover manga by title without
  leaving the terminal, finding a source URL manually, then pasting it
  back into `memanga add`. The new `memanga search` command reuses the
  shared multi-source search engine, with relevance filtering, source
  ordering, chapter-count probes, JSON output, and direct add support.
- #35 A source could report a huge bogus chapter jump and MeManga would
  trust it, potentially downloading or emailing dozens of incorrect
  chapters. Suspicious update batches are now scored before delivery,
  checked against backup sources when available, and held back unless
  they are confirmed or explicitly forced.

### Fixed
- #42 Backup import ignored the export schema version, so unsupported
  backup data could be accepted silently. Import now validates the
  version field before restoring data, giving future migrations a safe
  rejection path instead of corrupt or surprising state.

## [0.2.0] - 2026-05-28

### Added
- `memanga failed` command: lists, retries, or clears failed
  chapter download records.
- Live scraper health-check test suite under `tests/scrapers/live/`
  (opt-in via `-m live`).
- Three previously-orphaned scrapers wired in: `blamemanga.com`,
  `jjkmanga.net`, `kagane.org`.

### Changed
- Search now sweeps ~120 curated aggregators (was 290) — template-
  based single-manga sites are filtered out by default since their
  `search()` only matches their own keyword list.
- Search results are sorted by source popularity (MangaDex first,
  then MangaPill, MangaFire, …).
- Search results are filtered for query relevance — single-manga
  aggregators no longer pollute results with their hard-coded title.
- WeebCentral search hits the real `/search/data?text=…` HTMX
  endpoint directly instead of typing into the quick-search
  sidebar, so results actually filter to the query.
- MangaFire search reuses a persistent Firefox via the existing
  `VRFGenerator` singleton instead of launching a fresh browser per
  call (~10× faster after warm-up).
- Each `PlaywrightScraper` subclass owns its own
  `ThreadPoolExecutor` + lock, so WeebCentral / Comick / MangaKatana
  / MangaClash run in parallel inside the search worker pool
  instead of queueing through one shared browser thread.
- Email attachment threshold lowered from 23 MB to 18 MB to account
  for base64 encoding overhead (Gmail's 25 MB limit applies to the
  encoded size).
- Partial chapter downloads are no longer silently saved as an
  incomplete CBZ. The downloader retries failed pages up to 3× with
  exponential backoff and raises `DownloaderError` if pages are
  still missing — the chapter is not marked as downloaded.

### Fixed
- `_get_browser_in_thread` is now atomic: on `firefox.launch()`
  failure it rolls back `sync_playwright().start()` instead of
  leaving `_thread_local.playwright` half-set, which previously
  crashed every subsequent scraper on the same worker thread.
- WeebCentral self-heals legacy library entries whose stored URL is
  a `/chapters/<id>` page by following the link back to the parent
  `/series/`.
- Cloudflare interstitial detection with homepage-warm-up retry on
  WeebCentral search.
- WeebCentral chapter-list reader scrolls until the document height
  stops growing (was capped at 12 000 px, truncating chapters above
  ~40 pages).
- Notable historical issues closed:
  - #20 `download_from N` didn't update last_chapter threshold
  - #23 Output paths weren't ending up under `<dir>/<title>/`
  - #26 Failed downloads created an incomplete CBZ marked complete

### Removed
- Internal "Not implemented" punch list moved out of the repo.

## Earlier versions

Pre-PySide6 versions tracked the CLI-only releases — see the git tag
history (`v0.0.x` → `v0.1.0`) for details.
