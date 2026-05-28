# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-05-28

### Added
- PySide6 desktop GUI (Library / Detail / Reader / Downloads / Search /
  Notifications / Sources / Settings) — full rewrite of the user-facing
  app.
- First-run Firefox install dialog with streaming progress bar and
  collapsible log, replacing the blocking "please wait" message box.
- App icon: a custom open-book + download-chevron mark drawn from
  primitives via `scripts/generate_icon.py`. Bundled as multi-resolution
  PNG / ICO / ICNS and applied as the window + dock / taskbar icon.
- Offline mode: `NetworkMonitor` daemon publishes online/offline events
  on a 30 s / 5 s probe cadence; UI gates network-bound actions and
  auto-recovers when the connection returns.
- Search-time chapter-count chips per source so out-of-date or empty
  sources are visible at a glance.
- `memanga failed` CLI command: lists, retries, or clears failed
  chapter download records.
- Two build modes: `python build.py` (single-file dev exe with console)
  and `python build_app.py` (single-file release exe, no console).
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
  aggregators no longer pollute results with their hardcoded title.
- WeebCentral search hits the real `/search/data?text=…` HTMX endpoint
  directly instead of typing into the quick-search sidebar, so results
  actually filter to the query.
- MangaFire search reuses a persistent Firefox via the existing
  `VRFGenerator` singleton instead of launching a fresh browser per
  call (~10× faster after warm-up).
- Each `PlaywrightScraper` subclass now owns its own
  `ThreadPoolExecutor` + lock, so WeebCentral / Comick / MangaKatana /
  MangaClash run in parallel inside the search worker pool instead of
  queueing through a single shared browser thread.
- Email attachment threshold lowered from 23 MB to 18 MB to account
  for base64 encoding overhead (Gmail's 25 MB limit applies to the
  encoded size).
- Partial chapter downloads are no longer silently saved as an
  incomplete CBZ. The downloader retries failed pages up to 3× with
  exponential backoff and raises `DownloaderError` if pages are still
  missing — the chapter is not marked as downloaded.

### Fixed
- `_get_browser_in_thread` is now atomic: on `firefox.launch()` failure
  it rolls back `sync_playwright().start()` instead of leaving
  `_thread_local.playwright` half-set, which previously crashed every
  subsequent scraper on the same worker thread.
- Windows release builds bundle `keyring.backends.Windows` +
  `pywin32_ctypes` as explicit PyInstaller hidden imports, so saved
  email passwords persist via the Credential Manager instead of being
  silently discarded by keyring's `Null` backend.
- Windows release builds no longer flash a `cmd.exe` window when the
  scheduled-task helpers run (`schtasks` calls now pass
  `no_window_kwargs()`).
- Bundled-driver Playwright install path correctly unpacks the
  `(node, cli)` tuple returned by `compute_driver_executable` on
  playwright >= 1.40 — previously failed silently with
  `FileNotFoundError`.
- Notable historical issues closed:
  - #13 GUI palette mismatch with theme tokens
  - #14 "Cancel all" wasn't draining the download queue
  - #15 Detail page wasn't preserving the downloaded-chapter list
  - #16 Reader's Ctrl+wheel zoom was firing on plain wheel
  - #18 Library cards didn't show read count
  - #20 `download_from N` didn't update last_chapter threshold
  - #21 Reader pan wasn't enabled when zoomed
  - #23 Output paths weren't ending up under `<dir>/<title>/`
  - #26 Failed downloads created an incomplete CBZ marked complete

### Removed
- Design references (HTML/CSS/JS used during the GUI port) are no
  longer tracked.
- Internal "Not implemented" punch list moved out of the repo.

## Earlier versions

Pre-PySide6 versions tracked the CLI-only releases — see the git tag
history (`v0.0.x` → `v0.1.0`) for details.
