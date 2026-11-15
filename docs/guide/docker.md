# Run MeManga in Docker

<script setup>
import { release } from '../.vitepress/release'
</script>

The Docker image runs the `memanga` command line in a container: on a home
server, a NAS or any machine with Docker. It does not contain the desktop
app.

This page assumes you know how to run a container. For the commands
themselves see [Use the command line](./cli).

::: warning Two different images
- The **published image** is built from release {{ release.tag }}. It is
  what `docker pull` gives you.
- An image you **build from the source code** has the development version.
  It can do more: it has `memanga watch` for scheduled checks,
  `memanga config set`, and passwords from environment variables.

Each section says which image it is about. A command from the development
version does not work in the published image.
:::

## The published image

The same image is published in two places:

- Docker Hub: `meellm/memanga`
- GitHub Container Registry: `ghcr.io/meellm/memanga`

| Tag | What it is |
|---|---|
| `0.4.4` | Release {{ release.tag }}. Does not change. |
| `0.4` | The newest 0.4 release. Today the same as `0.4.4`. |
| `latest` | The newest release. Today the same as `0.4.4`. |

For a setup that runs unattended, use a full version such as `0.4.4`, so
that an update happens when you decide.

```sh
docker pull meellm/memanga:0.4.4
```

**Systems:** Linux on `amd64` (most PCs and servers) and `arm64` (for
example a 64-bit Raspberry Pi). There is no image for 32-bit ARM.

**Size:** the download for `0.4.4` is about 750 MB compressed on both
systems, as Docker Hub reports it for the image pushed on 3 October 2026.
Unpacked on disk it is larger. To see the size on your machine after the
pull:

```sh
docker image ls meellm/memanga
```

**Why it is large:** the image contains two browsers, Firefox and
Chromium, with the system libraries they need. MeManga uses them for
sources that do not work without a real browser; Chromium is there for
sources that block Firefox. An image with one browser does not exist yet:
see [Planned](#planned).

## Keep your data

A container is thrown away after each run. Your settings, your library and
your downloaded chapters live in two folders that you must keep outside it:

- `/home/memanga/.config/memanga` holds `config.yaml` and `state.json`:
  your settings, your library and the download history.
- `/home/memanga/Downloads/MeManga` holds the downloaded chapters.

### Named volumes

The simplest way. Docker creates the volumes on first use and keeps them
until you remove them:

```sh
docker run --rm --init \
  -v memanga-config:/home/memanga/.config/memanga \
  -v memanga-downloads:/home/memanga/Downloads/MeManga \
  meellm/memanga:0.4.4 list
```

Everything on this page uses this command. Only the last part changes:
`list` here, `status` or `check --auto` elsewhere.

- `--rm` removes the container after the run. The named volumes stay.
- `--init` is explained under [Stopping](#stopping-and-the-init-option).

### Folders on your machine

To have the chapters in a normal folder, give a path instead of a volume
name. Replace `DOWNLOADS-DIR` and `CONFIG-DIR` with full paths:

```sh
docker run --rm --init \
  -v "CONFIG-DIR:/home/memanga/.config/memanga" \
  -v "DOWNLOADS-DIR:/home/memanga/Downloads/MeManga" \
  meellm/memanga:0.4.4 list
```

MeManga runs in the container as a user with the ID `1000`, not as root.
Both folders must exist and be writable for that user ID. If MeManga
reports that it cannot write, give the folders to that ID:

```sh
chown -R 1000:1000 "CONFIG-DIR" "DOWNLOADS-DIR"
```

You may need administrator rights for this command. Files that MeManga
creates belong to user ID `1000` on your machine.

## Run commands

### Commands that ask questions

Some commands ask questions, for example `memanga config`. They need a
terminal, which Docker only provides with `-it`:

```sh
docker run --rm --init -it \
  -v memanga-config:/home/memanga/.config/memanga \
  -v memanga-downloads:/home/memanga/Downloads/MeManga \
  meellm/memanga:0.4.4 config
```

Without `-it` such a command cannot ask and does not do its work.

### Commands without questions

Most everyday commands can be written so that they ask nothing. These work
in the published image. Each is the last part of the command, with the
same volumes as above:

- `add -t "TITLE" -u "SERIES-URL"` adds a series.
- `list` shows your library.
- `check --dry-run` lists new chapters and downloads nothing.
- `check --auto` downloads new chapters without asking.
- `status` shows the settings.

Replace `TITLE` and `SERIES-URL` with your own values. `check` contacts the
sources; `check --auto` downloads.

**In an image built from source** you can also change single settings
without questions, for example
`config set delivery.output_format epub`. The rules for running without a
terminal are in
[Use MeManga in scripts](../reference/scripting#questions-and-running-without-a-terminal).

## Send to a Kindle

Email delivery works in a container as it does elsewhere:
[Send chapters to a Kindle](./kindle) explains the settings.

**Published image:** enter the email settings with the `config` command
above. A container normally has no system keyring, so the password is saved
as plain text in `config.yaml`, in the config volume. Anyone who can read that
volume can read the password.

**Image built from source:** you can keep the password out of the config
volume and pass it in from outside. Put it in a file on your machine that
only you can read, in this form:

```sh
MEMANGA_SMTP_PASSWORD=YOUR-APP-PASSWORD
```

Then add `--env-file "ENV-FILE"` to the `docker run` command, with the path
of that file. `MEMANGA_SMTP_PASSWORD_FILE` works too: it names a file
inside the container that holds only the password.

## Check on a schedule

`memanga cron install` is for a normal installation. **Do not use it in a
container:** no scheduler runs there, so nothing would ever start.

### Published image: let your machine start it

The published image has no command that keeps running. Let the scheduler of
your machine start a container when it is time. With cron on Linux, a line
like this checks every day at 06:00:

```sh
0 6 * * * docker run --rm --init -v memanga-config:/home/memanga/.config/memanga -v memanga-downloads:/home/memanga/Downloads/MeManga meellm/memanga:0.4.4 check --auto --quiet
```

The time is the time of your machine, because your machine starts the run.

### Image built from source: `memanga watch`

The development version has `memanga watch`. It stays running, checks
once at the start and then again after each interval: every 6 hours unless
you say otherwise, and not more often than every 15 minutes.

The Compose file in the repository is set up for this. It **builds the
image from the source code**, so you need a copy of the repository:

```sh
docker compose build
docker compose run --rm memanga list
docker compose up -d scheduler
```

- `memanga` is the service for single commands. `docker compose run`
  connects it to your terminal, so commands that ask questions work.
- `scheduler` runs `memanga watch` every 6 hours with a random delay of up
  to 30 minutes. Docker starts it again when it ends or the machine
  restarts, unless you stopped it yourself.
- `docker compose logs scheduler` shows what it did, and
  `docker compose stop scheduler` stops it.

The Compose file does not use the published image yet: see
[Planned](#planned).

## Stopping and the init option

When a container is stopped, Docker first asks the program to end and
ends it by force after a waiting time, 10 seconds unless you set another.

- With the published image, let a run finish instead of stopping it.
- In the development version, a check that is stopped keeps the chapters
  it had already finished, and `memanga watch` lets a running check save
  its results first. The Compose file gives it one minute for that. With
  plain Docker, use `docker stop -t 60 CONTAINER`.

**`--init`:** the browsers start helper processes. Something has to clean
up after them when they end. The published image has nothing built in for
that, so the commands on this page pass `--init`, which makes Docker add a
small helper. An image built from source has this built in; `--init` is not
needed there and does no harm.

## Update

Your data is in the volumes or folders, not in the image, so updating is
pulling a newer image and using its tag from then on:

```sh
docker pull meellm/memanga:NEW-VERSION
```

Replace `NEW-VERSION` with the version you want. Read the
[release notes](https://github.com/meellm/MeManga/releases) first. Keep a
copy of the config folder before a larger update; `memanga export` writes
your library and history into one file.

To remove an old image, use `docker image rm` with its name and tag.
Removing an image does not touch the volumes.

## Time zone

The image sets no time zone, so the times MeManga prints and saves in a
container are in UTC.

- A schedule from your machine's cron follows your machine's clock.
- `memanga watch` counts intervals and does not depend on the time of day.

Setting a local time zone for the container is not documented as supported
yet: see [Planned](#planned).

## When something does not work

- **"Permission denied" or MeManga cannot save.** A folder from your
  machine is not writable for user ID `1000`. See
  [Folders on your machine](#folders-on-your-machine).
- **A command stops and says it needs a terminal, or a question never
  appears.** Add `-it`, or write the command so that it asks nothing. See
  [Run commands](#run-commands).
- **My library is empty after a restart.** The run did not use the same
  volumes or folders as before. Check both `-v` parts of the command.
- **A command or an option is not recognised.** It probably belongs
  to the development version and the published image is
  {{ release.tag }}. `memanga --help` in the container shows what it has:
  put `--help` as the last part of the command.
- **`--gui` is refused.** The image has no desktop app.
- **A source fails only in the container.** Sources change and block
  automated visits from time to time; this is not specific to Docker. Try
  the same series again later, or on another source.

## Planned

These are not available yet:

- A Compose file that uses the published image, so that no copy of the
  repository is needed:
  [issue 328](https://github.com/meellm/MeManga/issues/328).
- A smaller image with fewer browsers, and documented sizes:
  [issue 332](https://github.com/meellm/MeManga/issues/332).
- Time zone support and guidance for containers:
  [issue 331](https://github.com/meellm/MeManga/issues/331).
