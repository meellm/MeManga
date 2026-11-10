# MeManga test suite

Run the whole suite:

The GUI tests need Qt, which is the package's `gui` extra. The `dev`
extra has it and the test tools; install them at the pinned versions,
then the project:

```bash
pip install -r requirements/dev.txt
pip install --no-deps -e .
pytest                          # full suite
pytest -x                       # stop on first failure
pytest -k state                 # only tests with "state" in the name
pytest tests/unit/              # only unit tests
pytest tests/integration/       # only integration
pytest --cov=memanga --cov-report=html   # HTML coverage report
```

## Layout

| Folder | What's in it |
|---|---|
| `unit/test_state.py` | Every `State` method — chapter tracking, notifications, search history, source health, reset, JSON persistence. |
| `unit/test_state_stores.py` | Domain stores behind `State` — compatibility wrappers, shared file/lock, `state.json` schema compatibility, common CLI and GUI state flows. |
| `unit/test_config.py` | `Config` load/save, dotted-key get/set, manga list mutations, keyring app-password helpers. |
| `unit/test_downloader.py` | `check_for_updates`, `download_chapter`, `_sanitize_filename`, format conversion paths, fallback delay logic. |
| `unit/test_downloader_modules.py` | `memanga.downloader` package layout — re-exported import surface, submodule dependency direction, browser cleanup registration. |
| `unit/test_emailer.py` | SMTP send wrapping, attachment building, error paths. |
| `unit/scrapers/` | `BaseScraper` interface conformance + per-scraper smoke tests (mocked HTTP). |
| `unit/gui/theme/` | Token table, flat() helper, QSS builder substitution. |
| `unit/gui/components/` | One file per widget — instantiation, theme reactivity, signal emission. |
| `unit/gui/pages/` | One file per page — header rendering, event subscription, `on_show`, refresh on event. |
| `unit/gui/pages/test_page_modules.py` | Settings and Reader page layout — tab and reader mixins, import direction, Qt class names, reader input dispatch, reader view-mode resolution. |
| `unit/gui/test_workers.py` | BackgroundWorker pool, pause/resume, ping_sources, cancel_download. |
| `unit/gui/test_events.py` | EventBus pub/sub, polling, thread safety. |
| `unit/gui/test_cache.py` | CoverCache disk/memory LRU, placeholders. |
| `unit/gui/test_keyboard_navigation.py` | Keyboard activation of cards and drop-downs, keyboard-only focus rings, focus following page changes and quick actions, no scroll-area Tab stops, dialog Tab order, page shortcuts, reader keys. |
| `unit/cli/` | `argparse` wiring, each subcommand's handler. |
| `integration/` | End-to-end flows that span multiple components. |

## Conventions

- **Fixtures** in `conftest.py` are reusable across files. The big ones:
  - `qapp` – shared QApplication (offscreen)
  - `isolated_home` – per-test tmp HOME so config/state never leak
  - `theme` – theme module with `_current` reset
  - `state` / `config` – clean instances pointed at tmp HOME
  - `sample_manga` – canonical manga dict
  - `patch_get_scraper` – inject `MockScraper` so no real network calls
  - `app_window` – fully-built MeMangaApp (slow, use sparingly)
  - `make_cbz` – factory for synthetic chapter files

- **Markers** (declared in `pytest.ini`):
  - `@pytest.mark.integration` – multi-component flow
  - `@pytest.mark.slow` – >1s
  - `@pytest.mark.network` – needs real network (skipped by default)
  - `@pytest.mark.gui` – requires QApplication

- **No real network**: tests must mock or patch HTTP. The `MockScraper`
  fixture is a drop-in for any real scraper.

## What's covered

- ✓ Every `State` public method
- ✓ Every `Config` public method
- ✓ Theme tokens + QSS builder
- ✓ Every component widget (instantiation + theme switch)
- ✓ Every page (constructor + on_show + event reaction)
- ✓ Worker pool semantics (queue, cancel, pause/resume, ping)
- ✓ EventBus thread safety
- ✓ CoverCache disk persistence
- ✓ CLI subcommand parsing
- ✓ End-to-end download flow
- ✓ Modal flow (Add Manga, Download From Chapter)
- ✓ Theme switch end-to-end

## What's NOT covered (deliberately)

- Live scraper HTTP (mocked instead — see `MockScraper`)
- PyInstaller packaging (separate `python build.py`)
- macOS-specific frame chrome (`launch_gui` ensure-browsers flow)
- How a real screen reader speaks the GUI (accessible names are unit-tested;
  see `docs/ACCESSIBILITY.md` for the manual pass)
- How focus rings look and the full Tab order of each page (the rules and
  focus handling are unit-tested; see the keyboard checklist in
  `docs/ACCESSIBILITY.md`)

## Adding a test

1. Pick the right folder (`unit/` for one class, `integration/` for flows).
2. Add `test_<thing>.py`.
3. Pull in fixtures from `conftest.py` — never instantiate `QApplication`
   yourself.
4. Mark slow / network / integration tests with the matching marker.

## In CI

`.github/workflows/ci.yml` runs on pushes and pull requests to `main`
and before every release. The whole default suite runs once, on Linux
with Python 3.12, in four parts that run at the same time:

```bash
pytest -n auto --dist loadfile tests/unit --ignore=tests/unit/gui tests/scrapers
pytest -n auto --dist worksteal tests/unit/gui/pages
pytest -n auto --dist worksteal tests/unit/gui --ignore=tests/unit/gui/pages
pytest -n auto --dist worksteal tests/integration
```

Most GUI and integration tests build the main window, which is what
makes them slow, so those parts hand out single tests to the workers
rather than whole files. The non-GUI unit tests also run on Python 3.10
and 3.13, on Windows and, except for pull requests, on macOS. Every test
file must run in exactly one part (`tests/unit/test_ci_workflows.py`
checks this). The live probes run weekly in
`.github/workflows/scraper-health.yml`.

## Known failures

Some tests will fail today — that's intentional. The user asked for
exhaustive coverage first, then fix-as-we-go. Failures point at real
bugs or API drift. Each red test is a TODO.
