# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.3.3] - 2026-07-12

### Fixed
- #83 MangaDex API requests could fail with HTTP 400 because the shared
  scraper session claimed a browser user agent without the `Sec-Fetch-*`
  headers MangaDex expects. Default scraper headers now include those
  browser fetch metadata headers, restoring MangaDex search and chapter
  requests.
- #84 The GUI could falsely report offline on connected networks because
  the network probe used TCP port 53, which some Windows networks reject
  even while normal HTTPS access works. The probe now checks an HTTPS
  host on port 443 so connected users are not blocked by DNS-over-TCP
  policy.

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
  same multi-source search engine as the GUI, with relevance filtering,
  source ordering, chapter-count probes, JSON output, and direct add
  support.
- #32 The Reader only supported continuous vertical scrolling, which is
  awkward for print-style manga where pages are meant to advance one at
  a time. Reader layout mode now supports continuous, single-page, and
  two-page reading with keyboard navigation and per-manga persistence.
- #35 A source could report a huge bogus chapter jump and MeManga would
  trust it, potentially downloading or emailing dozens of incorrect
  chapters. Suspicious update batches are now scored before delivery,
  checked against backup sources when available, and held back unless
  they are confirmed or explicitly forced.

### Changed
- #45 Reader progress previously marked a chapter as read before the
  user actually reached the end. The read threshold now waits until the
  final portion of the chapter, so library progress reflects real
  reading progress instead of early scroll position.
- #46 Clicking the concurrent-downloads slider could snap straight to
  the minimum or maximum instead of the clicked value. Slider clicks now
  map to the actual clicked position, making the setting predictable.
- Release workflow actions now use Node 24-compatible major versions,
  avoiding the GitHub Actions Node 20 deprecation warning before the
  v0.3.0 tag build runs.

### Fixed
- #42 Backup import ignored the export schema version, so unsupported
  backup data could be accepted silently. Import now validates the
  version field before restoring data, giving future migrations a safe
  rejection path instead of corrupt or surprising state.
- #43 Reader arrow keys did not navigate, even though page-based
  reading expects keyboard controls. Arrow/Page/Home/End handling now
  works with the active reader layout mode.
- #44 Very long filename-template previews in Settings could overflow
  and break the theme options layout. The preview now stays constrained
  inside the settings panel.
- #47 The Downloads page left "Cancel All" enabled when there was no
  active or queued work, then reported a misleading cancellation. The
  action is now disabled for an empty queue.
- #48 MangaPill cover images could fail to load in the GUI because the
  source rejected image requests without its expected referer. Cover
  fetching now sends the required source referer.
- #49 The Reader's "Next chapter" button could hide its label, making
  the navigation control unclear. The button layout now keeps the label
  visible.

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
