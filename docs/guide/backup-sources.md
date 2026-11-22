# Use a backup source

<script setup>
import { release } from '../.vitepress/release'
</script>

A backup source is a second site with the same series. MeManga uses it in
two ways:

- for a new chapter that the main source does not have yet, after a waiting
  time you choose;
- for a chapter whose download from the main source fails, straight away.

## Choose a backup

- Pick the same series on another
  [supported source](../reference/sources).
- Prefer a source that numbers the chapters the same way as the main one.
  MeManga matches chapters on the two sources by their chapter label, such
  as `12` or `12.5`. A chapter labelled differently on the backup, such as
  `12.0`, counts as a different chapter.

## Add a backup

### In the desktop app

When you add a series, **Add backup source** is ticked. Paste the series
page of the backup into **Backup URL** and set **Fallback delay (days)**;
the default is 2.

To add or change the backup later, open the series, choose **Edit**, fill
in **Backup URL** and **Fallback delay (days)**, and choose
**Save Changes**. The form shows and keeps one backup source.

### On the command line

```sh
# Add a series with a backup and a delay of 2 days
memanga add --title "TITLE" --url MAIN_URL --backup BACKUP_URL --fallback-days 2

# Add or replace the backup of a tracked series
memanga edit "TITLE" --backup BACKUP_URL

# Change the delay
memanga edit "TITLE" --fallback-days 1
```

`memanga add -i` asks for a backup source and the delay as well.
`edit --backup` replaces the first backup and keeps any further ones. All
options are in the [command reference](../reference/cli#memanga-edit).

The command is called `memanga update` <Badge type="info" :text="`In ${release.tag}`" />
and takes only `--backup`, so on the command line the
delay is set when the series is added. `memanga add --backup` and
`--fallback-days` work as above, and the desktop app's **Edit** form changes
the delay in both versions.

## When MeManga uses the backup

### Chapters the main source does not have yet

Every check reads the chapter list of the main source and of each backup.

1. The first check that finds a new chapter only on a backup notes the
   time and does not download it, whatever the delay.
2. Once the delay has passed since then, counted in whole days, the next
   check treats the chapter as new and takes it from the backup. In
   [manual mode](../desktop/library#auto-and-manual-mode) it is listed, not
   downloaded.
3. If the main source shows the chapter before that, it comes from the
   main source and the wait ends.

A check with `--dry-run` shows what it would do, but does not start the
waiting time. While the main source cannot be reached, the waiting time
still applies to chapters found on the backup. When no source of a series
can be read, the check of that series fails.

### A download that fails

When a chapter cannot be downloaded from the main source, MeManga looks for
a chapter with the same label on the backup sources, in order, and
downloads it from the first that has it. There is no waiting time. If that
fails too and [partial chapters](../reference/config#partial-chapters) are
allowed, MeManga keeps a copy with a few missing pages when one is within
the allowed share; otherwise the chapter is recorded as
[failed](./cli#when-chapters-fail).

A backup source also helps with
[suspicious batches](../desktop/library#suspicious-batches): a sudden batch
of new chapters is not held back when the backup sources list at least half
of it.

## Remove a backup

- **Desktop app:** open the series, choose **Edit**, empty **Backup URL**
  and choose **Save Changes**.
- **Command line:** `memanga edit "TITLE" --no-backup` removes every backup
  source of the series and its delay.

Chapters already downloaded from the backup stay in your library.
