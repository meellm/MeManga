# Changelog

All notable changes are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- #360 A chapter that was saved but could not be sent to the Kindle is
  no longer only a log line. It stays downloaded, its file is kept and it
  is recorded as not sent until a send succeeds. `memanga send --pending
  [TARGET]` sends those chapters again (`--list` only lists them,
  `--clear` forgets the records; the files stay), and the desktop app
  shows "Not sent to Kindle" with a Send button in the manga's chapter
  list. `delivery.delete_after_send` still only deletes a file once it
  was sent. `check` and `failed retry` now report such chapters and exit
  `3`, like other incomplete runs.
- #343 Settings in the desktop app has an About page with the MeManga
  version, install type (packaged app or not), Python, OS, Qt and
  Playwright versions, whether the Playwright browsers are installed and
  which keyring stores the app password. "Copy diagnostics" copies the
  same list for a bug report; it holds no folder paths, user names,
  e-mail addresses or passwords.
- #247 The app password can come from `MEMANGA_SMTP_PASSWORD_FILE` (a
  file such as a Docker secret) or `MEMANGA_SMTP_PASSWORD`, ahead of the
  keyring and `config.yaml`, and is then never saved. Setting both, or a
  file that cannot be read, leaves no app password (a stored one is not
  used instead) and `memanga doctor` says why. Saving the password
  without a usable keyring now warns, in the command line and in the
  desktop app's Settings, that it is in plain text in `config.yaml`, with
  the file's path; a keyring that silently drops secrets counts as
  unusable. `config show` also hides email addresses (`***@domain`);
  `config get KEY` still prints one value in full.
- #409 `config.yaml` and `state.json` carry a `schema_version`. Files
  from older releases load as before and are upgraded on their next
  save, with the previous file kept as the `.bak` copy; future layout
  changes run as step-by-step migrations. A file from a newer MeManga
  is refused and left as it is instead of being overwritten: commands
  exit 1 with an update hint, the desktop app shows an error and
  `memanga doctor` reports it.
- #357 `memanga path TARGET` prints the download folder of a tracked manga
  (only the absolute path, so `cd "$(memanga path TARGET)"` works) and
  `memanga open TARGET` opens it in the system file manager. A manga with
  nothing downloaded yet, or a missing file opener such as `xdg-open`, is
  reported on stderr with the folder path and exits 1; nothing is created.
- #356 `memanga read TARGET CHAPTER...` and `memanga unread TARGET
  CHAPTER...` mark chapters read or unread in the same read state the
  desktop reader, Library and chapter list use. `read --all` marks every
  downloaded chapter; `unread --all` clears the manga's read chapters.
  Every chapter is checked before anything changes, and files and download
  history are never touched.
- #248 `memanga --version` (also `-V`) prints the installed version, and
  `memanga completion bash` prints a bash completion script.
  Help and error messages always name the program `memanga`, also under
  `python -m memanga`. `check` takes its target as a positional argument
  like `edit` and `remove` (`check "Blue Lock"`); `-t TITLE`
  still works.
- #354 `memanga export -` writes the backup JSON to stdout and
  `memanga import -` reads it from stdin. `import --dry-run` checks the
  backup and lists what would be added or skipped without changing
  anything. File paths work as before.
- #353 `memanga config` gains `show [--json]`, `get KEY`, `set KEY VALUE`,
  `path`, `edit` and `email [--test]` for scripts, Docker and support.
  `get` prints only the value, `set` checks the key and value before
  saving, and the app password stays masked; it is set with
  `config set email.app_password -` from stdin, never from the command
  line. `config path` and `config edit` also work when config.yaml cannot
  be loaded. The existing `config` flags and the interactive editor are
  unchanged.
- #400 MangaDex chapters credit MangaDex and the scanlation group in the
  built-in reader and in saved chapters (EPUB/PDF metadata, ComicInfo
  `Translator`, or `Source.txt`). Chapters from groups that asked for
  removal are skipped; `config --mangadex-remove-group GROUP_ID` adds a
  group locally.
- #400 MangaDex image quality can be set to data saver for smaller
  e-reader downloads (`config --mangadex-quality data-saver` or Settings →
  General). Original quality stays the default.
- #400 MangaDex@Home image loads are reported to MangaDex, and a failed
  page is retried on a newly assigned image server.
- #250 `memanga doctor` checks the config and state files, download
  directory, email and keyring setup, the scheduled-check entry, cached
  source health and the Playwright browser installs in one report. It
  exits 1 when a check fails (`--strict` also fails on warnings). The
  SMTP login test (`--smtp`) and headless browser launch
  (`--launch-browsers`) only run when asked.
- #262 `memanga doctor` adds a `runtime` check that reports the Python
  version and executable, platform, MeManga version, package path and
  install mode (editable, source, installed, frozen or unknown). It warns when
  the package metadata for the imported code has a different version;
  unrelated metadata, such as an older install shadowed by a source
  checkout, is reported but ignored.
- #250 `list`, `status` and `failed` accept `--json` for scripts. The
  output is plain JSON with a `schema_version` field, and
  `status --json` never includes the app password.
- #351 `memanga check --download` is the explicit way to download new
  chapters without prompting. `-a`/`--auto` and `-y`/`--yes` are aliases
  and keep working without warnings, so existing cron lines are
  unchanged. `check --help`, the README and the guide describe the
  check-only (`--dry-run`), download and ask modes and the exit codes,
  including exit 0 for no new chapters and for a withheld suspicious
  batch.
- #352 `memanga failed` has explicit actions: `failed list`, `failed
  retry` and `failed clear`, each with an optional TARGET (a title or
  `#N`). Plain `failed` still lists, and `--retry`/`--clear` keep working
  as aliases of `retry`/`clear`.

### Changed
- #372 The plain summary line of `memanga check` ends with the next
  step when there is one: `next: run 'memanga failed' for details` after
  failed chapters, or `next: rerun with --download` when chapters needed
  confirmation. It shows even with `memanga -q`, which hides the
  separate warning.
- #226 Output and logging work the same everywhere. Scrapers, the
  downloader, email delivery and the desktop app report through logging
  instead of printing to stdout, so stdout only carries command results
  and `--json` stays clean. Diagnostics go to stderr: warnings and errors
  by default, more with `memanga -v` (progress) or `-vv` (debug), only
  errors with `memanga -q`, or any level through `MEMANGA_LOG_LEVEL`;
  this covers the warnings and errors `check` and `failed retry` report
  themselves. When stdout is not a terminal (pipes, files, cron), or
  with `--plain`, output is plain text without colour, emoji, borders or
  line wrapping, and `check` prints a single summary line;
  `NO_COLOR` turns colour off. Log lines on a redirected stderr or in a
  log file, traceback lines included, carry a timestamp and level. `memanga --log-file`
  also writes a rotating `diagnostics.log` in the config folder. The
  desktop app keeps the last three `runtime.log` files instead of
  overwriting it at every start. Passwords and tokens
  are masked in log output, and redirected output on Windows is written
  as UTF-8.
- #249 Config and state live in the platform config folder:
  `%APPDATA%\memanga` on Windows, `~/Library/Application Support/memanga`
  on macOS and `$XDG_CONFIG_HOME/memanga` (default `~/.config/memanga`) on
  Linux. The CLI and the desktop app pick the same folder. An existing
  `~/.config/memanga` is moved there once, as a single rename under the
  config lock, and a `MOVED.txt` note stays behind so scheduled checks
  installed earlier keep running. When the move is not safe (another
  MeManga is running, the new folder is not empty, settings point inside
  the old folder, or the rename fails) the old folder stays in use
  unchanged. `--config-dir` and `MEMANGA_CONFIG_DIR` still win and never
  move anything, and now apply to the desktop app too:
  `memanga --config-dir DIR --gui` opens the app on DIR (it was refused
  before), the app started on its own honours `MEMANGA_CONFIG_DIR`, and
  the daily check set up in its Settings keeps the chosen directory.
- #348 `edit` is the command for changing a tracked manga, including its
  status (`memanga edit "One Piece" --status on-hold`); `update` stays an
  alias. Help and the bash completion list `edit (update)`.
- #354 `import --replace` asks for confirmation before replacing the
  library and download state. Non-interactive runs and stdin imports must
  pass `--yes` (`-y`); without it they exit 1 and change nothing.
- #354 `import` checks the whole backup before writing: invalid JSON, a
  `manga` value that is not a list, entries without a title and
  non-object state entries are rejected (exit 1) instead of crashing
  midway or being written to config.yaml as-is.
- #352 `failed` targets (TARGET or `-t`) are matched like `check -t`: `#N`
  from `memanga list`, an exact title, then a unique part of a title. A
  target that matches nothing or several manga is now an error (exit 1)
  and changes nothing; it used to act on every title containing the
  text, or exit 0 with nothing found.
- #352 `failed retry` (and `--retry`) downloads through the same chapter
  steps as `check --download`: it now also emails chapters saved from the
  backup source, honors delete-after-send, page retries and the
  partial-chapter settings, and clears backup-delay clocks. A chapter
  saved as a partial again keeps its record and counts as not recovered
  (exit 3).
- #222 `failed retry` reads each manga's chapter list from the primary
  source once per run, instead of once for every failed chapter of that
  manga. `check` and `failed retry` now process chapters through one
  shared module, so their download, backup, partial, delivery and state
  handling stay the same.
- #295 GUI downloads now go through the same chapter steps as
  `check --download` and `failed retry`. The Detail and Downloads pages
  honor "Delete after sending to Kindle", image folders are no longer
  emailed, the backup source is searched with the same group filters as
  the command line, and a backup-delay clock is cleared once the chapter
  is saved. Chapters the reader fetches ahead of time are never deleted
  after sending.
- #351 `memanga check --quiet` on a terminal without `--download` now
  skips new chapters and exits 1 with a hint, as it already did without a
  terminal. It used to skip them silently and exit 0. `--quiet` never
  prompts and never gives permission to download.

### Deprecated
- #348 `memanga set TITLE STATUS` is deprecated in favour of
  `memanga edit TITLE --status STATUS`. It still works in this release
  with the same output and exit codes, prints the matching `edit` command
  on stderr, and no longer appears in help or completion. It will be
  removed in the next release.

### Fixed
- #341 The command line now honors the per-manga mode and Kindle settings
  of the desktop app. `check --download` (and cron's `check --auto
  --quiet`) without a manga name lists the new chapters of `manual`-mode
  manga instead of downloading them, and the summary counts them;
  naming the manga or answering the per-chapter question still
  downloads. A manga with Kindle delivery turned off is never emailed by
  `check`, `failed retry`, `send --pending` or the desktop app's Send
  button; its chapters are saved as usual. Entries without these fields
  keep the old defaults (automatic, Kindle on).
- #342 The desktop app no longer cuts error messages off after 30-80
  characters. Toasts, download rows and the Settings email test show a
  short summary, and the Notifications entry keeps the complete error
  behind a Details button, with a Copy action. For the 20 most recent
  errors longer than 4,000 characters, up to 100,000 characters are kept
  in a private file in the config folder's `error-details` directory
  (removed with its notification, about 2 MB at most); when less than
  the whole error is kept, the Details view says so. Kindle delivery
  failures now get a notification too. The Search page has a Failure
  details button listing why each source failed in the current search
  (up to 20,000 characters per source and 100,000 per search, with any
  cut marked). Passwords, tokens, the whole user part of URLs
  (`https://***@host/...`), the name part of email addresses and the
  home folder are masked in shown, copied and saved error text,
  notification titles included. Check, download, Kindle, search and
  Settings (email test, schedule, export, import) failures are written
  to the log. The log masks passwords, tokens and the user part of URLs,
  now also when the app is started with the `memanga-gui` command, which
  printed its log lines unmasked before; it does not mask email
  addresses or the home folder.
- #246 File and folder names are valid on Windows, macOS and Linux:
  control characters are removed and a Windows device name such as
  `CON` or `nul` gets a `_` suffix. `add`, `edit --title`, `search --add`
  and the app's Add page refuse a title that would share another
  manga's download folder (`A:B` and `AB`), since their chapter files
  would overwrite each other.
- #246 EPUB metadata no longer names the manga title as the author. The
  author comes from the manga entry; the language comes from the entry's
  `language` or from a source that serves one language (MangaDex, TCB
  Scans, Thunder Scans EN, the Spanish and Indonesian sources), and is
  `und` (undetermined) instead of English when unknown. CBZ ComicInfo
  adds `LanguageISO` when the language is known and `Manga` =
  `YesAndRightToLeft` only for titles known to read right to left (TCB
  Scans, or `reading_direction: rtl` on the manga entry); manhwa and
  webtoons are no longer marked right to left.
- #246 Cancelling a chapter download waits for page downloads already
  in progress before the temporary folder is removed.
- #246 `add --fallback-days` without `--backup` fails instead of being
  ignored. `import` reads files as UTF-8 (a BOM is accepted) and rejects,
  before anything is written, manga entries whose `url`, `source`,
  `sources` or `fallback_delay_days` have the wrong type, and imports
  (merge or `--replace`) that would give two manga the same download
  folder.
- #246 Config changes from different threads take the same lock as
  saving, and scrapers no longer swallow Ctrl+C.
- #212 Installing the package (`pip install .`, `pip install -e ".[dev]"`,
  `pip wheel .`) no longer runs the setup script. The build backend
  executed the old root `setup.py`, which created a `venv`, installed
  requirements, downloaded Playwright browsers and on Linux ran `sudo
  apt-get`. The script is now `scripts/bootstrap.py` and runs only when
  called: `python scripts/bootstrap.py` replaces `python setup.py`;
  `scripts\windows\setup.bat` calls it as before.
- #244 Only one MeManga process at a time changes a config directory, so
  a cron `check`, a manual command and the desktop app no longer overwrite
  each other's downloads, failed records, reading progress or imports.
  Commands that change config or state take a lock on the directory
  (`memanga.lock`) before loading anything; while another check, command
  or the desktop app holds it they exit 1 with a message on stderr and
  change nothing, and the desktop app shows an error instead of starting.
  Read-only commands (`list`, `status`, `path`, `open`, `sources`,
  `export`, `doctor`, `failed` listing, `config show/get/path`,
  `cron status`, `search --json` without `--add`) still run. The system
  releases the lock when the process ends, even after a crash, so there
  is nothing to clean up. Scheduled checks use the same lock. A
  read-only command leaves a damaged `state.json` untouched while another
  process holds the lock, and `export` refuses to write over MeManga's own
  files in the config directory.
- #243 A damaged `state.json` is no longer replaced by empty state. It
  is kept as `state.json.corrupt-<time>-<id>`, the previous copy is
  restored from `state.json.bak` when there is one, and the CLI (on
  stderr), the desktop app and `memanga doctor` say where the damaged
  file went. A state file that can't be read or copied aside is never
  overwritten: commands other than `doctor` stop with exit 1 and the
  desktop app shows an error instead of starting. The same happens when
  the restored copy can't be written to `state.json`, or when
  `state.json.bak` exists but can't be read; the damaged file then stays
  in place, so the next start tries the restore again, `state.json.bak`
  is unchanged, and an identical damaged file is kept only once. Every
  save keeps the previous `state.json` and `config.yaml` as `.bak` and
  flushes the new file to disk before replacing the old one (and the
  folder afterwards, where the system supports it); if the previous copy
  can't be kept, the save fails and both files stay as they were. A CLI
  command whose save fails (for example on a full disk) stops with exit
  1 and a short message naming the file instead of a traceback. The
  desktop app also shows an error for a broken `config.yaml` instead of
  crashing.
- #230 `check` and `failed retry` write `state.json` after every chapter,
  so a run that is killed, crashes or times out no longer forgets
  chapters it already saved and sent, and the next run does not download
  or send them again. If the state file can't be written, the command
  stops with exit 1 before downloading or sending anything else. SIGTERM
  (cron `timeout`, `systemctl stop`, `docker stop`) now saves pending
  state like Ctrl-C and exits 143. A chapter can still be sent twice if
  the process dies after sending it and before its state is written.
  The desktop app is unchanged.
- #241 Downloaded chapter files and folders are named so that they sort in
  chapter order, extension included, both by plain character order and
  under locale sorting that skips punctuation. Numeric chapters use a
  fixed-width number: four digits, a dot and three decimals
  (`Chapter 0002.000`, `Chapter 0002.500`, `Chapter 0010.000`). Chapters
  up to 9999 with up to three decimal places are ordered exactly. Part
  chapters keep a readable label after their chapter's numeric names
  (`Chapter 0002_Part 02`, `Chapter 0002_Part 10`) instead of the
  decimal-looking `2.10`. Labels that the number alone would not spell
  (`2.0`, `2.00`, `02`, `2.50`) get the source label added
  (`Chapter 0002.000 (2.00)`), so different numeric chapters no longer
  share a file and one download cannot replace another. Names for the same
  chapter number stay together, in no fixed order among themselves. File
  names are still capped at 100 characters, but a long manga title is now
  shortened instead of the end of the name, so the chapter part is never
  cut off. `{chapter}` in a custom naming template uses the same form.
  Other labels such as `Extra` are unchanged. Existing files are not
  renamed and still open in the reader. Post-processing `{chapter}` and
  `MEMANGA_CHAPTER` still receive the original chapter number.
- #406 `scripts/run.sh` and `scripts\windows\run.bat` no longer switch to
  the project folder before running MeManga. Relative paths such as
  `import backup.json` or `export backup.json` now resolve in the folder
  the command was typed in. On Windows, `run.bat` and `setup.bat` also
  leave the Command Prompt in its original folder.
- #398 Scraper requests no longer retry permanent HTTP errors. A 403, 404
  or 410 (and other 4xx) used to be sent three times with back-off; now
  only connection errors, timeouts, 429 and 5xx responses are retried.
  MangaBall still retries a 419 after refreshing its CSRF token.
- #351 `memanga check --dry-run` no longer changes state. It used to
  record a check (last-check time and a history entry counting listed
  chapters as downloaded), start or clear backup-delay clocks, advance the
  catalogue baseline, and record or clear suspicious batches. In
  particular, `--dry-run --force-suspicious`, `--dry-run --all` or
  `--dry-run --from N` could accept a held suspicious batch so the next
  scheduled check downloaded it. A forced preview now only shows what
  accepting the batch would download.
- #231 `memanga cron install` and `cron remove` (and the GUI Settings
  buttons) only change the crontab line they own, now marked with a
  trailing `# memanga-managed` comment. Other lines, comments and blank
  lines are kept as they are, including hand-written MeManga jobs. Lines
  from earlier installs have no marker, so they are left in place and
  listed; remove them with `crontab -e` to avoid running the check twice.
  `cron remove` no longer rewrites the crontab when there is no managed
  line, and `cron status` only reports a job as installed when it is marked.
  The GUI Settings cron status and install also point out unmarked MeManga
  lines. Install now refuses to write when `crontab -l` fails for a reason
  other than "no crontab", and remove keeps scheduled checks enabled in
  the config when writing the crontab fails.
- #250 CLI commands no longer print a MangaFire browser-restart notice
  to stdout on exit, which broke `search --json` output.
- #250 An invalid `config.yaml` no longer crashes the CLI with a
  traceback. `memanga doctor` reports it as a failed `config` check;
  other commands exit 1 with a short error and leave the file untouched.
- #238 `memanga add` only asks questions with `--interactive`. Without it,
  an unsupported source or a similar tracked title exits 1 with an error
  instead of prompting, even in a terminal; pass the new `--force` (or the
  existing `--yes`) to add it anyway. Exact duplicates are still refused.
  An invalid fallback delay in interactive mode asks again instead of
  crashing.
- #237 `remove`, `set`, `update` and `check -t` no longer pick the wrong
  manga. An exact title (any case) wins over a partial one, and a partial
  title that matches several manga exits 1 and lists them. A bare number
  such as `86` now matches only an exact title; use `#N` (quoted in the
  shell) for the Nth manga in `memanga list`. `remove --yes` keeps the
  download history; pass the new `--purge` to delete it as well.
- #239 CLI exit codes are now predictable: 0 success, 1 error, 2 usage
  error, 3 when `check` or `failed --retry` ran but some chapters failed,
  and 130 when interrupted. `remove`, `set`, `update` and `check -t` exit
  1 when the manga is not found (they used to exit 0), and `check` exits
  1 when no manga could be checked. Errors and warnings are written to
  stderr so stdout only carries results.

## [0.4.4] - 2026-10-03

### Added
- #185 Thunder Scans EN (en-thunderscans.com) is now available as a
  supported source with search, chapter lists and page downloads.
  Coin-locked early-access chapters are left out of the chapter list, and
  saved series links keep working when the site rotates its numeric slug
  prefixes.
- #184 ZonaTMO (zonatmo.org) is now available as a supported source.
  Search, chapter lists and reader pages are read from the site's HTML;
  text novels are skipped since they have no page images to download.
- #183 Olympus Scanlation (olympusxyz.com) is now available as a supported
  source through the site's catalogue, chapter-list and reader APIs. Search
  covers comics only; the site's text novels have no page images to
  download.
- #186 Lector Manga (lector-mangas.lat) is now available as a supported
  source with search, chapter listing and page downloads. Links on the
  old lectormangass.net host, which now redirects to the new one, keep
  resolving to the same scraper.
- #187 Wurmz (wurmz.net) is now available as a supported source with
  search, chapter lists and page downloads for its Indonesian manga,
  manhwa and manhua translations.

### Changed
- Docker image publishing now builds and runs a local smoke-test image
  before the multi-platform release images are published, so broken
  container entrypoints fail before they reach Docker Hub or GHCR.
- Version metadata synchronized for the v0.4.4 release.

### Fixed
- #163 macOS release builds can optionally be signed and notarized. When
  paid Apple Developer ID credentials are configured as repository
  secrets, the release workflow signs the Apple Silicon and Intel apps with
  the hardened runtime, notarizes them with Apple, staples the ticket and
  stops before upload if signing, notarization, the Gatekeeper check or
  the final app self-test fails. Without those credentials releases still
  publish unsigned `MeManga.app` zips, which macOS may still report as
  "damaged"; the README documents the `xattr` workaround for that case.
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
  unrelated titles. Titles the site doesn't host (licensed series served
  only on a sister domain) are left out, and chapter lists no longer pick
  up other series' chapters or hidden placeholder links.
- #177 Asura Scans search works again and is no longer skipped in the
  multi-source search sweep. The scraper now reads the site's JSON API
  instead of driving a headless browser at the retired asuracomic.net
  domain, which redirected to the homepage and dropped the query.
  Chapter listing, page extraction, and covers use the same API, and
  entries saved against the old domains keep resolving, including the
  older `/manga/<slug>/` paths. Asura is also back in the curated
  default source set, so fresh installs search it out of the box, and
  a one-shot repair re-ticks it for installs that were seeded while it
  was broken.
- #177 Asura early-access chapters are no longer listed as downloadable.
  They appeared in the chapter list but served zero pages until their
  paywall window closed.
- #174 MangaHere page downloads now fetch the real CDN images through the
  reader's `chapterfun.ashx` endpoint instead of falling back to reader
  page URLs, so chapters no longer download as HTML saved with an image
  extension. Chapter listings also skip the sidebar links to other series,
  and a hotlink-blocked response is rejected rather than written to disk.

## [0.4.3] - 2026-08-19

### Added
- #153 Atsumaru is now available as a supported source through the site's
  Typesense and reader APIs.
- #156 VyManga is now available as a supported source, including legacy
  host canonicalization for saved or manually added entries.
- #157 Mangadot is now available as a supported source through its rendered
  search pages and JSON chapter/image APIs.

### Fixed
- #150 MangaBall search and reader extraction now use the current API flow.
- #151 Mangago connection failures now fail quickly on blocked networks
  instead of hanging the multi-source search sweep.
- #152 MangaTaro page extraction now uses the current reader/API flow again.
- #163 macOS release downloads now ship as `.zip` archives containing
  `MeManga.app`, so users get a normal launchable app bundle instead of a
  raw extensionless binary.
- #167 Linux release downloads now ship as `MeManga-linux-x64.tar.gz` so
  the executable bit survives download and extraction. A raw ELF asset
  saved through a browser lost its `+x` bit and failed to launch with
  "Permission denied"; the tarball records the executable bit inside the
  archive, so `tar xzf` restores a runnable binary.

## [0.4.2] - 2026-08-06

### Added
- #147 macOS releases now publish separate Apple Silicon and Intel assets.

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
- #104 Reader settings can remove chapters after they are marked read, helping
  users keep local storage under control.
- #107 The reader can prefetch the next manual-mode chapter, reducing wait time
  when moving through a series.
- #117 Accepted partial downloads are now tracked so missing pages can be
  retried without discarding pages that were already saved.

### Changed
- #108 GUI click responsiveness and shared backend performance were improved,
  especially around library refreshes and repeated user actions.
- #106 The reader now resumes the last viewed page when reopening a chapter.
- #102 Manual backlog checks now use a trusted chapter catalogue baseline so
  suspicious-batch protection does not incorrectly reject intentional backlog
  downloads.

### Fixed
- #109 Unix cron setup now quotes scheduled-check paths, so installs work when
  the repository path contains spaces or shell-sensitive characters.
- #110 State mutations are consistently synchronized to avoid races between GUI,
  background, and persistence paths.
- #111 The reader can locate downloaded chapters even when title or chapter
  labels were normalized on disk.
- #112 Download-from-chapter actions no longer crash when history contains
  non-numeric or part-style chapter labels.
- #113 Kindle attachment-size errors now report the correct limit and recovery
  guidance.
- #114 Backup imports no longer append duplicate titles from the same file.
- #115 Backup imports now preserve existing manga state while merging incoming
  records.
- #116 The Settings email test now reports results through the GUI thread instead
  of updating Qt widgets from a background thread.
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
