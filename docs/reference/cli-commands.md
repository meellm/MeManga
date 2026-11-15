<!-- Generated from the argument parser by `python -m memanga.cli_docs`. Do not edit by hand. -->

## Global options

These go before the command.

```text
memanga [options] [COMMAND]
```

**Options**

- `-V, --version`: show program's version number and exit
- `--config-dir DIR`: Use DIR for config.yaml and state.json, also with --gui (default: $MEMANGA_CONFIG_DIR or the platform config folder). Goes before the command.
- `--gui`: Launch the graphical user interface (needs the gui extra)
- `-v, --verbose`: Show more diagnostics on stderr (-v progress, -vv debug). Overrides $MEMANGA_LOG_LEVEL. Goes before the command.
- `-q, --quiet`: Hide warning, progress and debug diagnostics; errors still show. Overrides $MEMANGA_LOG_LEVEL. Goes before the command.
- `--plain`: Plain text output: no colour, emoji, borders or line wrapping (automatic when output is not a terminal). Goes before the command.
- `--log-file`: Also write diagnostics to diagnostics.log in the config directory (rotated, with timestamps). Goes before the command.

Only one of `--verbose` and `--quiet` can be given.

## Commands at a glance

- [`memanga list`](#memanga-list): List tracked manga
- [`memanga add`](#memanga-add): Add a manga to track
- [`memanga remove`](#memanga-remove): Remove a manga
- [`memanga edit`](#memanga-edit): Edit a manga's sources, title, status, mode, Kindle toggle or fallback delay
- [`memanga set`](#memanga-set): Deprecated: use 'memanga edit TARGET --status STATUS'.
- [`memanga read`](#memanga-read): Mark chapters of a manga as read
- [`memanga unread`](#memanga-unread): Mark chapters of a manga as unread
- [`memanga path`](#memanga-path): Print the download folder of a manga
- [`memanga open`](#memanga-open): Open the download folder of a manga in the file manager
- [`memanga check`](#memanga-check): Check for new chapters
- [`memanga status`](#memanga-status): Show status and configuration
- [`memanga config`](#memanga-config): Configure settings
- [`memanga cron`](#memanga-cron): Manage cron job
- [`memanga watch`](#memanga-watch): Keep running and check on an interval (containers)
- [`memanga sources`](#memanga-sources): List supported sources
- [`memanga search`](#memanga-search): Search sources for a manga by title
- [`memanga export`](#memanga-export): Export manga list and state to JSON
- [`memanga import`](#memanga-import): Import manga list and state from JSON
- [`memanga failed`](#memanga-failed): List, retry or clear failed and partial chapter downloads
- [`memanga send`](#memanga-send): Send downloaded chapters to Kindle
- [`memanga doctor`](#memanga-doctor): Diagnose setup problems (runtime/install, paths, browsers, email, scheduler)
- [`memanga setup`](#memanga-setup): Prepare a first run: config, download folder and browsers
- [`memanga tui`](#memanga-tui): Interactive terminal UI
- [`memanga completion`](#memanga-completion): Print a shell completion script (bash)

## memanga list

List tracked manga.

Alias: `memanga ls`.

```text
memanga list [options]
```

**Options**

- `--json`: Machine-readable JSON output
- `--status {reading,on-hold,dropped,completed}`: Only show manga with this status (repeat for several)
- `--sort {list,title,status,last-chapter,downloaded}`: Sort order (default: list, the order manga were added). Ties keep list order; # stays the list number for #N
- `--reverse`: Reverse the sort; manga with no numeric last chapter or an unknown status stay last

## memanga add

Add a manga to track.

```text
memanga add [options]
```

**Options**

- `-t, --title TITLE`: Manga title
- `-u, --url URL`: Primary source URL
- `-b, --backup BACKUP`: Backup source URL
- `--fallback-days FALLBACK_DAYS`: Days to wait before using the backup (0 or more; default: 2); needs --backup
- `--status {reading,on-hold,dropped,completed}`: Initial status (default: reading)
- `--mode {auto,manual}`: Desktop-app download mode (default: auto)
- `--kindle`: Turn the desktop app's per-manga Kindle toggle on (without either flag, email.kindle_scope decides)
- `--no-kindle`: Turn the desktop app's per-manga Kindle toggle off
- `-i, --interactive`: Interactive mode (--status, --mode and --kindle/--no-kindle still apply)
- `-f, --force, -y, --yes`: Add even if the source might be unsupported or a similar title is tracked

Only one of `--kindle` and `--no-kindle` can be given.

## memanga remove

Remove a manga.

Alias: `memanga rm`.

```text
memanga remove [options] target
```

**Arguments**

- `target`: Manga title, or #N for its number in 'memanga list'

**Options**

- `-y, --yes`: Skip the removal confirmation only (never purges history or deletes files)
- `--purge-history, --purge`: Also remove its download history
- `--keep-files`: Keep its downloaded files (default; skips the interactive prompt)
- `--delete-files`: Also delete its download folder (&lt;download dir&gt;/&lt;title&gt;)

Only one of `--keep-files` and `--delete-files` can be given.

## memanga edit

Edit a manga's sources, title, status, mode, Kindle toggle or fallback delay.

Alias: `memanga update`.

```text
memanga edit [options] target
```

Change only the fields given; everything else is kept. Output format is global (memanga config, or check --format); there is no per-manga format.

**Arguments**

- `target`: Manga title, or #N for its number in 'memanga list'

**Options**

- `-u, --url URL`: New primary source URL
- `-b, --backup BACKUP`: Add a backup source URL, or replace the first backup
- `--no-backup`: Remove every backup source and its fallback delay
- `--fallback-days FALLBACK_DAYS`: Days to wait before using the backup (0 or more); needs a backup source
- `-t, --title TITLE`: Rename manga title (moves its history and downloads)
- `--status {reading,on-hold,dropped,completed}`: New status
- `--mode {auto,manual}`: Desktop-app download mode
- `--kindle`: Turn the desktop app's per-manga Kindle toggle on
- `--no-kindle`: Turn the desktop app's per-manga Kindle toggle off

Only one of `--backup` and `--no-backup` can be given.
Only one of `--kindle` and `--no-kindle` can be given.

## memanga set

```text
memanga set target {reading,on-hold,dropped,completed}
```

Deprecated: use 'memanga edit TARGET --status STATUS'. 'set' will be removed in the next release.

**Arguments**

- `target`: Manga title, or #N for its number in 'memanga list'
- `{reading,on-hold,dropped,completed}`: New status

## memanga read

Mark chapters of a manga as read.

```text
memanga read [options] TARGET [CHAPTER ...]
```

```text
Mark chapters of a manga as read, as the desktop app's reader and chapter list show it.

CHAPTER is a chapter number or label from the manga's chapter list
(downloaded, found by 'check', or marked read elsewhere); give one
or more, or --all. Every CHAPTER is checked before anything changes.
Marking read also resets the chapter's saved page, as finishing it
in the reader does. Files and download history are never touched.

Exit codes: 0 success (also when nothing needed changing); 1 the
manga or a chapter was not found or is ambiguous; 2 usage error.
```

**Arguments**

- `TARGET`: Manga title, or #N for its number in 'memanga list'
- `CHAPTER`: Chapter number or label, e.g. 12 or 10.5

**Options**

- `--all`: Mark every downloaded chapter read

## memanga unread

Mark chapters of a manga as unread.

```text
memanga unread [options] TARGET [CHAPTER ...]
```

```text
Mark chapters of a manga as unread, as the desktop app's reader and chapter list show it.

CHAPTER is a chapter number or label from the manga's chapter list
(downloaded, found by 'check', or marked read elsewhere); give one
or more, or --all. Every CHAPTER is checked before anything changes.
Marking read also resets the chapter's saved page, as finishing it
in the reader does. Files and download history are never touched.

Exit codes: 0 success (also when nothing needed changing); 1 the
manga or a chapter was not found or is ambiguous; 2 usage error.
```

**Arguments**

- `TARGET`: Manga title, or #N for its number in 'memanga list'
- `CHAPTER`: Chapter number or label, e.g. 12 or 10.5

**Options**

- `--all`: Mark every read chapter unread

## memanga path

Print the download folder of a manga.

```text
memanga path TARGET
```

```text
Print the download folder of a manga: <download dir>/<title>, where its chapters are saved.
Only the absolute path is printed to stdout, so scripts can use
it: cd "$(memanga path TARGET)".
Nothing is created; a manga with nothing downloaded yet is an error.

Exit codes: 0 success; 1 the manga was not found or is ambiguous,
it has no download folder yet, or the folder could not be opened;
2 usage error.
```

**Arguments**

- `TARGET`: Manga title, or #N for its number in 'memanga list'

## memanga open

Open the download folder of a manga in the file manager.

```text
memanga open TARGET
```

```text
Open the download folder of a manga in the file manager: <download dir>/<title>, where its chapters are saved.
Uses the system file manager (xdg-open on Linux).
Nothing is created; a manga with nothing downloaded yet is an error.

Exit codes: 0 success; 1 the manga was not found or is ambiguous,
it has no download folder yet, or the folder could not be opened;
2 usage error.
```

**Arguments**

- `TARGET`: Manga title, or #N for its number in 'memanga list'

## memanga check

Check for new chapters.

```text
memanga check [options] [TARGET]
```

```text
Check tracked manga for new chapters.

Modes:
  check --dry-run    check only: list what a download run would fetch;
                     never downloads, delivers or changes state
  check --download   download without prompting (--auto and --yes are
                     aliases; scheduled runs use 'check --auto --quiet')
  check              ask per chapter on a terminal; without a terminal,
                     or with --quiet, download nothing and exit 1

--dry-run wins over --download. --all and --from choose where to start;
they don't download by themselves.

Exit codes: 0 no new chapters, chapters listed or all downloaded, or a
suspicious batch withheld (warning on stderr); 1 every checked manga
failed, the target was not found, chapters needed confirmation, or
state.json could not be written; 2 usage error; 3 some chapters or
manga failed; 130 interrupted; 143 terminated (SIGTERM).
```

**Arguments**

- `TARGET`: Check one manga only (title, or #N from 'memanga list')

**Options**

- `-t, --title TITLE`: Same as TARGET
- `-f, --from FROM_CHAPTER`: Start from chapter N (for fresh downloads)
- `--all`: Start from the first chapter (backfill; skips the suspicious-batch check)
- `--download, -a, --auto, -y, --yes`: Download new chapters without prompting (--auto and --yes are aliases)
- `-q, --quiet`: Never prompt; without --download, new chapters are skipped and the run exits 1 (to hide warnings, use `memanga -q check`)
- `-s, --safe`: Safe mode: restart browser every 3 chapters (for bulk downloads)
- `-n, --dry-run`: Check only: list what would be downloaded; no downloads or state changes (wins over --download)
- `--force-suspicious`: Accept a chapter batch even if it was flagged as suspicious
- `--format {pdf,epub,cbz,zip,jpg,png,webp}`: Output format (overrides config)
- `--retries N`: Retry failed page downloads N times (default: 3, 0 to disable)
- `--allow-partial`: Keep a chapter with a few missing pages instead of discarding it
- `--no-partial`: Force-discard any chapter with missing pages, even if partial tolerance is enabled in config
- `--partial-threshold PCT`: Max % of pages allowed to fail before a partial is refused, 0-100 (default: config value)

Only one of `--allow-partial` and `--no-partial` can be given.

## memanga status

Show status and configuration.

```text
memanga status [options]
```

**Options**

- `--json`: Machine-readable JSON output

## memanga config

Configure settings.

```text
memanga config [options] [ACTION]
```

**Options**

- `--show`: Show current config
- `--mangadex-quality {original,data-saver}`: Select MangaDex chapter image quality
- `--mangadex-remove-group GROUP_ID`: Block a scanlation group's MangaDex chapters by group ID
- `--partial {on,off}`: Enable/disable partial-chapter tolerance without prompting
- `--partial-threshold PCT`: Persist the max % of pages allowed to fail (0-100)

### memanga config show

Show the current config (app password and email addresses masked).

```text
memanga config show [options]
```

**Options**

- `--json`: Machine-readable JSON output

### memanga config get

Print one setting's value.

```text
memanga config get KEY
```

KEY is one of: delivery.mode, delivery.download_dir, delivery.delete_after_send, delivery.output_format, delivery.naming_template, delivery.post_processing.enabled, delivery.post_processing.command, delivery.post_processing.fail_on_error, email.kindle_email, email.sender_email, email.smtp_server, email.smtp_port, email.smtp_tls, email.smtp_timeout, email.max_email_mb, email.app_password, email.kindle_scope, cron.enabled, cron.time, gui.sort_by, gui.auto_check, gui.auto_check_interval, gui.reader_prefetch_next, gui.network_check, gui.network_check_hosts, gui.mangadex_cover_fallback, gui.search_chapter_counts, gui.cover_cache_max_mb, reader.remove_after_read, mangadex.data_saver, mangadex.removed_group_ids, partial_chapters.enabled, partial_chapters.threshold_percent

**Arguments**

- `KEY`

### memanga config set

Change one setting.

```text
memanga config set KEY [VALUE]
```

KEY is one of: delivery.mode, delivery.download_dir, delivery.delete_after_send, delivery.output_format, delivery.naming_template, delivery.post_processing.enabled, delivery.post_processing.command, delivery.post_processing.fail_on_error, email.kindle_email, email.sender_email, email.smtp_server, email.smtp_port, email.smtp_tls, email.smtp_timeout, email.max_email_mb, email.app_password, email.kindle_scope, cron.enabled, cron.time, gui.sort_by, gui.auto_check, gui.auto_check_interval, gui.reader_prefetch_next, gui.network_check, gui.network_check_hosts, gui.mangadex_cover_fallback, gui.search_chapter_counts, gui.cover_cache_max_mb, reader.remove_after_read, mangadex.data_saver, mangadex.removed_group_ids, partial_chapters.enabled, partial_chapters.threshold_percent. For email.app_password pass '-' and send the value on stdin, or omit VALUE on a terminal to be prompted.

**Arguments**

- `KEY`
- `VALUE`

### memanga config path

Print the config file path.

```text
memanga config path
```

### memanga config edit

Open config.yaml in $VISUAL or $EDITOR, then check it.

```text
memanga config edit
```

### memanga config email

Show email delivery settings (app password masked).

```text
memanga config email [options]
```

**Options**

- `--test`: Connection check only: log in to the configured SMTP server; sends nothing (network)
- `--send-test`: Email a small test PDF to the configured Kindle address (network). Mail server acceptance does not prove Kindle delivery

Only one of `--test` and `--send-test` can be given.

## memanga cron

Manage cron job.

```text
memanga cron [options] {status,install,remove}
```

**Arguments**

- `{status,install,remove}`: Action

**Options**

- `--time TIME`: Check time (HH:MM) for install

## memanga watch

Keep running and check on an interval (containers).

```text
memanga watch [options]
```

```text
Stay in the foreground and run 'check --auto --quiet' now and then
every --every interval, start to start, for Docker and other hosts
without cron. Checks never overlap; a failed check is reported and
the schedule continues. Each check locks the config directory only
while it runs, so other commands work in between. SIGTERM or Ctrl-C
lets a running check save its state, then exits 143 or 130.

Durations: a number with d, h, m or s, e.g. 6h, 90m or 1h30m.
```

**Options**

- `--every DURATION`: Time between check starts (default: 6h, at least 15m)
- `--jitter DURATION`: Add a random delay of up to DURATION to each wait (default: 0)

## memanga sources

List supported sources.

```text
memanga sources [options] [query]
```

**Arguments**

- `query`: Only show sources whose domain or alias contains this text

**Options**

- `--json`: Machine-readable JSON output
- `--search {included,not-searched}`: Only show sources the search sweep includes or skips
- `--health {ok,warning,error,unknown}`: Only show sources with this saved health (repeat for several); unknown means never checked

## memanga search

Search sources for a manga by title.

```text
memanga search [options] query
```

**Arguments**

- `query`: Manga title to search for

**Options**

- `--json`: Machine-readable JSON output
- `--source SOURCE`: Search a single source only (e.g. mangadex.org)
- `--limit N`: Cap results per source
- `--add N`: Add result #N without prompting
- `--status {reading,on-hold,dropped,completed}`: Status for the added manga (with --add or the prompt)
- `--no-chips`: Skip chapter counts: no chapter-list fetch per result, which can take several requests each (faster, less traffic)

## memanga export

Export manga list and state to JSON.

```text
memanga export [file]
```

**Arguments**

- `file`: Output file, or - for stdout (default: memanga_export.json)

## memanga import

Import manga list and state from JSON.

```text
memanga import [options] file
```

**Arguments**

- `file`: JSON file to import, or - for stdin

**Options**

- `--replace`: Replace all data instead of merging (asks first; see --yes)
- `--dry-run`: Validate the backup and show what would change, without writing
- `-y, --yes`: Confirm --replace without prompting (required when not interactive or reading stdin)

## memanga failed

List, retry or clear failed and partial chapter downloads.

```text
memanga failed [options] [ACTION]
```

```text
List, retry or clear chapters that failed or were saved as partial.

Actions:
  failed [list [TARGET]]   list the records (the default)
  failed retry [TARGET]    download the chapters again the way 'check'
                           does: backup source, partial rules, delivery
  failed clear [TARGET]    forget the records without downloading

TARGET is a title or '#N' from 'memanga list', matched like 'check -t';
without it every manga is included. '--retry' and '--clear' are kept as
aliases of 'failed retry' and 'failed clear'. '--json' only lists.

Exit codes: 0 success; 1 the target was not found or is ambiguous;
2 usage error; 3 retry left some chapters failed or partial.
```

**Options**

- `-t, --title TITLE`: Only this manga (title, or #N from 'memanga list'); same as TARGET
- `--retry`: Alias of 'failed retry'
- `--clear`: Alias of 'failed clear'
- `--json`: Machine-readable JSON output (listing only)

### memanga failed list

```text
memanga failed list [options] [TARGET]
```

List failed and partial chapters (default).

**Arguments**

- `TARGET`: Title or #N from 'memanga list' (default: every manga)

**Options**

- `-t, --title TITLE`: Same as TARGET
- `--json`: Machine-readable JSON output

### memanga failed retry

```text
memanga failed retry [options] [TARGET]
```

Download the listed chapters again.

**Arguments**

- `TARGET`: Title or #N from 'memanga list' (default: every manga)

**Options**

- `-t, --title TITLE`: Same as TARGET

### memanga failed clear

```text
memanga failed clear [options] [TARGET]
```

Forget the listed records without downloading.

**Arguments**

- `TARGET`: Title or #N from 'memanga list' (default: every manga)

**Options**

- `-t, --title TITLE`: Same as TARGET

## memanga send

Send downloaded chapters to Kindle.

```text
memanga send [options] [TARGET] [CHAPTER ...]
```

```text
Send saved chapters to Kindle.

  send TARGET CHAPTER...           send these downloaded chapters
  send TARGET CHAPTER... --dry-run only show what would be sent
  send --pending [TARGET]          send every chapter whose Kindle
                                   delivery failed
  send --pending --list [TARGET]   only list them
  send --pending --clear [TARGET]  forget the records; the files stay

CHAPTER is a downloaded chapter's number or label, e.g. 12 or 10.5.
Every CHAPTER is checked before anything is sent; its saved file is
taken from the manga's download folder, and nothing is downloaded.
A chapter is sent again even if an earlier send worked. Sending more
than one chapter asks first; --yes skips that, and is required when
no one can answer.

A chapter that was saved but could not be emailed stays on the
--pending list until it is sent. 'delivery.delete_after_send' removes
a file only after it was sent. TARGET is a title or '#N' from
'memanga list', matched like 'check -t'; with --pending and no
TARGET every manga is included.

Exit codes: 0 success, nothing to send, or sending was declined at
the question; 1 the target or a chapter was not found or is
ambiguous, Kindle delivery is not set up, or several chapters were
given without --yes and no one can answer; 2 usage error; 3 some
chapters could not be sent (with --dry-run: would not be sent).
```

**Arguments**

- `TARGET`: Title or #N from 'memanga list' (with --pending, default: every manga)
- `CHAPTER`: Downloaded chapter number or label, e.g. 12 or 10.5

**Options**

- `--pending`: Chapters whose Kindle delivery failed
- `--list`: With --pending: only list them; send nothing
- `--clear`: With --pending: forget the records without sending; the files stay
- `--dry-run`: Only show what would be sent; send nothing
- `-y, --yes`: Send several chapters without asking

Only one of `--list`, `--clear` and `--dry-run` can be given.

## memanga doctor

Diagnose setup problems (runtime/install, paths, browsers, email, scheduler).

```text
memanga doctor [options]
```

Run local health checks. Exits 0 when no check fails, 1 when any selected check fails.

**Options**

- `--json`: Machine-readable JSON output
- `--check NAME`: Run only this check; repeatable. One of: runtime, config, state, download_dir, email, keyring, smtp, scheduler, sources, browsers
- `--smtp`: Log in to the configured SMTP server (network; skipped by default)
- `--launch-browsers`: Launch Firefox and Chromium headless instead of only checking they are installed
- `--strict`: Also exit non-zero on warnings

## memanga setup

Prepare a first run: config, download folder and browsers.

```text
memanga setup [options]
```

```text
Create the config file and download folder when missing, and
check that the Firefox and Chromium builds the scrapers use are
installed and start. Missing browsers are downloaded only with
--install-browsers or after you agree on a terminal; without a
terminal nothing is downloaded. Missing system libraries are
reported with the command that installs them; setup never runs
sudo or a package manager. Safe to run again at any time.

Exits 0 when everything is ready, 1 when something still needs
you.
```

**Options**

- `--install-browsers, --no-install-browsers`: Download missing browsers without asking (--install-browsers) or never download them (--no-install-browsers). Default: ask on a terminal, don't download otherwise

## memanga tui

Interactive terminal UI.

```text
memanga tui
```

## memanga completion

Print a shell completion script (bash).

```text
memanga completion {bash}
```

```text
Print a completion script for SHELL to stdout. Only bash is
supported for now.

Load it for the current session, or add the line to ~/.bashrc:
  source <(memanga completion bash)
```

**Arguments**

- `{bash}`: Target shell
