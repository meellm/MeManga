# Troubleshooting

<script setup>
import { release } from '../.vitepress/release'
</script>

What to do when MeManga does not start, where its log files are, how to
repair the browser download, what to put in a bug report, and how to move
or remove MeManga.

::: info How to read this page
Most of it applies to {{ release.tag }} and to the development version.
Where they differ, the page says so. Steps for the command line need the
[command line from source](./install#command-line-from-source).
:::

## Find MeManga's files

MeManga keeps its files in four places. Keep them apart when you clean up:
only the config folder and the program belong to MeManga alone.

| What | Where | What is in it |
|---|---|---|
| Config folder | {{ release.tag }}: `.config/memanga` in your user folder. Development version: see [where MeManga keeps its files](./install#where-memanga-keeps-its-files). | Settings and library (`config.yaml`), downloads and reading history (`state.json`), log files, the cover cache (`covers`) |
| Download folder | `Downloads/MeManga` in your user folder, unless you chose another | The chapters you downloaded |
| Browser components | Windows: `%LOCALAPPDATA%\ms-playwright`. macOS: `~/Library/Caches/ms-playwright`. Linux: `ms-playwright` in `$XDG_CACHE_HOME`, or `~/.cache/ms-playwright` | Firefox and Chromium for MeManga, and possibly for other programs that use Playwright |
| The program | Where you saved or unpacked it | The desktop app, or the folder you installed the command line in |

To open the config folder, choose **Settings → Advanced → Open logs folder**
in the desktop app. On the command line, `memanga config path` prints where
the config file is. [Files in the config folder](../reference/state#files-in-the-config-folder)
lists everything in it.

## MeManga does not start

### Windows says it protected your PC

The Windows download is not signed, so Windows SmartScreen may stop it the
first time. If you downloaded the file from the
<a :href="release.url">release page</a>, choose **More info**, then
**Run anyway**.

### macOS says the app cannot be opened

The {{ release.tag }} macOS builds are not signed or notarized, so macOS may
refuse to open them. Apple describes how to open such an app
([Apple Support](https://support.apple.com/en-us/102445)):

1. Try to open **MeManga.app** once, and close the message.
2. Open **System Settings → Privacy & Security**, scroll down and choose
   **Open Anyway**.
3. Choose **Open** in the message that follows.

Do this only for the file from the MeManga release page. Apple warns that
software that is not signed and notarized can expose your computer to
malware. There is no need to turn off these protections for other apps.

Download the file for your Mac's chip: `macos-arm64` for Apple silicon,
`macos-x64` for Intel. **Apple menu → About This Mac** shows which one you
have.

### There is no download for your system

The desktop download exists for Windows on x64, macOS on Apple silicon and
Intel, and Linux on x64. There is none for Linux on ARM, such as a Raspberry
Pi, or for 32-bit systems.

On a Raspberry Pi or another 64-bit ARM Linux system, use the
[command line from source](./install#command-line-from-source) or the
[Docker image](./docker), which is published for `arm64`.

### MeManga is already running

<Badge type="info" :text="`Not in ${release.tag}`" /> The message **MeManga is
already running for this library** means another MeManga program is using
the config folder: a second window, a check that is running, or a command.
Close it or let it finish, then start MeManga again.

### The settings or the library cannot be read

<Badge type="info" :text="`Not in ${release.tag}`" /> MeManga shows a message
and stops instead of starting with empty settings. The message names the
file. [When state.json cannot be read](../reference/state#when-state-json-cannot-be-read)
explains how to get back to the previous copy.

### The window closes right away

Look in the config folder for `crash.log`. When an error in MeManga closes
the desktop app, the error is added to the end of this file, under the date
and time.

If there is no `crash.log`, start the app from a terminal to see what it
prints:

::: code-group

```text [Windows]
Look in runtime.log in the config folder instead; see Log files below.
```

```sh [macOS]
# Use the folder where MeManga.app is.
/Applications/MeManga.app/Contents/MacOS/MeManga
```

```sh [Linux]
# In the folder where you unpacked the download.
./MeManga-linux-x64
```

:::

## Log files

All of these are in the config folder.

| File | Written by | Content |
|---|---|---|
| `crash.log` | The desktop app | Errors that closed the app. New entries are added at the end. |
| `runtime.log` | The desktop app on Windows | What the app reports while it runs. {{ release.tag }} starts the file again at every start; the development version keeps the three sessions before as `runtime.log.1` to `runtime.log.3`. On macOS and Linux the same messages go to the terminal you start the app from. |
| `diagnostics.log` | The command line with `--log-file` <Badge type="info" :text="`Not in ${release.tag}`" /> | Diagnostic messages of commands |
| `memanga.log` | Scheduled checks on Linux and macOS | The output of each check; see [Check on a schedule](./schedule#where-the-output-goes) |
| `error-details` | The desktop app <Badge type="info" :text="`Not in ${release.tag}`" /> | The full text of long error messages shown in **Notifications** |

## Browser components

Some sources only work through a browser, so MeManga uses its own copies of
Firefox and Chromium. They are downloaded once, about 250 MB, into the
browser folder listed [above](#find-memanga-s-files).

### They are missing

- {{ release.tag }}: the desktop app asks to download them at every start
  until they are there.
- <Badge type="info" :text="`Not in ${release.tag}`" /> Development version:
  if you skipped the download, choose **Settings → Advanced → Install browser
  components**. On the command line, `memanga setup` installs them after you
  agree.

If the download fails, the app shows what went wrong and offers to try
again. Check the internet connection first.

### They are broken

When the download was cut off or the files were damaged, sources that need
a browser fail, often with a message that an executable does not exist or
that the browser could not start. Download them again:

1. Close MeManga.
2. Open the browser folder. The error message usually names the folder
   MeManga expects, for example `firefox-1234` or `chromium-1234`. On the
   command line, `memanga doctor --check browsers --json` shows the paths
   of both browsers.
3. Rename that folder, for example to `firefox-1234.old`.
4. Start MeManga. It finds the browser missing and offers the download; in
   the development version you can also use **Install browser components**.
5. When sources work again, delete the renamed folder.

Do not delete the whole `ms-playwright` folder: other programs that use
Playwright keep their browsers there too.

On Linux, a browser can also fail because system libraries are missing.
`memanga doctor --launch-browsers` tells you, and `memanga setup` shows the
command that installs them.

## Downloads, sources and delivery

These pages cover problems after MeManga has started:

- [Library and downloads](../desktop/library) in the desktop app, and
  [When chapters fail](./cli#when-chapters-fail) on the command line.
- [Sources](../reference/sources#find-out-whether-a-source-works-now):
  whether a site works now, and which sources need the browser components.
- [When a chapter does not arrive](./kindle#when-a-chapter-does-not-arrive)
  on a Kindle.
- [When something does not work](./schedule#when-something-does-not-work)
  for scheduled checks, and in
  [Docker](./docker#when-something-does-not-work).

On the command line, `memanga doctor` checks the installation, the config
and state files, the download folder, email, the keyring, the scheduled
check and the browser components. It does not use the network unless you
ask it to.

## Report a problem

Open an issue on [GitHub](https://github.com/meellm/MeManga/issues) and
include:

- the MeManga version and your system. <Badge type="info" :text="`Not in ${release.tag}`" />
  **Settings → About → Copy diagnostics** copies the version, the system,
  and the state of the browser components and the keyring, without folder
  paths;
- what you did, what you expected and what happened;
- the relevant part of a log file.

Read what you paste before you post it. Log files and messages can contain
your user name in file paths, email addresses and the titles of your
series. Replace what you do not want to share. Never post your app password
or `config.yaml`: it can contain the password.

Report a security problem privately, as the
[security policy](https://github.com/meellm/MeManga/blob/main/SECURITY.md)
describes.

## Move to another computer

1. Close MeManga on both computers, including any `memanga watch`.
2. Copy the config folder and the download folder to the new computer.
3. Put the config folder where MeManga looks for it on the new computer:
   see [where MeManga keeps its files](./install#where-memanga-keeps-its-files).
4. Start MeManga. If the download folder is in a different place now, set it
   in **Settings → General** or with `memanga config set
   delivery.download_dir PATH`.
5. Enter the email app password again: it stays in the old computer's
   keyring. If MeManga had to save it in `config.yaml`, it came along with
   the file.
6. Let MeManga download the browser components on the new computer, and set
   up a [scheduled check](./schedule) again if you used one.

To take only your library and the state of each series, without settings,
use [export and import](../reference/state#export-and-import) instead.

## Uninstall

These steps remove MeManga and leave your downloaded chapters where they
are.

1. **Remove the scheduled check first**, while MeManga is still installed:
   `memanga cron remove`, or **Settings → Advanced → Scheduled Checks →
   Remove**. Stop any `memanga watch`.
2. Close MeManga.
3. **Delete the program**: the file or folder of the desktop app, or the
   folder of the command line from source with its virtual environment. For
   Docker, see [Docker](./docker).
4. **Rename the config folder**, for example to `memanga-removed`, and
   delete it once you are sure you do not need it. It holds your settings,
   library, reading history and logs. If you might use MeManga again, keep
   it, or export your library first.
5. **Delete the app password from the keyring**, if you set up email
   delivery. The entry belongs to the service `memanga` and the account
   `app_password`:
   - Windows: **Credential Manager → Windows Credentials**, the entry
     `memanga`.
   - macOS: **Keychain Access**, search for `memanga`.
   - Linux: the passwords app of your desktop, search for `memanga`, or
     `secret-tool clear service memanga username app_password`.
6. **Delete the remembered theme** of the desktop app, if you like: on
   Windows the registry key `HKEY_CURRENT_USER\Software\MeManga`, on Linux
   the folder `~/.config/MeManga` (with capital letters; it is not the config
   folder), on macOS the file with `MeManga` in its name in
   `~/Library/Preferences`.
7. **The browser components** take about 250 MB. Delete the `ms-playwright`
   folder only if no other program on the computer uses Playwright, such as
   tools for testing websites. If you are not sure, leave it.

Your downloaded chapters stay in the download folder. Delete that folder
yourself only if you no longer want the chapters.
