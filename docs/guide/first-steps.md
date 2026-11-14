# First steps

<script setup>
import { release } from '../.vitepress/release'
</script>

This page takes you from a fresh install to a working setup, without
downloading any chapters. If MeManga is not installed yet, start with
[Download and install](./install).

## Desktop app

1. Start MeManga. The first time, it asks to download the
   [browser components](./install#first-start-browser-components) it needs
   for some sources.
2. The window opens on **Library**, which is empty at first.
3. The sidebar has the main areas:

| Area | What it is for |
|---|---|
| Library | The series you follow |
| Downloads | Chapters being downloaded |
| Search | Find a series across the enabled sources |
| Notifications | Messages from MeManga |
| Sources | The sites MeManga can read |
| Settings | Download folder, output format, email delivery and more |

To follow a series, use **Add manga** in the Library, or find it with
**Search**.

These areas are the same in {{ release.tag }} and in the development version.

## Command line

<Badge type="warning" text="Development version" />

The commands in this section are for an
[install from source](./install#command-line-from-source). Several of them do
not exist in {{ release.tag }}.

### Check the installation

None of these commands downloads chapters.

| Command | What it does |
|---|---|
| `memanga --version` | Shows the installed version |
| `memanga setup` | Creates a missing config file and folders, and checks the browser components |
| `memanga doctor` | Runs local health checks |
| `memanga config path` | Shows where the config file is |
| `memanga status` | Shows the current status and configuration |
| `memanga sources` | Lists the sources MeManga knows |

`memanga doctor` exits with 0 when no check fails and 1 when one does, so a
script can test it.

### Follow a series

::: warning Replace the placeholders before running
`TITLE` and `URL` below are placeholders, not working values. Replace `TITLE`
with the name you want to give the series and `URL` with the address of its
page on a source that MeManga supports. `memanga sources` lists them.
:::

```sh
memanga add -t "TITLE" -u "URL"
```

To be asked for the details one at a time instead, run `memanga add -i` in a
terminal.

### See what a check would do

```sh
memanga check --dry-run
```

A dry run lists the chapters MeManga would download. It does not download
them and it does not change your library. It still connects to the source
sites to look for chapters, so it needs a network connection.

When you are ready to download, run `memanga check` without `--dry-run`.
What you download, and from where, is your decision and your
responsibility.

### Look at your library, or undo

List the series you follow:

```sh
memanga list
```

Stop following one. Replace `TITLE` with its name first:

```sh
memanga remove "TITLE"
```

`memanga remove` asks before it removes anything. It keeps downloaded files
unless you tell it otherwise.

### The interactive menu

Running `memanga` with no command opens a menu in the terminal. It needs a
real terminal, so use the commands above in scripts.

## Where things went

Your settings, library and downloads are in the folders listed under
[where MeManga keeps its files](./install#where-memanga-keeps-its-files).

## Next

More pages are on the way. Until then, the [docs overview](./) lists where
to read about everything else.
