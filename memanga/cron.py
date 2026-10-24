"""
Scheduled daily check shared by the CLI (`memanga cron`) and the GUI
Settings page: shell-safe construction of the Unix cron entry and the
Windows Task Scheduler command, plus the install/remove/status service
both surfaces call (issue #297).
"""

import csv
import platform
import shlex
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

# Trailing shell comment that marks the crontab line `cron install` owns.
# install/remove/status only ever touch lines carrying it (issue #231).
MANAGED_MARKER = "# memanga-managed"

# Scheduled-check log, kept in the user-writable runtime dir (issue #232).
LOG_NAME = "memanga.log"

# Windows Task Scheduler task that `cron install` owns.
WINDOWS_TASK_NAME = "MeManga_AutoCheck"

# Seconds one crontab/schtasks call may take, so a stuck scheduler cannot
# hang the CLI or freeze the Settings page.
SCHEDULER_TIMEOUT = 30

# What running a scheduler command can raise: a missing or failing
# executable, a timeout, or output that is not text in the locale's
# encoding (``text=True`` decodes it). All become results, never crashes.
_SCHEDULER_ERRORS = (OSError, subprocess.SubprocessError, UnicodeError)


def quote_cron_path(path) -> str:
    """Quote a filesystem path for use inside a crontab command.

    ``shlex.quote()`` guards against spaces and shell metacharacters;
    crontab(5) additionally turns an unescaped ``%`` into a newline, so
    those are backslash-escaped on top of the shell quoting.
    """
    return shlex.quote(str(path)).replace("%", r"\%")


def scheduled_checks_supported() -> bool:
    """Whether this install can schedule a headless ``check --auto`` run.

    A frozen desktop build has no command-line entry point: its single
    windowed executable starts the app and ignores ``-m memanga check``,
    so a scheduled task would open the window instead of checking
    (issues #324, #336). Source, pip and pipx installs run ``-m memanga``
    with their interpreter and are supported.
    """
    return not getattr(sys, "frozen", False)


def source_checkout_root(package_dir=None):
    """The source checkout ``memanga`` is imported from, or None.

    A checkout set up with ``scripts/linux/setup.sh`` only installs the
    requirements into ``venv``, so ``-m memanga`` is importable only with
    the checkout as working directory (issue #232). Installed packages
    live in ``site-packages``/``dist-packages`` and frozen builds have no
    importable source; both return None.
    """
    if getattr(sys, "frozen", False):
        return None
    if package_dir is None:
        package_dir = Path(__file__).resolve().parent
    root = Path(package_dir).parent
    if root.name in ("site-packages", "dist-packages"):
        return None
    return root


def build_cron_line(minute, hour, runtime_dir, python_path, config_dir=None,
                    source_root=None) -> str:
    """Build the daily auto-check crontab entry with shell-safe paths.

    ``python_path`` is the interpreter that runs ``-m memanga`` (normally
    ``sys.executable``), so the job works for source checkouts and for
    pip/pipx/packaged installs alike (issue #232). ``runtime_dir`` is a
    user-writable MeManga directory (the config root) that receives
    ``memanga.log``; it must never be the package install directory.

    The job runs from ``source_root`` (see :func:`source_checkout_root`)
    so a requirements-only checkout venv can import ``memanga``. For an
    installed package (``source_root`` None) it runs from ``runtime_dir``,
    so a stray ``memanga`` module in cron's default working directory
    cannot shadow the installed package.

    ``config_dir`` pins the scheduled run to a non-default config root
    (issue #221); None keeps the default location.
    """
    runtime_dir = PurePosixPath(Path(runtime_dir).as_posix())
    work_dir = (PurePosixPath(Path(source_root).as_posix())
                if source_root is not None else runtime_dir)
    python_path = Path(python_path).as_posix()
    memanga = f"{quote_cron_path(python_path)} -m memanga"
    if config_dir is not None:
        memanga += f" --config-dir {quote_cron_path(Path(config_dir).as_posix())}"
    command = (
        f"cd {quote_cron_path(work_dir)} && "
        f"{memanga} check --auto --quiet"
    )
    log_path = quote_cron_path(runtime_dir / LOG_NAME)
    return f"{minute} {hour} * * * {command} >> {log_path} 2>&1 {MANAGED_MARKER}"


def _quote_win_arg(value) -> str:
    """Double-quote one argument for Windows ``CommandLineToArgvW`` parsing.

    Trailing backslashes are doubled so a drive root such as ``D:\\``
    does not escape the closing quote.
    """
    value = str(value)
    stripped = value.rstrip("\\")
    return '"' + stripped + "\\" * 2 * (len(value) - len(stripped)) + '"'


def build_task_command(python_path, config_dir=None, source_root=None) -> str:
    """Build the Windows Task Scheduler ``/TR`` command for the daily check.

    Like :func:`build_cron_line` it runs ``-m memanga`` with the given
    interpreter rather than a checkout-local ``venv`` (issue #232).
    Scheduled tasks created by ``schtasks /TR`` have no working directory,
    so for a source checkout the command is wrapped as
    ``cmd /d /c "cd /d "<root>" && "<python>" ..."``. Per ``cmd /?``, when
    the text after ``/c`` starts with a quote and is not a single quoted
    executable, cmd removes only the first and the last quote, so the
    inner quotes around paths with spaces (or ``&``) survive intact.
    """
    cmd = f"{_quote_win_arg(python_path)} -m memanga"
    if config_dir is not None:
        cmd += f" --config-dir {_quote_win_arg(config_dir)}"
    cmd += " check --auto --quiet"
    if source_root is not None:
        cmd = f'cmd /d /c "cd /d "{source_root}" && {cmd}"'
    return cmd


def read_crontab(result):
    """Crontab text from a finished ``crontab -l`` run, or None if unreadable.

    A failed run counts as an empty crontab only when stderr says there is
    no crontab yet (cronie/vixie/macOS: "no crontab for USER"; busybox:
    "No such file or directory"). Any other failure returns None so
    callers never overwrite a crontab they could not read (issue #231).
    """
    if result.returncode == 0:
        return result.stdout or ""
    err = (result.stderr or "").lower()
    if "no crontab" in err or "no such file" in err:
        return ""
    return None


def is_managed_line(line: str) -> bool:
    """True for an active crontab line written by ``cron install``.

    Ownership comes only from the trailing marker (issue #231). Lines that
    merely mention MeManga, and commented-out lines, belong to the user.
    """
    stripped = line.strip()
    return (not stripped.startswith("#")
            and stripped.endswith(f" {MANAGED_MARKER}"))


def managed_lines(crontab: str) -> list:
    """The managed MeManga lines in ``crontab``."""
    return [line for line in crontab.splitlines() if is_managed_line(line)]


def unmanaged_memanga_lines(crontab: str) -> list:
    """Active lines that mention MeManga but lack the marker: hand-written
    jobs or entries from older installs. Reported, never modified."""
    return [line for line in crontab.splitlines()
            if "memanga" in line.lower() and not is_managed_line(line)
            and not line.lstrip().startswith("#")]


def remove_managed_lines(crontab: str):
    """Drop managed lines from ``crontab``, keeping every other line,
    blank line and comment as-is. Returns ``(new_text, removed_count)``."""
    kept, removed = [], 0
    for line in crontab.splitlines(keepends=True):
        if is_managed_line(line):
            removed += 1
        else:
            kept.append(line)
    return "".join(kept), removed


def replace_managed_line(crontab: str, cron_line: str) -> str:
    """Replace any managed lines in ``crontab`` with a single ``cron_line``
    appended at the end; unrelated entries are left untouched."""
    text, _ = remove_managed_lines(crontab)
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}{cron_line}\n"


def parse_schedule_time(text):
    """``(hour, minute)`` for a valid ``HH:MM`` daily check time, else None."""
    parts = str(text).strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


class ScheduleStatus(Enum):
    """Outcome of a scheduler action."""

    INSTALLED = "installed"    # install succeeded, or status found the job
    REMOVED = "removed"
    NOT_FOUND = "not_found"    # status/remove: no MeManga-owned job
    UNREADABLE = "unreadable"  # scheduler could not be read; nothing changed
    FAILED = "failed"          # scheduler could not be written


@dataclass(frozen=True)
class ScheduleResult:
    """What a scheduler action did, for the CLI and GUI to word.

    ``entries`` holds the managed crontab line(s), the installed task
    command or the task's row from the task list; ``unmanaged`` the crontab
    lines that mention MeManga but are left alone (issue #231);
    ``detail`` the scheduler's error text when the action failed.
    """

    status: ScheduleStatus
    windows: bool
    entries: tuple[str, ...] = ()
    unmanaged: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status not in (ScheduleStatus.UNREADABLE,
                                   ScheduleStatus.FAILED)


def _uses_task_scheduler() -> bool:
    return platform.system() == "Windows"


def _run(runner, argv, **kwargs):
    """Run one scheduler command with captured text output and a timeout.

    ``runner`` defaults to :func:`subprocess.run`; the GUI passes one that
    hides the console window in the windowed desktop build.
    """
    runner = runner or subprocess.run
    return runner(argv, capture_output=True, text=True,
                  timeout=SCHEDULER_TIMEOUT, **kwargs)


def _error_text(error) -> str:
    if isinstance(error, UnicodeDecodeError):
        return (f"output is not valid {error.encoding} text "
                f"({error.reason} at byte {error.start})")
    if isinstance(error, UnicodeEncodeError):
        return f"text cannot be written as {error.encoding} ({error.reason})"
    return str(error).strip() or type(error).__name__


def _load_crontab(runner):
    """``(text, detail)``: the current crontab, or None and the reason
    when it could not be read (see :func:`read_crontab`)."""
    try:
        result = _run(runner, ["crontab", "-l"])
    except _SCHEDULER_ERRORS as e:
        return None, _error_text(e)
    text = read_crontab(result)
    if text is None:
        return None, (result.stderr or "").strip()
    return text, ""


def _store_crontab(text, runner):
    """Write ``text`` as the crontab; an empty result deletes it.
    Returns None on success, else the error text."""
    try:
        if text.strip():
            result = _run(runner, ["crontab", "-"], input=text)
        else:
            result = _run(runner, ["crontab", "-r"])
    except _SCHEDULER_ERRORS as e:
        return _error_text(e)
    if result.returncode != 0:
        return (result.stderr or "").strip() or "crontab exited with an error"
    return None


def install_schedule(hour, minute, *, runtime_dir, config_dir=None,
                     source_root=None, python_path=None,
                     runner=None) -> ScheduleResult:
    """Install or replace the daily ``check --auto`` job.

    Unix replaces only the managed crontab line and never writes after a
    failed read (issue #231); Windows recreates :data:`WINDOWS_TASK_NAME`.
    ``runtime_dir``, ``config_dir`` and ``source_root`` are passed to
    :func:`build_cron_line` / :func:`build_task_command`; ``python_path``
    defaults to the running interpreter (issue #232).
    """
    hour, minute = int(hour), int(minute)
    if python_path is None:
        python_path = sys.executable
    if _uses_task_scheduler():
        return _install_task(hour, minute, python_path, config_dir,
                             source_root, runner)

    cron_line = build_cron_line(minute, hour, runtime_dir, python_path,
                                config_dir=config_dir, source_root=source_root)
    existing, detail = _load_crontab(runner)
    if existing is None:
        return ScheduleResult(ScheduleStatus.UNREADABLE, False, detail=detail)
    unmanaged = tuple(unmanaged_memanga_lines(existing))
    error = _store_crontab(replace_managed_line(existing, cron_line), runner)
    if error is not None:
        return ScheduleResult(ScheduleStatus.FAILED, False,
                              unmanaged=unmanaged, detail=error)
    return ScheduleResult(ScheduleStatus.INSTALLED, False, (cron_line,),
                          unmanaged)


def _install_task(hour, minute, python_path, config_dir, source_root, runner):
    command = build_task_command(python_path, config_dir,
                                 source_root=source_root)
    try:
        # /f replaces an existing task in place. Never delete it first: a
        # failed create would then leave no task while config says enabled.
        result = _run(runner, [
            "schtasks", "/create",
            "/tn", WINDOWS_TASK_NAME,
            "/tr", command,
            "/sc", "daily",
            "/st", f"{hour:02d}:{minute:02d}",
            "/f",
        ])
    except _SCHEDULER_ERRORS as e:
        return ScheduleResult(ScheduleStatus.FAILED, True, detail=_error_text(e))
    if result.returncode != 0:
        return ScheduleResult(ScheduleStatus.FAILED, True,
                              detail=(result.stderr or "").strip())
    return ScheduleResult(ScheduleStatus.INSTALLED, True, (command,))


def remove_schedule(*, runner=None) -> ScheduleResult:
    """Remove the job :func:`install_schedule` created, leaving every
    other crontab entry, comment and blank line as-is (issue #231)."""
    if _uses_task_scheduler():
        return _remove_task(runner)

    existing, detail = _load_crontab(runner)
    if existing is None:
        return ScheduleResult(ScheduleStatus.UNREADABLE, False, detail=detail)
    unmanaged = tuple(unmanaged_memanga_lines(existing))
    owned = tuple(managed_lines(existing))
    if not owned:
        return ScheduleResult(ScheduleStatus.NOT_FOUND, False,
                              unmanaged=unmanaged)
    new_crontab, _ = remove_managed_lines(existing)
    error = _store_crontab(new_crontab, runner)
    if error is not None:
        return ScheduleResult(ScheduleStatus.FAILED, False, owned, unmanaged,
                              error)
    return ScheduleResult(ScheduleStatus.REMOVED, False, owned, unmanaged)


def _find_task(runner):
    """Look up the task :func:`install_schedule` creates in the root
    folder of the ``schtasks /query /fo csv /nh`` task list.

    schtasks reports "not found", "access denied" and an unavailable
    scheduler with the same exit code and localized text, so only a task
    list that was read and lacks the task shows it is absent. Returns
    ``(row, error)``: the task's CSV row, or None when the list was read
    without it; ``error`` is why the list could not be read (row None).
    """
    try:
        listing = _run(runner, ["schtasks", "/query", "/fo", "csv", "/nh"])
    except _SCHEDULER_ERRORS as e:
        return None, _error_text(e)
    if listing.returncode != 0:
        return None, ((listing.stderr or "").strip()
                      or "schtasks exited with an error")
    name = WINDOWS_TASK_NAME.lower()
    for row in csv.reader((listing.stdout or "").splitlines()):
        if row and row[0].strip().lstrip("\\").lower() == name:
            return row, None
    return None, None


def _task_status(runner):
    """Windows status: ask for the task by name, and only when that fails
    use the task list to tell "absent" from "could not query"."""
    try:
        result = _run(runner, ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME])
    except _SCHEDULER_ERRORS as e:
        return ScheduleResult(ScheduleStatus.UNREADABLE, True,
                              detail=_error_text(e))
    if result.returncode == 0:
        lines = tuple(line.strip() for line in (result.stdout or "").splitlines()
                      if line.strip())
        return ScheduleResult(ScheduleStatus.INSTALLED, True, lines)
    row, error = _find_task(runner)
    if error is not None:
        return ScheduleResult(ScheduleStatus.UNREADABLE, True,
                              detail=(result.stderr or "").strip() or error)
    if row is None:
        return ScheduleResult(ScheduleStatus.NOT_FOUND, True)
    # Task name, next run time and status, as schtasks lists them.
    shown = "  ".join(field.strip() for field in row if field.strip())
    return ScheduleResult(ScheduleStatus.INSTALLED, True, (shown,))


def _remove_task(runner):
    try:
        result = _run(runner, ["schtasks", "/delete", "/tn",
                               WINDOWS_TASK_NAME, "/f"])
    except _SCHEDULER_ERRORS as e:
        return ScheduleResult(ScheduleStatus.FAILED, True, detail=_error_text(e))
    if result.returncode == 0:
        return ScheduleResult(ScheduleStatus.REMOVED, True)
    row, error = _find_task(runner)
    if row is None and error is None:
        return ScheduleResult(ScheduleStatus.NOT_FOUND, True)
    # Still listed, or no proof it is gone: fail safe so the caller
    # keeps its config.
    detail = (result.stderr or "").strip() or error or ""
    return ScheduleResult(ScheduleStatus.FAILED, True, detail=detail)


def schedule_status(*, runner=None) -> ScheduleResult:
    """Whether the job :func:`install_schedule` creates is present.

    Only the marked crontab line counts as installed (issue #231); an
    unreadable crontab or task list is reported as such, never as "not
    installed".
    """
    if _uses_task_scheduler():
        return _task_status(runner)

    existing, detail = _load_crontab(runner)
    if existing is None:
        return ScheduleResult(ScheduleStatus.UNREADABLE, False, detail=detail)
    owned = tuple(managed_lines(existing))
    status = ScheduleStatus.INSTALLED if owned else ScheduleStatus.NOT_FOUND
    return ScheduleResult(status, False, owned,
                          tuple(unmanaged_memanga_lines(existing)))
