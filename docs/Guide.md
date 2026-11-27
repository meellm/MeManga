# MeManga Setup & Usage Guide

This guide has moved to the
[MeManga documentation site](https://meellm.github.io/MeManga/). The
sections below keep their old links and point to where each topic is now.
MeManga knows <!-- source-count:start -->235 scrapers / 300 domains<!-- source-count:end -->;
the [list of sources](https://meellm.github.io/MeManga/reference/sources)
shows them.

## Table of Contents

Start with the [docs overview](https://meellm.github.io/MeManga/guide/), or
go straight to a topic below.

## Setup — Windows

[Download and install](https://meellm.github.io/MeManga/guide/install): the
desktop app, or the
[command line from source](https://meellm.github.io/MeManga/guide/install#command-line-from-source).
[Where MeManga keeps its files](https://meellm.github.io/MeManga/guide/install#where-memanga-keeps-its-files)
lists the folders.

## Setup — macOS

[Download and install](https://meellm.github.io/MeManga/guide/install) covers
macOS too.

## Setup — Linux

[Download and install](https://meellm.github.io/MeManga/guide/install) covers
Linux too. On a server,
[Set up without questions](https://meellm.github.io/MeManga/guide/install#set-up-without-questions)
prepares MeManga from a script.

## Setup — pip install

[Command line from source](https://meellm.github.io/MeManga/guide/install#command-line-from-source).
To install from PyPI, see
[Package installs](https://meellm.github.io/MeManga/guide/install#package-installs).

- <a name="desktop-app-from-pip"></a>Desktop app from pip:
  [Desktop app from source](https://meellm.github.io/MeManga/guide/install#desktop-app-from-source)

## Setup — Docker

[Run MeManga in Docker](https://meellm.github.io/MeManga/guide/docker).

- <a name="build-and-run"></a>Build and run:
  [The published image](https://meellm.github.io/MeManga/guide/docker#the-published-image),
  or [an image built from source](https://meellm.github.io/MeManga/guide/docker#image-built-from-source-memanga-watch)
- <a name="persist-config-state-and-downloads"></a>Persist config, state and downloads:
  [Keep your data](https://meellm.github.io/MeManga/guide/docker#keep-your-data)
- <a name="compose"></a>Compose:
  [Use Docker Compose](https://meellm.github.io/MeManga/guide/docker#use-docker-compose)
- <a name="scheduling-in-docker"></a>Scheduling in Docker:
  [Check on a schedule](https://meellm.github.io/MeManga/guide/docker#check-on-a-schedule)
- <a name="kindle-delivery"></a><a name="app-password-as-a-docker-secret"></a>Kindle delivery and the app password:
  [Send to a Kindle](https://meellm.github.io/MeManga/guide/docker#send-to-a-kindle)

## Your First Manga

[First steps](https://meellm.github.io/MeManga/guide/first-steps), then
[Use the command line](https://meellm.github.io/MeManga/guide/cli).

- <a name="interactive-mode-recommended"></a><a name="direct-mode"></a>Add a series:
  [Add a series by its address](https://meellm.github.io/MeManga/guide/cli#add-a-series-by-its-address)
- <a name="view-your-tracked-manga"></a>View your library:
  [See your library](https://meellm.github.io/MeManga/guide/cli#see-your-library)
- <a name="remove-a-manga"></a>Remove a series:
  [Keep your library tidy](https://meellm.github.io/MeManga/guide/cli#keep-your-library-tidy)

## Checking for New Chapters

[Check for new chapters](https://meellm.github.io/MeManga/guide/cli#check-for-new-chapters).

- <a name="check-modes"></a>Check modes and running without a terminal:
  [Questions and running without a terminal](https://meellm.github.io/MeManga/reference/scripting#questions-and-running-without-a-terminal)

## Downloading From the Start

`--all` and `--from` are described under
[Check for new chapters](https://meellm.github.io/MeManga/guide/cli#check-for-new-chapters)
and in the [command reference](https://meellm.github.io/MeManga/reference/cli#memanga-check).

## Downloading From a Specific Chapter

See [Downloading From the Start](#downloading-from-the-start).

## Managing Status

[Keep your library tidy](https://meellm.github.io/MeManga/guide/cli#keep-your-library-tidy)
and [`memanga edit`](https://meellm.github.io/MeManga/reference/cli#memanga-edit).

## Marking Chapters Read

[Keep your library tidy](https://meellm.github.io/MeManga/guide/cli#keep-your-library-tidy)
and [`memanga read`](https://meellm.github.io/MeManga/reference/cli#memanga-read).

## Changing Output Format

- <a name="change-the-default-format"></a>The default format:
  [Download folder and output format](https://meellm.github.io/MeManga/desktop/settings#download-folder-and-output-format)
  and [`delivery.output_format`](https://meellm.github.io/MeManga/reference/config#delivery-output-format)
- <a name="override-format-for-a-single-check"></a>One check in another format:
  [`memanga check`](https://meellm.github.io/MeManga/reference/cli#memanga-check)

## MangaDex Image Quality and Group Removal

- Image quality: [`mangadex.data_saver`](https://meellm.github.io/MeManga/reference/config#mangadex-data-saver)
- Group removal: [MangaDex scanlation groups](https://meellm.github.io/MeManga/reference/sources#mangadex-scanlation-groups)

## Post-Processing After Download

[Run a command after each download](https://meellm.github.io/MeManga/guide/post-processing).

- <a name="available-values"></a>Placeholders and variables:
  [`delivery.post_processing.command`](https://meellm.github.io/MeManga/reference/config#delivery-post-processing-command)
- <a name="failure-behavior"></a>When the command fails:
  [When the command runs and what a failure does](https://meellm.github.io/MeManga/guide/post-processing#when-the-command-runs-and-what-a-failure-does)

## Setting Up Kindle Email

[Send chapters to a Kindle](https://meellm.github.io/MeManga/guide/kindle).

- <a name="choose-which-manga-are-sent"></a>Which series are sent:
  [Which series are sent](https://meellm.github.io/MeManga/guide/kindle#which-series-are-sent)
- <a name="other-mail-providers-and-encryption"></a>Other providers:
  [Other email providers](https://meellm.github.io/MeManga/guide/kindle#other-email-providers)
- <a name="email-size-limit"></a>Size limit:
  [Large chapters are split](https://meellm.github.io/MeManga/guide/kindle#large-chapters-are-split)
- <a name="switch-back-to-local-downloads"></a>Back to local downloads:
  [Switch back to local downloads](https://meellm.github.io/MeManga/guide/kindle#switch-back-to-local-downloads)
- <a name="note-on-formats-and-email"></a>Formats:
  [What you need](https://meellm.github.io/MeManga/guide/kindle#what-you-need)

## Backup Sources

[Use a backup source](https://meellm.github.io/MeManga/guide/backup-sources).

- <a name="how-fallback-works"></a>How fallback works:
  [When MeManga uses the backup](https://meellm.github.io/MeManga/guide/backup-sources#when-memanga-uses-the-backup)

## Updating Manga Details

[`memanga edit`](https://meellm.github.io/MeManga/reference/cli#memanga-edit);
for backups, [Add a backup](https://meellm.github.io/MeManga/guide/backup-sources#add-a-backup)
and [Remove a backup](https://meellm.github.io/MeManga/guide/backup-sources#remove-a-backup).

## Scheduling Automatic Checks

[Check on a schedule](https://meellm.github.io/MeManga/guide/schedule).

- <a name="one-memanga-at-a-time"></a>One MeManga at a time:
  [MeManga is already running](https://meellm.github.io/MeManga/guide/troubleshooting#memanga-is-already-running)
- <a name="file-versions"></a>File versions:
  [Schema version](https://meellm.github.io/MeManga/reference/state#schema-version)

## Export and Import

[Export and import](https://meellm.github.io/MeManga/reference/state#export-and-import).

## All Commands Reference

[Command reference](https://meellm.github.io/MeManga/reference/cli).

- <a name="json-output"></a>JSON output:
  [JSON output](https://meellm.github.io/MeManga/reference/scripting#json-output)
- <a name="failed-chapters"></a>Failed chapters:
  [When chapters fail](https://meellm.github.io/MeManga/guide/cli#when-chapters-fail)
- <a name="output-and-logging"></a>Output and logging:
  [Output](https://meellm.github.io/MeManga/reference/scripting#output) and
  [Log files](https://meellm.github.io/MeManga/guide/troubleshooting#log-files)
- <a name="exit-codes"></a>Exit codes:
  [Exit codes](https://meellm.github.io/MeManga/reference/scripting#exit-codes)

## Troubleshooting — Windows

[Troubleshooting](https://meellm.github.io/MeManga/guide/troubleshooting).

- <a name="playwright-browsers-fail-to-launch"></a>Browser components:
  [Browser components](https://meellm.github.io/MeManga/guide/troubleshooting#browser-components)
- <a name="scheduled-task-not-running"></a><a name="cron-job-not-running"></a>Scheduled checks:
  [When something does not work](https://meellm.github.io/MeManga/guide/schedule#when-something-does-not-work)
- <a name="config-file-location"></a>Config file location:
  [Where MeManga keeps its files](https://meellm.github.io/MeManga/guide/install#where-memanga-keeps-its-files)

## Troubleshooting — macOS

See [Troubleshooting — Windows](#troubleshooting--windows).

## Troubleshooting — Linux

See [Troubleshooting — Windows](#troubleshooting--windows).
