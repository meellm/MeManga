# Check on a schedule

<script setup>
import { release } from '../.vitepress/release'
</script>

MeManga can check for new chapters without you: once a day at a time you
choose, started by your computer's scheduler, or on a fixed interval by a
command that keeps running. Both run the same command,
`memanga check --auto --quiet`.

::: info How to read this page
- This page describes the **development version** of the command line.
  [In release {{ release.tag }}](#in-release-v0-4-4) explains what is
  different there.
- In a Docker container, follow
  [Check on a schedule](./docker#check-on-a-schedule) on the Docker page
  instead.
:::

## Choose a way

| | Daily scheduled check | `memanga watch` |
|---|---|---|
| Started by | Your system's scheduler: cron on Linux and macOS, Task Scheduler on Windows | You, or whatever keeps it running; it stays in the foreground |
| When | Once a day at a fixed time | At the start, then every interval (6 hours unless you choose another) |
| After a restart | Stays set up | Stops; it has to be started again |
| Set up with | `memanga cron install`, or the desktop app | `memanga watch` |
| Made for | A computer you use every day | Containers and systems without a scheduler |

For most people the daily scheduled check is the simpler choice.

### What you need

- The **command-line version** of MeManga, installed from source: see
  [Command line from source](./install#command-line-from-source). The
  desktop app you download has no command line, so it cannot run a check
  in the background.
- For the daily check on Linux and macOS, a working `cron` and the
  `crontab` command. On Windows, Task Scheduler.

## What a scheduled check does

Every scheduled check is `memanga check --auto --quiet` (see
[Check for new chapters](./cli#check-for-new-chapters)):

- It checks every series with the status `reading` and downloads the new
  chapters without asking.
- If delivery is set to email, the new chapters are also sent: see
  [Send to a Kindle](./kindle).
- Series in [manual mode](./cli#series-in-manual-mode) are checked, but their
  new chapters are only listed, not downloaded.
- A suspicious batch of chapters is held back, as in a check you start
  yourself.
- It never asks a question.

::: warning New series
For a series with no downloaded chapters, every chapter counts as new, and a
scheduled check downloads the whole series. When you add a series, say
which chapter you are on, or run the first check yourself with
`--from`: see [The first check of a new series](./cli#check-for-new-chapters).
:::

## Daily scheduled check

### Set it up

Run this once, with the time of day for the check:

```sh
memanga cron install --time 06:00
```

Without `--time`, MeManga asks for the time; that only works in a
terminal. The time is `HH:MM`, from `00:00` to `23:59`.

On Linux and macOS this adds one line to your crontab. It ends with
`# memanga-managed`, which marks the line as MeManga's. Your other crontab
lines stay as they are. Running `cron install` again replaces MeManga's line,
so there is only ever one.

On Windows it creates the task `MeManga_AutoCheck` in Task Scheduler, or
replaces it if it is already there.

The check uses:

- the Python that ran `cron install`, by its full path, so the virtual
  environment does not need to be active;
- your user account, because it is your crontab or your task;
- the config folder you used when you set it up. If you chose one with
  `--config-dir` or `MEMANGA_CONFIG_DIR`, that folder is written into the
  scheduled command.

If you move or delete the folder with the program or its virtual
environment, run `memanga cron install` again.

### See and remove it

```sh
memanga cron status
memanga cron remove
```

`cron status` shows MeManga's crontab line or task. `cron remove` removes
only that line or task.

If MeManga cannot read your crontab, `install` and `remove` change nothing
and say so.

`cron status` and `cron install` also list crontab lines that mention
MeManga but are not marked as MeManga's, for example a line you wrote
yourself or one from an older version. MeManga leaves those alone. Change or
delete them with `crontab -e`; otherwise both may run.

### In the desktop app

When you run the desktop app from source, **Settings → Advanced →
Scheduled Checks** does the same: enter the time and choose **Install**,
**Remove** or **Status**.

In the desktop app you download, setting up is turned off because it has no
command line. **Remove** and **Status** still work, for a check set up
earlier.

### Time and missed checks

- The time is the local time of the computer, as the scheduler reads it.
  MeManga does not set a time zone for the scheduler.
- If the computer is off or asleep at that time, MeManga does not make up
  the check. Whether the scheduler starts it later depends on the scheduler
  and its settings. Otherwise the next check runs the next day.
- On Windows, the task is created with Task Scheduler's default settings.
  Open the task in Task Scheduler to see when it runs, for example whether
  only while you are signed in.

### Where the output goes

On Linux and macOS, each check appends its output to `memanga.log` in the
config folder (`memanga config path` shows where the config file is). Each
run starts with a line showing its date and time. MeManga does not shorten
this file; delete it when no check is running if it grows too large.

On Windows, the task does not keep the output. Task Scheduler shows when the
task last ran and its result, which is the exit code of the check.

The exit codes are listed in [Exit codes](../reference/scripting#exit-codes):
for example `1` when every check failed or MeManga was busy, and `3` when
some chapters failed.

## memanga watch

`memanga watch` stays in the foreground and checks for new chapters at the
start and then again after each interval:

```sh
memanga watch
memanga watch --every 12h
memanga watch --every 6h --jitter 20m
```

- `--every` is the time from the start of one check to the start of the
  next: 6 hours unless you say otherwise, at least 15 minutes. Durations
  are a number with `d`, `h`, `m` or `s`, for example `90m` or `1h30m`.
- `--jitter` adds a random delay of up to that long to each wait.
- It prints when each check starts and ends and when the next one is due,
  in the local time.
- Each check runs as its own process. If one takes longer than the
  interval, the next starts as soon as it is done; two checks never run at
  once.
- If a check fails, `watch` says so and keeps the schedule.
- `watch` measures the interval, not the time of day, so a change of the
  clock does not move it. Whether time the computer spends asleep counts
  towards the interval depends on the system; the next check can come
  later than you expect after a sleep.
- Global options go before `watch`, for example
  `memanga --config-dir DIR watch` or `memanga --log-file watch`; they are
  passed on to each check.

To stop it, press Ctrl-C or send it the `TERM` signal. A check that is
running then gets up to 45 seconds to save what it has done. `watch` exits
with `130` after Ctrl-C and `143` after `TERM`.

`watch` does not restart itself after an error that stops it or after the
computer restarts, and MeManga comes with no service file for it. In
Docker, the `scheduler` service of `compose.dev.yaml` keeps it running: see
[Check on a schedule](./docker#check-on-a-schedule) on the Docker page.

## While other MeManga programs run

Only one MeManga program at a time may change the config folder. A check
that starts while another one is still running, or while the desktop app is
open, does nothing, prints `another MeManga process is using …` and exits
with `1`. The next scheduled check runs normally.

So close the desktop app when a check is due, or let the desktop app check
by itself: when it starts or comes back online, it checks if the last check
is older than an hour, unless you changed that (see
[`gui.auto_check`](../reference/config#gui-auto-check)).

Commands that only read, such as `memanga list` and `memanga status`, work
while a check runs.

## When the computer shuts down

When a check is stopped with the `TERM` signal, as many systems do when they
shut down, it saves what it has done and exits with `143`. Each chapter is
recorded as soon as it is saved, so the next check carries on from there.

## When something does not work

- `memanga doctor` compares the scheduled check with your settings: whether
  one is set up and whether that matches what MeManga recorded. On Linux
  and macOS it also looks for duplicate lines and whether the Python a line
  uses still exists.
- `memanga cron status` shows what is set up. `memanga status` shows the
  settings MeManga recorded when you set it up, not the scheduler itself.
- Read `memanga.log`, or on Windows the task's last result in Task
  Scheduler.
- Chapters downloaded but not sent: a scheduled check may not be able to
  open the keyring your desktop session uses. `memanga send --pending` sends
  them again; [Where the password is stored](./kindle#where-the-password-is-stored)
  lists other ways to give MeManga the password.
- cron starts the check with few environment variables; settings from your
  shell profile are not there. A variable the check needs, such as
  `MEMANGA_SMTP_PASSWORD_FILE`, can go into the crontab as a line
  `NAME=value` above MeManga's line.
- `memanga failed` lists chapters that failed.

## In release v0.4.4

- **`memanga cron install` and `remove` in {{ release.tag }} delete every
  crontab line that contains the word `memanga`**, including lines you wrote
  yourself. Keep a copy of your crontab first, with `crontab -l`.
- Its log file `memanga.log` is in the folder the program is installed in,
  not in the config folder.
- {{ release.tag }} has no `memanga watch`.
- In the {{ release.tag }} desktop app you download, **Scheduled Checks**
  creates a task that starts the app instead of running a check. Do not use
  it there.
- After moving from {{ release.tag }} to the development version, the line
  {{ release.tag }} wrote is not marked as MeManga's. `cron status` lists it,
  but `install` and `remove` leave it alone. Delete it with `crontab -e`, then
  run `memanga cron install`. On Windows the task has the same name and is
  replaced.
