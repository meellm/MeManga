# 📖 MeManga

**Automatic manga downloader with Kindle support.**

Download manga chapters as PDFs, optionally send them directly to your Kindle via email.

## ✨ Features

- 📚 **Track multiple manga** from different sources
- 🔍 **Automatic chapter detection** - knows what you've already downloaded
- 📄 **PDF output** - optimized for e-readers
- 📧 **Email to Kindle** - automatic delivery (optional)
- ⏰ **Cron scheduling** - daily automatic checks

## 🌐 Supported Sources

| Source | Type | Best For |
|--------|------|----------|
| **tcbonepiecechapters.com** | Requests | Jump manga (One Piece, JJK, MHA, Black Clover) |
| **weebcentral.com** | Hybrid | Large library (1000+ manga series) |
| **asuracomic.net** | Playwright | Manhwa / Webtoons (Solo Leveling, etc.) |
| **mangakatana.com** | Playwright | General manga library |
| **mangadex.org** | API | Fan translations (skip official Shueisha) |
| **mangapill.com** | Requests | Large library, fast (no Cloudflare) |
| **mangataro.org** | Requests | ComicK replacement, large library |
| **mangareader.to** | Requests | Large library, clean UI |
| **mangabuddy.com** | Requests | Popular aggregator |
| **mangakakalot.com** | Requests | Huge library |
| **manganato.com** | Requests | Same network as Mangakakalot |

All sources tested and working as of February 2026.

**Note:** MangaFire (mangafire.to) has heavy DRM protection and is not supported.

## 🚀 Quick Start

### Installation

```bash
cd MeManga
./setup.sh
```

This creates a virtual environment and installs all dependencies including Playwright browsers.

### Basic Usage

```bash
# Launch interactive TUI
./run.sh

# Or use CLI commands
./run.sh add -i                    # Add manga interactively
./run.sh list                      # List tracked manga
./run.sh check                     # Check for new chapters
./run.sh check --auto              # Auto-download without prompts
```

## 📋 Commands

| Command | Description |
|---------|-------------|
| `./run.sh` | Launch interactive TUI |
| `./run.sh list` | Show all tracked manga |
| `./run.sh add -i` | Add manga interactively |
| `./run.sh add -t "Title" -u URL` | Add manga directly |
| `./run.sh remove <#/title>` | Remove manga from tracking |
| `./run.sh check` | Check for new chapters |
| `./run.sh check --auto` | Auto-download all new chapters |
| `./run.sh status` | Show configuration status |
| `./run.sh config` | Configure settings (delivery mode, email) |
| `./run.sh cron install` | Set up daily automatic checks |
| `./run.sh cron status` | Check cron job status |
| `./run.sh sources` | List supported sources |

## ⚙️ Configuration

### Delivery Modes

**Local (default):**
- Downloads PDFs to `~/.config/memanga/downloads/`
- No additional setup needed

**Email to Kindle:**
1. Get a [Gmail App Password](https://support.google.com/accounts/answer/185833)
2. Add your Gmail to Amazon's [Approved Email List](https://www.amazon.com/hz/mycd/myx#/home/settings/payment)
3. Run `./run.sh config` and enter your details

### Automatic Checking (Cron)

```bash
# Install daily check at 6:00 AM
./run.sh cron install

# Custom time
./run.sh cron install --time 07:30

# Check status
./run.sh cron status

# Remove
./run.sh cron remove
```

## 📁 File Locations

| File | Location |
|------|----------|
| Config | `~/.config/memanga/config.yaml` |
| State | `~/.config/memanga/state.json` |
| Downloads | `~/.config/memanga/downloads/` |
| Logs | `~/clawd/MeManga/memanga.log` |

## 🔧 How It Works

### Architecture

```
MeManga/
├── memanga.py      # Main CLI application
├── config.py       # Configuration management
├── state.py        # Download state tracking
├── downloader.py   # Chapter download + PDF creation
├── emailer.py      # Email-to-Kindle delivery
└── scrapers/       # Source-specific scrapers
    ├── base.py           # Base scraper class
    ├── tcbscans.py       # TCB Scans (requests)
    ├── weebcentral.py    # WeebCentral (cloudscraper + Playwright)
    ├── asurascans.py     # Asura Scans (Playwright)
    ├── mangakatana.py    # Mangakatana (Playwright)
    ├── mangadex.py       # MangaDex (API)
    ├── mangapill.py      # Mangapill (requests)
    ├── mangataro.py      # MangaTaro (requests) - ComicK replacement
    └── ...               # + more scrapers
```

### Scraper Types

- **Requests**: Simple HTTP requests (fastest, for sites without protection)
- **Playwright**: Browser automation (for JavaScript-rendered sites)
- **Hybrid**: Combination of both (cloudscraper for chapters, Playwright for images)
- **API**: Direct API calls (most reliable when available)

### Download Flow

1. **Check for updates** - Compare available chapters vs downloaded
2. **Download images** - Fetch all pages for new chapters
3. **Create PDF** - Convert images to Kindle-optimized PDF
4. **Send to Kindle** - Email PDF (if configured)
5. **Update state** - Mark chapter as downloaded

## 🛠️ Development

### Adding a New Source

1. Create `scrapers/newsite.py` inheriting from `BaseScraper`
2. Implement `search()`, `get_chapters()`, `get_pages()`
3. Register in `scrapers/__init__.py`

### Running Tests

```bash
source venv/bin/activate
python3 -c "from scrapers.tcbscans import TCBScansScraper; s = TCBScansScraper(); print(len(s.get_chapters('https://tcbonepiecechapters.com/mangas/5/one-piece')))"
```

## 📝 Notes

- **Playwright scrapers** require Xvfb on headless systems (installed by setup.sh)
- **WeebCentral** uses a hybrid approach because images are lazy-loaded
- **MangaDex** skips chapters with external URLs (Shueisha manga on MangaPlus)
- **TCBScans** is the fastest source (no browser automation needed)

## 📄 License

MIT

---
