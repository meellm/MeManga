# MeManga

Automatic manga downloader with Kindle support.

Track manga from multiple sources, download chapters as PDF/EPUB/CBZ, and optionally deliver them directly to your Kindle via email.

## ✨ Features

- Track multiple manga from 224 scrapers covering 319+ domains
- Automatic update detection — skips already-downloaded chapters
- Backup sources — fall back to a secondary source after a configurable delay
- Status tracking — reading, on-hold, dropped, completed
- Bulk downloads — download from chapter 1 with `--from`
- Output formats — PDF, EPUB, CBZ, ZIP, JPG, PNG, WEBP
- Kindle delivery — automatic email to your device
- Scheduled checks — daily cron job support
- Cross-platform — Windows, macOS, Linux, Raspberry Pi

## 🔧 Installation

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
python setup.py
```

## 🚀 Quick Start

```bash
./scripts/run.sh add -i       # Add manga interactively
./scripts/run.sh check        # Check for new chapters
./scripts/run.sh              # Launch interactive TUI
```

On Windows, use `.\scripts\windows\run.bat` in place of `./scripts/run.sh`.

## 🌐 Supported Sources

| Source | Method | Notes |
|--------|--------|-------|
| mangadex.org | API | Largest fan translation library |
| weebcentral.com | Playwright | 1,000+ series, fast search |
| mangafire.to | Playwright | VRF bypass + image descrambling |
| mangapill.com | Requests | Fast, no Cloudflare |
| bato.to | Requests | Community-driven |
| comick.io | Requests | Clean API |
| tcbscans.com | Requests | Jump manga (One Piece, JJK) |
| asuracomic.net | Playwright | Manhwa/Webtoons |
| mangakakalot.com | Requests | Large library |
| mangasee123.com | Requests | High quality scans |

Full list: [docs/SUPPORTED_SOURCES.md](docs/SUPPORTED_SOURCES.md)

Playwright scrapers run a headless Firefox browser for JavaScript rendering and bot detection bypass.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `run` | Interactive TUI |
| `run list` | Show tracked manga with status |
| `run add -i` | Add manga interactively |
| `run add -t "Title" -u URL -b BACKUP` | Add with backup source |
| `run check` | Check for new chapters |
| `run check --auto` | Auto-download all new chapters |
| `run check -t "Title" --from 1 --auto --safe` | Download from chapter 1 |
| `run set "Title" on-hold` | Set manga status |
| `run remove "Title"` | Remove manga |
| `run config` | Configure settings |
| `run cron install` | Set up daily checks |
| `run sources` | List all sources |

### Status System

```bash
run set "Manga Title" reading     # Currently reading (checked daily)
run set "Manga Title" on-hold     # Paused (skipped during check)
run set "Manga Title" dropped     # Dropped (skipped during check)
run set "Manga Title" completed   # Finished (skipped during check)
```

### Bulk Downloads

```bash
# Download all chapters from the beginning
run check -t "Manga Title" --from 1 --auto --safe

# Start from a specific chapter
run check -t "Manga Title" --from 50 --auto --safe
```

Use `--safe` for bulk downloads — it restarts the browser every 3 chapters to prevent memory exhaustion.

## ⚙️ Configuration

Config files are stored in `~/.config/memanga/`. See `examples/` for reference templates:

- `examples/config.example.yaml` — full configuration reference
- `examples/state.example.json` — state file format

### Backup Sources

```yaml
manga:
- title: My Manga
  fallback_delay_days: 2       # Wait 2 days before trying the backup source
  sources:
    - url: https://mangafire.to/manga/my-manga.xxx    # Primary
    - url: https://mangadex.org/title/uuid-here       # Backup
```

### Kindle Delivery

1. Generate a [Gmail App Password](https://support.google.com/accounts/answer/185833)
2. Add your Gmail address to [Amazon's Approved Senders list](https://www.amazon.com/hz/mycd/myx#/home/settings/payment)
3. Run `run config` and enter your credentials

### Scheduled Checks

```bash
./scripts/run.sh cron install               # Daily at 06:00
./scripts/run.sh cron install --time 07:30  # Custom time
./scripts/run.sh cron status                # Check current schedule
```

## 🛠️ Contributing a Scraper

The `memanga/scrapers/examples/` directory contains ready-to-use templates for every supported scraper pattern. Pick the one that matches the target site and fill in the attributes.

| Example file | When to use |
|---|---|
| `example_base_requests.py` | Standard HTML site, no Cloudflare, no JavaScript |
| `example_cloudscraper.py` | Cloudflare-protected site that works without a real browser |
| `example_playwright.py` | JavaScript-heavy or bot-protected site requiring a real browser |
| `example_og_image_meta.py` | Single-manga WordPress site; chapter images in `og:image` meta tags |
| `example_nuxt_ssr.py` | Single-manga Nuxt SSR site with sequential assets CDN |
| `example_wordpress_madara.py` | WordPress Madara theme (single-manga or aggregator) |
| `example_laiond_cdn.py` | WordPress site with laiond.com / loinew.com CDN images |
| `example_mangosm.py` | WordPress Mangosm theme with external CDN images |
| `example_readmanga_base.py` | read[manga].com family (readsnk, readberserk, etc.) |
| `example_api.py` | Site with a public REST API |

Each file is annotated with instructions, real-world examples, and the key attributes to configure.

### Registration

After creating a scraper, register it in `memanga/scrapers/__init__.py`:

```python
from .mynewsite import MyNewSiteScraper

SCRAPERS = {
    ...
    "mynewsite.com": MyNewSiteScraper,
}
```

## 📝 Notes

- MangaDex skips chapters with external URLs (official Shueisha releases)
- TCBScans is the fastest source (no browser automation required)
- MangaFire descrambles tile-scrambled images client-side via Playwright

## 📄 License

MIT
