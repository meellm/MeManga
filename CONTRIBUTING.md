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
pip install -r requirements/dev.txt   # pinned: gui extra + test tools
pip install --no-deps -e .            # the package itself, editable
python -m playwright install chromium firefox   # browsers for the scrapers

# Or run the one-step setup instead (venv, deps, browsers, config folder):
# python scripts/bootstrap.py

# Run the GUI
python -m memanga.gui

# Run the CLI
python -m memanga --help
```

The GUI launches in offscreen mode in CI (`QT_QPA_PLATFORM=offscreen`);
locally it opens the real Qt window.

### Package extras

`pip install .` installs the CLI only; PySide6 is not a default
dependency. The extras in `pyproject.toml`:

| Extra | Adds | Use it for |
|---|---|---|
| `gui` | PySide6 | Running the desktop app (`memanga --gui`, `memanga-gui`) |
| `dev` | `gui` plus pytest, pytest-qt, pytest-mock, pytest-env, pytest-xdist, pytest-cov, packaging | Running the test suite; the GUI tests need Qt |
| `build` | `gui` plus PyInstaller, certifi and (on Windows) pywin32-ctypes | Desktop builds |

`pyproject.toml` is the only place dependencies are declared; the
pinned installs in `requirements/` are generated from it (see
[Dependency locks](#dependency-locks)). A new dependency that only the
GUI imports goes in the `gui` extra, never in `dependencies`.
Code outside `memanga/gui/` must not import Qt at import time;
`tests/unit/test_optional_gui.py` checks that and the metadata.

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
scripts/                # Setup (bootstrap.py) and launcher scripts
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

# Curated end-to-end probes only — each walks search → chapters →
# pages → image and a failure names the first broken stage
pytest -m live tests/scrapers/live/test_live_parsing.py -v

# Machine-readable report (per-stage details + failures_by_stage)
pytest -m live tests/scrapers/live/ --health-report=health.json
```

All checked-in tests should pass before you push. CI runs `pytest` on
every push.

## Adding a scraper

1. Drop `memanga/scrapers/newsite.py` (or pick a template under
   `memanga/scrapers/templates/` and add an entry to
   `memanga/scrapers/registry.py`).
2. Subclass `BaseScraper` (or `PlaywrightScraper` if JS-rendered). If the
   site sits behind Cloudflare's JavaScript check, call
   `self._use_cloudscraper()` in `__init__` (optionally with a browser
   profile such as `CLOUDSCRAPER_CHROME_DESKTOP`) instead of importing
   `cloudscraper` yourself. cloudscraper is best-effort: it stops working
   when a site raises its protection, so a source that needs a real
   browser should use `PlaywrightScraper`.
3. Implement `search()`, `get_chapters()`, `get_pages()`.
4. Register the domain in `_SCRAPER_PATHS` in `memanga/scrapers/__init__.py`
   as `"newsite:NewSiteScraper"` (module and class; it is imported on first
   use), or in the registry's `TEMPLATE_SCRAPERS` map for template-based
   scrapers.
5. Add a fixture-based test under `tests/scrapers/`.
6. Declare `engine`, `content_language`, and `nsfw` on the scraper class
   where applicable. Add per-domain search skips or notes in
   `memanga/scrapers/catalog.py` when needed.
7. Regenerate the source lists with `python -m memanga.source_docs`.

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
python build_app.py    # Release app, no console (release/MeManga/)
```

`build.py` moves the dev exe to the repo root. `build_app.py` puts the
release app under `release/`: a one-folder app (`MeManga[.exe]` plus
`_internal/`) on Windows and Linux, a one-file binary on macOS. Both
sweep the `build/` + `dist/` scratch directories.

### macOS signing and notarization

Signing and notarization are optional and need a paid Apple Developer
Program membership. When all of these repository secrets are set, tag
builds sign the macOS apps with a Developer ID Application certificate,
notarize them with Apple and staple the ticket before upload, and the
release job fails if any of those steps or the Gatekeeper check fails:

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE_BASE64` | Base64 of the Developer ID Application `.p12` export |
| `MACOS_CERTIFICATE_PASSWORD` | Password of that `.p12` |
| `MACOS_CODESIGN_IDENTITY` | Identity name, e.g. `Developer ID Application: Name (TEAMID)` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_TEAM_ID` | Ten-character Apple Developer Team ID |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password for that Apple ID |

If any secret is missing the release workflow logs a warning and still
publishes unsigned, unnotarized `MeManga.app` zips. They pass the same
bundle, architecture and Playwright checks, but Gatekeeper may report
them as damaged or from an unidentified developer until the user clears
the quarantine flag (see the README).

Local `python build_app.py` runs on a Mac stay unsigned (ad-hoc) unless
`MEMANGA_CODESIGN_IDENTITY` is set; hardened-runtime entitlements live in
`packaging/macos-entitlements.plist`.

### Dependency locks

`pyproject.toml` declares every dependency: `dependencies` for the CLI
and the `gui`, `dev` and `build` extras. Nothing else lists them. The
files in `requirements/` are generated from it, one per kind of install:

| File | Installs | Used by |
|---|---|---|
| `requirements/cli.txt` | `dependencies` | The Docker image, the source docs check |
| `requirements/gui.txt` | `dependencies` + `gui` | `scripts/bootstrap.py`, `scripts/linux/setup.sh` |
| `requirements/dev.txt` | `dependencies` + `dev` | Contributors and the test suite |
| `requirements/build.txt` | `dependencies` + `build` | `build.py`, `build_app.py` and the release workflow |

Each file pins every direct **and transitive** dependency to an exact
version, with hashes, for every platform and Python version MeManga
supports (environment markers select the rows that apply). pip then
installs the same versions everywhere and refuses a download whose hash
does not match. This is what makes the binary on every GitHub release
rebuildable from the same git tag with the same package versions, and
what keeps the Docker image on the release builds' versions.

**Which versions:** `[tool.lock-dependencies]` in `pyproject.toml`
decides that too. Each package is pinned at its newest release that fits
the declared bounds, as PyPI was at `resolve-at` (UTC), or at the time
listed for it under `resolve-package-at` (uv's `--exclude-newer` and
`--exclude-newer-package`). Files uploaded to PyPI after that time are
ignored as well, so the locks are a function of `pyproject.toml` alone
and come out the same whenever they are generated.

**When to refresh:** after any change to the dependencies or to
`[tool.lock-dependencies]` in `pyproject.toml`. To update a package (for
example for a security fix), move its time under `resolve-package-at`,
or move `resolve-at` to update all the others, then regenerate.
Generating needs [uv](https://docs.astral.sh/uv/) 0.13.1 and the network:

```bash
python -m pip install "uv==0.13.1"
python scripts/lock_dependencies.py
git add pyproject.toml requirements/
```

Never edit the files by hand.

`python scripts/lock_dependencies.py --check` first checks, without uv
or the network, that every file in `requirements/` was generated from the
current `pyproject.toml` and that none is missing or extra. It then
generates each file again from `pyproject.toml` alone, never from the
committed files, and compares the two, so any hand edit fails: a pin
moved to another version, even one that fits the bounds and carries that
version's valid hashes, a hash, marker or comment changed, a row removed
or added. It writes no file. The *Dependency locks* workflow runs it on
every pull request. `--check --offline` does only the first part;
`tests/unit/test_dependency_locks.py` runs that with the tests.

The dev build (`build.py`) and the release build (`build_app.py`) both
install `requirements/build.txt`, which includes PyInstaller. The Docker
image installs `requirements/cli.txt` with `--require-hashes`, then the
package itself with `--no-deps`; `pip check` fails the build if
`pyproject.toml` needs anything the lock does not provide.

## Reporting issues

See [SECURITY.md](SECURITY.md) for vulnerability reports. For
everything else, open a GitHub issue with the **Bug report** or
**Feature request** template.
