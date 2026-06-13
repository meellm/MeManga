# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-06-13

### Added
- #31 `memanga search` command for live multi-source CLI search.
- #32 Reader page-by-page mode with left/right navigation and layout
  controls.
- #35 Suspicious chapter-jump detection that checks backup sources
  before accepting unusually large update batches.

### Changed
- Reader progress now marks chapters as read only near the end of the
  chapter instead of too early.
- Concurrent-download slider clicks now jump to the clicked value
  rather than snapping to the minimum or maximum.

### Fixed
- #42 Backup import now validates the exported schema version instead
  of silently accepting unsupported backup data.
- #43 Reader arrow keys navigate chapters/pages as expected.
- #44 Long settings filename-template previews no longer break the
  theme options layout.
- #47 "Cancel All" is disabled when there is no active or queued
  download work.
- #48 MangaPill covers load in the GUI by sending the required source
  referer.
- #49 The Reader "Next chapter" button label remains visible.

## [0.2.2] - 2026-06-10

### Added
- Release builds now run an actual frozen-executable Playwright
  self-test before publishing artifacts. Windows runs the no-console
  app with null standard handles to match a user double-click; macOS
  runs the same `--verify-playwright` gate against the built binary.
- Tagged releases now build and upload Windows, macOS, and Linux
  single-file binaries through GitHub Actions.

### Fixed
- #28 Playwright-based sources could still fail inside frozen desktop
  builds when the bundled driver looked in the wrong browser cache path
  or inherited invalid standard handles from a windowed executable.
  MeManga now pins the browser install path for packaged builds,
  creates valid hidden subprocess handles where needed, and verifies the
  real release artifact before publishing.
- #39 Open-folder buttons in the Windows release exe did nothing because
  Explorer was launched through a hidden subprocess path. Folder opening
  now uses the platform shell directly so the action works from the
  packaged GUI.
- #40 Pause All / Resume All could make queued downloads disappear from
  the active downloads tab, and in some flows lose the queued work
  entirely. Paused items now stay represented in the queue model and are
  restored correctly when downloads resume.
- #41 Renaming a manga could orphan already-downloaded chapter files, so
  the Detail page later failed with "couldn't find the chapter". Rename
  operations now move the downloaded files along with the library entry.
- #50 "Download All" and explicit "Download from" actions could do
  nothing for manual-mode manga: no chapters were queued and the UI gave
  no useful feedback. Explicit download actions now bypass the
  reading-only update filter and queue the requested chapters.
- #55 Selecting Email to Kindle delivery could prevent manga detail
  pages from opening because the delivery setting was normalized through
  a stale config shape. The Detail page now accepts the modern email
  delivery mode and renders normally.
- MangaFire chapter checks now raise and retry on network errors,
  non-JSON responses, HTTP failures, and Cloudflare-wrapped 5xx payloads
  instead of silently reporting an empty chapter list.

## [0.2.1] - 2026-06-04

### Fixed
- #28 Playwright-based sources (MangaFire, WeebCentral, Comick,
  MangaKatana, …) silently returned no search results in the no-console
  release exe. A `console=False` Windows build has null standard
  streams, so Playwright's driver subprocess inherited an invalid
  stderr handle and failed to start. The frozen entry point now
  restores real, file-descriptor-backed streams before any scraper
  runs.
- #29 Source-health checks flagged almost every source as "warning":
  the slow threshold was 500 ms, but healthy sites routinely answer in
  500–2000 ms. Raised to a tunable `State.SLOW_LATENCY_MS` (2500 ms) so
  the warning tier is reserved for genuinely slow responses.
- #30 The Detail-page "Check updates" button silently did nothing for
  manga whose status wasn't "reading". Explicit per-manga actions now
  check regardless of status; only the library-wide sweep keeps the
  reading-only filter.
- MangaFire `get_chapters` now raises on network error, non-200,
  non-JSON, and wrapped Cloudflare 5xx envelopes (with 3× backoff
  retries) instead of returning an empty list, so `check_for_updates`
  logs a real error and falls back to the backup source instead of
  reporting "No new chapters". MangaDex chapter dedup is now stable
  across repeated checks.

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
