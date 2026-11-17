# Architecture

<script setup>
import { release } from '../.vitepress/release'
</script>

How MeManga is put together, for people who work on its code: the path a
chapter takes from the config file to the download folder, where each
decision is made, which threads do the work, and what happens when
something fails or is cancelled.

::: info Which code this page describes
The page follows the `main` branch. {{ release.tag }} predates much of this
structure: the chapter pipeline, the config folder lock, the state stores,
the source catalog, `memanga watch` and `memanga.api` are not in it, and its
downloader is a single module.
:::

## The path of a chapter

```text
 config folder                        sources
 config.yaml   state.json             (scrapers)
      │             │                     │
      ▼             ▼                     │
  Config        State  ◄── lock: one      │
      │             │      process per    │
      └──────┬──────┘      config folder  │
             ▼                            │
      check_for_updates  ◄────────────────┤  chapter lists
             │  new chapters per series   │
             ▼                            │
      ChapterPipeline.process             │
        download_chapter  ◄───────────────┘  pages
          pages → file (PDF, EPUB, CBZ, ZIP, images)
          post-processing command
        Kindle delivery (optional)
        records in State
             │
             ▼
        state.json saved
```

Every way of running MeManga goes through the same pieces:

- the command line, `memanga/cli.py`;
- the desktop app, `memanga/gui/`, started as `memanga --gui` or as the
  desktop download;
- a scheduled check, which is a crontab line or a Windows task that runs
  `memanga check --auto --quiet` (`memanga/cron.py`);
- `memanga watch` (`memanga/watch.py`), which runs that same check as a
  child process at an interval.

## Start-up: config folder, lock and files

**Choosing the config folder.** `--config-dir`, then `$MEMANGA_CONFIG_DIR`,
then the platform folder (`config.default_config_dir`). When only the old
`~/.config/memanga` holds data, it is moved to the platform folder once
(`migrate_legacy_config_dir`). An explicitly chosen folder is never moved.
[Download and install](../guide/install#where-memanga-keeps-its-files)
lists the folders.

**The lock.** Config and state are loaded whole, changed in memory and
written back whole, so two processes on one folder would overwrite each
other's changes. `memanga/process_lock.py` therefore allows one process
that changes things per config folder. It uses an operating-system lock
on `memanga.lock`, which the system releases when the process ends, even
after a crash. Taking the lock never waits: when another process holds it,
the command stops with a message.

- The command line takes the lock before it loads anything, except for the
  commands in `READ_ONLY_COMMANDS` and the read-only forms that
  `_needs_config_lock` lists. It holds the lock until `main()` returns.
- The desktop app holds the lock for its whole session.
- `memanga watch` loads and locks nothing; each check it starts locks the
  folder while it runs.
- `memanga.api` never takes the lock.

**Loading.** `Config` (`memanga/config.py`) reads `config.yaml`, upgrades
an older layout and adds missing defaults. `State` (`memanga/state.py`)
does the same for `state.json` and can go back to the safety copy of a
damaged file, but only while it holds the lock. A file written by a newer
MeManga is refused, not loaded (`memanga/schema.py`). A file that cannot be
loaded is never overwritten: `save()` refuses while `load_error` is set,
and the command line stops unless the command is `doctor` or a
`config path`/`config edit` that has to work on a broken file.

**Saving.** `persist.atomic_write_text` writes a temporary file, flushes
it to disk and puts it in place with `os.replace`, keeping the previous
file as `.bak`. The two files are saved separately; there is no
transaction that covers both. [Data files and backups](../reference/state)
describes the files and their fields, and the
[settings reference](../reference/config) every key in `config.yaml`.

## Checking for new chapters

`check_for_updates(manga, state)` in `memanga/downloader/updates.py` decides
which chapters of one series are new:

1. The series' sources come from its config entry. The first is the
   primary source; the others are backups.
2. For each source, `get_scraper(domain)` returns the scraper and
   `get_chapters(url)` the chapter list. A failing source is noted and
   skipped. When every source fails, the check of that series fails with
   `DownloaderError`.
3. A chapter is new when its number is above the last downloaded chapter
   and it is not downloaded yet.
4. New chapters from the primary source are checked by the suspicious
   batch guard (below). Chapters it holds back are not returned.
5. A chapter that only a backup source has is returned only after it has
   waited `fallback_delay_days` (2 by default); until then a pending backup
   record keeps the date it was first seen. When the primary source gets
   the chapter, the record is cleared.

The callers decide what happens next:

- `memanga check` (`cmd_check`) goes through the series one after another,
  skips those not marked as reading unless a title was given, and
  downloads, asks or only lists, depending on its flags and on manual mode.
- The desktop app runs one background task for the whole library
  (`BackgroundWorker.check_updates`), caches each series' full chapter
  list for the detail page, and queues new chapters for download on the
  main thread (`DownloadsPage._on_check_complete`).

## Downloading and delivering a chapter

`memanga check`, `memanga failed retry` and downloads in the desktop app
all hand each chapter to `ChapterPipeline.process` in
`memanga/chapter_pipeline.py`, so recovery, delivery and records cannot
differ between them. The pipeline decides and writes state; it prints
nothing and reports progress to a `ChapterReporter`.

**Download** (`memanga/downloader/chapter.py`, `download_chapter`):

1. The scraper returns the page URLs.
2. Pages are fetched into a temporary folder by four threads. A page counts
   only if the saved bytes are an image. Failed pages are tried again
   `max_retries` times.
3. If pages are still missing, the chapter fails, unless partial chapters
   are allowed and the share of missing pages is within the threshold.
4. The pages are written in the output format (`memanga/downloader/formats/`)
   under the name from `memanga/downloader/naming.py`.
5. The user's post-processing command runs, if one is set
   (`memanga/downloader/post_processing.py`). It runs without a shell and
   is stopped after 600 seconds. When `fail_on_error` is set, its failure
   fails the chapter.

**Recovery** (`ChapterPipeline._recover`). When the download fails, the
pipeline tries a complete copy from a backup source, then, with partial
chapters on, the best partial copy within the threshold, backup first. If
nothing works, it writes a failed-chapter record.

**Saving and delivery** (`ChapterPipeline._save`):

1. A partial chapter gets a partial record and a notification.
2. With Kindle delivery on for the series, the file is sent
   (`_deliver`, `memanga/emailer.py`); a PDF larger than
   `email.max_email_mb` is split. Delivery runs before the chapter is
   marked downloaded. A failed send leaves the file on disk and writes an
   undelivered record; the chapter still counts as downloaded.
3. The chapter is marked downloaded, its pending backup and failed records
   are cleared, and an entry is added to the download history. The
   suspicious batch guard learns typical batch sizes from that history.

## Where decisions are made

| Decision | Where | Notes |
|---|---|---|
| Which sources a search covers | `memanga/search.py` `compute_search_sources` | Aggregators and the sources in the library, minus `sources.disabled` and the skips declared in the catalog. `search.sweep` runs the search. |
| Source facts: search skips, popularity order, first-launch defaults, notes | `memanga/scrapers/catalog.py` | `SEARCH_SKIPS`, `POPULAR_SOURCES`, `DEFAULT_ENABLED_SOURCES`, `SOURCE_NOTES`. Per-class facts such as `engine`, `content_language` and `nsfw` are attributes of the scraper class. The [sources reference](../reference/sources) is generated from these. |
| Source health | `state.source_health` (`memanga/state_stores/source_health.py`) | Written by the desktop app: a check of a series counts for its primary source, and the Sources page has a health check of its own. `memanga check` does not write it. The catalog says nothing about whether a site works now. |
| Fallback to a backup source | `check_for_updates` (waiting time) and `ChapterPipeline._recover` (failed download) | `fallback_delay_days` per series, 2 by default. |
| Suspicious batches | `memanga/suspicion.py` (score), `check_for_updates` (guard) | A held batch is stored with `state.set_suspicious_batch` and accepted with `memanga check --force-suspicious`. The batch is accepted without that when the backup sources together list at least half of its chapters. |
| Partial chapters | `partial_chapters.*` in the config, `download_chapter` (threshold), `ChapterPipeline` (order of attempts) | Partial records are kept in `state.failures`. |
| Manual mode | `chapter_pipeline.manga_auto_downloads` | Used by both `memanga check` and the desktop app: a background check only lists the new chapters of a series with `mode: manual`. |
| Whether a series is sent to the Kindle | `memanga/email_settings.py` | `email.kindle_scope` and the series' own `send_to_kindle`; `kindle_delivery_settings` returns the settings, or `None` when nothing is sent. |
| Chapters waiting for Kindle delivery | Undelivered records in `state.failures` | Sent again through `ChapterPipeline.redeliver` and `send_saved`, always from the file path stored in the record. |
| The desktop app's download queue | `BackgroundWorker` in `memanga/gui/workers.py` | Queue, pause and cancel; `gui.max_concurrent_downloads` limits how many downloads it starts at once. |
| Download folders and file names | `memanga/downloader/folders.py`, `memanga/downloader/naming.py` | Each series has a folder named after its title in the download folder. |
| Scheduled checks | `memanga/cron.py`, `memanga/watch.py` | See [Check on a schedule](../guide/schedule). |

## Threads and processes

MeManga gives no ordering guarantees beyond the locks named here.

### Processes

One process at a time may change a config folder (see the lock above).
`memanga watch` starts each check as a child process and starts the next
one only after the previous one has ended. Post-processing commands and
browsers are child processes too; they do not inherit the lock.

### The command line

A command runs on the main thread. `memanga check` handles one series and
one chapter at a time; within a chapter, `download_chapter` fetches pages
on a pool of four threads. `memanga search` asks up to eight sources at
once (`search.sweep`) and counts chapters with four threads.

### The desktop app

Qt widgets may only be used from the main thread, and the app keeps to
that: background work never touches a widget.

- **Pools, not Qt threads.** The app does its work on Python
  `ThreadPoolExecutor` pools in `BackgroundWorker`. Checks, downloads,
  Kindle sends and one-off tasks share a pool of three threads, so at most
  three of these jobs run at a time, whatever the download setting says.
  Searches (a new pool of eight for each search), chapter counts (four) and
  covers (four) have pools of their own. The reader decodes pages on its own
  pool. A few short tasks, such as the network monitor and the email test
  in Settings, use plain threads and report back through Qt signals.
- **Back to the main thread.** Workers publish events to an `EventBus`
  (`memanga/gui/events.py`), which is a thread-safe queue. A `QTimer` on
  the main thread empties it every 100 ms, at most 50 events at a time, and
  calls the subscribers there. The reader hands decoded pages back through
  a Qt signal with a queued connection, so its slot runs on the main thread.
- **Stale results.** Each search has a sequence number; the search page
  drops events from an older search.

### Browsers

Playwright's synchronous objects belong to the thread that created them.
Each Playwright-based scraper class therefore has one `BrowserWorker`
(`memanga/scrapers/playwright_base.py`): a single thread that owns its
browser and runs one task at a time. When a caller's time runs out, the
task keeps running, because Python cannot stop a thread; the next caller
waits for it within its own time limit.

### Scrapers and shared data

- `get_scraper` gives each thread its own instance per scraper class.
  Threads that share one chapter's work get their own `worker_copy()`.
  Request spacing is shared by the whole class across threads.
- `Config` and `State` each serialize access with a reentrant lock.
  `State` returns copies, so no caller holds a live reference into its
  data.

## Failures, cancelling and saving state

**Failures.**

- A source that fails during a check is skipped. When the whole check of a
  series fails, the desktop app marks its primary source as unhealthy.
- A chapter that cannot be saved gets a failed record, which
  `memanga failed retry` or the desktop app can try again. In the desktop
  app, an unexpected error in a download also leaves a failed record.
- On the command line, an error in one series is counted and the check
  goes on with the next.

**Cancelling a download** (desktop app). Each queued download has a
`threading.Event`. `download_chapter` checks it before it starts, while
pages are fetched and before it retries them. Page fetches that have not
started are dropped; those already running finish. The download then ends
with `InterruptedError`, nothing is recorded, and the temporary folder is
removed. Pausing stops the queue from starting new downloads; running ones
go on.

**Saving state.**

- Most changes only mark the state as changed. A few, such as the time of
  the last check, are saved at once.
- The desktop app saves changed state every 5 seconds and when the window
  closes. On closing, it first saves the reader position, then the state,
  and then shuts the pools down without waiting. Downloads still in its own
  queue are not started; work a pool has already started is not stopped.
- The command line saves state after every chapter (`_process_chapter`):
  the pipeline first downloads the chapter, sends it if Kindle delivery is
  on and records it in memory, and only then is `state.json` written. If
  that save fails, the command stops before the next chapter. The chapter just processed may
  already be on disk or on the Kindle while `state.json` still holds the
  previous copy, so a later run can download and send it again; nothing
  ties delivery and the state file together. On Ctrl-C or SIGTERM the
  command saves what is left and exits.

## The Python interface

`memanga.api` and `memanga.__version__` are the only supported Python
interface. `memanga.api.Library` reads a library: it never writes either
file, never repairs state and never takes the lock, so it works while a
check or the desktop app runs. Every other module, including those named
on this page, is internal and may change in any release. To change a
library from a script, use the command line;
[Use MeManga in scripts](../reference/scripting) describes its exit codes
and JSON output.

## Where to change what

| To change | Look in |
|---|---|
| A command, its options or its output | `memanga/cli.py`; then regenerate the command reference with `python -m memanga.cli_docs` |
| A setting or its default | `memanga/config.py`; then regenerate the settings reference with `python -m memanga.config_docs` |
| What is stored about a series or the library | `memanga/state.py` and the store for that area in `memanga/state_stores/` |
| The layout of `config.yaml` or `state.json` | The schema version and a migration in `memanga/config.py` or `memanga/state.py`; see `memanga/schema.py` |
| Which chapters count as new | `memanga/downloader/updates.py`, `memanga/suspicion.py` |
| How a chapter is downloaded, recovered, delivered or recorded | `memanga/chapter_pipeline.py`, `memanga/downloader/chapter.py` |
| An output format | `memanga/downloader/formats/` |
| Kindle email | `memanga/emailer.py`, `memanga/email_settings.py` |
| A source | `memanga/scrapers/`: a site with its own module is registered in `memanga/scrapers/__init__.py`; a site built on a template family (`memanga/scrapers/templates/`) is listed in `memanga/scrapers/registry.py` |
| Facts about a source | `memanga/scrapers/catalog.py`; then regenerate the lists with `python -m memanga.source_docs` |
| Search | `memanga/search.py` |
| The desktop app | `memanga/gui/app.py` (window, events), `memanga/gui/workers.py` (background work), `memanga/gui/pages/` and `memanga/gui/components/` |
| Scheduled checks | `memanga/cron.py`, `memanga/watch.py` |
| Setup, browser components and `memanga doctor` | `memanga/first_run.py`, `memanga/doctor.py` |
| Export and import | `memanga/backup.py` |
| The read-only Python interface | `memanga/api.py` |
