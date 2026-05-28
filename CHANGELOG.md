# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

> This is the changelog for the **`cli` branch** — the GUI-free
> variant of MeManga. Desktop-app changes (PySide6 pages, themes,
> first-run install dialog, app icon, build scripts) land on `main`.
> Engine and scraper fixes land on both.

## [Unreleased]

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
