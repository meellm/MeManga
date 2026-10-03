# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

> This is the changelog for the **`cli` branch** — the GUI-free
> variant of MeManga. Desktop-app changes (PySide6 pages, themes,
> first-run install dialog, app icon, build scripts) land on `main`.
> Engine and scraper fixes land on both.

## [Unreleased]

## [0.4.4] - 2026-10-03

### Added
- #185 Thunder Scans EN (en-thunderscans.com) is now available as a
  supported CLI source with search, chapter lists and page downloads.
  Coin-locked early-access chapters are left out of the chapter list, and
  saved series links keep working when the site rotates its numeric slug
  prefixes.
- #184 ZonaTMO (zonatmo.org) is now available as a supported CLI source.
  Search, chapter lists and reader pages are read from the site's HTML;
  text novels are skipped since they have no page images to download.
- #183 Olympus Scanlation (olympusxyz.com) is now available as a supported
  CLI source through the site's catalogue, chapter-list and reader APIs.
  Search covers comics only; the site's text novels have no page images to
  download.
- #186 Lector Manga (lector-mangas.lat) is now available as a supported
  CLI source with search, chapter listing and page downloads. Links on the
  old lectormangass.net host, which now redirects to the new one, keep
  resolving to the same scraper.
- #187 Wurmz (wurmz.net) is now available as a supported CLI source with
  search, chapter lists and page downloads for its Indonesian manga,
  manhwa and manhua translations.

### Changed
- Docker images now install Chromium alongside Firefox so MangaPark can keep
  using its browser-backed path in headless containers.
- Version metadata synchronized for the v0.4.4 release.

### Fixed
- #182 Kagane is skipped by the multi-source search sweep. kagane.org now
  redirects to kagane.to, and both sit behind a Cloudflare challenge that
  answers searches with a 403. Links on either domain still resolve to
  the Kagane scraper so saved entries stay in the library, but searches,
  chapter lists and page downloads will not work until a reliable way
  past the challenge is found.
- #181 ComicK search and chapter lists work again. The scraper now reads
  the site's JSON API instead of the browser-rendered pages, which sit
  behind Cloudflare's headless verification and returned no results.
  When several groups upload the same chapter, scan-group uploads are
  preferred over official ones. Official/external chapters that only link
  out to the publisher have no hosted images, so they still download no
  pages rather than faking a download.
- #175 MangaHere.onl search now queries the site's catalogue API instead of
  scraping the home page, so results match the query instead of listing
  unrelated titles. Titles the site doesn't host are left out, and chapter
  lists no longer pick up other series' chapters or hidden placeholder links.
- #177 Asura Scans search works again and is no longer skipped in the
  multi-source search sweep. The scraper now reads the site's JSON API
  instead of driving a headless browser at the retired asuracomic.net
  domain, and entries saved against the old domains keep resolving.
- #177 Asura early-access chapters are no longer listed as downloadable.
  They appeared in the chapter list but served zero pages until their
  paywall window closed.
- #174 MangaHere page downloads now fetch the real CDN images through the
  reader's `chapterfun.ashx` endpoint instead of falling back to reader
  page URLs, so chapters no longer download as HTML saved with an image
  extension. Chapter listings also skip sidebar links to other series.

## [0.4.3] - 2026-08-19

### Added
- #153 Atsumaru is now available as a supported CLI source through the site's
  Typesense and reader APIs.
- #156 VyManga is now available as a supported CLI source, including legacy
  host canonicalization for saved or manually added entries.
- #157 Mangadot is now available as a supported CLI source through its rendered
  search pages and JSON chapter/image APIs.

### Changed
- Version metadata synchronized for the v0.4.3 release.

### Fixed
- #150 MangaBall search and reader extraction now use the current API flow.
- #151 Mangago connection failures now fail quickly on blocked networks
  instead of hanging the multi-source search sweep.
- #152 MangaTaro page extraction now uses the current reader/API flow again.

## [0.4.2] - 2026-08-06

### Changed
- Version metadata synchronized for the v0.4.2 release.

## [0.4.1] - 2026-08-02

### Fixed
- #142 MangaFire now signs each JSON API call with a per-request token, so
  search, chapter listing, and page fetches no longer fail with HTTP 403.

## [0.4.0] - 2026-07-19

### Added
- #88 Official Docker images are now supported for headless servers, NAS boxes,
  Raspberry Pi systems, and cron-style automation. Release tags publish a
  CLI-only image to Docker Hub and GitHub Container Registry, while local
  `docker build` and Compose workflows remain available for testing.
- #89 Downloads can now run a configurable post-processing command after a
  chapter finishes, making it easier to plug MeManga into local conversion,
  sync, or automation pipelines.
- #90 CBZ downloads now include ComicInfo.xml metadata so compatible comic
  readers can show series, chapter, and title details.
- #117 Accepted partial downloads are now tracked so missing pages can be
  retried without discarding pages that were already saved.

### Changed
- #102 Manual backlog checks now use a trusted chapter catalogue baseline so
  suspicious-batch protection does not incorrectly reject intentional backlog
  downloads.

### Fixed
- #109 Unix cron setup now quotes scheduled-check paths, so installs work when
  the repository path contains spaces or shell-sensitive characters.
- #110 State mutations are consistently synchronized to avoid races between
  background and persistence paths.
- #112 Download-from-chapter actions no longer crash when history contains
  non-numeric or part-style chapter labels.
- #113 Kindle attachment-size errors now report the correct limit and recovery
  guidance.
- #114 Backup imports no longer append duplicate titles from the same file.
- #115 Backup imports now preserve existing manga state while merging incoming
  records.
- #118 Auto-mode new-chapter badges now remain stable until the active download
  batch finishes.

### Security
- Mail credential handling and download path handling were hardened to reduce
  the risk of unsafe paths or credential exposure during local workflows.

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
