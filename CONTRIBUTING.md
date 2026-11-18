# Contributing to MeManga

Thanks for taking the time to contribute! This guide covers setting up
the project locally, running the tests and getting a pull request landed.
The [developer pages](https://meellm.github.io/MeManga/developer/contributing)
on the documentation site go into more detail.

## Code of Conduct

Be kind. Treat other contributors the way you'd want to be treated.
Disagreements are fine; personal attacks aren't.

MeManga's [Code of Conduct](CODE_OF_CONDUCT.md) is the Contributor
Covenant 2.1. Report conduct problems privately by email to
`info.meellm@gmail.com`, not in a public issue or discussion.

## Quick start

[Set up for development](https://meellm.github.io/MeManga/developer/contributing) is the full guide:
system libraries, running MeManga from the clone, browser components,
tests, what CI runs and the generated files. The short version, as CI
installs it:

```bash
git clone https://github.com/meellm/MeManga.git
cd MeManga
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements/dev.txt   # pinned: gui extra + test tools
python -m pip install --no-deps -e .                             # the package itself, editable
python -m pytest                                                 # the default test run
```

`memanga setup` or `python -m playwright install firefox chromium`
installs the browser components. Only sources that use a browser and the
live probes need them.

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

[Architecture](https://meellm.github.io/MeManga/developer/architecture#where-to-change-what) maps
the modules and says where to change what.

## Running the tests

```bash
python -m pytest                          # the default run: everything but the live probes
python -m pytest tests/unit/test_api.py   # one file while you work
python -m pytest -n auto                  # the default run in parallel
python -m pytest -m live tests/scrapers/live/   # live probes against the real sites, opt-in
```

[Run the tests](https://meellm.github.io/MeManga/developer/contributing#run-the-tests) explains the
defaults and markers, and [Write a scraper](https://meellm.github.io/MeManga/developer/scrapers#live-probe)
the live probes. Pushes and pull requests to `main` run the CI workflow;
[What CI runs](https://meellm.github.io/MeManga/developer/contributing#what-ci-runs) lists every
workflow and when it runs.

## Adding a scraper

[Write a scraper](https://meellm.github.io/MeManga/developer/scrapers)
explains each step, the fixtures, the tests and the live probe in detail.

1. Drop `memanga/scrapers/newsite.py` (or pick a template under
   `memanga/scrapers/templates/` and add an entry to
   `memanga/scrapers/registry.py`).
2. Subclass `BaseScraper` (or `PlaywrightScraper` if JS-rendered). If the
   site sits behind Cloudflare's JavaScript check, call
   `self._use_cloudscraper()` in `__init__` (optionally with a browser
   profile such as `CLOUDSCRAPER_CHROME_DESKTOP`) instead of importing
   `cloudscraper` yourself. cloudscraper is best-effort: it stops working
   when a site raises its protection, so a source that needs a real
   browser should use `PlaywrightScraper`. When a block or challenge page
   still comes back, raise a clear error instead of parsing it as content.
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

The pull request template has the same items, except the commit style
and the generated files, which are listed only here.

- [ ] `pytest` passes locally
- [ ] New behaviour has tests (or notes saying why not)
- [ ] No `print()` debug noise left in production code
- [ ] Commit messages follow the style above
- [ ] No secrets, `.env`, or personal config in the diff
- [ ] Generated files are regenerated when their inputs changed
- [ ] If you touched a scraper, you ran the live probe at least once

## Building executables

```bash
python build.py        # dev build with a console: MeManga-Dev[.exe] in the repo root
python build_app.py    # release build, no console: release/MeManga and release/THIRD_PARTY_NOTICES.txt
```

Both install `requirements/build.txt` into the current environment first,
so run them in a virtual environment made for building, and both delete
the `build/` and `dist/` scratch folders when they succeed.
`python build_app.py --no-install` builds from the packages already
installed. [Build and release](https://meellm.github.io/MeManga/developer/build-release#build-the-desktop-app) describes
the outputs on each system and how a version is released.

### macOS signing and notarization

Signing and notarization of the macOS downloads are optional and need a
paid Apple Developer Program membership. The release workflow uses them
only when all six repository secrets are set; without them it still
publishes unsigned, unnotarized `MeManga.app` zips. The secrets and what
the workflow checks are listed under
[macOS signing and notarization](https://meellm.github.io/MeManga/developer/build-release#macos-signing-and-notarization).

### Dependency locks

`pyproject.toml` is the only place dependencies are declared; the files in
`requirements/` are generated from it, pinned with hashes. After changing
the dependencies or `[tool.lock-dependencies]`, regenerate them (needs
uv 0.13.1 and the network) and commit both:

```bash
python -m pip install "uv==0.13.1"
python scripts/lock_dependencies.py
git add pyproject.toml requirements/
```

Never edit the files by hand. `python scripts/lock_dependencies.py --check`
verifies them; [Dependency locks](https://meellm.github.io/MeManga/developer/build-release#dependency-locks) explains the
files, `--check`, `--check --offline` and `--check-installed build`.

## Translations

The desktop app, the command line and the documentation are in English
only today, and translations are welcome.
[Translations](https://meellm.github.io/MeManga/developer/contributing#translations)
explains how to start: with an issue that names the language and a small
first part to translate.

## Reporting issues

See [SECURITY.md](SECURITY.md) for vulnerability reports. For
everything else, open a GitHub issue with the **Bug report** or
**Feature request** template.
