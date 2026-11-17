# MeManga tests

The automated tests of MeManga. How to install the test tools, what the
defaults are and what CI runs are on the documentation site:

- [Install for development](https://meellm.github.io/MeManga/developer/contributing#install-for-development)
- [Run the tests](https://meellm.github.io/MeManga/developer/contributing#run-the-tests)
- [What CI runs](https://meellm.github.io/MeManga/developer/contributing#what-ci-runs)

## Run tests

From the root of the clone, with the development environment active:

```sh
python -m pytest tests/unit/test_api.py             # one file
python -m pytest tests/unit/test_api.py -k reload   # tests in it by name
python -m pytest tests/unit --ignore=tests/unit/gui # the non-GUI unit tests
python -m pytest -n auto                            # the default run, in parallel
```

## Layout

| Folder | What it holds |
|---|---|
| `unit/` | Tests of one module or area each: config, state and its stores, the downloader and chapter pipeline, email, search, scheduling, the docs generators, packaging and the workflow files |
| `unit/cli/` | The command-line commands and their output |
| `unit/gui/` | The desktop app: `components/`, `pages/` and `theme/`, plus the window, background workers, events, caches, keyboard use and accessible names |
| `unit/scrapers/` | The scraper base class, the browser worker, the source catalog and registry, and a few scrapers in depth |
| `unit/fixtures/` | Data files for unit tests, such as config and state files in older layouts |
| `scrapers/` | Parser tests that run each scraper on saved pages and responses in `scrapers/fixtures/`, one file per site or template family |
| `scrapers/live/` | Live probes against the real sites, only run when selected (see below) |
| `integration/` | Flows across several parts, mostly through the desktop window |

## Shared fixtures

`conftest.py` provides these to every test:

- `isolated_home` points `HOME`, `USERPROFILE`, `APPDATA` and
  `XDG_CONFIG_HOME` at the test's temporary folder, pins the default
  config folder there, and removes `MEMANGA_CONFIG_DIR` and a few other
  variables a developer may have set. It is not automatic: a test that
  reads or writes config, state or the home folder must request it,
  directly or through one of the fixtures below.
- `config` and `state` are fresh `Config` and `State` objects in the
  isolated home.
- `qapp` is the one `QApplication` of the run, with the isolated home and a
  stand-in for the system trash. `theme` and `fresh_settings` reset the
  theme and Qt settings. `app_window` builds the whole main window, which
  is slow.
- `mock_scraper` and `patch_get_scraper` make `get_scraper()` return a
  scraper that answers from memory.
- `sample_manga`, `sample_manga_with_backup`, `make_cbz`, `declared_png`,
  `event_bus` and `lock_holder` build common inputs.

Three fixtures run for every test without being requested: they undo the
logging and console setup a command-line run leaves behind, drop the cached
scrapers, and make the code believe it is not running in a container.

`scrapers/conftest.py` adds `load_fixture`, `load_json_fixture`,
`patch_html`, `patch_json`, `patch_request` and `fake_response` for the
parser tests; see
[Write a scraper](https://meellm.github.io/MeManga/developer/scrapers#fixtures).

## Markers

`pytest.ini` registers the markers, and `--strict-markers` turns an
unregistered one into an error.

- `live` and `health` mark the probes in `scrapers/live/`. The default run
  leaves them out; `-m live` selects them. See
  [Live probe](https://meellm.github.io/MeManga/developer/scrapers#live-probe).
- `integration`, `slow`, `network` and `gui` are labels. The default run
  includes them; select or skip them with `-m`, for example
  `-m "not integration"`.

Outside the live probes the tests use saved responses and mocks, but
nothing in the setup blocks network access.

## What the tests show

Each test checks the behaviour its assertions cover, mostly with saved
pages, mocks and Qt's offscreen platform. A passing run does not show that
a site works today, or how the desktop app looks and sounds to a person.
Those are checked by the live probes and by hand: the
[accessibility checklist](../docs/ACCESSIBILITY.md) covers a screen
reader and keyboard pass.

## Adding a test

- Put it in the folder of its area, in a file named `test_*.py`.
- Use the fixtures above; never create a `QApplication` yourself, and use
  `isolated_home` for anything that touches config, state or the home
  folder.
- Use saved responses instead of real sites. A parser test declares what
  it covers in `PARSER_TESTS`; see
  [Offline parser tests](https://meellm.github.io/MeManga/developer/scrapers#offline-parser-tests).
- Every test file must fall in one CI test shard;
  `tests/unit/test_ci_workflows.py` checks this.
