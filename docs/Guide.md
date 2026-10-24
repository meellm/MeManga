# MeManga Setup & Usage Guide

Automatic manga downloader with desktop GUI + Kindle support. Track
manga from 224 scrapers / 319 domains, download chapters as
PDF / EPUB / CBZ / ZIP / JPG / PNG / WEBP, and optionally email
them to your Kindle.

> This guide covers the CLI flow only. For the desktop app, grab the
> latest build from the
> [GitHub releases page](https://github.com/meellm/MeManga/releases) —
> double-click on Windows/macOS, or on Linux extract the `.tar.gz` and
> run the binary. See the [README download section](../README.md#download)
> for the file to pick and how to launch it. Nothing to configure up front.

---

## Table of Contents

- [Setup — Windows](#setup--windows)
- [Setup — macOS](#setup--macos)
- [Setup — Linux](#setup--linux)
- [Setup — Docker](#setup--docker)
- [Your First Manga](#your-first-manga)
- [Checking for New Chapters](#checking-for-new-chapters)
- [Downloading From the Start](#downloading-from-the-start)
- [Downloading From a Specific Chapter](#downloading-from-a-specific-chapter)
- [Managing Status](#managing-status)
- [Marking Chapters Read](#marking-chapters-read)
- [Changing Output Format](#changing-output-format)
- [MangaDex Image Quality and Group Removal](#mangadex-image-quality-and-group-removal)
- [Post-Processing After Download](#post-processing-after-download)
- [Setting Up Kindle Email](#setting-up-kindle-email)
- [Backup Sources](#backup-sources)
- [Updating Manga Details](#updating-manga-details)
- [Scheduling Automatic Checks](#scheduling-automatic-checks)
- [Export and Import](#export-and-import)
- [All Commands Reference](#all-commands-reference)
- [Troubleshooting — Windows](#troubleshooting--windows)
- [Troubleshooting — macOS](#troubleshooting--macos)
- [Troubleshooting — Linux](#troubleshooting--linux)

---

## Setup — Windows

### Requirements

- Python 3.10+ — download from [python.org](https://www.python.org/downloads/)
  - During installation, **check "Add Python to PATH"**
- Git — download from [git-scm.com](https://git-scm.com/download/win)

### Installation

Open **Command Prompt** or **PowerShell** and run:

```
git clone https://github.com/meellm/MeManga.git
cd MeManga
python scripts\bootstrap.py
```

This creates a virtual environment, installs all dependencies, and downloads Chromium and Firefox browsers for Playwright scrapers.

If `python` isn't recognized, try `py` instead:
```
py scripts\bootstrap.py
```

Alternatively, use the provided batch script:
```
.\scripts\windows\setup.bat
```

### Verify Installation

```
.\scripts\windows\run.bat --help
```

You should see the help output with available commands.

### Running MeManga

From now on, launch MeManga with:

```
.\scripts\windows\run.bat
```

This opens the interactive TUI. For specific commands:

```
.\scripts\windows\run.bat list
.\scripts\windows\run.bat add -i
.\scripts\windows\run.bat check
```

Or run directly through the virtual environment:

```
venv\Scripts\python.exe -m memanga --help
```

### Where files are stored

```
%APPDATA%\memanga\config.yaml      # Configuration
%APPDATA%\memanga\state.json        # Download history
```

`%APPDATA%` is usually `C:\Users\YourName\AppData\Roaming`. Chapters
download to `Downloads\MeManga` in your user folder by default.

---

## Setup — macOS

### Requirements

- Python 3.10+
- Git (comes preinstalled on macOS)

Install Python via Homebrew:

```bash
brew install python3
```

Or download from [python.org](https://www.python.org/downloads/).

### Installation

Open **Terminal** and run:

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
python3 scripts/bootstrap.py
```

This creates a virtual environment, installs all dependencies, and downloads Chromium and Firefox browsers for Playwright scrapers.

### Verify Installation

```bash
./scripts/run.sh --help
```

### Running MeManga

From now on, launch MeManga with:

```bash
./scripts/run.sh
```

This opens the interactive TUI. For specific commands:

```bash
./scripts/run.sh list
./scripts/run.sh add -i
./scripts/run.sh check
```

Or run directly through the virtual environment:

```bash
./venv/bin/python -m memanga --help
```

### Where files are stored

```
~/Library/Application Support/memanga/config.yaml      # Configuration
~/Library/Application Support/memanga/state.json        # Download history
```

Chapters download to `~/Downloads/MeManga` by default.

---

## Setup — Linux

### Requirements

- Python 3.10+
- Git
- pip and venv

**Debian / Ubuntu / Raspberry Pi:**

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv python3-pip git
```

**Fedora:**

```bash
sudo dnf install python3 python3-pip git
```

**Arch:**

```bash
sudo pacman -S python python-pip git
```

### Installation

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
python3 scripts/bootstrap.py
```

This creates a virtual environment, installs all dependencies, downloads Chromium and Firefox browsers, and installs Playwright system dependencies. On Debian/Ubuntu it also installs `xvfb` for headless browser support on servers without a display.

For Debian/Ubuntu, there's also a dedicated script that handles everything:

```bash
./scripts/linux/setup.sh
```

### Verify Installation

```bash
./scripts/run.sh --help
```

### Running MeManga

From now on, launch MeManga with:

```bash
./scripts/run.sh
```

This opens the interactive TUI. For specific commands:

```bash
./scripts/run.sh list
./scripts/run.sh add -i
./scripts/run.sh check
```

Or run directly through the virtual environment:

```bash
./venv/bin/python -m memanga --help
```

### Where files are stored

```
~/.config/memanga/config.yaml      # Configuration
~/.config/memanga/state.json        # Download history
```

If `XDG_CONFIG_HOME` is set, the folder is `$XDG_CONFIG_HOME/memanga`
instead. Chapters download to `~/Downloads/MeManga` by default.

---

## Setup — Docker

Docker is the easiest option for headless servers, NAS boxes, Raspberry
Pi systems, and cron-style automation because the image includes the CLI
and Playwright Firefox runtime without requiring a local Python install.
The Docker image does **not** include PySide6 or any other GUI runtime.

### Requirements

- Docker
- Docker Compose v2 if you want to use `compose.yaml`

### Build and run

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
docker build -t memanga:cli .
docker run --rm memanga:cli --help
```

Official release images are published to Docker Hub and GitHub Container
Registry when a release tag is pushed:

```bash
docker pull meellm/memanga:latest
docker run --rm meellm/memanga:latest --help

docker pull ghcr.io/meellm/memanga:latest
docker run --rm ghcr.io/meellm/memanga:latest --help
```

Stable releases are published to both registries with `X.Y.Z`, `X.Y`,
and `latest` tags; pin to a specific `X.Y.Z` tag for reproducible runs.
Use a local `docker build` when testing unreleased code from the
repository.

### Persist config, state, and downloads

MeManga stores config and state under
`/home/memanga/.config/memanga` in the container. Downloads use the
default path `/home/memanga/Downloads/MeManga`.

```bash
mkdir -p memanga-data/config memanga-data/downloads

docker run --rm \
  -v "$PWD/memanga-data/config:/home/memanga/.config/memanga" \
  -v "$PWD/memanga-data/downloads:/home/memanga/Downloads/MeManga" \
  memanga:cli status
```

> The container runs as a non-root user with UID 1000. With host bind
> mounts like the ones above, the mounted directories must be writable by
> UID 1000 or downloads and config saves will fail with permission
> errors. This works automatically when your host user is UID 1000 (the
> default first user on most Linux and Raspberry Pi systems); otherwise
> run `sudo chown -R 1000:1000 memanga-data`. The Compose setup below
> uses named volumes and avoids the issue entirely.

### Compose

The included `compose.yaml` keeps config/state and downloads in named
volumes:

```bash
docker compose build
docker compose run --rm memanga list
docker compose run --rm memanga check --auto
docker compose run --rm memanga config
```

For daily checks, add a host cron entry from the repository directory:

```cron
0 6 * * * cd /path/to/MeManga && docker compose run --rm memanga check --auto --quiet >> memanga-docker.log 2>&1
```

### Kindle delivery

Run `docker compose run --rm memanga config`, choose email delivery,
enter the Kindle/Gmail settings, and choose which manga to send. Containers usually do not have a desktop
keyring, so a password entered there is stored in plain text in the
config volume (MeManga prints a warning with the file path); keep that
volume private.

To keep the password out of the config volume, pass it in instead:
point `MEMANGA_SMTP_PASSWORD_FILE` at a file holding it (for example a
Docker secret, mounted under `/run/secrets/`), or set
`MEMANGA_SMTP_PASSWORD`. A password passed this way is never saved and
is used instead of a stored one.

---

## Your First Manga

> In all examples below, `run` means the launcher for your platform:
> - **Windows:** `.\scripts\windows\run.bat`
> - **macOS / Linux:** `./scripts/run.sh`

### Interactive mode (recommended)

```bash
run add -i
```

MeManga will prompt you step by step:

```
➕ Add New Manga

N supported sources; run `memanga sources` to see them.

📖 Manga title: One Piece
🔗 Primary source URL: https://tcbonepiecechapters.com/mangas/5/one-piece
Add a backup source? [y/n]: n

✅ Added: One Piece (tcbonepiecechapters.com)
```

### Direct mode

Add a manga in one command without prompts:

```bash
run add -t "One Piece" -u "https://tcbonepiecechapters.com/mangas/5/one-piece"
```

Add with a backup source:

```bash
run add -t "Solo Leveling" -u "https://mangafire.to/manga/solo-leveling.xxx" -b "https://mangadex.org/title/uuid-here"
```

Set the per-manga fields the desktop app manages while adding:

```bash
run add -t "Blue Lock" -u "https://mangadex.org/title/uuid-here" --status on-hold --mode manual --no-kindle
```

| Flag | Values | Default when omitted |
|------|--------|----------------------|
| `--status` | `reading`, `on-hold`, `dropped`, `completed` | `reading` |
| `--mode` | `auto`, `manual` | `auto` |
| `--kindle` / `--no-kindle` | per-manga Kindle toggle on or off | follows `email.kindle_scope` |

`--kindle` and `--no-kindle` cannot be combined. Without either, the manga
follows the choice of which manga to send (`email.kindle_scope`, see
[Choose which manga are sent](#choose-which-manga-are-sent)). `--mode` and the Kindle
toggle are the same per-manga settings shown on the desktop app's manga page,
and the command line honors them the same way (the Kindle toggle only matters
when email delivery is enabled). A `manual` manga is checked and its new
chapters are listed, but a `check` of every manga that doesn't ask per
chapter (`--download`, cron's `check --auto --quiet`) never downloads them;
`check "Title" --download` or answering the per-chapter question does. With
the Kindle toggle off, chapters are saved but never emailed, by `check`,
`failed retry` or `send --pending`. Omitted flags are not written to `config.yaml`, so the defaults
above apply. Invalid values are rejected before any config is saved. These
flags also work with `add -i`, which does not ask for them. Output format
stays global (`config`, or `check --format`); there is no per-manga format.

If a URL's site is not recognized, `add` warns and points you to
`run sources` for the list of supported sites.

### View your tracked manga

```bash
run list
```

Output:

```
┌───┬───────────────┬─────────┬────────────────────────────┬──────────┬────────────┬────────┐
│ # │ Title         │ Status  │ Source                     │ Last Ch. │ Downloaded │  Mode  │
│   │               │         │                            │          │            │ Kindle │
├───┼───────────────┼─────────┼────────────────────────────┼──────────┼────────────┼────────┤
│ 1 │ One Piece     │ reading │ tcbonepiecechapters.com    │ —        │ 0          │  auto  │
│   │               │         │                            │          │            │   on   │
├───┼───────────────┼─────────┼────────────────────────────┼──────────┼────────────┼────────┤
│ 2 │ Solo Leveling │ reading │ mangafire.to (+1)          │ —        │ 0          │  auto  │
│   │               │         │                            │          │            │   on   │
└───┴───────────────┴─────────┴────────────────────────────┴──────────┴────────────┴────────┘
```

### Remove a manga

By title:

```bash
run remove "One Piece"
```

By list number (quote it, since `#` starts a shell comment):

```bash
run remove "#1"
```

A title that matches more than one manga is refused and the matches are
listed, so use the full title.

Removing only stops tracking: download history and downloaded files are
kept unless you ask for more.

| Option | Effect |
|---|---|
| `-y`, `--yes` | Skip the removal confirmation. It never purges history or deletes files. |
| `--purge-history` | Also remove its download history. `--purge` is an older alias. |
| `--keep-files` | Keep its downloaded files (the default). |
| `--delete-files` | Also delete its download folder, `<download dir>/<title>`. |

`--keep-files` and `--delete-files` can't be combined. Without `--yes`, a
terminal session asks whether to remove the manga, then whether to remove
its history and its files (both default to no); the flags answer those
questions up front. Without a terminal (cron, scripts) nothing is asked,
so `--yes` is required:

```bash
run remove "One Piece" --yes --purge-history --delete-files
```

`--delete-files` only deletes that manga's own folder inside the download
directory. It refuses, before changing anything, if that folder is a
symlink or another tracked manga uses the same folder. Files saved at the
top of the download directory by old versions are left alone.

---

## Checking for New Chapters

### Using the menu (easiest)

Run `run` and select option **[4] Check Now**. The menu walks you through everything:

```
📚 Tracked Manga
┌───┬───────────────┬─────────┬────────────────────────────┐
│ # │ Title         │ Status  │ Source                     │
├───┼───────────────┼─────────┼────────────────────────────┤
│ 1 │ One Piece     │ reading │ tcbonepiecechapters.com    │
│ 2 │ Solo Leveling │ reading │ mangafire.to (+1)          │
└───┴───────────────┴─────────┴────────────────────────────┘

Check which manga? (a=all, or enter #N / title) [a]: a
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number):
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

That's it — MeManga checks all your manga and downloads new chapters automatically.

### Using CLI commands

These are the command-line equivalents if you prefer typing commands directly in your terminal (not inside the menu):

```bash
run check                            # Interactive — asks y/n per chapter
run check --download                 # Download all new chapters without asking
run check "One Piece"                # Check one specific manga
run check "One Piece" --download     # Download new chapters for one manga
run check --dry-run                  # Check only: list what's new, change nothing
run check --auto --quiet             # What scheduled checks run (never prompts)
```

The manga is a title or `#N` from `run list`. The older `-t "One Piece"`
(`--title`) form still works and means the same.

### Check modes

`check` runs in one of three modes:

| Mode | How to pick it | What happens |
|------|----------------|--------------|
| Check only | `--dry-run` (`-n`) | Lists the chapters a download run would fetch, with the same backup-delay and suspicious-batch rules. Nothing is downloaded, emailed or post-processed, and nothing is saved: no check history or last-check time, no backup-delay clock, no suspicious-batch record or notification, and a held batch stays held. `--dry-run` wins over `--download` and its aliases. |
| Download | `--download` (aliases `-a`/`--auto` and `-y`/`--yes`) | Downloads every new chapter without asking. Without a manga name, `manual`-mode manga are only listed, like in the desktop app. |
| Ask | neither flag | On a terminal, asks once per chapter. Without a terminal (cron, pipes, CI), or with `--quiet`, it downloads nothing and exits `1` with a hint. |

`--auto` and `--yes` keep working and are not deprecated; existing cron
lines such as `check --auto --quiet` behave as before. `--quiet` only
means "never prompt"; it doesn't give permission to download and doesn't
shorten the output. `--all` and `--from N` choose where to start
(`--all` is `--from 0`); they don't download anything without
`--download`, and they skip the suspicious-batch check, so preview them
with `--dry-run` first.

A suspicious batch (a sudden jump in chapter numbers that no backup
source confirms) is withheld, and the run still exits `0` with a warning
on stderr. Run `check --download --force-suspicious` to accept it. With
`--dry-run --force-suspicious` the preview shows what accepting it would
download, but the batch stays held.

---

## Downloading From the Start

### Using the menu (easiest)

Run `run`, select **[4] Check Now**, then:

```
Check which manga? (a=all, or enter #N / title) [a]: #1
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number): 1
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

That's all you need. MeManga downloads every chapter from chapter 1 onward. Safe mode (browser restarts every 3 chapters to save memory) is enabled automatically when you type a starting chapter.

### Using CLI commands

The command-line equivalent, typed directly in your terminal (not inside the menu):

```bash
run check "One Piece" --from 1 --download --safe
```

**What each flag does:**

| Flag | Purpose |
|------|---------|
| `"One Piece"` | Target a specific manga (`-t "One Piece"` also works) |
| `--from 1` | Start from chapter 1 instead of where you left off |
| `--download` | Download without prompting for each chapter (`--auto` and `--yes` are aliases) |
| `--safe` | Restart the browser every 3 chapters to prevent memory buildup |

The `--safe` flag is important for bulk downloads — without it, the browser can consume too much memory after many chapters.

---

## Downloading From a Specific Chapter

### Using the menu (easiest)

Run `run`, select **[4] Check Now**, then:

```
Check which manga? (a=all, or enter #N / title) [a]: One Piece
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number): 50
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

This downloads chapter 50, 51, 52, etc. Chapters you already have are automatically skipped. Safe mode is enabled automatically.

### Using CLI commands

```bash
run check "One Piece" --from 50 --download --safe
```

Start from chapter 100 in EPUB format:

```bash
run check "One Piece" --from 100 --download --safe --format epub
```

Start from a decimal chapter:

```bash
run check "One Piece" --from 55.5 --download
```

---

## Managing Status

Each manga has a status that controls whether it gets checked during `run check`:

| Status | Checked? | Use case |
|--------|----------|----------|
| `reading` | Yes | Currently following this manga |
| `on-hold` | No | Paused, will resume later |
| `dropped` | No | Stopped reading |
| `completed` | No | Manga is finished, no more chapters expected |

New manga default to `reading`; pass `add --status` to start with another
status.

### Set a manga to on-hold

```bash
run edit "One Piece" --status on-hold
```

Output:

```
Updated One Piece:
  Status → on-hold
```

### Mark as completed

```bash
run edit "Solo Leveling" --status completed
```

### Resume reading

```bash
run edit "One Piece" --status reading
```

### Set by list number

```bash
run edit "#1" --status on-hold
```

You can also use partial title matching — `run edit "Solo" --status completed` will match "Solo Leveling" if no other title contains "Solo".

`run set "Title" STATUS` still works for now but is deprecated: it prints
the matching `edit` command on stderr and will be removed in the next
release.

---

## Marking Chapters Read

The desktop reader marks a chapter read when you reach its end. `read` and
`unread` change the same read state from the command line, so the Library
("X/N read") and the chapter list show it too.

```bash
run read "One Piece" 1 2 3      # mark chapters read
run read "One Piece" --all      # mark every downloaded chapter read
run unread "One Piece" 3        # mark a chapter unread again
run unread "One Piece" --all    # mark the whole manga unread
```

The manga is a title or `#N` from `run list`, matched like `edit`. Each
chapter must be in the manga's chapter list in the desktop app: downloaded,
found by `check`, or marked read elsewhere. `5`, `05` and `5.0` all name the
chapter stored as `5`; labels such as `Extra` must be typed as shown. If any
chapter is not found, nothing is changed and the command exits `1`. Chapters
that are already read (or unread) are reported and left as they are.

Marking a chapter read also resets its saved page, as finishing it in the
reader does. Downloaded files, download history and "Continue Reading" are
never changed. Close the desktop app before using these commands: while it
is open it keeps its own copy of the read state and can overwrite the change.

---

## Changing Output Format

MeManga supports seven formats:

| Format | Output | Best for |
|--------|--------|----------|
| **PDF** | `.pdf` file | Kindle, general reading. Auto-splits large files for email. |
| **EPUB** | `.epub` file | Kindle, e-readers. Fixed-layout with cover art. |
| **CBZ** | `.cbz` file | Comic book readers (CDisplayEx, YACReader, Tachiyomi). |
| **ZIP** | `.zip` file | Same as CBZ but with standard .zip extension. Works with any archive tool. |
| **JPG** | folder of `.jpg` | Local viewing. One folder per chapter with JPEG images. |
| **PNG** | folder of `.png` | Local viewing. Lossless quality, larger file sizes. |
| **WEBP** | folder of `.webp` | Local viewing. Modern format, smaller than JPEG at similar quality. |

Image formats (JPG/PNG/WEBP) save chapters as folders: `downloads/Manga Title/Chapter 001/000.jpg, 001.jpg, ...`

EPUB and CBZ files record the language of the pages, and CBZ files mark
right-to-left manga for comic readers, only when MeManga knows them: from
a source that serves one language or only right-to-left titles, or from
the manga entry in `config.yaml`:

```yaml
manga:
  - title: "Berserk"
    language: en               # BCP 47 tag of the translation
    reading_direction: rtl     # rtl, ltr or vertical
```

Otherwise CBZ files carry no language or reading direction, and EPUB
files use the language `und` (undetermined).

### Change the default format

Run the config wizard:

```bash
run config
```

Select from the numbered menu (1-7).

Or edit `~/.config/memanga/config.yaml` directly:

```yaml
delivery:
  output_format: epub   # Change from "pdf" to "epub" or "cbz"
```

### Override format for a single check

When using the menu (**[4] Check Now**), you'll be asked:

```
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp): epub
```

Or from the command line:

```bash
run check --format epub
```

Download one manga in CBZ:

```bash
run check "One Piece" --format cbz --download
```

---

## MangaDex Image Quality and Group Removal

MangaDex chapters use original-quality images by default. To download smaller
images for an e-reader, run `run config --mangadex-quality data-saver`, or
choose **Settings → General → MangaDex Image Quality** in the desktop app.
Use `run config --mangadex-quality original` to restore the default. Existing
files do not change.

The built-in reader displays MangaDex and the scanlation group credited by
MangaDex. Saved chapters also carry that credit in their metadata, or in
`Source.txt` for ZIP, CBZ and image folders.

Group leaders who want their chapters removed can open an issue with the
group's MangaDex link. Accepted group IDs are added to a future release; none
are built in yet. To block a group yourself,
copy the UUID from its MangaDex group page and run
`run config --mangadex-remove-group GROUP_ID`. Checks, downloads and the
built-in reader then skip that group's chapters. Delete chapters already
downloaded from it, including e-reader copies; MeManga does not delete saved
files. Restart the desktop app after changing this setting
from the CLI. Blocked IDs appear in `run config --show`.

---

## Post-Processing After Download

MeManga can run a command of your choice after each chapter's output
file (or image folder) is created - for converting, compressing, copying to an
archive, or triggering another tool.

Post-processing is **disabled by default**.

> ⚠️ The command runs on your machine. Only enable commands you trust and
> understand.

### Enable it

In the desktop app, open **Settings -> Advanced -> Post-Processing**, enable
the command, then save settings.

In the CLI, run the config wizard and answer the post-processing prompts:

```bash
run config
```

Or edit `~/.config/memanga/config.yaml` directly:

```yaml
delivery:
  post_processing:
    enabled: true
    command: 'cp -R {output_path} /mnt/archive/'
    fail_on_error: false
```

### Available values

Each value is available both as a `{placeholder}` in the command string and as
an environment variable:

| Placeholder | Environment variable | Meaning |
|-------------|----------------------|---------|
| `{output_path}` | `MEMANGA_OUTPUT_PATH` | Final file or folder path |
| `{title}` | `MEMANGA_MANGA_TITLE` | Manga title |
| `{chapter}` | `MEMANGA_CHAPTER` | Chapter number |
| `{source}` | `MEMANGA_SOURCE` | Source the chapter came from |
| `{format}` | `MEMANGA_OUTPUT_FORMAT` | Output format (`pdf`, `cbz`, `jpg`, …) |
| `{is_dir}` | `MEMANGA_IS_DIR` | `1` if the output is a folder (image formats), else `0` |

The hook receives the final output path whether it is an archive/document file
(`pdf`, `epub`, `cbz`, `zip`) or an image folder (`jpg`, `png`, `webp`).
The command is split into arguments and run directly, without a shell.
Placeholder values are substituted after splitting, so manga metadata cannot
become shell syntax. For shell features like pipes, redirects, or globbing,
invoke a shell explicitly and prefer the `MEMANGA_*` environment variables.

### Failure behavior

- `fail_on_error: false` (default) - a failed command prints a warning but the
  chapter is still recorded as downloaded.
- `fail_on_error: true` - a failed command marks the chapter as failed, so it
  shows up under `run failed` for retry. During CLI checks, backup-source
  handling applies the same way it does for other download failures.

A command is considered failed if it exits non-zero, times out (10 minute
limit), or can't be launched.

### Examples

Copy every download into an archive directory:

```yaml
command: 'cp -R {output_path} /mnt/archive/'
```

Optimize a CBZ/ZIP or run a script with the passed environment variables:

```yaml
command: '/home/me/scripts/process-chapter.sh'
```

```bash
#!/usr/bin/env bash
# process-chapter.sh
echo "Finished $MEMANGA_MANGA_TITLE chapter $MEMANGA_CHAPTER ($MEMANGA_OUTPUT_FORMAT)"
if [ "$MEMANGA_IS_DIR" = "1" ]; then
  # image-folder output, e.g. compress each image
  find "$MEMANGA_OUTPUT_PATH" -name '*.png' -print
fi
```

---

## Setting Up Kindle Email

MeManga can send downloaded chapters directly to your Kindle device via email.

### Step 1 — Get a Gmail App Password

1. Go to your Google Account and enable **2-Factor Authentication**
2. Go to [App Passwords](https://support.google.com/accounts/answer/185833)
3. Generate a new app password for "Mail"
4. Copy the 16-character password (looks like `abcd efgh ijkl mnop`)

### Step 2 — Add your Gmail to Amazon's approved list

1. Go to [Amazon Kindle Settings](https://www.amazon.com/hz/mycd/myx#/home/settings/payment)
2. Find **"Personal Document Settings"**
3. Under **"Approved Personal Document E-mail List"**, add your Gmail address

### Step 3 — Configure MeManga

```bash
run config
```

The wizard will prompt you:

```
Delivery mode (local/email): email
Kindle email: yourname@kindle.com
Sender email: youremail@gmail.com
App password: abcdefghijklmnop
Send which manga: 1 (selected) or 2 (all)

✅ Configuration saved!
```

#### Choose which manga are sent

When you turn email delivery on, MeManga asks which manga to send
(`email.kindle_scope`):

| Choice | Value | Sent |
|--------|-------|------|
| Only manga I choose | `selected` | manga with the Kindle toggle on (`update TITLE --kindle`, or **Send to Kindle after download** on the manga's page) |
| Every manga | `all` | every manga except those with the Kindle toggle off |

A manga you already turned on or off for Kindle keeps that choice either
way. Turning email delivery on proposes `selected`, so it never starts
sending the whole library unasked; `run config set delivery.mode email`
and switching from local to email in `run config edit` cannot ask, so they
choose `selected` when no choice was made yet and say so. A backup import
never changes the delivery mode or this choice. A config that used email
delivery before this choice existed and has none keeps sending every
manga, as before. Change it later in
**Settings → General → Send to Kindle**, by running `run config` again, or
with `run config set email.kindle_scope all` (or `selected`). `run config
email` shows the current choice.

The app password is stored in your system keyring when available. If the keyring isn't available, it is stored in plain text in the config file instead, and MeManga warns you with the file's path. Keep that file private (on Linux and macOS, readable only by you). On servers and in containers you can set `MEMANGA_SMTP_PASSWORD_FILE` (a file holding the password) or `MEMANGA_SMTP_PASSWORD` instead; a password passed this way is never saved.

Each step of talking to the SMTP server (connecting, logging in, sending, logging out) waits at most 60 seconds, so an unreachable or stalled server ends with a timeout error instead of hanging `check`. Change the limit with `memanga config set email.smtp_timeout SECONDS` (1 to 600).

#### Other mail providers and encryption

The steps above use Gmail, but any provider that lets you send with SMTP and a password (usually an app password) works. Set the server and port with `memanga config set email.smtp_server HOST` and `memanga config set email.smtp_port PORT`, or in **Settings → Kindle / Email** in the desktop app, and use your provider's address as the sender.

The connection to the mail server is always encrypted. `email.smtp_tls` says how:

| Value | What MeManga does | Usual port |
|---|---|---|
| `auto` (default) | Implicit TLS on port 465, STARTTLS on any other port | — |
| `starttls` | Connects, then switches to TLS with STARTTLS before logging in | 587 |
| `implicit` | Starts TLS as soon as it connects (providers often call this "SSL/TLS") | 465 |

Both modes check the server's certificate and host name and need TLS 1.2 or later. There is no unencrypted mode: a server that doesn't offer STARTTLS is reported as an error, and the password is never sent in plain text. With the standard ports `auto` is right. Set the value yourself only when your provider uses implicit TLS on a port other than 465, for example `memanga config set email.smtp_tls implicit`. The desktop app has no control for it, but its **Check Login** and **Send Test PDF** use the setting, and with `auto` the port you type. `memanga config email` shows what will be used.

Settings published by the providers as of October 2026 (they change, so check the linked page if a login fails):

| Provider | Server | Port and encryption | Password |
|---|---|---|---|
| [Gmail / Google Workspace](https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app) | `smtp.gmail.com` | 587 (STARTTLS) or 465 (implicit TLS) | [App password](https://support.google.com/accounts/answer/185833); needs 2-Step Verification |
| [iCloud Mail](https://support.apple.com/en-ie/102525) | `smtp.mail.me.com` | 587 (STARTTLS) | App-specific password; use your full iCloud address as the sender |
| [Fastmail](https://www.fastmail.help/hc/en-us/articles/1500000279921-IMAP-POP-and-SMTP) | `smtp.fastmail.com` | 465 (implicit TLS) or 587 (STARTTLS) | App password; your normal password doesn't work |
| [Microsoft 365](https://learn.microsoft.com/en-us/exchange/mail-flow-best-practices/how-to-set-up-a-multifunction-device-or-application-to-send-email-using-microsoft-365-or-office-365) (work or school) | `smtp.office365.com` | 587 (STARTTLS) only | Mailbox password, only if your administrator allows it (see below) |
| [Outlook.com](https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com) (Outlook, Hotmail, Live) | `smtp-mail.outlook.com` | 587 (STARTTLS) | Not supported (see below) |

Microsoft accounts are a special case:

- **Outlook.com** personal accounts require sign-in with OAuth2 ("Modern Auth"), according to Microsoft. MeManga logs in only with a password, so these accounts are expected to fail with an authentication error even when the server and port are right. Use a sender address at another provider.
- **Microsoft 365** work or school accounts can send with a password only when SMTP AUTH is turned on for the mailbox. It is off by default for organizations created after January 2020, and it doesn't work with Microsoft Entra ID security defaults. Microsoft has also scheduled the end of password (Basic) sign-in for SMTP AUTH and recommends OAuth, so this may stop working; ask your administrator. Port 465 isn't supported; use 587.

For another provider or your own server, use the server and port it publishes. "SSL/TLS" or port 465 means implicit TLS, and "STARTTLS" or port 587 means STARTTLS. Port 25 is meant for mail servers relaying to each other and is often blocked by internet providers. [RFC 8314](https://www.rfc-editor.org/rfc/rfc8314) recommends implicit TLS on port 465 for sending mail, with STARTTLS on 587 still widely used; both are equally safe here.

If the encryption doesn't match the port, the login fails. On ports 25, 465 and 587 the error then says which setting to change. STARTTLS on an implicit TLS port usually ends in a timeout, because the server waits for TLS while MeManga waits for the server's greeting. Implicit TLS on a STARTTLS port usually fails at once with an SSL error such as "wrong version number".

#### Email size limit

Mail providers limit how large an email or its attachments may be, and attachments grow by about a third when they are encoded for email. `email.max_email_mb` is the email size MeManga keeps under (25 by default, a conservative choice). MeManga sends a file only when it is at most 72% of that (files up to 18 MB by default). Larger PDFs are split into parts of that size. A PDF that still has a part over the limit, such as a single very large page, is refused, and so are larger EPUB files, because they can't be split. Change it with `memanga config set email.max_email_mb MB` (10 to 50). `memanga config email` shows the current limit.

In this setting 1 MB is 1,048,576 bytes. Providers usually don't say whether their "MB" means that or 1,000,000 bytes, or whether they measure the encoded email or the original attachments. To stay safe, set a value a little below the published number, for example 19 for a provider that states 20 MB, and lower it further if the provider still rejects large emails. No value can guarantee that a provider accepts an email when it doesn't say how it measures.

Published limits as of October 2026 (they change, and work or school accounts may be set differently by their administrator):

| Sender | Published limit | Suggested setting |
|---|---|---|
| [Gmail](https://support.google.com/mail/answer/6584) | 25 MB in total for attachments | 25 (default) |
| [Outlook.com](https://support.microsoft.com/topic/8c698842-b462-4a4c-8d53-5c5dd04f77ef) | 20 MB email, attachments included | 19 |
| [iCloud Mail](https://support.apple.com/en-us/102198) | 20 MB per message (Mail Drop links don't apply to SMTP) | 19 |
| [Fastmail](https://www.fastmail.help/hc/en-us/articles/1500000277382) | 70 MB email, about 50 MB attachment | 50 |

Send to Kindle has its own limit on what it accepts by email. Amazon's help says to send [a total size of 50 MB or less](https://www.amazon.com/gp/help/customer/display.html?nodeId=G7NECT4B4ZWHQ8WV) per email, without saying whether that counts the files or the encoded email; the setting stops at 50 for that reason. The smaller of your provider's limit and Amazon's applies.

### Step 4 — Test it

Send a one-page test PDF to your Kindle first:

```bash
run config email --send-test
```

`--test` instead only logs in to the SMTP server and sends nothing. In the desktop app, use **Send Test PDF** (or **Check Login**) in **Settings → Kindle / Email**. When the mail server accepts the test PDF, Amazon still delivers it only if the sender address is on your Approved Personal Document E-mail List. Look for "MeManga test document" in your Kindle library after a few minutes. If Amazon rejects it, it usually emails the sender address.

Then check for real chapters:

```bash
run check --download
```

When a new chapter is found and downloaded, MeManga sends it to your Kindle automatically. If the PDF is too large for one email (see [Email size limit](#email-size-limit)), it's automatically split into smaller parts.

If sending fails, the chapter stays downloaded, its file is kept and it is listed as not sent to Kindle until it is: run `run send --pending` to send it again (`--list` only lists, `--clear` forgets the records), or use **Send** next to the chapter in the desktop app's chapter list.

To send a chapter you already have again, for example after a reset of the Kindle, run `run send "Title" 12` (several chapters at once ask first; `--yes` skips that, `--dry-run` only shows which file each chapter would send). It uses the saved file in the manga's download folder and never downloads anything.

A split PDF is sent part by part over one mail session, stopping at the first part that fails. The error names that part and the parts the mail server already accepted; a retry of the unchanged file to the same Kindle address sends only the remaining parts; otherwise every part is sent again. "Accepted" means your mail server took the email, not that the Kindle has it yet.

### Switch back to local downloads

```bash
run config
```

Set delivery mode to `local`. Downloaded chapters will be saved to the download folder from Settings (`~/Downloads/MeManga` by default).

### Note on formats and email

- **PDF:** Auto-splits if too large for one email (over 18MB by default; see [Email size limit](#email-size-limit)). Best choice for email delivery.
- **EPUB:** Sent as-is. Kindle supports EPUB natively. Cannot be split — if over the same limit, switch to PDF.
- **CBZ:** Kindle does not support CBZ, so it is never emailed: the chapter is saved but not sent. Use PDF or EPUB for email delivery.
- **ZIP:** Kindle does not support ZIP either; saved but not sent, like CBZ.
- **JPG/PNG/WEBP:** Cannot be emailed (saved as image folders). Use PDF or EPUB for email delivery.

With email delivery on and one of these formats chosen, `memanga check`
warns before downloading, and `memanga doctor` reports a warning.

---

## Backup Sources

Configure a primary and backup source for each manga. If the primary doesn't have a new chapter, MeManga checks the backup. To avoid getting lower-quality early scans, there's a configurable delay.

### Add a manga with backup (interactive)

```bash
run add -i
```

```
📖 Manga title: Jujutsu Kaisen
🔗 Primary source URL: https://tcbonepiecechapters.com/mangas/13/jjk
Add a backup source? [y/n]: y
🔗 Backup source URL: https://mangadex.org/title/some-uuid
⏱️  Fallback delay (days): 3

✅ Added: Jujutsu Kaisen
   Primary: tcbonepiecechapters.com
   Backup: mangadex.org (after 3 days)
```

### Add with backup (direct)

```bash
run add -t "Jujutsu Kaisen" -u "https://tcbonepiecechapters.com/mangas/13/jjk" -b "https://mangadex.org/title/some-uuid" --fallback-days 3
```

`--fallback-days` accepts whole numbers of days, 0 or greater (default: 2).
Use `--fallback-days 0` to use the backup immediately. Negative values and
non-integers are rejected before any config is saved. It needs `--backup`
in the same command; without a backup source the command fails instead of
ignoring the delay.

### How fallback works

1. MeManga checks the primary source first
2. If only the backup has a new chapter, it starts a timer
3. After `fallback_delay_days` (default: 2), it downloads from the backup
4. If the primary catches up during the wait, it downloads from primary instead

### Config format

```yaml
manga:
  - title: "Jujutsu Kaisen"
    fallback_delay_days: 3
    sources:
      - url: "https://tcbonepiecechapters.com/mangas/13/jjk"
      - url: "https://mangadex.org/title/some-uuid"
```

---

## Updating Manga Details

Change the sources, title, or per-manga settings of a tracked manga.
`update` is an alias for `edit`. Only the fields you pass change; everything
else is kept.

### Change the primary URL

```bash
run edit "One Piece" -u "https://new-source.com/one-piece"
```

### Add or change backup URL

```bash
run edit "One Piece" -b "https://mangadex.org/title/uuid-here"
```

### Rename a manga

```bash
run edit "One Piece" -t "One Piece (Colored)"
```

### Remove the backup source

```bash
run edit "One Piece" --no-backup
```

This removes every backup source and the fallback delay, like clearing the
backup field in the desktop app. `--backup ""` is rejected instead of
silently removing it.

### Change the fallback delay

```bash
run edit "One Piece" --fallback-days 0
run edit "One Piece" -b "https://mangadex.org/title/uuid-here" --fallback-days 3
```

`--fallback-days` takes whole numbers of days, 0 or greater. It needs a
backup source: the manga must already have one, or you add it with `--backup`
in the same command. It cannot be combined with `--no-backup`.

### Change status, mode, or the Kindle toggle

```bash
run edit "One Piece" --status on-hold --mode manual --no-kindle
```

| Flag | Values |
|------|--------|
| `--status` | `reading`, `on-hold`, `dropped`, `completed` |
| `--mode` | `auto`, `manual` |
| `--kindle` / `--no-kindle` | per-manga Kindle toggle on or off |

These are the same per-manga settings `add` accepts (see above), with the
same effect of `--mode` and the Kindle toggle. Output format
stays global (`config`, or `check --format`); there is no per-manga format.

### Combining changes

Flags can be combined in one command. Every value is checked before anything
is saved, so an invalid URL, an empty title, a title that another manga
already uses, or a conflicting combination (`--backup` with `--no-backup`,
`--kindle` with `--no-kindle`, `--fallback-days` with `--no-backup` or
without a backup) leaves `config.yaml` untouched. If every given value already
matches, nothing is written.

### You can also update by list number

```bash
run edit "#1" -u "https://new-source.com/one-piece"
```

---

## Scheduling Automatic Checks

### Windows — Task Scheduler

Install a daily scheduled task:

```
.\scripts\windows\run.bat cron install
```

You'll be asked what time to run (default: 06:00):

```
Check time (HH:MM): 07:30
✅ Scheduled task installed! Will check daily at 07:30
```

Check if it's active:

```
.\scripts\windows\run.bat cron status
```

Remove it:

```
.\scripts\windows\run.bat cron remove
```

The task is named `MeManga_AutoCheck` and can also be seen in Windows Task Scheduler (`taskschd.msc`).

### macOS — Cron

Install a daily cron job:

```bash
./scripts/run.sh cron install
```

With a custom time:

```bash
./scripts/run.sh cron install --time 07:30
```

Check status:

```bash
./scripts/run.sh cron status
```

Remove:

```bash
./scripts/run.sh cron remove
```

Output is logged to `memanga.log` in the MeManga config directory (the platform folder listed in [Where your data lives](../README.md#where-your-data-lives) by default, or the directory passed with `--config-dir`). Each run prints one summary line, and its warnings and errors (a source that failed or fell back to a backup, a partial or failed chapter) are logged with a timestamp and level (see [Output and logging](#output-and-logging)).

### Linux — Cron

Same commands as macOS:

```bash
./scripts/run.sh cron install
./scripts/run.sh cron install --time 07:30
./scripts/run.sh cron status
./scripts/run.sh cron remove
```

On headless servers (no display), make sure `xvfb` is installed — the setup script handles this on Debian/Ubuntu.

### One MeManga at a time

Only one MeManga process changes a config directory at a time: a check,
any other command that changes your library or settings, or the desktop
app (for as long as its window is open). They hold a lock on the
directory (`memanga.lock` next to `state.json`). A second one exits `1`
with this message on stderr and changes nothing:

```
error: another MeManga process is using ~/.config/memanga (a running check, the desktop app or another command).
```

A scheduled check that runs while the desktop app is open or another
check is still running is skipped this way, and the next run picks up
where it left off. Read-only commands (`list`, `status`, `path`, `open`,
`sources`, `export`, `doctor`, `failed` without `retry`/`clear`,
`config show`/`get`/`path`, `cron status` and `search --json` without
`--add`) still run. A read-only command never repairs a damaged
`state.json` while another process holds the lock: it stops with exit
`1`, says nothing was changed, and the next command that can take the
lock copies the damaged file aside and restores the backup as usual.
`export` refuses to write over MeManga's own files in the config
directory (`config.yaml`, `state.json`, `memanga.lock`, their backups
and recovery copies), also through a link. When the destination already
exists and MeManga cannot check that it is not one of those files (for
example on a file system without file IDs), it refuses too and writes
nothing; export to a new file name instead.

The system releases the lock when the process ends, even after a crash
or a kill, so `memanga.lock` never needs to be deleted. A config
directory on a file system without file-lock support is refused with
`cannot lock`; use a directory on a local disk.

### File versions

`config.yaml` and `state.json` record their layout in a `schema_version`
field. Files from an older MeManga, including ones without the field,
load as before and are upgraded the next time MeManga saves them; the
file as it was before is kept as `config.yaml.bak` or `state.json.bak`.
A file written by a newer MeManga is never loaded or overwritten:
commands exit `1`, the desktop app shows an error and `memanga doctor`
reports a failure until MeManga is updated (or the file is moved).
Leave `schema_version` as it is when editing `config.yaml` by hand.

---

## Export and Import

### Export your manga list and state

```bash
run export
```

Saves to `memanga_export.json` by default. Specify a custom filename:

```bash
run export my_backup.json
```

Use `-` to write the JSON to stdout instead, for piping or redirecting:

```bash
run export - > backup.json
```

### Import into another machine

Copy the export file to the new machine, then:

```bash
run import memanga_export.json
```

This **merges** with your existing data — duplicates are skipped and download histories are combined.

Use `-` to read the backup from stdin, and `--dry-run` to check the file and
see what would be added or skipped without changing anything:

```bash
run import memanga_export.json --dry-run
cat memanga_export.json | run import -
```

The whole file is checked before anything is written; a malformed or
unsupported backup is rejected and your library is left as it was.

To **replace** all data instead (asks for confirmation first):

```bash
run import memanga_export.json --replace
```

Scripts, pipes and stdin imports cannot answer the prompt, so they must pass
`--yes` to replace:

```bash
run import - --replace --yes < memanga_export.json
```

---

## All Commands Reference

| Command | Description |
|---------|-------------|
| `run` | Open the interactive TUI |
| `run list` | Show tracked manga with status and progress |
| `run list --json` | Tracked manga as JSON (see [JSON output](#json-output)) |
| `run list --status reading` | Only one status (repeat `--status` for several) |
| `run list --sort title` | Sort by `list` (default), `title`, `status`, `last-chapter` or `downloaded` |
| `run list --sort downloaded --reverse` | Reverse the sort order |
| `run add -i` | Add manga interactively |
| `run add -t "Title" -u URL` | Add manga directly |
| `run add -t "Title" -u URL -b BACKUP` | Add with backup source |
| `run add -t "Title" -u URL --status on-hold --mode manual --no-kindle` | Add with status, mode and Kindle setting |
| `run check` | Check for new chapters (interactive) |
| `run check --download` | Download all new chapters without asking (`--auto`, `--yes` are aliases) |
| `run check "Title"` | Check one manga |
| `run check "Title" --from 1 --download --safe` | Download from chapter 1 |
| `run check "Title" --from 50 --download` | Download from chapter 50 |
| `run check --format epub` | Override output format |
| `run check --dry-run` | Check only: list new chapters, download and save nothing |
| `run edit "Title" --status reading` | Set status to reading |
| `run edit "Title" --status on-hold` | Set status to on-hold |
| `run edit "Title" --status dropped` | Set status to dropped |
| `run edit "Title" --status completed` | Set status to completed |
| `run read "Title" 1 2` | Mark chapters read |
| `run read "Title" --all` | Mark every downloaded chapter read |
| `run unread "Title" 2` | Mark a chapter unread |
| `run unread "Title" --all` | Mark every chapter unread |
| `run path "Title"` | Print the manga's download folder (only the path; exits `1` if nothing is downloaded yet) |
| `run open "Title"` | Open the manga's download folder in the file manager |
| `run remove "Title"` | Remove a manga |
| `run edit "Title" -u URL` | Change primary source URL |
| `run edit "Title" -b URL` | Change backup source URL |
| `run edit "Title" -t "New Name"` | Rename a manga |
| `run edit "Title" --no-backup` | Remove the backup source |
| `run edit "Title" --fallback-days 3` | Change the backup fallback delay |
| `run edit "Title" --status on-hold --mode manual --no-kindle` | Change status, mode and Kindle setting |
| `run config` | Configure settings (delivery, email, format) |
| `run status` | Show overall status and config |
| `run status --json` | Status and config as JSON, without secrets |
| `run failed` | List failed and accepted-partial chapters (same as `run failed list`) |
| `run failed list "Title"` | Only one manga (title or `#N`, matched like `check TARGET`) |
| `run failed retry` | Download every listed chapter again (`--retry` is an alias) |
| `run failed retry "Title"` | Retry one manga only |
| `run failed clear` | Forget every listed chapter (`--clear` is an alias) |
| `run failed clear "Title"` | Forget one manga's records only |
| `run failed --json` | Failed and partial chapters as JSON (listing only) |
| `run send "Title" 12 13` | Send downloaded chapters to Kindle (again); several chapters ask first unless `--yes` |
| `run send "Title" 12 --dry-run` | Show the file each chapter would send, sending nothing |
| `run send --pending` | Send every chapter whose Kindle delivery failed again |
| `run send --pending --list "Title"` | List them (title or `#N`), sending nothing |
| `run send --pending --clear` | Forget them; the files stay |
| `run sources` | List all supported sources |
| `run cron install` | Set up daily automatic checks |
| `run cron install --time 07:30` | Set custom check time |
| `run cron status` | Check if scheduling is active |
| `run cron remove` | Remove scheduled checks |
| `run export [FILE\|-]` | Export manga list to JSON (`-` = stdout) |
| `run import FILE\|-` | Import manga list from JSON (`-` = stdin) |
| `run import FILE --dry-run` | Check a backup and show what would change |
| `run import FILE --replace [--yes]` | Import and replace all data (asks unless `--yes`) |

### JSON output

With `--json`, `list`, `status` and `failed` print one JSON document to
stdout and nothing else. Errors and warnings still go to stderr, so
`memanga list --json | jq ...` is safe. Each payload has a top-level
`schema_version` (currently `1`). New keys may be added within a
version; it is bumped only when a key is renamed or removed or changes
type, so ignore keys you don't use. Optional values are `null`, not
missing.

`list --json` keeps the order of `list`, including any `--status`
filter and `--sort` order, and `count` is the number of entries shown:

```json
{
  "schema_version": 1,
  "count": 1,
  "manga": [
    {
      "n": 1,
      "title": "Blue Lock",
      "status": "reading",
      "source": "mangadex.org",
      "source_display": "mangadex.org (+1)",
      "url": "https://mangadex.org/title/...",
      "sources": [
        {"source": "mangadex.org", "url": "https://mangadex.org/title/..."},
        {"source": "mangapill.com", "url": "https://mangapill.com/manga/..."}
      ],
      "last_chapter": "251",
      "downloaded_count": 12,
      "mode": "auto",
      "send_to_kindle": true,
      "backup_count": 1
    }
  ]
}
```

`n` is the list number; pass it as `#N` to `edit` or `remove`.
It stays the same when `--status` or `--sort` hide or reorder entries.
`source` and `url` are the primary source (`null` if there is none),
and `sources` lists the primary first, then backups. `last_chapter`
is a string or `null`. `mode` is `auto` or `manual`, `send_to_kindle`
is whether the manga is sent to Kindle: its own toggle, or the
`email.kindle_scope` choice when it has none (email delivery must also
be on), and
`backup_count` is the number of sources after the primary (shown as
`(+N)` in the table's Source column).

`--sort` orders `title` case-insensitively, `status` as reading,
on-hold, dropped, completed, `last-chapter` numerically and
`downloaded` by count, all ascending; `--reverse` flips it. Ties keep
list order, and manga without a numeric last chapter (under
`last-chapter`) or with an unknown status (under `status`) always come
last.

`status --json` has the keys `paths` (`config_dir`, `config`, `state`),
`manga_count`, `output_format`, `delivery` (`mode`, `download_dir`,
`delete_after_send`), `email` (`kindle_email`, `sender_email`,
`smtp_server`, `smtp_port`, `smtp_tls`), `post_processing` (`enabled`,
`fail_on_error`), `partial_chapters` (`enabled`, `threshold_percent`),
`cron` (`enabled`, `time`) and `last_check` (ISO timestamp or `null`).
The email app password is never included.

`failed --json` has one entry per chapter, sorted by title and then by
chapter number. `title_filter` is the `-t` value or `null`:

```json
{
  "schema_version": 1,
  "title_filter": null,
  "count": 1,
  "chapters": [
    {
      "title": "Vinland Saga",
      "chapter": "10",
      "status": "failed",
      "recorded_at": "2026-01-01T06:00:00",
      "source": "mangadex.org",
      "failed_pages": [3],
      "total_pages": null,
      "attempts": 2,
      "error": "HTTP 503"
    }
  ]
}
```

`status` is `failed` or `partial`. If a chapter has both records, it is
listed once as `failed`. `chapter` is always a string. `attempts` and
`error` are `null` for partial chapters, and `total_pages` is `null`
for failed ones. `failed --json` (or `failed list --json`) only lists:
combining it with `retry`, `clear`, `--retry` or `--clear` is a usage
error (exit code `2`) and changes nothing.

### Failed chapters

`failed` has three actions, each with an optional target:

| Command | What it does |
|---------|--------------|
| `failed [list [TARGET]]` | Lists failed and accepted-partial chapters. Plain `failed` lists every manga; a TARGET goes after `list`. |
| `failed retry [TARGET]` | Downloads the chapters again the way `check --download` does: the primary source, then the backup source, then (with partial chapters turned on) the best partial copy. Saved chapters are emailed when delivery is email. |
| `failed clear [TARGET]` | Forgets the records without downloading anything. |

TARGET is a title or `#N` from `run list`, matched like `check TARGET`: an
exact title (ignoring case) wins, then a unique part of a title. A target
that matches nothing, or more than one manga, is an error (exit code `1`)
and changes nothing. Manga you no longer track can still be targeted by
title while they have records. Without a target every manga is included.
`-t TITLE` still works and is the same as TARGET.

`--retry` and `--clear` are kept as aliases of `failed retry` and
`failed clear`. `failed retry` exits `3` when a chapter still fails or is
saved as a partial again; its record stays listed.

### Output and logging

Results go to stdout; diagnostics go to stderr through logging, at these
levels:

| Level | Used for |
|-------|----------|
| `DEBUG` | Scraper internals and per-page retries |
| `INFO` | Normal progress (browser restarts, PDF splitting) |
| `WARNING` | Degraded or fallback behaviour (a source could not be fetched, a backup was used, a partial chapter) |
| `ERROR` | Failures |

stderr shows `WARNING` and up by default. The level comes from, in order:

1. `memanga -v` (`INFO`), `memanga -vv` (`DEBUG`) or `memanga -q`
   (`ERROR`)
2. `MEMANGA_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
3. the default: `WARNING`, or `INFO` for the desktop app

The warnings and errors of `check` and `failed retry` themselves (a
source that could not be checked, a backup used, a partial or failed
chapter) follow the same level, so `memanga -q` hides the warnings and
keeps the errors. `check --quiet` only means "never prompt" and does not
change the level, so the daily check still records warnings. A
command's direct answer, such as "Not found", always shows.

When stderr is not a terminal (cron, a redirect), each log line starts
with a timestamp and level, for example
`2026-10-21 06:00:03 WARNING memanga.downloader.updates: Failed to fetch from ...`.
`memanga --log-file` also writes `diagnostics.log` in the config
directory: `INFO` and up, a timestamp and level on every line, rotated at
1 MB with three old files kept. Passwords and tokens are masked in log
output.

When stdout is not a terminal, or with `memanga --plain`, output is plain
text without colour, emoji, borders or line wrapping (symbols in manga
titles are kept; `doctor` names each result `OK`, `WARN`, `FAIL` or
`SKIP`), and `check` prints one summary line such as
`Summary: 2/3 chapters downloaded, 1 failed; checked 4 manga, 0 could not be checked; next: run 'memanga failed' for details`.
The `; next: ...` part only appears when something is left to do:
`run 'memanga failed' for details` after failed chapters, or
`rerun with --download` when chapters were skipped because no one could
confirm them.
`NO_COLOR` only turns colour off. Redirected output is written as UTF-8,
also on Windows. `-v`, `-q`, `--plain` and `--log-file` go before the
command, like `--config-dir`.

### Exit codes

Results go to stdout; errors and warnings go to stderr. Scripts and
cron jobs can rely on these exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success. For `check`: no new chapters, a `--dry-run` listing, every chapter downloaded, or a suspicious batch withheld (the warning goes to stderr) |
| `1` | Error: manga not found, invalid input, refused or failed command, `check` could not check any manga, `check` skipped chapters that needed confirmation (no terminal, or `--quiet`, without `--download`), or `check`/`failed retry` could not write `state.json` after a chapter (the run stops there), or another MeManga process is using the config directory |
| `2` | Invalid command-line usage |
| `3` | `check` or `failed retry` ran, but some chapters (or some manga's source checks) failed |
| `130` | Interrupted with Ctrl-C |
| `143` | Stopped by SIGTERM (for example a cron `timeout` or a service stop); pending state is saved first |

When `check` both skips unconfirmed chapters and has failures, it exits
`1`.

An exact title duplicate (ignoring case) is refused by `add` with exit code
`1`, including with `--force` or `--yes`. The existing entry is preserved.

---

## Troubleshooting — Windows

### "python is not recognized"

Python isn't in your PATH. Either:

1. Reinstall Python from python.org and check **"Add Python to PATH"**
2. Or use `py scripts\bootstrap.py` and `py -m memanga` instead

### "Virtual environment not found"

The `venv` folder is missing. Re-run setup:

```
python scripts\bootstrap.py
```

Or:

```
.\scripts\windows\setup.bat
```

### Playwright browsers fail to launch

Reinstall the browsers:

```
venv\Scripts\python.exe -m playwright install chromium firefox
```

### ModuleNotFoundError

Dependencies aren't fully installed. Reinstall:

```
venv\Scripts\activate
pip install -r requirements.txt
```

### Scheduled task not running

Open Task Scheduler (`taskschd.msc`) and find `MeManga_AutoCheck`. Check:

- The task is enabled
- The path to `python.exe` in the action is correct
- "Run whether user is logged on or not" may need to be set

### Config file location

```
%APPDATA%\memanga\
```

---

## Troubleshooting — macOS

### "python3: command not found"

Install Python via Homebrew:

```bash
brew install python3
```

Or download from [python.org](https://www.python.org/downloads/).

### "Permission denied" on run.sh

Make the script executable:

```bash
chmod +x scripts/run.sh
```

### Playwright browsers fail to launch

Reinstall the browsers:

```bash
./venv/bin/python -m playwright install chromium firefox
```

### ModuleNotFoundError

Reinstall dependencies:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Cron job not running

Check if it's installed:

```bash
./scripts/run.sh cron status
```

Check the log file:

```bash
cat ~/Library/Application\ Support/memanga/memanga.log
```

Verify the paths in the cron entry are correct:

```bash
crontab -l
```

### Config file location

```
~/Library/Application Support/memanga/
```

---

## Troubleshooting — Linux

### "python3-venv: No such file or directory"

On Debian/Ubuntu, the venv module needs to be installed separately:

```bash
sudo apt-get install python3-venv
```

### Playwright browsers fail to launch

Playwright needs system libraries. Install them:

```bash
./venv/bin/python -m playwright install-deps
```

Then reinstall browsers:

```bash
./venv/bin/python -m playwright install chromium firefox
```

### Headless server (no display)

Playwright needs a display. Install xvfb:

**Debian/Ubuntu:**

```bash
sudo apt-get install xvfb
```

The setup script handles this automatically on Debian/Ubuntu.

### ModuleNotFoundError

Reinstall dependencies:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### "Permission denied" on run.sh

```bash
chmod +x scripts/run.sh
```

### Cron job not running

Check if it's installed:

```bash
./scripts/run.sh cron status
```

Check the log:

```bash
cat ~/.config/memanga/memanga.log
```

Verify cron entries:

```bash
crontab -l
```

On some headless servers, make sure `xvfb-run` is available — the cron command may need to be wrapped with it.

### Config file location

```
/home/YourName/.config/memanga/
```
