# Download and install

<script setup>
import { release } from '../.vitepress/release'
</script>

There are three ways to run MeManga. Pick the one that fits you.

| You want | Use | Status |
|---|---|---|
| The desktop app | [A release download](#desktop-app) | Available |
| The command line, for example on a server | [An install from source](#command-line-from-source) | Available |
| A container | [Docker](#docker) | Available |
| `pip`, `pipx` or `uv` from a package index | [Not available yet](#package-installs) | Coming soon |

## Desktop app

<Badge type="tip" :text="'Release ' + release.tag" />

Download the file for your system from the
<a :href="release.url">{{ release.tag }} release page</a>.

<table>
  <thead>
    <tr><th scope="col">System</th><th scope="col">File</th></tr>
  </thead>
  <tbody>
    <tr v-for="asset in release.assets" :key="asset.file">
      <td>{{ asset.platform }}</td>
      <td><code>{{ asset.file }}</code></td>
    </tr>
  </tbody>
</table>

There is no desktop download for Linux on ARM, such as a Raspberry Pi. Use
the [command line](#command-line-from-source) or [Docker](#docker) there.

### Start it

These steps are for the v0.4.4 files. None of them is an installer: you run
the program straight from where you saved it.

::: code-group

```text [Windows]
Run the downloaded file:

MeManga-windows-x64.exe
```

```sh [macOS]
# Unzip the download. It contains MeManga.app.
unzip MeManga-macos-arm64.zip      # or MeManga-macos-x64.zip
open MeManga.app
```

```sh [Linux]
# The archive contains one program file.
tar -xzf MeManga-linux-x64.tar.gz
./MeManga-linux-x64
```

:::

On Linux, if the program does not start because the tool you extracted it
with dropped its permission to run, restore it with
`chmod +x MeManga-linux-x64`.

::: warning macOS: the v0.4.4 builds are not signed
The v0.4.4 macOS builds were published without Apple signing or
notarization, so macOS may warn about the app or refuse to open it the first
time. [Troubleshooting](./troubleshooting#macos-says-the-app-cannot-be-opened)
shows how to open it.
:::

### First start: browser components

Some sources only work through a real browser, so MeManga uses its own
copies of Firefox and Chromium. The first time you start v0.4.4 it asks to
download them. This is a large download; the app's own prompt estimates it
at about 250 MB.

In v0.4.4 the app needs this download to continue. If you answer no, it
offers to quit.

### What changes after v0.4.4

<Badge type="warning" text="Development version" />

The development version already works differently. These changes are not in
the v0.4.4 download:

- The Windows download becomes a `.zip` and the Linux archive holds a folder
  instead of a single file: `MeManga-windows-x64` with `MeManga.exe`, and
  `MeManga-linux-x64` with `MeManga`. Keep the `_internal` folder next to
  the program.
- The browser download can be skipped at first start and done later from
  **Settings → Advanced**.
- A new library asks once where downloads should go.
- Settings move to the usual folder for each system. See
  [where MeManga keeps its files](#where-memanga-keeps-its-files).

## Command line from source

<Badge type="warning" text="Development version" />

This installs the current development version from the repository. It can be
ahead of {{ release.tag }}.

You need Python 3.11.5 or newer and Git.

::: code-group

```sh [Linux and macOS]
git clone https://github.com/meellm/MeManga.git
cd MeManga
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
memanga setup
```

```powershell [Windows]
git clone https://github.com/meellm/MeManga.git
cd MeManga
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
memanga setup
```

:::

`memanga setup` prepares the first run. It is safe to run again at any time.

- It creates the config file and the download folder when they are missing.
  An existing config file is not changed.
- It checks that the Firefox and Chromium components are installed and start.
- It downloads missing components only after you agree on a terminal, or
  when you pass `--install-browsers`. With `--no-install-browsers` it never
  downloads them.
- It never runs `sudo` or a package manager. If system libraries are missing,
  it prints the command that installs them.

The `memanga` command is available while the virtual environment is active.

### Set up without questions

For a server or a script, `memanga setup` can run without asking anything:

```sh
memanga --config-dir /srv/memanga setup --install-browsers
```

- `--config-dir`, given before the command, puts the config file and the
  library data in that folder. Later commands use it only when they name it
  the same way, or when `MEMANGA_CONFIG_DIR` is set to it.
- The download folder is the one in that config file, `Downloads/MeManga`
  in the home folder by default. To use another, run
  `memanga --config-dir /srv/memanga config set delivery.download_dir PATH`
  and then run setup again.
- `--install-browsers` downloads missing browser components without asking.
  With `--no-install-browsers`, or without a terminal and without either
  option, nothing is downloaded and setup reports what is missing.
- When all browser components are present, setup starts each one once on
  an empty page to check that it runs, also with `--no-install-browsers`.
- It exits with `0` when everything is ready and `1` when a step still needs
  you; each step prints a line that says what to do.

### Desktop app from source

The default install is the command line only. To run the desktop app from
source, install the `gui` extra and start it:

```sh
python -m pip install ".[gui]"
memanga --gui
```

To build the desktop app yourself, see
[Build and release](../developer/build-release#build-the-desktop-app).

## Docker

A published image runs the command line in a container. It does not
include the desktop app. [Run MeManga in Docker](./docker) explains the
image, where your data is kept, and how to check on a schedule.

## Package installs

<Badge type="info" text="Coming soon" />

Installing MeManga with `pip`, `pipx` or `uv` from a package index is planned
and **not available yet**. There is no package to install today. Progress is
tracked in [issue 218](https://github.com/meellm/MeManga/issues/218).

## Third-party licenses

MeManga's own code is under the MIT license. The desktop downloads and the
Docker image also contain third-party software under its own licenses.
Among them, Qt, PySide6, Shiboken6 and img2pdf are used under the GNU LGPL.

<Badge type="info" :text="`Not in ${release.tag}`" /> Downloads and images
built from the development version come with a `THIRD_PARTY_NOTICES.txt`
that reproduces those licenses, links the source code of the LGPL
components, and explains how to use a modified version of them:

- on the release page, next to each download;
- inside the download: at the top of the Windows and Linux folders, and in
  `MeManga.app/Contents/Resources` on macOS;
- in the Docker image, in `/usr/share/doc/memanga/`.

On Windows and Linux the app is a folder, so the LGPL components are
separate files under `_internal` that you can replace. On macOS the app is
a single program file; to use a modified component you build the app from
source, as the notices file describes.

The {{ release.tag }} downloads and image came out before these notices
files.

## Where MeManga keeps its files

MeManga keeps your settings and your library in `config.yaml`, and what it
has downloaded, what you have read and its history in `state.json`, both in
one config folder. [Data files and backups](../reference/state) explains
both files and their safety copies.

### In release v0.4.4

The config folder is `.config/memanga` in your user folder, on every system:

- Windows: `.config\memanga` in your user folder
- macOS and Linux: `~/.config/memanga`

Downloads go to `Downloads/MeManga` in your user folder unless you choose
another folder in the settings.

### In the development version

The config folder follows the convention of each system:

- Windows: `%APPDATA%\memanga`
- macOS: `~/Library/Application Support/memanga`
- Linux: `$XDG_CONFIG_HOME/memanga`, or `~/.config/memanga` when that
  variable is not set

The default download folder is still `Downloads/MeManga` in your user
folder.

You can also:

- print the config file location with `memanga config path`;
- use another config folder with `--config-dir DIR` before the command, or
  with the `MEMANGA_CONFIG_DIR` environment variable.

If your settings are still in `~/.config/memanga`, the development version
moves that folder to the new location once, when it can do so safely.
Otherwise it keeps using the old folder.
