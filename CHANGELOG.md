# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- PySide6 desktop GUI (Library / Detail / Reader / Downloads / Search /
  Notifications / Sources / Settings) — full rewrite of the user-facing
  app.
- Offline mode: `NetworkMonitor` daemon publishes online/offline events
  on a 30 s / 5 s probe cadence; UI gates network-bound actions and
  auto-recovers when the connection returns.
- Search-time chapter-count chips per source so users can spot
  out-of-date / empty sources at a glance.
- `memanga failed` CLI command: lists, retries, or clears failed
  chapter download records.
- Two build modes: `python build.py` (single-file dev exe with console)
  and `python build_app.py` (single-file release exe, no console).
- Live scraper health-check test suite under `tests/scrapers/live/`
  (opt-in via `-m live`).
- Three previously-orphaned scrapers wired in: `blamemanga.com`,
  `jjkmanga.net`, `kagane.org`.

### Changed
- Search now searches ~120 curated aggregators (was 290) — template-
  based single-manga sites are filtered out by default since their
  `search()` only matches their own keyword list.
- Search results are sorted by source popularity (MangaDex first, then
  MangaPill, MangaFire, …).
- Search results are filtered for query relevance — single-manga
  aggregators no longer pollute results with their hardcoded title.
- WeebCentral switched to full Playwright (cloudscraper was returning
  404 on chapter listings).
- Email attachment threshold lowered from 23 MB to 18 MB to account
  for base64 encoding overhead (Gmail's 25 MB limit applies to the
  encoded size).
- Partial chapter downloads are no longer silently saved as an
  incomplete CBZ. The downloader now retries failed pages up to 3×
  with exponential backoff and raises `DownloaderError` if pages are
  still missing — the chapter is not marked as downloaded.

### Removed
- Design references (HTML/CSS/JS used during the GUI port) are no
  longer tracked.
- Internal "Not implemented" punch list moved out of the repo.

### Fixed
- See git log for the full change set during the PySide6 development
  cycle. Notable issues closed:
  - #13 GUI palette mismatch with theme tokens
  - #14 "Cancel all" wasn't draining the download queue
  - #15 Detail page wasn't preserving the downloaded-chapter list
  - #16 Reader's Ctrl+wheel zoom was firing on plain wheel
  - #18 Library cards didn't show read count
  - #20 `download_from N` didn't update last_chapter threshold
  - #21 Reader pan wasn't enabled when zoomed
  - #23 Output paths weren't ending up under `<dir>/<title>/`
  - #26 Failed downloads created an incomplete CBZ marked complete

## Earlier versions

Pre-PySide6 versions tracked the CLI-only releases — see the git tag
history (`v0.0.x` → `v0.1.0`) for details.
