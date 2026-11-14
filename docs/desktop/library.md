# Library, downloads and settings

<script setup>
import { release } from '../.vitepress/release'
</script>

This page covers the desktop app outside the reader: following series,
downloading chapters, and the settings you are most likely to change. The
[reader](./reader) has its own page.

Unless a section says otherwise, everything here works the same in
{{ release.tag }} and in the development version.

## Follow a series

There are two ways to add a series to your library.

- **Search.** Open **Search**, type a title and press Enter. MeManga asks
  every enabled source and lists the results. Choosing a result opens the
  add dialog with its details filled in.
- **Add manga.** In **Library**, choose **Add manga** and paste the address
  of the series page on a supported source.

The add dialog asks for:

| Field | What it does |
|---|---|
| Source URL | The series page on the source. The title is detected from it; you can type your own instead. |
| I'm currently on chapter | Optional. See [chapters you read elsewhere](#chapters-you-read-elsewhere). |
| Reading status | Reading, Plan to read, On hold, Completed or Dropped. |
| Add backup source | Optional second source to fall back on when the primary one cannot be reached. |
| Fallback delay (days) | How long MeManga waits before it turns to the backup source. |

### Which series are checked

**Check all** in the Library looks for new chapters only for series with the
status **Reading**. Series that are on hold, completed or dropped are
skipped. **Check updates** on a series' own page always checks that series,
whatever its status.

## Auto and manual mode

Each series has a **Mode**, set on its page.

| Mode | What happens after a check |
|---|---|
| Auto | New chapters are downloaded. |
| Manual | New chapters are listed, and you download the ones you want with the **Download** button on each row. |

In manual mode a check tells you how many new chapters are available and
leaves them for you to pick.

A series' page also has **Download from…**, which downloads from a chapter
number you give (use `0` for all chapters from the beginning), and
**Download all**.

## Chapters you read elsewhere

If you have already read part of a series somewhere else, enter the chapter
you are on in **I'm currently on chapter** when you add it. Every chapter
before that number is marked **Read elsewhere**. Those chapters are not
treated as new and are not downloaded by a check.

Leave the field empty to start from the beginning.

## The chapter list

A series' page lists its chapters. Each row shows where the chapter stands:

| Row says | Meaning |
|---|---|
| Not downloaded | Not on disk yet. **Download** fetches it. |
| Downloaded | On disk. **Read** opens it in the reader. |
| Read | You finished it in the reader. |
| Read elsewhere | Marked as already read when you added the series. |
| Partial, with a page count | Downloaded with some pages missing. **Retry** downloads it again. |

Chips above the list filter it by Downloaded, Partial, Not downloaded and
Unread, and the list can be sorted newest or oldest first.

### Partial chapters

Sometimes a source fails to deliver a few pages of a chapter. By default
MeManga discards such a chapter. To keep it instead:

1. Open **Settings → Advanced → Partial Chapters**.
2. Turn on **Allow partial chapters**.
3. Set **Max pages allowed to fail**, as a percentage of the chapter's pages.

A chapter that is missing more pages than this limit is still refused. A
chapter that was kept shows as partial in the list, with the number of
missing pages, and can be retried.

### Suspicious batches

A source sometimes reports chapters that do not exist, for example a sudden
jump of dozens of chapters. MeManga compares each batch of new chapters with
the series' usual pace. When a batch looks wrong:

- If the series has a backup source and it lists at least half of those
  chapters, the batch is accepted.
- Otherwise the batch is held back and a warning appears in
  **Notifications**. Chapters that were already known stay downloadable.

The desktop app has no button to accept a held batch. To accept it, use the
command line:

```sh
memanga check --force-suspicious
```

## Downloads

**Downloads** shows what is being downloaded and what has finished, in three
tabs: Active, Completed and History.

- **Pause all** stops new downloads from starting. Downloads already running
  finish.
- **Cancel all** cancels the queue.
- **Open folder** opens your download folder.

## Notifications

**Notifications** keeps a history of what MeManga did: new chapters found,
finished downloads, chapters sent to Kindle, warnings and errors. Entries are
grouped by day and can be filtered by New chapters, Downloads and System.

**Mark all read** clears the unread count. **Clear all** deletes the history
after asking.

## Settings

Open **Settings**. Changes apply when you choose **Save settings**, except
the theme, which switches at once.

### Theme

**Settings → General → Appearance** offers a dark and a light theme.

### Download folder and output format

**Settings → General** sets where chapters are saved and in which format.
Each series gets its own subfolder.

PDF and EPUB suit e-readers and can be sent to a Kindle. CBZ, ZIP and image
folders are kept on your computer only.

### Concurrent downloads

**Concurrent Downloads** sets how many chapters download at the same time,
from 1 to 8. A higher number is faster but makes it more likely that a
source limits you.

### File names

**File Naming** takes a template for the file name of each chapter. The
default is `{title} - Chapter {chapter}`. The variables are `{title}`,
`{chapter}`, `{source}` and `{date}`. A preview under the field shows the
name your template produces.

### Storage and cover cache

Covers are stored on disk so the Library opens quickly.
**Settings → Advanced → Clear cache** removes them; they are downloaded
again when needed. **Open logs folder** opens the folder with MeManga's log
files.

### Back up and restore your library

**Settings → Advanced → Import / Export** saves your library and its history
to a JSON file and reads it back.

| Button | What it does |
|---|---|
| Export | Writes your series and their history to a file. |
| Import (Merge) | Adds what is in the file to your current library. |
| Import (Replace) | Replaces your current library with the file. |

The command line reads and writes the same file with `memanga export` and
`memanga import`.

### Kindle delivery

Sending chapters to a Kindle is set up under **Settings → Kindle / Email**.
A page for it is still to come; until then the
[docs overview](../guide/) lists where to read about it.

## What is different in the development version

These are not in {{ release.tag }}:

- **Remove** on a series' page keeps your read progress and download history
  unless you choose **Also delete progress and history**. Downloaded files
  stay in your download folder either way.
- A chapter whose email to your Kindle failed says **Not sent to Kindle** on
  its row and can be sent again from there.
- Search can show why a source failed, with **Failure details**.
- The cover cache has a size limit that you can change.
- **Settings → About** can copy version details for a bug report.
