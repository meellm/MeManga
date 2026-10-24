"""
Crontab helpers for shell-safe construction of the Unix cron entry shared
by the CLI (`memanga cron install`) and the GUI Settings page.
"""

import shlex
import sys
from pathlib import Path, PurePosixPath

# Trailing shell comment that marks the crontab line `cron install` owns.
# install/remove/status only ever touch lines carrying it (issue #231).
MANAGED_MARKER = "# memanga-managed"

# Scheduled-check log, kept in the user-writable runtime dir (issue #232).
LOG_NAME = "memanga.log"


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
