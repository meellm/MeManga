# Contributing to MeManga

Thanks for taking the time to contribute! This guide covers everything
you need to set up the project locally, run the tests, and get a pull
request landed.

## Code of Conduct

Be kind. Treat other contributors the way you'd want to be treated.
Disagreements are fine; personal attacks aren't.

## Quick start

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga

# Create a venv and install everything (deps + dev deps)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"           # also pulls pytest, pyinstaller, etc.

# Run the GUI
python -m memanga.gui

# Run the CLI
python -m memanga --help
```

The GUI launches in offscreen mode in CI (`QT_QPA_PLATFORM=offscreen`);
locally it opens the real Qt window.

## Project layout

```
memanga/
├── cli.py              # CLI entry point (memanga.cli:main)
├── config.py           # YAML config persistence
├── state.py            # State journal (downloaded chapters, etc.)
├── downloader.py       # Chapter download + format conversion
├── emailer.py          # Kindle/SMTP delivery
├── scrapers/           # 200+ site scrapers
│   ├── base.py         # BaseScraper / Chapter / Manga dataclasses
│   ├── playwright_base.py
│   ├── templates/      # NuxtSSR, OGImageMeta, WordPressMadara, …
│   └── *.py            # Per-site scrapers
└── gui/
    ├── app.py          # MeMangaApp QMainWindow
    ├── pages/          # Library / Detail / Reader / Settings / Sources
    ├── components/     # Reusable widgets
    ├── workers.py      # Background thread pool + EventBus dispatch
    └── theme/          # tokens + QSS builder

tests/                  # Unit + integration tests
docs/                   # User-facing documentation
examples/               # Sample config + state
packaging/              # PyInstaller specs (dev + release)
scripts/                # Platform setup scripts
```

## Running the tests

```bash
# Full suite (fast — uses fixtures, no real network)
pytest

# Only unit
pytest tests/unit

# Only GUI
pytest tests/unit/gui

# Live scraper health checks (hits real sites — slow, opt-in)
pytest -m live tests/scrapers/live/
```

All checked-in tests should pass before you push. CI runs `pytest` on
every push.

## Adding a scraper

1. Drop `memanga/scrapers/newsite.py` (or pick a template under
   `memanga/scrapers/templates/` and add an entry to
   `memanga/scrapers/registry.py`).
2. Subclass `BaseScraper` (or `PlaywrightScraper` if JS-rendered).
3. Implement `search()`, `get_chapters()`, `get_pages()`.
4. Register the domain in `memanga/scrapers/__init__.py` (or the
   registry's `TEMPLATE_SCRAPERS` map for template-based scrapers).
5. Add a fixture-based test under `tests/scrapers/`.

## Commit style

Conventional Commits — `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`.
Scope optional, body explains *why*, not *what*. Keep the first line
under 70 characters.

Examples:
```
fix(gui): clear badge text when count drops to zero
feat(scrapers): register blamemanga, jjkmanga, kagane
docs: clarify Playwright first-launch download
```

## Pull request checklist

- [ ] Tests pass locally (`pytest`)
- [ ] New behaviour has tests
- [ ] No `print()` debug noise left in production code
- [ ] Commit messages follow the style above
- [ ] No secrets, `.env`, or personal config in the diff
- [ ] If you touched a scraper, you noted whether you tested it live

## Building executables

```bash
python build.py        # Single-file dev exe with console (MeManga-Dev.exe)
python build_app.py    # Single-file release exe, no console (MeManga.exe)
```

Both scripts move the final binary to the repo root and sweep the
`build/` + `dist/` scratch directories.

### Dependency pinning for release builds

The dev build (`build.py`) installs from `requirements.txt`
(`>=` ranges) so you get the latest patch-level updates while
iterating.

The release build (`build_app.py`) installs from
**`requirements-lock.txt`** — exact pins for every direct **and
transitive** dependency. This is what makes the binary on every
GitHub release reproducible six months later from the same git tag.

**When to refresh the lock:**
- Any time you bump a dependency in `requirements.txt`.
- Before cutting a release tag.

**How to refresh:**

```bash
pip install pip-tools
pip-compile --output-file=requirements-lock.txt --strip-extras requirements.txt
git add requirements-lock.txt
git commit -m "chore(deps): refresh requirements-lock.txt"
```

`pip-compile` walks the full transitive tree once and writes one
row per package with the resolved version + the chain that pulled
it in. If a security advisory drops, bump the offending package in
`requirements.txt` and re-run pip-compile — the lock will
recompute consistently.

## Reporting issues

See [SECURITY.md](SECURITY.md) for vulnerability reports. For
everything else, open a GitHub issue with the **Bug report** or
**Feature request** template.
