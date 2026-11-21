# Build and release

How the desktop app is built, how the pinned dependency files are kept up
to date, and what happens when a version is released. To set up a clone
for development first, see [Set up for development](./contributing).

## What gets built

| What | Built by | Where it ends up |
|---|---|---|
| The Python package (sdist and wheel) | The `package` job of CI, on every push and pull request to `main` | Nowhere yet: CI only checks it builds and starts. Installing from a package index is [not available yet](../guide/install#package-installs). |
| The desktop app | `build.py` and `build_app.py`, with PyInstaller | A local file or folder; on a version tag, the release downloads |
| The Docker image | The Docker Image workflow | GHCR and Docker Hub, on a version tag |

PyInstaller builds for the system it runs on; it does not build a Windows
app on Linux or the other way round
([PyInstaller: operating mode](https://pyinstaller.org/en/stable/operating-mode.html)).
The release workflow builds each download on its own runner.

## Build the desktop app

Both scripts run from the root of the clone and **change the Python
environment they run in**: they install `requirements/build.txt`, which
replaces the versions already installed. Use a virtual environment made
for building, not the one you develop in.

| | `python build.py` | `python build_app.py` |
|---|---|---|
| For | Trying a build, with a console window for tracebacks | The app as it is released, without a console |
| Installs first | `requirements/build.txt` | `requirements/build.txt`, only with hashes, wheels only, every package reinstalled |
| PyInstaller layout | One file | One folder on Windows and Linux; one file on macOS |
| Output | `MeManga-Dev.exe` (Windows) or `MeManga-Dev` in the root of the clone | `release/MeManga/` with `MeManga.exe` or `MeManga` and `_internal/` (Windows, Linux), or the file `release/MeManga` (macOS), plus `release/THIRD_PARTY_NOTICES.txt` |
| After the build | Moves the file to the root, deletes `build/` and `dist/` | Replaces `release/MeManga` and the notices file, deletes `build/` and `dist/`, and on Windows and Linux checks the folder with `packaging/third_party_notices.py check-bundle` |

Both scripts check that the main modules import before PyInstaller runs.
When PyInstaller fails, they leave `build/` and `dist/` in place to look
at.

**Building without reinstalling.** `python build_app.py --no-install`
builds from the packages already installed instead of installing
`requirements/build.txt` again. It is for building with a modified
component, as the [third-party notices](../guide/install#third-party-licenses)
describe for the LGPL components, and for the release workflow, which
installs and checks the environment itself before it builds.

**macOS.** `build_app.py` makes the one-file program; the release workflow
then wraps it in `MeManga.app` with `packaging/macos_app.py build`. A
local build is signed ad hoc, as PyInstaller does by default
([PyInstaller: macOS code signing](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)),
unless `MEMANGA_CODESIGN_IDENTITY` names a signing identity. With an
identity, the build also uses the hardened-runtime entitlements in
`packaging/macos-entitlements.plist`, or the file `MEMANGA_ENTITLEMENTS_FILE`
names. A local build is never notarized.

## Dependency locks

`pyproject.toml` is the only place dependencies are declared: the
command line in `dependencies`, and the `gui`, `dev` and `build` extras.
The files in `requirements/` are generated from it. Each pins every
package, dependencies of dependencies included, to an exact version with
hashes, for every supported system and Python version:

| File | Installs | Used by |
|---|---|---|
| `requirements/cli.txt` | `dependencies` | The Docker image, the package check in CI, the source docs check |
| `requirements/gui.txt` | `dependencies` and `gui` | `scripts/bootstrap.py`, `scripts/linux/setup.sh` |
| `requirements/dev.txt` | `dependencies` and `dev` | Development and the test suite |
| `requirements/build.txt` | `dependencies` and `build` | `build.py`, `build_app.py` and the release workflow |

Which versions are pinned is set in `pyproject.toml` too, under
`[tool.lock-dependencies]`: each package at its newest release within the
declared bounds as of `resolve-at`, or as of its own time under
`resolve-package-at`. To update packages, change those times or the
dependencies, then generate the files again. This needs uv 0.13.1 and the
network:

```sh
python -m pip install "uv==0.13.1"
python scripts/lock_dependencies.py
```

Commit `pyproject.toml` and `requirements/` together, and never edit the
files in `requirements/` by hand.

| Command | Checks | Needs |
|---|---|---|
| `python scripts/lock_dependencies.py --check` | Every file was generated from the current `pyproject.toml`, and generating it again gives exactly the same file, so a pin changed by hand fails. Writes nothing. | uv 0.13.1 and the network |
| `python scripts/lock_dependencies.py --check --offline` | Only the first part: the files match the current `pyproject.toml`, and none is missing or extra. | Nothing; the tests run it |
| `python scripts/lock_dependencies.py --check-installed build` | The running Python holds exactly the rows of `requirements/build.txt` that apply to it, at their pinned versions, from the package index, and nothing else besides pip and MeManga itself. It compares names and versions, not file contents. | The installed build environment |

The Dependency locks workflow runs `--check` on pushes and pull requests
to `main`; the release workflow runs `--check` and, on each build runner,
`--check-installed build`.

## Release a version

<Badge type="info" text="Maintainers" />

A release is made by pushing a version tag. Everything else happens in
the Build & Release workflow (`.github/workflows/release.yml`).

1. Set the version in `memanga/__init__.py` (`__version__`).
   `pyproject.toml` reads it from there.
2. Give the version its own section in `CHANGELOG.md`, `## [1.2.3]`. The
   section becomes the text of the GitHub release. In the links at the end
   of the file, below `## Earlier versions` so that they stay out of the
   release text, add the new version and move `[Unreleased]` to its tag:

   ```md
   [Unreleased]: https://github.com/meellm/MeManga/compare/v1.2.3...main
   [1.2.3]: https://github.com/meellm/MeManga/compare/v1.2.2...v1.2.3
   ```

   `tests/unit/test_release_notes.py` checks these links against the
   section headings.
3. Push the tag `v` plus that version, for example `v1.2.3`.

The workflow then runs, and publishes nothing unless every step passes:

- **Release notes:** `scripts/release_notes.py` fails when the tag is not
  `v<version>` or `CHANGELOG.md` has no section, or an empty one, for it.
- **Checks of the tagged tree:** the CI workflow, the dependency audit, and
  the full lock check.
- **Builds:** Windows, macOS on Apple silicon and on Intel, and Linux. Each
  build:
  - checks that the tag matches `__version__`, because the notices point
    to the source at that tag;
  - installs `requirements/build.txt` with hashes, then checks it with
    `--check-installed build`;
  - builds with `python build_app.py --no-install`, then checks the
    third-party notices and, on Windows and macOS, that the browser
    components start from the built app;
  - on macOS, wraps it in `MeManga.app`, signed and notarized only when the
    signing secrets are set (below);
  - packs the download: a `.zip` folder on Windows, a `.tar.gz` folder on
    Linux, a zipped `MeManga.app` on macOS, each with its
    `<download>-THIRD_PARTY_NOTICES.txt`.
- **Publish:** a GitHub release for the tag, with the `CHANGELOG.md`
  section followed by GitHub's list of changes, and all downloads.

After a release, update `docs/.vitepress/release.ts`, so this site names
the new release and its downloads.

**The Docker image** has its own Docker Image workflow. The same tag
starts it, but it does not wait for the release workflow or its checks:
it builds the image, runs a smoke test of it and publishes it. It can also be run by
hand, with or without publishing.

<Badge type="info" text="Not in v0.4.4" /> The one-folder Windows and
Linux downloads and the notices files came after v0.4.4; see
[Download and install](../guide/install#what-changes-after-v0-4-4).

## macOS signing and notarization

Signing and notarization are optional and need a paid Apple Developer
Program membership. When all of these repository secrets are set, the
release workflow signs both macOS apps with a Developer ID Application
certificate, notarizes them with Apple and staples the ticket before
upload. The release then fails if any of those steps or the Gatekeeper
check fails.

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE_BASE64` | Base64 of the Developer ID Application `.p12` export |
| `MACOS_CERTIFICATE_PASSWORD` | Password of that `.p12` |
| `MACOS_CODESIGN_IDENTITY` | Identity name, such as `Developer ID Application: Name (TEAMID)` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_TEAM_ID` | Ten-character Apple Developer Team ID |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password for that Apple ID |

If any secret is missing, the workflow logs a warning and still publishes
unsigned, unnotarized `MeManga.app` zips. They pass the same bundle,
architecture and browser checks, but macOS may refuse to open them until
the user allows it; see
[Troubleshooting](../guide/troubleshooting#macos-says-the-app-cannot-be-opened).
