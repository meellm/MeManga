# 📖 MeManga

**Automatic manga downloader with Kindle support.**

Track manga from multiple sources, download chapters as PDFs, and optionally send them directly to your Kindle via email.

## ✨ Features

- 📚 **Track multiple manga** from 15 sources
- 🔍 **Automatic updates** — knows what you've already downloaded
- 📄 **PDF/EPUB output** — optimized for e-readers
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

> **Windows:** Use `scripts\windows\run.bat` instead of `./scripts/run.sh`

## 🌐 Supported Sources

| Source | Type | Notes |
|--------|------|-------|
| mangadex.org | API | Fan translations, largest library |
| tcbonepiecechapters.com | Requests | Jump manga (One Piece, JJK, etc.) |
| weebcentral.com | Playwright | 1000+ series, Quick Search |
| mangapill.com | Requests | Fast, no Cloudflare |
| mangakatana.com | Playwright | General library |
| mangareader.to | Requests | Clean UI |
| mangafire.to | Playwright | VRF bypass + image descrambling |
| mangasee123.com | Requests | High quality scans |
| asuracomic.net | Playwright | Manhwa/Webtoons |
| mangabuddy.com | Requests | Popular aggregator |
| bato.to | Requests | Community-driven |
| mangakakalot.com | Requests | Huge library |
| manganato.com | Requests | Mangakakalot network |
| mangago.me | Requests | Yaoi/Shoujo collection |
| mangataro.org | Requests | ComicK alternative |

> **Note:** Playwright scrapers use Firefox headless browser for JavaScript rendering and bot detection bypass.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `run` | Interactive TUI |
| `run list` | Show tracked manga |
| `run add -i` | Add manga interactively |
| `run check` | Check for new chapters |
| `run check --auto` | Auto-download all new |
| `run config` | Configure settings |
| `run cron install` | Set up daily checks |
| `run sources` | List all sources |

## ⚙️ Configuration

Config files are stored in `~/.config/memanga/`. See `examples/` folder for templates:
- `examples/config.example.yaml` — configuration template
- `examples/state.example.json` — state file format

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

> **Windows:** Use Task Scheduler instead of cron.

## 🛠️ Adding a Source

1. Create `memanga/scrapers/newsite.py`
2. Inherit from `BaseScraper`
3. Implement `search()`, `get_chapters()`, `get_pages()`
4. Register in `memanga/scrapers/__init__.py`

## 📝 Notes

- Playwright scrapers use Firefox (better at bypassing bot detection)
- MangaDex skips chapters with external URLs (official Shueisha)
- TCBScans is fastest (no browser automation)
- MangaFire includes image descrambling for protected content

## 💬 Contact

Feel free to suggest new manga sources.

## 📄 License

MIT
