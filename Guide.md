# MeManga Setup & Usage Guide

Automatic manga downloader with Kindle support. Track manga from 260+ scrapers / 300+ domains, download chapters as PDF/EPUB/CBZ/ZIP/JPG/PNG/WEBP, and optionally send them directly to your Kindle.

---

## Table of Contents

- [Setup — Windows](#setup--windows)
- [Setup — macOS](#setup--macos)
- [Setup — Linux](#setup--linux)
- [Your First Manga](#your-first-manga)
- [Checking for New Chapters](#checking-for-new-chapters)
- [Downloading From the Start](#downloading-from-the-start)
- [Downloading From a Specific Chapter](#downloading-from-a-specific-chapter)
- [Managing Status](#managing-status)
- [Changing Output Format](#changing-output-format)
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
python setup.py
```

This creates a virtual environment, installs all dependencies, and downloads Chromium and Firefox browsers for Playwright scrapers.

If `python` isn't recognized, try `py` instead:
```
py setup.py
```

Alternatively, use the provided batch script:
```
scripts\windows\setup.bat
```

### Verify Installation

```
scripts\windows\run.bat --help
```

You should see the help output with available commands.

### Running MeManga

From now on, launch MeManga with:

```
scripts\windows\run.bat
```

This opens the interactive TUI. For specific commands:

```
scripts\windows\run.bat list
scripts\windows\run.bat add -i
scripts\windows\run.bat check
```

Or run directly through the virtual environment:

```
venv\Scripts\python.exe -m memanga --help
```

### Where files are stored

```
C:\Users\YourName\.config\memanga\config.yaml      # Configuration
C:\Users\YourName\.config\memanga\state.json        # Download history
C:\Users\YourName\.config\memanga\downloads\        # Downloaded chapters
```

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
python3 setup.py
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
/Users/YourName/.config/memanga/config.yaml      # Configuration
/Users/YourName/.config/memanga/state.json        # Download history
/Users/YourName/.config/memanga/downloads/        # Downloaded chapters
```

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
python3 setup.py
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
/home/YourName/.config/memanga/config.yaml      # Configuration
/home/YourName/.config/memanga/state.json        # Download history
/home/YourName/.config/memanga/downloads/        # Downloaded chapters
```

---

## Your First Manga

> In all examples below, `run` means the launcher for your platform:
> - **Windows:** `scripts\windows\run.bat`
> - **macOS / Linux:** `./scripts/run.sh`

### Interactive mode (recommended)

```bash
run add -i
```

MeManga will prompt you step by step:

```
➕ Add New Manga

Supported sources: mangadex.org, weebcentral.com, mangafire.to, ...

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

### View your tracked manga

```bash
run list
```

Output:

```
┌───┬───────────────┬─────────┬────────────────────────────┬──────────┬────────────┐
│ # │ Title         │ Status  │ Source                     │ Last Ch. │ Downloaded │
├───┼───────────────┼─────────┼────────────────────────────┼──────────┼────────────┤
│ 1 │ One Piece     │ reading │ tcbonepiecechapters.com    │ —        │ 0          │
│ 2 │ Solo Leveling │ reading │ mangafire.to (+1)          │ —        │ 0          │
└───┴───────────────┴─────────┴────────────────────────────┴──────────┴────────────┘
```

### Remove a manga

By title:

```bash
run remove "One Piece"
```

By list number:

```bash
run remove 1
```

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

Check which manga? (a=all, or enter # / title) [a]: a
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number):
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

That's it — MeManga checks all your manga and downloads new chapters automatically.

### Using CLI commands

These are the command-line equivalents if you prefer typing commands directly in your terminal (not inside the menu):

```bash
run check                        # Interactive — asks y/n per chapter
run check --auto                 # Auto-download all new chapters
run check -t "One Piece"        # Check one specific manga
run check -t "One Piece" --auto # Auto-download for one manga
run check --dry-run              # Preview what's new without downloading
run check --auto --quiet         # Quiet mode (for scripts and cron)
```

---

## Downloading From the Start

### Using the menu (easiest)

Run `run`, select **[4] Check Now**, then:

```
Check which manga? (a=all, or enter # / title) [a]: 1
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number): 1
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

That's all you need. MeManga downloads every chapter from chapter 1 onward. Safe mode (browser restarts every 3 chapters to save memory) is enabled automatically when you type a starting chapter.

### Using CLI commands

The command-line equivalent, typed directly in your terminal (not inside the menu):

```bash
run check -t "One Piece" --from 1 --auto --safe
```

**What each flag does:**

| Flag | Purpose |
|------|---------|
| `-t "One Piece"` | Target a specific manga |
| `--from 1` | Start from chapter 1 instead of where you left off |
| `--auto` | Download without prompting for each chapter |
| `--safe` | Restart the browser every 3 chapters to prevent memory buildup |

The `--safe` flag is important for bulk downloads — without it, the browser can consume too much memory after many chapters.

---

## Downloading From a Specific Chapter

### Using the menu (easiest)

Run `run`, select **[4] Check Now**, then:

```
Check which manga? (a=all, or enter # / title) [a]: One Piece
Auto-download new chapters? [Y/n]: y
Start from chapter? (Enter for latest, or type a number): 50
Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp):
```

This downloads chapter 50, 51, 52, etc. Chapters you already have are automatically skipped. Safe mode is enabled automatically.

### Using CLI commands

```bash
run check -t "One Piece" --from 50 --auto --safe
```

Start from chapter 100 in EPUB format:

```bash
run check -t "One Piece" --from 100 --auto --safe --format epub
```

Start from a decimal chapter:

```bash
run check -t "One Piece" --from 55.5 --auto
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

New manga default to `reading`.

### Set a manga to on-hold

```bash
run set "One Piece" on-hold
```

Output:

```
One Piece: reading → on-hold
```

### Mark as completed

```bash
run set "Solo Leveling" completed
```

### Resume reading

```bash
run set "One Piece" reading
```

### Set by list number

```bash
run set 1 on-hold
```

You can also use partial title matching — `run set "Solo" completed` will match "Solo Leveling".

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
run check -t "One Piece" --format cbz --auto
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

✅ Configuration saved!
```

The app password is stored in your system keyring when available. If the keyring isn't available, it falls back to storing it in the config file.

### Step 4 — Test it

```bash
run check --auto
```

When a new chapter is found and downloaded, MeManga sends it to your Kindle automatically. If the PDF exceeds 23MB, it's automatically split into smaller parts.

### Switch back to local downloads

```bash
run config
```

Set delivery mode to `local`. Downloaded chapters will be saved to `~/.config/memanga/downloads/`.

### Note on formats and email

- **PDF:** Auto-splits if over 23MB. Best choice for email delivery.
- **EPUB:** Sent as-is. Kindle supports EPUB natively. Cannot be split — if over 25MB, switch to PDF.
- **CBZ:** Kindle does not support CBZ. Use PDF or EPUB for email delivery.
- **ZIP:** Sent as-is. Cannot be split — if over 25MB, switch to PDF.
- **JPG/PNG/WEBP:** Cannot be emailed (saved as image folders). Use PDF, EPUB, or CBZ for email delivery.

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

Set `fallback_delay_days: 0` to use the backup immediately without waiting.

---

## Updating Manga Details

Change the URL, backup, or title of a tracked manga.

### Change the primary URL

```bash
run update "One Piece" -u "https://new-source.com/one-piece"
```

### Add or change backup URL

```bash
run update "One Piece" -b "https://mangadex.org/title/uuid-here"
```

### Rename a manga

```bash
run update "One Piece" -t "One Piece (Colored)"
```

### You can also update by list number

```bash
run update 1 -u "https://new-source.com/one-piece"
```

---

## Scheduling Automatic Checks

### Windows — Task Scheduler

Install a daily scheduled task:

```
scripts\windows\run.bat cron install
```

You'll be asked what time to run (default: 06:00):

```
Check time (HH:MM): 07:30
✅ Scheduled task installed! Will check daily at 07:30
```

Check if it's active:

```
scripts\windows\run.bat cron status
```

Remove it:

```
scripts\windows\run.bat cron remove
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

Output is logged to `memanga.log` in the project directory.

### Linux — Cron

Same commands as macOS:

```bash
./scripts/run.sh cron install
./scripts/run.sh cron install --time 07:30
./scripts/run.sh cron status
./scripts/run.sh cron remove
```

On headless servers (no display), make sure `xvfb` is installed — the setup script handles this on Debian/Ubuntu.

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

### Import into another machine

Copy the export file to the new machine, then:

```bash
run import memanga_export.json
```

This **merges** with your existing data — duplicates are skipped and download histories are combined.

To **replace** all data instead:

```bash
run import memanga_export.json --replace
```

---

## All Commands Reference

| Command | Description |
|---------|-------------|
| `run` | Open the interactive TUI |
| `run list` | Show tracked manga with status and progress |
| `run add -i` | Add manga interactively |
| `run add -t "Title" -u URL` | Add manga directly |
| `run add -t "Title" -u URL -b BACKUP` | Add with backup source |
| `run check` | Check for new chapters (interactive) |
| `run check --auto` | Auto-download all new chapters |
| `run check -t "Title"` | Check one manga |
| `run check -t "Title" --from 1 --auto --safe` | Download from chapter 1 |
| `run check -t "Title" --from 50 --auto` | Download from chapter 50 |
| `run check --format epub` | Override output format |
| `run check --dry-run` | List new chapters without downloading |
| `run set "Title" reading` | Set status to reading |
| `run set "Title" on-hold` | Set status to on-hold |
| `run set "Title" dropped` | Set status to dropped |
| `run set "Title" completed` | Set status to completed |
| `run remove "Title"` | Remove a manga |
| `run update "Title" -u URL` | Change primary source URL |
| `run update "Title" -b URL` | Change backup source URL |
| `run update "Title" -t "New Name"` | Rename a manga |
| `run config` | Configure settings (delivery, email, format) |
| `run status` | Show overall status and config |
| `run sources` | List all supported sources |
| `run cron install` | Set up daily automatic checks |
| `run cron install --time 07:30` | Set custom check time |
| `run cron status` | Check if scheduling is active |
| `run cron remove` | Remove scheduled checks |
| `run export` | Export manga list to JSON |
| `run import FILE` | Import manga list from JSON |
| `run import FILE --replace` | Import and replace all data |

---

## Troubleshooting — Windows

### "python is not recognized"

Python isn't in your PATH. Either:

1. Reinstall Python from python.org and check **"Add Python to PATH"**
2. Or use `py setup.py` and `py -m memanga` instead

### "Virtual environment not found"

The `venv` folder is missing. Re-run setup:

```
python setup.py
```

Or:

```
scripts\windows\setup.bat
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
C:\Users\YourName\.config\memanga\
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
cat memanga.log
```

Verify the paths in the cron entry are correct:

```bash
crontab -l
```

### Config file location

```
/Users/YourName/.config/memanga/
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
cat memanga.log
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
