# Settings

<script setup>
import { release } from '../.vitepress/release'
</script>

This page covers the settings of the desktop app that you are most likely to
change. Open **Settings** in the sidebar of the app. Changes apply when you
choose **Save settings**, except the theme, which switches at once.

Unless a section says otherwise, everything here works the same in
{{ release.tag }} and in the development version.

## Theme

**Settings → General → Appearance** offers a dark and a light theme.

## Download folder and output format

**Settings → General** sets where chapters are saved and in which format.
Each series gets its own subfolder.

PDF and EPUB suit e-readers and can be sent to a Kindle. CBZ, ZIP and image
folders are kept on your computer only.

## Concurrent downloads

**Concurrent Downloads** sets how many chapters download at the same time,
from 1 to 8. A higher number is faster but makes it more likely that a
source limits you.

## File names

**File Naming** takes a template for the file name of each chapter. The
default is `{title} - Chapter {chapter}`. The variables are `{title}`,
`{chapter}`, `{source}` and `{date}`. A preview under the field shows the
name your template produces.

## Storage and cover cache

Covers are stored on disk so the Library opens quickly.
**Settings → Advanced → Clear cache** removes them; they are downloaded
again when needed. **Open logs folder** opens the folder with MeManga's log
files; [Troubleshooting](../guide/troubleshooting#log-files) says what is in
them.

## Back up and restore your library

**Settings → Advanced → Import / Export** saves your library to a JSON file
and reads it back: each series with the chapters downloaded and read and
where you stopped reading. Your settings and the app's history are not in
the file.

| Button | What it does |
|---|---|
| Export | Writes your series and their state to a file. |
| Import (Merge) | Adds what is in the file to your current library. |
| Import (Replace) | Replaces your current library with the file. |

The command line reads and writes the same file with `memanga export` and
`memanga import`. [Export and import](../reference/state#export-and-import)
describes the file and how a merge combines it with your library.

## Kindle delivery

Sending chapters to a Kindle is set up under **Settings → Kindle / Email**.
[Send chapters to a Kindle](../guide/kindle) explains it step by step.

## Network and privacy

**Settings → Advanced → Network & Privacy** turns the connection check, the
MangaDex cover search and the chapter counts in search on or off.
[Network connections](../reference/network) lists every connection the
app makes and what each setting changes.

## Reader and partial chapters

Two groups of settings are described where they are used:

- [Prefetch](./reader#prefetch-the-next-chapter) and
  [remove after reading](./reader#remove-chapters-after-reading), on the
  reader page.
- [Partial chapters](./library#partial-chapters), on the library page.

## What is different in the development version

These are not in {{ release.tag }}:

- The cover cache has a size limit that you can change.
- The **Network & Privacy** settings.
- **Settings → About** can copy version details for a bug report.
