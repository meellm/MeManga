# Run a command after each download

MeManga can run a command of your own each time a chapter has been saved:
to copy it somewhere, add it to another library, or keep a log. This works
in the desktop app and on the command line.

## An example: keep a log of downloads

This example appends one line per chapter to a log file. It changes nothing
else and is easy to remove.

1. Save this script, for example as `~/memanga-hooks/log_chapter.py`:

   ```python
   import os
   from datetime import datetime
   from pathlib import Path

   log = Path.home() / "memanga-hooks" / "downloads.log"
   with log.open("a", encoding="utf-8") as f:
       f.write(f"{datetime.now():%Y-%m-%d %H:%M}\t"
               f"{os.environ['MEMANGA_MANGA_TITLE']}\t"
               f"{os.environ['MEMANGA_CHAPTER']}\t"
               f"{os.environ['MEMANGA_OUTPUT_PATH']}\n")
   ```

2. Turn it on, with the full path to Python and to the script.

   In the desktop app, open **Settings → Advanced → Post-Processing**, tick
   **Run a command after each chapter download**, enter the command and
   choose **Save settings**.

   On the command line:

   ```sh
   memanga config set delivery.post_processing.command "/usr/bin/python3 /home/you/memanga-hooks/log_chapter.py"
   memanga config set delivery.post_processing.enabled true
   ```

3. Download a chapter. A new line appears in `downloads.log`.

To turn it off, untick the box, or run
`memanga config set delivery.post_processing.enabled false`.

If you edit `config.yaml` by hand, write `enabled` and `fail_on_error` as
`true` or `false` without quotes. A
[quoted value or a number](../reference/config#when-a-setting-is-not-valid)
counts as off, and MeManga warns about it.

## How the command is run

- **No shell.** MeManga splits the command into the program and its
  arguments and starts the program directly. Pipes, redirection with `>`,
  `~` and `$VARIABLES` are therefore not expanded.
- **Quoting.** Put a path that contains spaces in quotes:
  `"/home/you/my hooks/log_chapter.py"`. On Windows, paths with
  backslashes can be written as they are, such as
  `py C:\Users\you\memanga-hooks\log_chapter.py`.
- **Placeholders.** `{output_path}`, `{title}`, `{chapter}`, `{source}`,
  `{format}` and `{is_dir}` are replaced after the command has been split,
  so each stays part of one argument even when its value contains spaces
  or quotes. You do not need to quote them. The same values are in the
  environment variables `MEMANGA_OUTPUT_PATH`, `MEMANGA_MANGA_TITLE`,
  `MEMANGA_CHAPTER`, `MEMANGA_SOURCE`, `MEMANGA_OUTPUT_FORMAT` and
  `MEMANGA_IS_DIR`; the [settings reference](../reference/config#delivery-post-processing-command)
  lists them.
- **A shell when you need one.** To use shell features, start a shell
  yourself and read the values from the environment variables, not from
  placeholders: for example
  `sh -c 'cp "$MEMANGA_OUTPUT_PATH" /media/backup/'`.
- **Where it runs.** The command gets MeManga's own environment, including
  its `PATH`. A [scheduled check](./schedule#when-something-does-not-work)
  or a container can have a different one, so use full paths to the
  program and its files, and make sure they exist there.

## When the command runs and what a failure does

The command runs after the chapter's file or folder has been written, and
before the chapter is sent to a Kindle or recorded as downloaded. It may
run for up to 10 minutes; after that, MeManga tries to stop it together
with the processes it started, and counts it as a failure. Its output is
kept only to explain a failure.

What happens when it fails, with **Mark download failed if the command
exits with an error** (`delivery.post_processing.fail_on_error`):

| Setting | Result |
|---|---|
| Off (the default) | MeManga logs a warning. The chapter counts as downloaded and is sent to the Kindle as usual. |
| On | The download of the chapter counts as failed. As for any failed download, MeManga tries a [backup source](./backup-sources#a-download-that-fails) and, if allowed, a partial copy; when none of them works, it records the chapter as [failed](./cli#when-chapters-fail) and does not send it. A failed command's changes are not undone, and a new download attempt can replace the chapter's file. |

`memanga failed retry` downloads a failed chapter again, and runs the
command again.
