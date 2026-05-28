# MeManga test suite (CLI branch)

Run the whole suite:

```bash
pip install -r tests/requirements-test.txt
pytest                          # full suite
pytest -x                       # stop on first failure
pytest -k state                 # only tests with "state" in the name
pytest tests/unit/              # only unit tests
pytest --cov=memanga --cov-report=html   # HTML coverage report
```

## Layout

| Folder | What's in it |
|---|---|
| `unit/test_state.py` | Every `State` method — chapter tracking, notifications, search history, source health, reset, JSON persistence. |
| `unit/test_config.py` | `Config` load/save, dotted-key get/set, manga list mutations, keyring app-password helpers. |
| `unit/test_downloader.py` | `check_for_updates`, `download_chapter`, `_sanitize_filename`, format conversion paths, fallback delay logic. |
| `unit/test_emailer.py` | SMTP send wrapping, attachment building, error paths. |
| `unit/scrapers/` | `BaseScraper` interface conformance + per-scraper smoke tests (mocked HTTP). |
| `unit/cli/` | `argparse` wiring, each subcommand's handler. |
| `scrapers/` | Per-scraper parsing tests (fixture-driven) and the opt-in live health probes under `scrapers/live/`. |

## Conventions

- **Fixtures** in `conftest.py` are reusable across files. The big ones:
  - `isolated_home` – per-test tmp HOME so config/state never leak
  - `state` / `config` – clean instances pointed at tmp HOME
  - `sample_manga` – canonical manga dict
  - `patch_get_scraper` – inject `MockScraper` so no real network calls
  - `make_cbz` – factory for synthetic chapter files

- **Markers** (declared in `pytest.ini`):
  - `@pytest.mark.integration` – multi-component flow
  - `@pytest.mark.slow` – >1s
  - `@pytest.mark.network` – needs real network (skipped by default)
  - `@pytest.mark.live` / `@pytest.mark.health` – hits real scraper
    sites (skipped by default; opt in with `-m live`)

- **No real network**: tests must mock or patch HTTP. The `MockScraper`
  fixture is a drop-in for any real scraper.

## What's covered

- ✓ Every `State` public method
- ✓ Every `Config` public method
- ✓ Every scraper's parsing path (fixture-driven)
- ✓ CLI subcommand parsing + handlers
- ✓ Downloader retry / fallback / format conversion paths

## What's NOT covered (deliberately)

- Live scraper HTTP (mocked instead — see `MockScraper`); opt-in
  health probes live under `scrapers/live/`.
- The PySide6 desktop app — that lives on the `main` branch with its
  own suite.

## Adding a test

1. Pick the right folder (`unit/` for one class, `scrapers/` for a
   scraper).
2. Add `test_<thing>.py`.
3. Pull in fixtures from `conftest.py`.
4. Mark slow / network / live tests with the matching marker.
