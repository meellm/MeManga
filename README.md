# 📖 MeManga

**Automatic manga downloader with Kindle support.**

Track manga from multiple sources, download chapters as PDF/EPUB/CBZ, and optionally send them directly to your Kindle via email.

## ✨ Features

- 📚 **Track multiple manga** from 260+ scrapers / 300+ domains
- 🔍 **Automatic updates** — knows what you've already downloaded
- 🔄 **Backup sources** — fallback to secondary sources after N days
- 📊 **Status tracking** — reading, on-hold, dropped, completed
- 📥 **Bulk downloads** — download from chapter 1 with `--from` flag
- 📄 **PDF/EPUB/CBZ/ZIP/JPG/PNG/WEBP output** — for e-readers, comic viewers, and local reading
- 📧 **Kindle delivery** — automatic email to your device
- ⏰ **Scheduled checks** — daily cron job support
- 🖥️ **Cross-platform** — Windows, macOS, Linux, Raspberry Pi

## 🚀 Quick Start

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
python setup.py
```

Then:
```bash
./scripts/run.sh add -i      # Add manga interactively
./scripts/run.sh check       # Check for new chapters
./scripts/run.sh             # Launch interactive TUI
```

> **Windows:** Use `.\scripts\windows\run.bat` instead of `./scripts/run.sh`

## 🌐 Popular Sources

| Source | Type | Notes |
|--------|------|-------|
| mangadex.org | API | Largest fan translation library |
| weebcentral.com | Playwright | 1000+ series, fast search |
| mangafire.to | Playwright | VRF bypass + image descrambling |
| mangapill.com | Requests | Fast, no Cloudflare |
| bato.to | Requests | Community-driven |
| comick.io | Requests | Clean API |
| tcbscans.com | Requests | Jump manga (One Piece, JJK) |
| asuracomic.net | Playwright | Manhwa/Webtoons |
| mangakakalot.com | Requests | Huge library |
| mangasee123.com | Requests | High quality scans |

**[→ Full list of 300+ supported domains](docs/SUPPORTED_SOURCES.md)**

> **Note:** Playwright scrapers use Firefox headless browser for JavaScript rendering and bot detection bypass.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `run` | Interactive TUI |
| `run list` | Show tracked manga with status |
| `run add -i` | Add manga interactively |
| `run add -t "Title" -u URL -b BACKUP` | Add with backup source |
| `run check` | Check for new chapters |
| `run check --auto` | Auto-download all new |
| `run check -t "Title" --from 1 --auto --safe` | Download from chapter 1 |
| `run set "Title" on-hold` | Set manga status |
| `run remove "Title"` | Remove manga |
| `run config` | Configure settings |
| `run cron install` | Set up daily checks |
| `run sources` | List all sources |

### Status System

Track your reading progress:

```bash
run set "Manga Title" reading     # Currently reading (checked daily)
run set "Manga Title" on-hold     # Paused (skipped during check)
run set "Manga Title" dropped     # Dropped (skipped during check)
run set "Manga Title" completed   # Finished (skipped during check)
```

### Bulk Downloads

Download a manga from scratch:

```bash
# Download all chapters from beginning
run check -t "Manga Title" --from 1 --auto --safe

# Start from specific chapter
run check -t "Manga Title" --from 50 --auto --safe
```

> **Note:** Use `--safe` for bulk downloads — it restarts the browser every 3 chapters to prevent memory issues.

## ⚙️ Configuration

Config files are stored in `~/.config/memanga/`. See `examples/` folder for templates:
- `examples/config.example.yaml` — configuration template
- `examples/state.example.json` — state file format

### Backup Sources

Configure primary and backup sources for each manga:

```yaml
manga:
- title: My Manga
  fallback_delay_days: 2  # Wait 2 days before using backup
  sources:
    - url: https://mangafire.to/manga/my-manga.xxx    # Primary
    - url: https://mangadex.org/title/uuid-here       # Backup
```

### Delivery Modes

**Local (default):**
Downloads to `~/.config/memanga/downloads/`

**Email to Kindle:**
1. Get a [Gmail App Password](https://support.google.com/accounts/answer/185833)
2. Add your Gmail to [Amazon's Approved List](https://www.amazon.com/hz/mycd/myx#/home/settings/payment)
3. Run `run config` and enter your details

### Automatic Checking

```bash
./scripts/run.sh cron install           # Daily at 06:00
./scripts/run.sh cron install --time 07:30  # Custom time
./scripts/run.sh cron status            # Check status
```

## 🛠️ Adding a Source

1. Create `memanga/scrapers/newsite.py`
2. Inherit from `BaseScraper` or `PlaywrightScraper`
3. Implement `search()`, `get_chapters()`, `get_pages()`
4. Register in `memanga/scrapers/__init__.py`

## 📝 Notes

- Playwright scrapers use Firefox (better at bypassing bot detection)
- MangaDex skips chapters with external URLs (official Shueisha)
- TCBScans is fastest (no browser automation)
- MangaFire includes image descrambling for protected content

## 📄 License

MIT
