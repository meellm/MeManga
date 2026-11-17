# Python API

<script setup>
import { release } from '../.vitepress/release'
</script>

`memanga.api` reads a MeManga library from Python: the tracked series,
their sources, the chapters downloaded and the chapters that failed. It
never changes the library. To check, download or edit, use the command
line; [Use MeManga in scripts](./scripting) describes its exit codes and
JSON output.

::: info Availability
`memanga.api` is in the **development version** only, not in
{{ release.tag }}. Install it with the
[command line from source](../guide/install#command-line-from-source); it
is then importable in that virtual environment. Installing from a package
index is [not available yet](../guide/install#package-installs).
:::

```python
from memanga.api import Library, LibraryError

try:
    library = Library()
except LibraryError as error:
    raise SystemExit(f"Cannot read the library: {error}")

for series in library.series(status="reading"):
    print(series.title, series.last_chapter or "-")
```

## Supported names

| Name | What it is |
|---|---|
| `memanga.api.Library` | A read-only view of the library in one config folder |
| `memanga.api.Series` | One tracked series |
| `memanga.api.Source` | One source of a series |
| `memanga.api.LibraryError` | Raised when the library cannot be read |
| `memanga.__version__` | The version, as a string such as `"0.4.4"` |

These names, listed in `memanga.api.__all__`, and `memanga.__version__`
are the only supported Python interface. Every other module of the
`memanga` package is internal and may change in any release.

## What the API does not do

Opening and reading a `Library`:

- never writes `config.yaml` or `state.json`;
- never repairs a damaged `state.json` and never restores the safety copy;
- never creates or moves a config folder;
- never takes the config folder lock, so it works while a check or the
  desktop app is running;
- prints nothing.

It also does not download, check sources or send to the Kindle.

## Library

```python
Library(config_dir=None)
```

Reads the library once, when it is created.

**`config_dir`** (`str`, `os.PathLike` or `None`) is the config folder to
read. It is chosen as the command line chooses it:

1. the argument, unless it is `None` or an empty string;
2. else the `MEMANGA_CONFIG_DIR` environment variable, when it is set and
   not empty;
3. else the default config folder.

A given folder has `~` expanded and is made absolute, relative to the
current directory. The argument and the variable are read once, when the
`Library` is created.

**The default folder** is the platform folder listed in
[where MeManga keeps its files](../guide/install#in-the-development-version).
When only the older `~/.config/memanga` holds MeManga files, that folder is
read in place; the API does not move it as the command line does.

**Raises** `LibraryError` when:

- the folder does not exist, or is not a folder;
- `config.yaml` or `state.json` cannot be read, or was written by a newer
  MeManga;
- a value the API reads is missing or has the wrong type, for example a
  `manga` entry without a title.

An existing folder without `config.yaml` and `state.json` is read as an
empty library, so `Library("some/empty/folder")` succeeds with no series.

### Library.config_dir

```python
Library.config_dir -> pathlib.Path
```

The config folder this library was read from.

### Library.download_dir

```python
Library.download_dir -> pathlib.Path
```

The download folder, `delivery.download_dir` in `config.yaml`, with `~`
expanded. When `config.yaml` has no value for it, the default applies,
`Downloads/MeManga` in the home folder. When the value is set to null,
it is the `downloads` folder inside the config folder. The folder may not
exist.

### Library.series()

```python
Library.series(status=None) -> list[Series]
```

The tracked series in library order, the order of `config.yaml`.

**`status`** keeps only the series whose `status` is equal to it: one
string, or an iterable of strings for several. With `None`, every series is
returned. The comparison is exact and uses each series' `status` field
(see [Series](#series)); when no series has a matching status, the list is
empty.

Each call returns a new list, so changing the list does not change the
library.

### Library.get()

```python
Library.get(title) -> Series | None
```

The series whose title is exactly `title`, case included, or `None`. When
several series have the same title, the first in library order is returned.

### Library.reload()

```python
Library.reload() -> None
```

Reads `config.yaml` and `state.json` again; until then, the `Library` keeps
what it read before. When no folder was given, the default folder is chosen
again, so a library the command line has since moved out of
`~/.config/memanga` is still found.

**Raises** `LibraryError` for the same reasons as the constructor. The
previous data is then kept, and `series()` and `get()` go on returning it.

## Series

A frozen dataclass: its fields cannot be assigned, and assigning one raises
`dataclasses.FrozenInstanceError`. A `Series` is a copy of what was read;
it does not change when the library changes, and nothing done with it
changes the library.

| Field | Type | Value |
|---|---|---|
| `position` | `int` | Its place in the library, from 1. The command line accepts it as `#N`. |
| `title` | `str` | The title. |
| `status` | `str` | The status saved in `config.yaml`, `"reading"` when none is saved. The values MeManga writes are `"reading"`, `"on-hold"`, `"dropped"` and `"completed"`; the API passes other text through unchanged. |
| `mode` | `str` | The desktop app's download mode, `"auto"` when none is saved. MeManga writes `"auto"` or `"manual"`; other text is passed through unchanged. |
| `sources` | `tuple[Source, ...]` | The primary source first, then the backup sources. Entries without a URL are left out, so the tuple can be empty. |
| `last_chapter` | `str` or `None` | The last downloaded chapter as recorded in `state.json`, as text, or `None`. |
| `downloaded_chapters` | `tuple[str, ...]` | The downloaded chapters, in chapter order. |
| `failed_chapters` | `tuple[str, ...]` | The chapters whose download failed and can be retried, in chapter order. |
| `send_to_kindle` | `bool` | Whether the series takes part in Kindle delivery: its own choice, or the library's `email.kindle_scope` when it has none. It does not say whether email delivery is set up. |

**Chapter order** sorts by the chapter's number, then by its label: plain
numbers by value, a label such as `"10 Part 1"` by its first number, and a
label without a number, such as `"Extra"`, as 0.

## Source

A frozen dataclass.

| Field | Type | Value |
|---|---|---|
| `name` | `str` | The source as saved, usually its domain. For an entry in the list of sources saved without one, the host of its URL without `www.`. For an old single-source entry saved without one, empty. |
| `url` | `str` | The series URL on that source. |

## LibraryError

```python
class LibraryError(Exception)
```

Raised by `Library()` and `Library.reload()` when the library cannot be
read. The message names the folder or file and the problem. Nothing was
created or changed.

## Reading while MeManga runs

- `config.yaml` and `state.json` are read one after the other, not as one
  snapshot. A check that saves between the two reads can leave the two
  files from different moments.
- The API makes no promise about sharing one `Library` between threads
  while `reload()` runs. Create one per thread, or reload from one thread
  only.

## Examples

Series that are on hold or dropped:

```python
from memanga.api import Library

library = Library()
for series in library.series(status=["on-hold", "dropped"]):
    print(f"#{series.position} {series.title}: {series.status}")
```

Failed chapters of one series, read from a chosen config folder:

```python
from pathlib import Path
from memanga.api import Library

library = Library(Path.home() / "memanga-test")
series = library.get("Example Series")
if series is None:
    print("Not in the library")
else:
    print(", ".join(series.failed_chapters) or "No failed chapters")
```

See changes made later, for example by a scheduled check:

```python
from memanga.api import Library, LibraryError

library = Library()
before = {s.title: s.last_chapter for s in library.series()}

# ... later ...
try:
    library.reload()
except LibraryError as error:
    print(f"Still showing the previous data: {error}")

for series in library.series():
    if series.last_chapter != before.get(series.title):
        print(f"{series.title}: now at {series.last_chapter}")
```
