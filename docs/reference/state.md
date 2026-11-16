# Data files and backups

<script setup>
import { release } from '../.vitepress/release'
const newer = `Not in ${release.tag}`
</script>

MeManga keeps two files in its config folder:

- `config.yaml` holds your settings and your library, the list of series you
  follow. The [settings reference](./config) describes it.
- `state.json` holds what has happened since: which chapters were
  downloaded and read, where you stopped reading, failed downloads, the
  check and download history, notifications and the state of the sources.

This page explains the safety copies of both files, the export file that
moves your library to another installation, and every field of
`state.json`. [Where MeManga keeps its files](../guide/install#where-memanga-keeps-its-files)
says where the config folder is; `state.json` is next to `config.yaml`.

::: info How to read this page
- This page describes the **development version**.
- Files, fields and options marked <Badge type="info" :text="newer" /> are not used by {{ release.tag }}.
- `state.json` is MeManga's working file, not an interface for other
  programs, and its layout can change in a new version. To read your data
  from a script, use the commands' JSON output (see
  [Use MeManga in scripts](./scripting)) or an export file.
- Do not edit `state.json` by hand while MeManga is running: it keeps the
  data in memory and writes it back over your changes.
:::

## Files in the config folder

| File | What it holds |
|---|---|
| `config.yaml` | Your settings and your library. |
| `config.yaml.bak` <Badge type="info" :text="newer" /> | The previous `config.yaml`, from before the last save. |
| `state.json` | Downloads, reading, history and source state; see [the fields](#fields-of-state-json). |
| `state.json.bak` <Badge type="info" :text="newer" /> | The previous `state.json`, from before the last save. |
| `state.json.corrupt-…` <Badge type="info" :text="newer" /> | A copy of a `state.json` that could not be read. MeManga never deletes it. |
| `error-details/` <Badge type="info" :text="newer" /> | The full text of long error messages in the desktop app's notifications, for the newest 20 of them. |
| `diagnostics.log` <Badge type="info" :text="newer" /> | Diagnostic messages, only when you start MeManga with `--log-file`. |
| `memanga.lock` <Badge type="info" :text="newer" /> | Shows that a MeManga process is working with these files. |

## Safety copies and export files

MeManga has two kinds of copies, and they do different jobs.

| | Safety copy (`.bak`) <Badge type="info" :text="newer" /> | Export file |
|---|---|---|
| Made | automatically, at every save | when you export |
| Contains | the whole previous file | your library and the state of each series |
| Does not contain | anything newer than the last save | your settings (including email addresses and the app password), the check and download history, notifications, source state and recent searches |
| How many | one: each save replaces it | as many as you keep |
| Good for | going back one save on this computer | keeping a copy, moving to another computer or installation |

An export file can contain the paths of files on your computer, such as
where a partial chapter was saved. Keep that in mind before you share one.

{{ release.tag }} keeps no safety copies. If its `state.json` cannot be read, it starts with empty state and replaces the file at its next save. Export your library regularly when you use {{ release.tag }}.

### Go back to the previous copy

1. Close the desktop app and stop anything else that may run MeManga, such
   as `memanga watch` or a scheduled check.
2. In the config folder, rename `state.json` to another name, then rename
   `state.json.bak` to `state.json`. Do the same with `config.yaml` and
   `config.yaml.bak` to go back to the previous settings and library.
3. Start MeManga again.

The copy is from before the last save, so the changes of that save are not
in it.

### When state.json cannot be read

<Badge type="info" :text="newer" /> When `state.json` is damaged, for example cut off by a crash or full disk:

1. MeManga keeps a copy of it as `state.json.corrupt-` followed by the time
   and a random part.
2. If `state.json.bak` can be read, MeManga loads it, writes it back as
   `state.json` and tells you so: a command prints a warning, the desktop
   app shows a message. Changes made after that copy are missing.
3. Otherwise it starts with empty state and tells you so in the same way.
   The message names the copy of the damaged file. Your library and
   settings in `config.yaml` stay as they are; the download history, read
   chapters, reading positions and source state start again.

MeManga does not start with empty state when it could lose the only good
copy. If `state.json` or its copy cannot be read at all (for example
because of file permissions), or the damaged file cannot be copied aside,
the command stops and nothing is changed. A command that only reads, such
as `memanga list`, does not repair the file while another MeManga process
is working with it; it stops and asks you to try again later.

When `config.yaml` cannot be read, commands stop and leave it as it is.
Only `memanga doctor`, `memanga config path` and `memanga config edit`
still run. Fix the file, or go back to `config.yaml.bak` as described above.

## Export and import

### Export

- **Desktop app:** Settings → Advanced → Import / Export → **Export**.
- **Command line:** `memanga export FILE`. Without a file name it writes
  `memanga_export.json` in the current folder. `memanga export -` writes
  to standard output instead <Badge type="info" :text="newer" />.

The export file is JSON:

| Key | Content |
|---|---|
| `version` | Format version of the export file, a whole number. It is `1`, and has been since export existed. It is not the `schema_version` of `state.json`. |
| `exported_at` | When the file was written, as a local time without a time zone. |
| `manga` | Your library: the series list from `config.yaml`, as it is there. |
| `state` | The state of each series: the [`manga` part of `state.json`](#each-series), by title. |

A shortened example with one series:

```json
{
  "version": 1,
  "exported_at": "2026-11-16T09:30:00.123456",
  "manga": [
    {
      "title": "Example Series",
      "source": "mangadex.org",
      "url": "https://mangadex.org/title/00000000-0000-4000-8000-000000000000"
    }
  ],
  "state": {
    "Example Series": {
      "downloaded": ["1", "2"],
      "last_chapter": "2",
      "read_chapters": ["1"],
      "reading_progress": {
        "last_chapter": "1",
        "last_read": "2026-11-15T21:04:10.512000"
      }
    }
  }
}
```

### Import and merge

- **Desktop app:** **Import (Merge)**.
- **Command line:** `memanga import FILE`, or `memanga import -` to read
  standard input <Badge type="info" :text="newer" />.

**Your library:** a series from the file is added unless your library has a
series with the same title, compared without regard to upper and lower
case. Such a series keeps its own entry and settings; only its state is
merged with the file's.

**The state of each series** is merged, never replaced. A series that has
no state here takes the file's state as it is. For a series that has state
on both sides:

| Field | After the merge |
|---|---|
| `downloaded`, `read_chapters`, `external_chapters` | Every chapter from both sides, in chapter order. |
| `available_chapters` | Both lists; a chapter with the same number, address, source and backup flag only once. |
| `failed_chapters`, `partial_chapters`, `pending_backup`, `saved_chapter_groups` | Records of both sides, by chapter. When both have a record for the same chapter, the one here is kept. |
| `undelivered_chapters`, `resolved_deliveries` <Badge type="info" :text="newer" /> | A Kindle delivery that was sent or dismissed on either side stays done. A failed delivery stays queued only when it provably failed after that; when the order cannot be told, it is dropped rather than risk sending the chapter twice. |
| `reading_progress` | The side with the later `last_read`. |
| `new_chapters_available` | The higher number. |
| `last_chapter` | The higher chapter. |
| `last_updated` | The later time. |
| `created` | The one here; the file's only when there is none here. |
| Any other field | The value here; the file's only when the field is missing here. Fields MeManga does not know are kept as they are. |

### Import and replace

- **Desktop app:** **Import (Replace)**. It replaces right away, without
  asking again: export your current library first.
- **Command line:** `memanga import --replace FILE`. It asks before it
  replaces anything; `--yes` answers for you <Badge type="info" :text="newer" />.

Replace sets your library to the file's series list and the state of each
series to the file's. A series of yours that is not in the file loses its
state. Your settings, the check and download history, notifications and
source state stay as they are.

### Checks before an import

Both ways refuse a file without a `version`, or with a version newer than
this MeManga knows, and change nothing.

The command line also checks every entry of the file before it changes
anything <Badge type="info" :text="newer" />: each series needs a title and
its fields need the types MeManga writes, and two series must not end up
sharing a download folder. `memanga import --dry-run FILE` runs these
checks and shows what would change, without changing anything
<Badge type="info" :text="newer" />. The desktop app checks only the
version, so check a file with `--dry-run` before you import it there.

### Between versions

Exports from {{ release.tag }} and from the development version both have `version` 1, and each imports the other's files. {{ release.tag }} may not be compatible with data that the development version has written, including its export files.

## Schema version

<Badge type="info" :text="newer" /> `config.yaml` and `state.json` each have a `schema_version`, a whole number
that changes only when the layout of the file changes in a way that needs a
conversion. For `state.json` it is currently `1`.

- A file without it, such as one from {{ release.tag }}, counts as version 0. MeManga converts it when it loads it and writes the new layout at the next save; the file before the conversion becomes the `.bak` copy.
- A file with a higher version than this MeManga knows is refused and left
  as it is. Update MeManga to use it.
- New fields can appear without a new version. MeManga leaves fields it
  does not use as they are.

## Fields of state.json

`state.json` is one JSON object. Throughout:

- **Times** are local times without a time zone, in ISO 8601, for example
  `2026-11-16T09:30:00.123456`. Kindle delivery records are the exception:
  they are in UTC with the offset, for example
  `2026-11-16T08:30:00.123456+00:00`, so that records from different
  computers can be compared.
- **Chapters** are text, as the source names them: `"12"`, `"10.5"` or
  `"3 Part 1"`. Lists of chapters are kept in chapter order.
- **Series** are keyed by their exact title in your library. Renaming a
  series moves its state and its download history to the new title.

### Top level

| Field | Type | What it holds |
|---|---|---|
| `schema_version` <Badge type="info" :text="newer" /> | number | The layout version; see [Schema version](#schema-version). |
| `manga` | object | The state of each series, by title; see [Each series](#each-series). |
| `last_check` | time or `null` | When the last check for new chapters ran. |
| `check_history` | list | One record per check: `timestamp`, `new_chapters` (found) and `downloaded`. The newest 50 are kept. |
| `download_history` | list | One record per saved chapter; see [Download history](#download-history). The newest 200 are kept. |
| `notifications` | list | The desktop app's notifications; see [Notifications](#notifications). The newest 100 are kept. |
| `source_health` | object | The result of the last tests of each source, by domain; see [Source state](#source-state). |
| `search_history` | list of text | Recent searches in the desktop app, newest first. Missing until the first search. The newest 8 are kept. |

### Each series

A series gets an entry the first time MeManga records something about it.
A new entry has `downloaded`, `last_chapter`, `last_updated`, `created`,
`reading_progress`, `new_chapters_available`, `available_chapters`,
`external_chapters` and `partial_chapters`; the other fields appear when
they are first needed.

Removing a series from your library keeps its entry and its download
history, so adding it again later continues where it was. `memanga remove
--purge-history`, or the matching choice in the desktop app, removes both.

**Downloads**

| Field | Type | What it holds |
|---|---|---|
| `downloaded` | list of chapters | Chapters saved in the download folder. When the desktop reader moves a chapter's file to the trash after reading, the chapter leaves this list and stays read. |
| `last_chapter` | chapter or `null` | The chapter saved last. |
| `last_updated` | time or `null` | When the downloads of this series last changed. |
| `created` | time | When the entry was made. |
| `saved_chapter_groups` <Badge type="info" :text="newer" /> | object | By chapter: the scanlation groups a saved chapter came from, as `source`, `group_ids` and `group_names`, where the source names them. |

**Reading**

| Field | Type | What it holds |
|---|---|---|
| `read_chapters` | list of chapters | Chapters marked as read, in the reader, in the chapter list or with `memanga read` and `memanga unread` <Badge type="info" :text="newer" />. |
| `reading_progress` | object | `last_chapter`, the chapter last opened in the reader, and `last_read`, when. The desktop app's Continue reading uses it. |
| `reader_positions` | object | By chapter: where reading stopped inside it, as `mode` (the reader layout), `updated_at` and `page_index` or `scroll_ratio` (0 to 1). Removed when the chapter is finished or marked read. |
| `external_chapters` | list of chapters | Chapters you marked as read somewhere else. They are not downloaded. |

**What the sources offer**

| Field | Type | What it holds |
|---|---|---|
| `available_chapters` | list | The chapter list from the last check in the desktop app. Each item has `number`, `title`, `source`, `source_url`, `is_backup`, `url`, `group_ids` and `group_names`. |
| `new_chapters_available` | number | The number of new chapters shown on the series. |
| `catalogue_baseline` | number | The highest chapter number the sources have shown that was not held back. MeManga compares new chapters with it to recognise suspicious jumps. |

**Problems and holds**

| Field | Type | What it holds |
|---|---|---|
| `failed_chapters` | object | By chapter: a download that failed, with `failed_at`, `source`, `error` (up to 300 characters), `failed_pages` and `attempts`. `memanga failed` lists and retries them. |
| `partial_chapters` | object | By chapter: a chapter kept with missing pages (see [partial chapters](./config#partial-chapters)), with `accepted_at`, `source`, `failed_pages`, `total_pages`, `path` and `from_backup`. It can be downloaded again in full. |
| `pending_backup` | object | By chapter: a chapter so far found only on the backup source, with `first_seen`, `backup_source` and `backup_url`. MeManga waits for the primary source as long as the series' fallback delay says. |
| `suspicious_batch` | object | A batch of new chapters held back because it looks wrong, with `detected_at`, `chapters`, `count`, `last_chapter`, `highest`, `score`, `reasons` and `backup_status`. |

**Kindle delivery** <Badge type="info" :text="newer" />

| Field | Type | What it holds |
|---|---|---|
| `undelivered_chapters` | object | By chapter: a saved chapter whose email to the Kindle failed, with `failed_at`, `path`, `error`, `attempts` and, for a PDF sent in parts, `parts`. `memanga send --pending` sends them again. |
| `resolved_deliveries` | object | By chapter: a delivery that was sent or dismissed, with `resolved_at` and `reason` (`sent` or `cleared`). It stops an import of an older export from queuing the chapter again. |

### Download history

Each record in `download_history` has:

- `title`, `chapter` and `format` of the saved chapter;
- `path`, where it was saved, and `size_mb`;
- `kindle_sent`: whether it was sent to the Kindle;
- `timestamp`: when it was saved;
- `source`, `from_backup`, `partial` and `deleted_after_send` <Badge type="info" :text="newer" />: where it came from, whether that was the backup source, whether it is a partial chapter, and whether the file was deleted after sending.

### Notifications

Each record in `notifications` has `type`, `message`, `timestamp` and
`read`. A notification with an error message also has `details`
<Badge type="info" :text="newer" />, the message without private details
such as passwords. A long message is cut there; `details_chars` gives the
full length and `details_file` names the file in `error-details/` with the
whole text.

### Source state

`source_health` has one record per source domain:

- `status`: `ok`, `warning` (slow, or one or two failures in a row) or
  `error` (three failures in a row or more);
- `last_success` and `last_error`: when the last test worked and failed;
- `last_error_msg`: what went wrong last;
- `error_count`: failures in a row;
- `latency_ms`: how long the last test took.
