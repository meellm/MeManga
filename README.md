# 📖 MeManga (CLI)

**Automatic manga downloader — command-line edition.**

Track manga across 224 scrapers / 319 domains, batch-download new
chapters, and optionally email them to your Kindle. No GUI, no Qt
runtime, no Playwright stealth dependencies you don't need — just the
engine and a cron-friendly CLI.

<p align="center">
  <a href="https://github.com/meellm/MeManga/releases"><img alt="latest release" src="https://img.shields.io/github/v/release/meellm/MeManga"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="platforms" src="https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-supported-success">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue">
</p>

> **Want the desktop app?** The [`main` branch](https://github.com/meellm/MeManga/tree/main)
> ships a full PySide6 GUI with a built-in reader, search page, and
> downloads dashboard. This `cli` branch is the same engine without
> the GUI layer — leaner venv, faster `pip install`, ideal for
> headless servers and Docker images.

---

## ✨ Highlights

- 🤝 **Power-user CLI** — scriptable, cron-friendly, works on headless servers
- 📚 **Library tracking** — read/unread state survives reboots
- 🔍 **Multi-source search** — 15 popular aggregators pre-checked, ranked by reliability
- 📥 **PDF / EPUB / CBZ / ZIP / JPG / PNG / WEBP** output
- 📧 **Kindle delivery** — auto-send chapters by email after download
- 🔄 **Backup sources** — fall back to a second source if the primary stops updating
- 🌐 **Offline-aware** — gracefully fails on network actions when offline
- 🔒 **No telemetry, no accounts, no cloud** — everything stays on your machine

---

## 🚀 Install

```bash
git clone -b cli https://github.com/meellm/MeManga.git
cd MeManga
python setup.py            # creates a venv + installs everything
```

The CLI lives at `python -m memanga` once the venv is active. On
Windows, prefer:

```cmd
.\scripts\windows\setup.bat
.\scripts\windows\run.bat <command>
```

On macOS / Linux:

```bash
./scripts/run.sh <command>
```

> **First run downloads Firefox** (~90 MB, one-time) via Playwright for
> the JS-heavy sources (MangaFire, WeebCentral, …). After that, startup
> is instant.

### Docker

The Docker image packages the CLI and Playwright Firefox runtime for
headless servers, NAS boxes, Raspberry Pi systems, and cron-style
automation.

```bash
docker build -t memanga:cli .
docker run --rm memanga:cli --help
```

Persist MeManga's config/state and downloads with two mounts:

```bash
mkdir -p memanga-data/config memanga-data/downloads

docker run --rm \
  -v "$PWD/memanga-data/config:/home/memanga/.config/memanga" \
  -v "$PWD/memanga-data/downloads:/home/memanga/Downloads/MeManga" \
  memanga:cli status
```

Use the included Compose file for repeated commands:

```bash
docker compose build
docker compose run --rm memanga list
docker compose run --rm memanga check --auto
```

For a host cron job, run Compose from the repository directory:

```cron
0 6 * * * cd /path/to/MeManga && docker compose run --rm memanga check --auto --quiet >> memanga-docker.log 2>&1
```

Kindle delivery works the same way as local installs: run
`docker compose run --rm memanga config` and keep the config volume
private because email settings are stored there when a system keyring is
not available inside the container.

---

## 🧭 First five minutes

```bash
# 1. Track a manga (either interactive or one-shot)
python -m memanga add -i
python -m memanga add -t "Blue Lock" -u "https://mangapill.com/manga/580/blue-lock"

# 2. Check for new chapters and download them
python -m memanga check --auto

# 3. List what you're tracking
python -m memanga list
```

Config + state live under `~/.config/memanga/` (and `%APPDATA%/memanga`
on Windows). Same paths as the desktop app, so you can drive the same
library from both interchangeably.

---

## 📜 Commands

| Command | Purpose |
|---|---|
| `list` (`ls`) | Show every tracked manga with status + chapter counts |
| `add` | Add a manga; supports `-t TITLE -u URL [-b BACKUP_URL]` or `-i` interactive |
| `set TITLE STATUS` | `reading` / `on-hold` / `dropped` / `completed` |
| `remove TITLE` (`rm`) | Drop a manga from tracking |
| `update TITLE …` | Edit URL, backup source, or rename |
| `check [TITLE] [--from N] [--auto] [--safe]` | Look for new chapters, optionally download them |
| `failed [--retry] [--clear]` | List / re-attempt / clear partially-failed downloads |
| `status` | Show config dir, download dir, manga count, last check time |
| `config` | Interactive settings editor |
| `cron install [--time 06:00]` | Schedule a daily `check --auto` job |
| `cron status` / `cron remove` | Inspect / uninstall the cron job |
| `sources` | List all 319 supported domains, marking which ones are healthy |
| `export FILE` / `import FILE` | Back up or restore your library + state as JSON |
| `tui` | Launch the in-terminal interactive view |

Run any subcommand with `--help` for full flags.

---

## 🍳 Common recipes

### Add a manga with a backup source

```bash
python -m memanga add \
    -t "Blue Lock" \
    -u "https://mangapill.com/manga/580/blue-lock" \
    -b "https://mangadex.org/title/4141c5dc-c525-4df5-afd7-cc7d192a832f"
```

If MangaPill stops updating, MeManga falls back to MangaDex after
`fallback_delay_days` (default 2) — long enough for a slow-translating
primary to catch up.

### Backfill an entire series from chapter 1

```bash
python -m memanga check -t "Blue Lock" --from 1 --auto --safe
```

`--safe` restarts the browser every 3 chapters to keep memory usage
flat across long bulk runs.

### Schedule daily checks

```bash
# Linux/macOS — installs a crontab entry
python -m memanga cron install --time 06:00

# Windows — registers a Task Scheduler entry (run as the current user)
python -m memanga cron install --time 06:00
```

### Retry every failed chapter

```bash
python -m memanga failed --retry
```

`failed` is the safety net for the "downloaded but incomplete" class
of errors — the downloader refuses to mark a chapter complete if any
page failed, and tracks the failure so the next run can batch-retry it.

### Send a manga to your Kindle after every download

1. [Generate a Gmail App Password](https://support.google.com/accounts/answer/185833)
   (regular passwords won't work; Google blocks them for SMTP).
2. Add your Gmail address to your
   [Amazon "Approved Personal Document E-mail List"](https://www.amazon.com/hz/mycd/myx#/home/settings/payment).
3. Run `python -m memanga config` and fill in Kindle email, sender
   Gmail, and the App Password.
4. Run `python -m memanga set "Blue Lock" reading` then enable Kindle
   delivery via `python -m memanga config` (per-manga toggle).

PDFs over 18 MB are split automatically; EPUB / CBZ files can't be
split so they fail-loud with a size warning.

---

## 🌐 Sources

The default search sweep covers these 15 verified working aggregators
(popularity order):

| Source | Type | Notes |
|---|---|---|
| mangadex.org | API | Largest fan-translation library |
| mangapill.com | Requests | Fast, no Cloudflare |
| mangafire.to | Playwright | VRF bypass + image descrambling |
| mangabuddy.com | Playwright | Popular aggregator |
| weebcentral.com | Playwright | 1000+ series |
| mangakatana.com | Playwright | General library |
| comick.io | Playwright | Clean API |
| mangahub.io | Requests | Huge library |
| mangahere.cc | Requests | Reliable mirror |
| mangapanda.onl | Requests | MangaHub network |
| mangaclash.com | Playwright | Manhwa-heavy |
| mangahere.onl | Playwright | Alternate mirror |
| mangataro.org | Requests | ComicK replacement |
| luminousscans.com | Requests | Scanlation focus |
| tcbonepiecechapters.com | Requests | Jump titles (One Piece, JJK, MHA) |

200+ more aggregators are in the registry — toggle them on via
`python -m memanga sources`. See the
[full domain list](docs/SUPPORTED_SOURCES.md).

---

## 📂 Where your data lives

| Path | What |
|---|---|
| `~/.config/memanga/config.yaml` | Library, settings, source toggles |
| `~/.config/memanga/state.json` | Read/unread state, download history, source health |
| `~/.config/memanga/covers/` | Cover image cache |
| `~/Downloads/MeManga/<title>/` | Default download folder (changeable via `config`) |

Sensitive credentials (SMTP App Password) are stored in the OS keyring
(Keychain on macOS, Credential Manager on Windows, Secret Service on
Linux) — never in plain text on disk.

---

## ❓ FAQ

**Will my downloads work without internet?**
Yes — once a chapter is on disk it's just files in your download
folder. The CLI gracefully fails on network actions (Search, Check,
Download) when no connection is available.

**Does it phone home / send analytics?**
No. The CLI talks only to the manga sources you enable. No telemetry,
no crash reports auto-sent.

**Why does the first run take a while?**
It's downloading Playwright's Firefox driver (~90 MB) so it can scrape
JS-heavy sites. One-time. After that, startup is instant.

**A source I use stopped working — what now?**
- Run `python -m memanga sources` to see health status. If it's
  marked unhealthy, the site is genuinely down or changed its HTML.
  File an issue with the **Scraper broken** template.
- Use `python -m memanga update <title>` to switch the manga to a
  backup source until the scraper is fixed.

**Can I use this on a Raspberry Pi?**
Yes — the CLI runs anywhere Python 3.10+ runs. On a headless Pi a
typical setup is cron + `--auto` flag + `xvfb-run` for Playwright
sources. You can also use the Docker setup above if Docker is available
on the Pi.

**Why is there a separate `cli` branch?**
`main` ships a full PySide6 desktop app — useful, but heavy. Some
users only want the engine. This branch removes the GUI module,
PySide6, and the desktop-only test suite so `pip install` is faster
and the venv is smaller. Both branches read and write the same
config + state files, so you can switch between them freely.

---

## 🤝 Contributing

PRs welcome — bug fixes, new scrapers, CLI polish, all of it.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, test
commands, and PR checklist. There are issue templates for
[bugs](.github/ISSUE_TEMPLATE/bug_report.md),
[features](.github/ISSUE_TEMPLATE/feature_request.md), and
[broken scrapers](.github/ISSUE_TEMPLATE/scraper_broken.md).

GUI-related PRs should target `main`, not `cli`. Engine fixes can
land on either — keep them GUI-free when targeting `cli` so the
branches don't drift further than necessary.

For security-sensitive reports, see [SECURITY.md](SECURITY.md).

## 📄 License

MIT — see [LICENSE](LICENSE).
