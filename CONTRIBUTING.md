# Contributing to MeManga (CLI branch)

Thanks for taking the time to contribute! This guide covers everything
you need to set up the CLI variant locally, run the tests, and get a
pull request landed.

> **GUI-related PRs should target the [`main` branch](https://github.com/meellm/MeManga/tree/main).**
> Engine and scraper fixes can land on either — keep them GUI-free
> when targeting `cli` so the two branches don't drift further than
> necessary.

## Code of Conduct

Be kind. Treat other contributors the way you'd want to be treated.
Disagreements are fine; personal attacks aren't.

## Quick start

```bash
git clone -b cli https://github.com/meellm/MeManga.git
cd MeManga

# Create a venv and install everything (deps + dev deps)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"

# Run the CLI
python -m memanga --help
```

## Project layout

```
memanga/
├── cli.py              # CLI entry point (memanga.cli:main)
├── config.py           # YAML config persistence
├── state.py            # State journal (downloaded chapters, etc.)
├── downloader.py       # Chapter download + format conversion
├── emailer.py          # Kindle/SMTP delivery
├── cron.py             # Crontab line builder
├── perf.py             # Optional timing instrumentation
└── scrapers/           # 200+ site scrapers
    ├── base.py         # BaseScraper / Chapter / Manga dataclasses
    ├── playwright_base.py
    ├── templates/      # NuxtSSR, OGImageMeta, WordPressMadara, …
    └── *.py            # Per-site scrapers

tests/                  # Unit + integration tests
docs/                   # User-facing documentation
examples/               # Sample config + state
scripts/                # Platform setup scripts
```

## Running the tests

```bash
# Full suite (fast — uses fixtures, no real network)
pytest

# Only unit
pytest tests/unit

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
2. Subclass `BaseScraper` (or `PlaywrightScraper` if JS-rendered).
3. Implement `search()`, `get_chapters()`, `get_pages()`.
4. Register the domain in `memanga/scrapers/__init__.py` (or the
   registry's `TEMPLATE_SCRAPERS` map for template-based scrapers).
5. Add a fixture-based test under `tests/scrapers/`.

## Dependency pinning

The dev install (`pip install -r requirements.txt`) uses `>=` ranges so
you get the latest patch-level updates while iterating.

**When to refresh the lock for Docker/reproducible builds:**

```bash
pip install pip-tools
pip-compile --output-file=requirements-docker.txt --strip-extras requirements.txt
git add requirements-docker.txt
git commit -m "chore(deps): refresh requirements-docker.txt"
```

## Commit style

Conventional Commits — `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`.
Scope optional, body explains *why*, not *what*. Keep the first line
under 70 characters.

Examples:
```
fix(scrapers): weebcentral now uses Playwright for chapter listing
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
- [ ] The change applies cleanly to `main` too (or you've explained
      why it's CLI-only)

## Reporting issues

See [SECURITY.md](SECURITY.md) for vulnerability reports. For
everything else, open a GitHub issue with the **Bug report** or
**Feature request** template.
