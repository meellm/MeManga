# Use the command line

<script setup>
import { release } from '../.vitepress/release'
</script>

This page follows one ordinary journey with the `memanga` command: find a
series, add it, check for new chapters, download them, and deal with the
chapters that did not work.

It is not a list of every command and option: that is the
[command reference](../reference/cli). Each command also explains itself
with `--help`, for example `memanga check --help`.

::: info Which version this describes
This page describes the development version, which is what you get when you
[install from source](./install). The command line of {{ release.tag }} is
smaller; see [Differences in {{ release.tag }}](#differences-in-the-latest-release).
:::

## Before you start

- Install MeManga and run `memanga setup` once, as described in
  [Download and install](./install) and [First steps](./first-steps).
- The `memanga` command is available while the virtual environment from the
  install steps is active. `python -m memanga` runs the same program.
- In the examples, words in capitals are placeholders. Replace `TITLE` with
  the title of a series and `SERIES-URL` with the address of its page on a
  source.

## How commands are written

```sh
memanga COMMAND [options]
```

Many commands take a `TARGET`: the series they act on. A target is either

- a title, in quotes if it contains spaces. Upper and lower case do not
  matter, and a part of the title is enough when it matches only one series;
- or `"#N"`, the number of the series in `memanga list`. Keep the quotes:
  many shells treat an unquoted `#` as the start of a comment.

A few options apply to every command and go **before** the command, for
example `memanga --config-dir DIR status` to use another settings folder.
`memanga --help` lists them.

## Find a series

```sh
memanga search "TITLE"
```

This asks the sources that are enabled for search and prints a numbered
table of results. It uses the network and can take a while, because many
sources are asked. [Sources](../reference/sources) lists which sources
search includes, and which of them serve adult content.

In a terminal, MeManga then asks **Add which?** Type a result number to add
that series to your library, or `q` to add nothing.

Useful options:

| Option | Effect |
|---|---|
| `--source DOMAIN` | Ask one source only. `memanga sources` lists the names. |
| `--limit N` | Show at most N results per source. |
| `--no-chips` | Do not fetch the chapter count of each result. Faster, and fewer requests. |

`memanga search "TITLE" --add N` adds result number N without asking. The
numbers belong to one search: a later search can order the results
differently, so look at the table first.

## Add a series by its address

If you already have the address of the series page on a supported source:

```sh
memanga add -t "TITLE" -u "SERIES-URL"
```

Adding saves the series in your library. It downloads no chapters. For a
supported source, MeManga may contact the source once to look up the cover
image.

Written this way, the command asks no questions. MeManga refuses to add the
series, and says why, in three cases:

- The source does not look supported. Check the address, and the list from
  `memanga sources`.
- A similar title is already in your library. Check `memanga list`.
- The same title is already in your library.

If you have checked and still want the series in the first two cases, repeat
the command with `--force`. The same title is never added twice.

`memanga add -i` asks for the title and the address one by one. In the
first two cases it asks **Add anyway?** where the command above refuses.

A second source can stand in when the first one is late with a chapter:

```sh
memanga add -t "TITLE" -u "SERIES-URL" -b "BACKUP-URL"
```

## See your library

```sh
memanga list
memanga status
```

`list` shows the series you track, with the number used for `"#N"`.
`status` shows your settings and a summary. Neither uses the network.

## Check for new chapters

`memanga check` asks each source for the chapter list of every series with
the status `reading`. What happens to the new chapters depends on how you
run it:

- `memanga check --dry-run` lists the new chapters. It downloads nothing
  and records nothing.
- `memanga check` asks **Download …?** for each new chapter, when you run
  it in a terminal.
- `memanga check --download` downloads every new chapter without asking.

All three use the network. To check one series only, add its target:

```sh
memanga check "TITLE" --dry-run
```

::: warning The first check of a new series
For a series with no downloaded chapters, every chapter counts as new.
`memanga check --download` would then download the whole series. Look at
the dry run first, and say where to start if you do not want everything:

```sh
memanga check "TITLE" --from 100 --dry-run
memanga check "TITLE" --from 100 --download
```

Replace `100` with the chapter number to start from. `--all` starts from the
first chapter on purpose.
:::

Chapters are saved in a folder named after the series inside your download
folder. `memanga path "TITLE"` prints that folder and `memanga open "TITLE"`
opens it in the file manager. If delivery is set to email, each chapter is
also sent: see [Send chapters to a Kindle](./kindle).

Without a terminal, for example in a scheduled job, `memanga check` cannot
ask. It then downloads nothing unless you pass `--download`.
[Check on a schedule](./schedule) sets up such a job.

### Series in manual mode

A series can be set to manual mode, in the desktop app or with
`memanga edit "TITLE" --mode manual`. A check of the whole library with
`--download` only lists the new chapters of such a series. To download
them, name the series:

```sh
memanga check "TITLE" --download
```

### When a check holds chapters back

Sometimes a source suddenly shows a batch of chapters that does not fit the
history of a series: far too many at once, or a big jump in the numbers.
MeManga then looks for the chapters on a backup source. If no backup source
confirms them, it downloads none of them and prints a warning that starts
with **Suspicious chapter batch detected** and gives the reasons.

Look at the source yourself. If the chapters are real, accept them:

```sh
memanga check "TITLE" --download --force-suspicious
```

## When chapters fail

A chapter fails when its pages cannot be downloaded. At the end of a run
MeManga tells you how many chapters failed. To list them with the reason,
run:

```sh
memanga failed
```

Then choose what to do with them:

- `memanga failed retry` downloads the listed chapters again, without
  asking. It uses the network.
- `memanga failed retry "TITLE"` does the same for one series.
- `memanga failed clear` forgets the records and downloads nothing.

Each page is tried several times before a chapter fails.
`memanga check --retries N` changes how many times for one run.

### Chapters with a few missing pages

By default, a chapter with even one missing page counts as failed and is
not kept. You can allow chapters with a few missing pages for one run:

```sh
memanga check "TITLE" --download --allow-partial
```

A chapter kept this way is listed by `memanga failed` as **partial**, so you
can retry it later. `--partial-threshold PCT` sets the largest share of
pages, in percent, that may be missing. `--no-partial` turns the allowance
off for one run when it is switched on in your settings. To switch it on
for every run:

```sh
memanga config --partial on
```

## Keep your library tidy

Change the status of a series. Statuses are `reading`, `on-hold`, `dropped`
and `completed`; only `reading` series are included in a check of the whole
library:

```sh
memanga edit "TITLE" --status on-hold
```

Change the source address. Other details stay as they are:

```sh
memanga edit "TITLE" -u "SERIES-URL"
```

Mark chapter 12 as read, as the desktop reader shows it. `memanga unread`
undoes it. Files are not touched:

```sh
memanga read "TITLE" 12
```

Remove a series from your library. MeManga asks first, and downloaded files
are kept unless you choose otherwise:

```sh
memanga remove "TITLE"
```

`memanga remove "TITLE" --delete-files` also deletes the folder with the
downloaded chapters of that series. This cannot be undone.

## Complete commands with Tab

In Bash, MeManga can complete its commands when you press Tab. To turn it
on in the current Bash session:

```sh
source <(memanga completion bash)
```

To keep it, add that line to your `~/.bashrc`. Bash reads that file when
it starts as an interactive shell that is not a login shell; a login shell
reads a profile file instead, such as `~/.bash_profile`, which may load
`~/.bashrc` itself. The Bash manual describes this under
[Bash Startup Files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html).

The line runs `memanga` when it is executed, so `memanga` must be available
at that point. If it is installed in a virtual environment, either activate
the environment earlier in `~/.bashrc`, or save the script once and load the
file instead:

```sh
memanga completion bash > ~/.memanga-completion.bash
```

```sh
# In ~/.bashrc
source ~/.memanga-completion.bash
```

A saved script does not change when MeManga does: write it again after you
update MeManga.

What Tab completes:

- commands and their other names, and the actions of commands such as
  `config` and `failed`;
- options, and the values of options that have a fixed list, such as
  `--status` and `--mode`; `search --source` offers every supported source;
- folders after `--config-dir`.

Where it has nothing to offer, Bash falls back to file names. The titles of
your series are not completed; `#N` from `memanga list` is the short way to
name one. The completion is set up for the `memanga` command, not for
`python -m memanga`, and only Bash is supported. The command is listed in
the [command reference](../reference/cli#memanga-completion).

To turn it off in the current session, run `complete -r memanga`. To stop
loading it, remove the line from `~/.bashrc`.

## Differences in the latest release

The command line of {{ release.tag }} has the same journey with fewer
commands and options.

- **Not in {{ release.tag }}:** the commands `setup`, `doctor`, `edit`,
  `read`, `unread`, `path`, `open`, `send` and `completion`; the spellings
  `failed retry`, `failed clear`, `check --download` and `check "TITLE"`;
  the options of `sources`; and the option `--config-dir`.
- **Use instead in {{ release.tag }}:**
  - `memanga check -t "TITLE"` to check one series
  - `memanga check --auto` to download without asking
  - `memanga set "TITLE" on-hold` to change the status
  - `memanga update "TITLE" -u "SERIES-URL"` to change the address
  - `memanga failed --retry` and `memanga failed --clear`
- `search`, `add`, `list`, `status`, `check --dry-run`, `--from`, `--all`,
  `--force-suspicious`, `--retries`, the partial options and `remove` exist
  in both. Details of how they behave can differ.

These older spellings still work in the development version. `set` is the
exception: it is being replaced by `edit`.

## Where to go next

- The [command reference](../reference/cli) lists every command and option.
- [Use MeManga in scripts](../reference/scripting) covers exit codes, JSON
  output and running without a terminal.
- [Run MeManga in Docker](./docker) covers containers and scheduled checks
  there.
- [Check on a schedule](./schedule) sets up a daily check or a check on an
  interval.
- The [settings reference](../reference/config) lists every setting.
