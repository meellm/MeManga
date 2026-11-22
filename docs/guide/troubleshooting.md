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
the browser components can be shared with other programs, and the download
folder can be inside one of the other folders.

| What | Where | What is in it |
|---|---|---|
| Config folder | {{ release.tag }}: `.config/memanga` in your user folder. Development version: see [where MeManga keeps its files](./install#where-memanga-keeps-its-files). | Settings and library (`config.yaml`), downloads and reading history (`state.json`), log files, the cover cache (`covers`) |
| Download folder | Shown in **Settings → General → Download Directory**. It starts as `Downloads/MeManga` in your user folder, and it is that folder too when `config.yaml` has no `delivery.download_dir` setting. Only when the setting is there without a value (`download_dir:` or `null`) is it `downloads` inside the config folder. | The chapters you downloaded |
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
refuse to open them, for example with the message **MeManga is damaged and
can't be opened**. Apple describes how to open such an app
([Apple Support](https://support.apple.com/en-us/102445)):

1. Try to open **MeManga.app** once, and close the message.
2. Open **System Settings → Privacy & Security**, scroll down and choose
   **Open Anyway**.
3. Choose **Open** in the message that follows.

If **Privacy & Security** does not offer **Open Anyway**, you can still use
the [command line from source](./install#command-line-from-source) or, if you
use Docker, the [Docker image](./docker). Both run the command line, not the
desktop app. Please [report the problem](#report-a-problem) too.

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

The message **MeManga is already running for this library** <Badge type="info" :text="`Not in ${release.tag}`" />
means another MeManga program is using
the config folder: a second window, a check that is running, or a command.
Close it or let it finish, then start MeManga again.

### The settings or the library cannot be read

MeManga shows a message and stops instead of starting with empty settings <Badge type="info" :text="`Not in ${release.tag}`" />.
The message names the
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
browser folder listed under
[Find MeManga's files](#find-memanga-s-files).

### The components are missing {#they-are-missing}

- {{ release.tag }}: the desktop app asks to download them at every start
  until they are there.
- Development version <Badge type="info" :text="`Not in ${release.tag}`" />:
  if you skipped the download, choose **Settings → Advanced → Install browser
  components**. On the command line, `memanga setup` installs them after you
  agree.

If the download fails, the app shows what went wrong and offers to try
again. Check the internet connection first.

### The components are broken {#they-are-broken}

When the download was cut off or the files were damaged, sources that need
a browser fail, often with a message that an executable does not exist or
that the browser could not start.

The browser folder is shared. Every program on the computer that uses
Playwright, such as tools for testing websites, keeps its browsers in the
same `ms-playwright` folder, and can use the very same `firefox-1234` or
`chromium-1234` folder in it as MeManga. Renaming or deleting such a folder
can break those programs too. Choose the way that fits your computer.

**Only if MeManga is the only program that uses Playwright**, download the
broken browser again:

1. Close MeManga.
2. Open the browser folder. The error message usually names the folder
   MeManga expects, for example `firefox-1234` or `chromium-1234`. On the
   command line, `memanga doctor --check browsers --json` shows the paths
   of both browsers.
3. Rename only that folder, for example to `firefox-1234.old`. Leave the
   rest of `ms-playwright` as it is.
4. Start MeManga. It finds the browser missing and offers the download; in
   the development version you can also use **Install browser components**.
5. Keep the renamed folder until sources that need the browser work again.
   Delete it only then.

**If other programs use Playwright, or you are not sure**, leave the shared
folder as it is and give MeManga a browser folder of its own:

1. Close MeManga and create an empty folder for its browsers.
2. Set the environment variable `PLAYWRIGHT_BROWSERS_PATH` to that folder
   in the environment MeManga starts from, for example in the terminal you
   start it from.
3. Start MeManga from there. It finds no browsers in the new folder and
   downloads them into it, without changing the shared folder.

The variable must be set every time MeManga starts; without it, MeManga
uses the shared folder again. On the command line,
`memanga doctor --check browsers --json` shows the variable as
`browsers_path`, or `null` when it is not set.

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

1. Note where the download folder is: **Settings → General → Download
   Directory**, or `memanga config get delivery.download_dir`
   <Badge type="info" :text="`Not in ${release.tag}`" />.
2. Close MeManga on both computers, including any `memanga watch`.
3. Copy the config folder and the download folder to the new computer. If
   the download folder is inside the config folder, it comes along with it.
4. Put the config folder where MeManga looks for it on the new computer:
   see [where MeManga keeps its files](./install#where-memanga-keeps-its-files).
5. Start MeManga. If the download folder is in a different place now, set it
   in **Settings → General → Download Directory** or with `memanga config
   set delivery.download_dir PATH`.
6. Enter the email app password again: it stays in the old computer's
   keyring. If MeManga had to save it in `config.yaml`, it came along with
   the file.
7. Let MeManga download the browser components on the new computer, and set
   up a [scheduled check](./schedule) again if you used one.

### What the new download folder changes

The library and the reader look for each series in a folder with its title
inside the download folder, so they find the copied chapters once the new
download folder is set.

Some records keep the full path a file was saved under, and still point to
the old place:

- **Chapters waiting for Kindle delivery.** <Badge type="info" :text="`Not in ${release.tag}`" /> `memanga send --pending`
  and `memanga send "TITLE" CHAPTER` both use the path saved with such a chapter, so they say the
  saved file is no longer there. Setting the new download folder does not
  change that path.
- **Partly downloaded chapters** and the **download history** keep the old
  path.

MeManga has no command to change these paths. Leave `state.json` as it is
rather than editing them by hand.

### Export and import

[Export and import](../reference/state#export-and-import) do not move a
whole installation. An export holds only the series list of your library
and the state of each series. It does not hold your settings, the history
of checks and downloads, or the downloaded chapters, and file paths in the
state of a series stay as they are. Use it to take only your library to
another computer.

## Uninstall

These steps remove MeManga. They keep your downloaded chapters only if the
download folder is outside the folders you remove, so check that first.

1. **Remove the scheduled check first**, while MeManga is still installed:
   `memanga cron remove`, or **Settings → Advanced → Scheduled Checks →
   Remove**. Stop any `memanga watch`.
2. **Find the download folder**: **Settings → General → Download
   Directory**, or `memanga config get delivery.download_dir`
   <Badge type="info" :text="`Not in ${release.tag}`" />.
3. Close MeManga. **If the download folder is inside the config folder or
   inside the program's folder**, move it somewhere else, or copy it to a
   safe place, before you go on. This is the case, for example, for a
   `downloads` folder in the config folder.
4. **Delete the program**: the file or folder of the desktop app, or the
   folder of the command line from source with its virtual environment. For
   Docker, see [Docker](./docker).
5. **Rename the config folder**, for example to `memanga-removed`, and
   delete it once you are sure you do not need it, and only after step 3.
   It holds your settings, library, reading history and logs. If you might
   use MeManga again, keep it, or export your library first.
6. **Delete the app password from the keyring**, if you set up email
   delivery. The entry belongs to the service `memanga` and the account
   `app_password`:
   - Windows: **Credential Manager → Windows Credentials**, the entry
     `memanga`.
   - macOS: **Keychain Access**, search for `memanga`.
   - Linux: the passwords app of your desktop, search for `memanga`, or
     `secret-tool clear service memanga username app_password`.
7. **The browser components** take about 250 MB. If you gave MeManga a
   browser folder of its own with `PLAYWRIGHT_BROWSERS_PATH`, delete that
   folder. Delete the shared `ms-playwright` folder only if no other
   program on the computer uses Playwright, such as tools for testing
   websites. If you are not sure, leave it.

The desktop app also remembers the theme you chose, in a small settings
entry outside the config folder. These steps leave that entry in place.

A download folder outside the folders you removed stays where it is, with
your chapters. Delete it yourself only if you no longer want them.
