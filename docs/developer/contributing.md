# Set up for development

How to install MeManga from a clone for development, run it and its tests,
what the checks on GitHub run, how to write command-line output and how to
start a translation. To use MeManga rather than work on it, see
[Download and install](../guide/install).

## Install for development

You need Git and Python 3.11.5 or newer. CI tests Python 3.11, 3.12 and
3.13.

The development install uses the same two steps as CI: first the pinned
test dependencies from `requirements/dev.txt`, then MeManga itself as an
editable install without dependencies.

::: code-group

```sh [Linux and macOS]
git clone https://github.com/meellm/MeManga.git
cd MeManga
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/dev.txt
python -m pip install --no-deps -e .
```

```powershell [Windows]
git clone https://github.com/meellm/MeManga.git
cd MeManga
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements/dev.txt
python -m pip install --no-deps -e .
```

:::

- `requirements/dev.txt` pins every package, the desktop app's Qt
  included, to an exact version with hashes, so pip checks every download.
  Because the file has hashes, pip requires them for everything installed
  in the same command, so MeManga itself goes in a second command with
  `--no-deps`
  ([pip: secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)).
- The editable install (`-e`) runs the code in the clone, so changes take
  effect without installing again. Install again after changing the
  package's metadata in `pyproject.toml`, such as its entry points
  ([pip: local project installs](https://pip.pypa.io/en/stable/topics/local-project-installs/)).
- After a change to the dependencies, install `requirements/dev.txt`
  again. How the files in `requirements/` are made is described under
  [Dependency locks](./build-release#dependency-locks).

**Linux system libraries.** The desktop app and its tests need Qt's
system libraries. A desktop Linux usually has them. On a bare Ubuntu
system, CI installs these:

```sh
sudo apt-get install libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
  libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xkb1 \
  libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3
```

## Run MeManga from the clone

With the virtual environment active:

| Command | Starts |
|---|---|
| `memanga` | The command line; `memanga --help` lists the commands |
| `memanga --gui` or `memanga-gui` | The desktop app |
| `python -m memanga.gui` | The desktop app, as a module |

To keep your own library out of the way while you work, give a test folder
with `--config-dir` or `MEMANGA_CONFIG_DIR`; see
[where MeManga keeps its files](../guide/install#where-memanga-keeps-its-files).

## Browser components

Sources that need a browser use Playwright's Firefox and Chromium. They
are needed to use such sources for real and for the
[live probes](./scrapers#live-probe). The default test run does not
download them. Install them with:

```sh
memanga setup
```

or directly with `python -m playwright install firefox chromium`. On
Linux, when `memanga setup` finds that system libraries the browsers need
are missing, follow its instructions for your system.

## Run the tests

`pytest.ini` sets the defaults:

- The tests in `tests/` run, except those marked `live` or `health`. Those
  use real sites; a marker expression given with `-m`, such as `-m live`,
  selects them. See [Write a scraper](./scrapers#live-probe).
- Qt runs on its offscreen platform, so no window opens.
- The ten slowest tests are listed after the run.

While you work, run the tests of the area you change, then the wider set
before you push:

```sh
# One file, or one test by name
python -m pytest tests/unit/test_api.py
python -m pytest tests/unit/test_api.py -k reload

# The non-GUI unit tests
python -m pytest tests/unit --ignore=tests/unit/gui

# Everything the default run includes, in parallel
python -m pytest -n auto
```

The other markers, `integration`, `slow`, `network` and `gui`, only label
tests; the default run does not leave them out. Use
`-m "not integration"` to skip the integration tests.

The tests are written to use saved responses and mocks instead of real
sites, and the `isolated_home` fixture in `tests/conftest.py` gives a test
a temporary home folder. Nothing in the test setup blocks network access
or protects your own config folder for a test that does not use that
fixture.

Every test file must fall in exactly one of the CI test shards listed
below, so a test folder outside their paths needs a shard of its own;
`tests/unit/test_ci_workflows.py` checks this.

## What CI runs

The workflows in `.github/workflows/` run on GitHub:

| Workflow | When | What |
|---|---|---|
| CI (`ci.yml`) | Pushes and pull requests to `main`; by hand; from the release workflow | See below |
| Source docs (`source-docs.yml`) | Pushes and pull requests to `main`; by hand | `--check` of `source_docs`, `cli_docs` and `config_docs` (see [Generated files](#generated-files)) |
| Dependency locks (`dependency-locks.yml`) | Pushes and pull requests to `main`; by hand | `python scripts/lock_dependencies.py --check` |
| Dependency audit (`dependency-audit.yml`) | Changes to `requirements/`, `pyproject.toml` or the audit settings on `main` and its pull requests; weekly; by hand; before a release | Known vulnerabilities in the pinned packages |
| Documentation site (`docs.yml`) | Pushes to `main` that change `docs/`, a file the site shows or the workflow itself ([full list](https://github.com/meellm/MeManga/blob/main/.github/workflows/docs.yml)) | Builds and publishes this site |
| Scraper health (`scraper-health.yml`) | Weekly; by hand | The live probes; never on pushes or pull requests |
| Build & Release, Docker Image | Version tags; the image also by hand | Release builds and the Docker image |

**The CI workflow:**

- **lint:** Ruff with only the rules for code that cannot run: syntax
  errors, invalid comparisons and statements, undefined names.
- **package:** builds the sdist and wheel, checks their metadata, installs
  the wheel over `requirements/cli.txt` and runs `memanga --help`.
- **tests:** the whole default run, on Linux with Python 3.12, in four
  shards: `core` (`tests/unit` without `tests/unit/gui`, and
  `tests/scrapers`), `gui-pages`, `gui` and `integration`.
- **core tests:** `tests/unit` without `tests/unit/gui`, on Python 3.11 and
  3.13 on Linux and on Python 3.12 on Windows. On macOS (Python 3.12) only
  for pushes to `main`, runs by hand and releases, not for pull requests.

To run the lint check as CI does:

```sh
python -m pip install "ruff==0.17.4"
ruff check --select E9,F63,F7,F82 --target-version py311 .
```

## Generated files

Some files are made from the code. When you change what they are made
from, regenerate them and commit the result; CI fails when one is out of
date.

| Change | Regenerate with | Writes |
|---|---|---|
| A command, an option or its help | `python -m memanga.cli_docs` | `docs/reference/cli-commands.md` |
| A setting or its default | `python -m memanga.config_docs` | `docs/reference/config-keys.md` |
| A source, its catalog entry, a `PARSER_TESTS` declaration or `docs/data/supported-websites.yaml` | `python -m memanga.source_docs` | The source lists, the source counts in the README and the guide, and `memanga/scrapers/coverage_data.py` |
| A dependency in `pyproject.toml` | `python scripts/lock_dependencies.py` (needs uv 0.13.1 and the network) | `requirements/*.txt` |

Each of the three `python -m` commands takes `--check` to compare without
writing.

The documentation site lives in `docs/` and needs Node.js 20 or newer:

```sh
cd docs
npm ci
npm run dev      # local preview while you write
npm run build    # the build CI runs
```

## Command-line output

How `memanga` prints today, then the rules for messages you add or change.
`memanga/cli.py` and `memanga/output.py` are the reference for the
development version.

### How output works today

- **Two consoles.** `console` writes to standard output and `err_console`
  to standard error. Results go to `console`. `_error()` prints an error on
  `err_console`. `_diagnostic()` reports a warning or error as a log record,
  so `memanga -q` and the log level decide whether it shows. It takes both
  the styled text and a plain message.
- **The split is not complete.** Some commands also print hints, warnings
  or progress on standard output; see
  [Output](../reference/scripting#output).
- **Plain or styled, per stream.** Standard output and standard error are
  decided separately, so one can be plain while the other is styled. A
  stream is plain with `--plain`, with `TERM=dumb`, or when it is not a
  terminal. `NO_COLOR` turns off colour only.
- **What plain output removes.** Colour, live widgets, line wrapping, box
  drawing and the icons listed in `APP_DECORATION`. Other Unicode stays,
  such as `→` or a `★` in a title. `_panel()` and `_table()` drop their
  frames when standard output is plain.
- **JSON.** With `--json`, standard output carries only the JSON document.
  `_print_json()` is the helper for this.

### For new or changed messages

Existing messages vary, and many do not follow these rules yet: for
example, several still say `chapter(s)`. Change an existing message on
purpose, together with any test that checks its text.

- **Status.** Do not carry meaning in an icon or colour alone, because plain
  output drops them. When a line or column needs a status word, use `OK`,
  `NEW`, `SKIP`, `WARN` or `FAIL`. In plain output, `memanga doctor` already
  prints `OK`, `WARN`, `FAIL` and `SKIP`. `NEW`, for something newly found,
  is the word to use from now on; no command prints it yet.
- **Grammar.** Write `<subject>: <what happened> (<detail>)`, as in
  `Some Title: check failed (connection timed out)`.
- **Plurals.** Use the real singular and plural, `1 chapter` and
  `2 chapters`, not `chapter(s)`.
- **Plain words.** Use terms a user knows. Keep class names and other
  internal details out of normal output.
- **Escaping.** Pass every value you insert into Rich markup, such as a
  title, path, URL or error text, through `_esc()`. Otherwise brackets in
  the value can [act as markup](https://rich.readthedocs.io/en/stable/markup.html#escaping).
- **Icons.** Add a new icon to `APP_DECORATION` in `memanga/output.py`, or
  plain output will keep it.
- **JSON.** Keep `--json` output to the JSON document alone. Send
  diagnostics to standard error, because
  [scripts read this output](../reference/scripting#json-output).

## Translations

Translations are welcome. Today MeManga is in English only:

- The desktop app and the command line show their text in English. The
  text is written directly in the code: there is no translation catalogue
  and nothing that loads translations yet.
- This site has one language, English.

This is about the language of MeManga itself. The language of the manga
you read comes from the source: the
[Language column](../reference/sources#the-columns) of the source list
shows it for a source that has only one, and MangaDex chapters are
requested in English. Translating MeManga does not change what a source
offers.

### Start with an issue

Because there is nothing to add a translation to yet, a translation starts
with a plan rather than a file:

1. Open an issue with the **Feature request** template. Name the language
   and say what you would translate first: the desktop app, the command
   line or pages of this site. A small first part, such as one page of the
   desktop app, is easier to agree on and review.
2. Agree in the issue on how it will work before translating a whole app
   or many pages. For the desktop app that means how text is marked for
   translation and how translations are loaded; for this site, how a second
   language is laid out.
3. Then open a pull request for the part you agreed on.

### Background

The libraries MeManga is built on have translation support. MeManga does
not use it yet; these pages explain how it works.

- **Desktop app:** Qt for Python's
  [Translating Applications](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/translations.html)
  marks text with `tr()` and loads translations with `QTranslator`. Qt's
  [Writing Source Code for Translation](https://doc.qt.io/qt-6/i18n-source-translation.html)
  explains why text put together from pieces or from template strings
  cannot be translated as it is. Some of MeManga's text is put together
  with Python f-strings, so that text needs changing first.
- **This site:** VitePress, which builds it, supports more than one
  language with its `locales` setting. See
  [Internationalization](https://vuejs.github.io/vitepress/v1/guide/i18n)
  for the VitePress version this site uses.

## Commits and pull requests

- Commit messages follow Conventional Commits, such as `fix(gui): ...` or
  `docs: ...`; [CONTRIBUTING](https://github.com/meellm/MeManga/blob/main/CONTRIBUTING.md#commit-style)
  has examples.
- Open pull requests against `main`. The pull request template asks for a
  summary, the type of change, and a checklist: tests pass, new behaviour
  has tests, no debug output, no secrets or personal config in the diff,
  and a live probe for a scraper change.
- Report security problems privately, as the
  [security policy](https://github.com/meellm/MeManga/blob/main/SECURITY.md)
  describes.

## Where to go next

- [Architecture](./architecture): how the parts fit together and where to
  change what.
- [Write a scraper](./scrapers): adding or fixing a source.
- [Build and release](./build-release): desktop builds, dependency locks
  and releases.
- [Python API](../reference/python-api): the supported Python interface.
