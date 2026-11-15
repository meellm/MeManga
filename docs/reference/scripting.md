# Use MeManga in scripts

<script setup>
import { release } from '../.vitepress/release'
</script>

This page is for people who call `memanga` from a script, a scheduled job
or another program. It describes how the command line behaves today: how a
series is picked, what the exit codes mean, when a command asks a question,
and what the JSON output contains.

For the commands themselves see [Use the command line](../guide/cli) and the
[command reference](./cli).

::: warning What this page is, and is not
- It describes the **development version** as it behaves now.
  {{ release.tag }} is older: of the JSON output described here it has only
  `search --json`, and the rules on this page were not checked against it.
- MeManga has **no written compatibility promise** yet. Nothing here is a
  guarantee that a later version behaves the same way. A written contract,
  including how long old spellings stay, is planned:
  [issue 358](https://github.com/meellm/MeManga/issues/358).
- Check what your version does with `memanga COMMAND --help`.
:::

## Output

- Results go to standard output. Warnings, errors and progress go to
  standard error.
- When the output is not a terminal, for example in a pipe or a file,
  MeManga prints plain text without colour, emoji, borders or line
  wrapping. `memanga --plain COMMAND` asks for the same in a terminal.
- `memanga -q COMMAND` hides warnings and progress. Errors still show.
- The wording of plain-text output is meant for people. To read results in
  a program, use [JSON output](#json-output) where a command offers it.

## How a series is picked

Commands that act on one series take a `TARGET`.

- `"#N"` picks the series with number N in `memanga list`. The number is
  the position in the full list, also when the list is filtered or sorted.
- Anything else is a title. Upper and lower case do not matter.
  - A title that matches one series exactly is used.
  - Otherwise a part of a title is enough, if only one series contains it.
  - If several series match, nothing is done: MeManga lists the matches on
    standard error and exits with code 1.
- A plain number such as `86` is a title, not a list number, and must match
  a title exactly.

In a script, use the full title or `"#N"`. Keep the quotes around `"#N"`:
many shells treat an unquoted `#` as the start of a comment.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The command did what was asked. Also when there was nothing to do. |
| `1` | It could not: a series or chapter was not found or the target matched several, the input was refused, a needed answer could not be asked for, or settings or saved data could not be read or written. |
| `2` | The command line was not understood: an unknown option, a missing argument, or options that cannot be combined. |
| `3` | The command ran, but part of the work failed. |
| `130` | Interrupted with Ctrl+C. |
| `143` | Stopped by a termination signal, for example by a timeout. |

Codes `3`, `130` and `143` need a closer look.

**`memanga check`**

- `0`: no new chapters, chapters only listed, or every chapter downloaded.
  Also when a suspicious batch was held back; the warning is on standard
  error.
- `1`: every checked series failed, the target was not found, or chapters
  were waiting for an answer that nobody could give (see
  [Questions](#questions-and-running-without-a-terminal)).
- `3`: some chapters or some series failed while the rest worked. Also when
  a chapter was saved but could not be emailed.

**Other commands that use `3`**

- `memanga failed retry`: some chapters are still failed or partial.
- `memanga send`: some chapters could not be sent. With `--dry-run`: some
  would not be sent.

**After an interruption** (`130`, `143`), chapters that were already
finished stay recorded.

**Commands with their own meaning for `1`**

- `memanga doctor`: a check failed. With `--strict`, also when a check only
  warned.
- `memanga setup`: something still needs you.
- `memanga search --json`: there were no results, or `--add` did not add
  the series.

## Questions and running without a terminal

Some commands ask before they act. MeManga asks only when its standard
input is a terminal. In a scheduled job, a pipe or a container without a
terminal it never waits for an answer: it either goes on without the
question or stops with exit code 1 and an `error:` line on standard error.

- **`memanga` with no command** opens the menu. Without a terminal it
  prints the help and exits 1. Name a command instead.
- **`add -t … -u …`** never asks, with or without a terminal. See
  [adding a series](../guide/cli#add-a-series-by-its-address) for when it
  refuses and what `--force` does.
- **`add -i`** asks for everything. Without a terminal it exits 1. Use `-t`
  and `-u` instead.
- **`remove`** asks to confirm. Without a terminal it exits 1 and removes
  nothing. `--yes` skips the question.
- **`check`** asks for each new chapter. Without a terminal it downloads
  nothing and exits 1 if chapters were waiting. Use `--download`, or
  `--dry-run` to only list them.
- **`search`** asks which result to add. Without a terminal it only prints
  the results. `--add N` adds one without asking.
- **`import --replace`** asks to confirm. Without a terminal it exits 1 and
  changes nothing. `--yes` skips the question.
- **`send`** with more than one chapter asks to confirm. Without a terminal
  it exits 1 and sends nothing. Use `--yes`, or `--dry-run` to preview.
- **`config`** with no action and no option starts a series of questions.
  Without a terminal it exits 1. Use `config show`, `config get` and
  `config set` instead.
- **`config edit`** opens your editor. Without a terminal it exits 1. Use
  `config set` instead.
- **`cron install`** asks for the time. Without a terminal it exits 1.
  `--time HH:MM` skips the question.
- **`setup`** asks before it downloads browsers. Without a terminal it
  downloads nothing. `--install-browsers` and `--no-install-browsers`
  decide without a question.

Things worth knowing:

- `check --quiet` also never asks. Like a run without a terminal, it
  downloads nothing unless `--download` is given.
- `remove --yes` only skips the confirmation. It keeps the download history
  and the downloaded files; those need `--purge-history` and
  `--delete-files`.
- `failed retry` and `failed clear` never ask.
- `config set email.app_password` does not take the password as an
  argument. Send it on standard input with `-` as the value, as below.

```sh
memanga config set email.app_password - < PASSWORD-FILE
```

Replace `PASSWORD-FILE` with the path of a file that holds only the
password.

## JSON output

These commands print JSON on standard output with `--json`, and nothing
else on that stream:

- `memanga list --json`
- `memanga status --json`
- `memanga failed --json`
- `memanga sources --json`
- `memanga doctor --json`
- `memanga config show --json`
- `memanga search "TITLE" --json`

The first five carry a `schema_version` key. `config show` and `search` do
not.

`schema_version` is `1` today. A note in the program's source says the
number is meant to go up when a key is renamed or removed or changes its
type, and that new keys may appear without a change of number. That is the
developers' stated intent, not a promise. Read the keys you need and ignore
the ones you do not know.

`failed --json` only lists. It cannot be combined with `retry` or `clear`.

`memanga export -` also writes JSON to standard output: the backup file,
which has its own format and is not described here.

### `list --json`

| Key | Content |
|---|---|
| `count` | Number of entries in `manga` |
| `manga` | The series, in the order they are printed |

Each entry in `manga`:

| Key | Content |
|---|---|
| `n` | Number for `"#N"` |
| `title` | Title |
| `status` | `reading`, `on-hold`, `dropped` or `completed` |
| `source` | Name of the first source, or `null` |
| `source_display` | The source as the table shows it |
| `url` | Address at the first source, or `null` |
| `sources` | All sources of the series, first one first |
| `last_chapter` | Last downloaded chapter, or `null` |
| `downloaded_count` | Number of downloaded chapters |
| `mode` | `auto` or `manual` |
| `send_to_kindle` | `true` or `false` |
| `backup_count` | Number of backup sources |

### `status --json`

- `paths`: where the settings and saved data are, with the keys
  `config_dir`, `config` and `state`
- `manga_count`: number of series
- `output_format`: output format
- `delivery`: `mode`, `download_dir`, `delete_after_send`
- `email`: `kindle_email`, `sender_email`, `smtp_server`, `smtp_port`,
  `smtp_tls`
- `post_processing`: `enabled`, `fail_on_error`
- `partial_chapters`: `enabled`, `threshold_percent`
- `cron`: `enabled`, `time`
- `last_check`: data about the last check, or `null`

The password is never part of this output. The two email addresses are, in
full. Keep that in mind before you store or share it.

### `failed --json`

| Key | Content |
|---|---|
| `title_filter` | The target that was given, or `null` |
| `count` | Number of entries in `chapters` |
| `chapters` | One entry per chapter, sorted by title, then chapter |

Each entry in `chapters`:

| Key | Content |
|---|---|
| `title` | Title of the series |
| `chapter` | Chapter number or label |
| `status` | `failed` or `partial` |
| `recorded_at` | When it was recorded, or `null` |
| `source` | Source, or `null` |
| `failed_pages` | Missing pages; can be empty |
| `total_pages` | Page count for a partial chapter, else `null` |
| `attempts` | Number of attempts for a failed chapter, else `null` |
| `error` | Reason for a failed chapter, else `null` |

### `doctor --json`

| Key | Content |
|---|---|
| `status` | Worst result: `ok`, `warning` or `fail` |
| `summary` | Number of checks per result: `ok`, `warning`, `fail`, `skip` |
| `checks` | One entry per check: `name`, `status`, `message`, `details` |

### `sources --json`

A `sources` list with one entry per source. Each entry has `domain`,
`aliases`, `scraper`, `engine`, `template`, `language`, `nsfw`, `note`,
`popularity`, `default_enabled`, `searchable`, `search_status`,
`search_skip`, `domain_search_skips` and `health`.

### `config show --json`

The settings file as it is, with the password and the email addresses
masked. It has no `schema_version`; its keys are the settings themselves.

### `search --json`

| Key | Content |
|---|---|
| `query` | The search text |
| `sources_searched` | Number of sources asked |
| `results` | One entry per result: `n`, `title`, `source`, `url`, `cover_url`, `chapters` |
| `failed` | Sources that failed: `source`, `error` |
| `added` | Only with `--add`: `ok` and `message` |

This command uses the network.

## Other spellings

These spellings are accepted today and do the same as the form on the
right. The program states no end date for them, except for `set`.

| Also accepted | Same as |
|---|---|
| `memanga ls` | `memanga list` |
| `memanga rm` | `memanga remove` |
| `memanga update` | `memanga edit` |
| `check --auto`, `-a`, `--yes`, `-y` | `check --download` |
| `check -t "TITLE"` | `check "TITLE"` |
| `remove --purge` | `remove --purge-history` |
| `failed --retry`, `failed --clear` | `failed retry`, `failed clear` |
| `add --yes`, `-y` | `add --force` |

**Deprecated: `memanga set`.** It still changes the status of a series, and
each time it prints a warning on standard error that it will be removed in
the next release. Use `memanga edit "TITLE" --status STATUS` instead. This
is the only command that announces its removal today.

## Examples

Download new chapters without questions and act on the result:

```sh
memanga check --download --quiet
case $? in
  0) echo "done" ;;
  3) echo "some chapters failed; see: memanga failed" ;;
  *) echo "check could not finish" ;;
esac
```

Save the library as JSON:

```sh
memanga list --json > library.json
```

Go to the download folder of a series. Replace `TITLE`:

```sh
cd "$(memanga path "TITLE")"
```

Use another settings folder for one command. Replace `DIR`:

```sh
memanga --config-dir "DIR" status --json
```

## Planned

A written contract for scripts, with a policy for how long old spellings
are kept, does not exist yet. It is tracked in
[issue 358](https://github.com/meellm/MeManga/issues/358).
