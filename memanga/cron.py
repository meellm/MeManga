"""
Crontab helpers for shell-safe construction of the Unix cron entry shared
by the CLI (`memanga cron install`) and the GUI Settings page.
"""

import shlex
from pathlib import Path


def quote_cron_path(path) -> str:
    """Quote a filesystem path for use inside a crontab command.

    ``shlex.quote()`` guards against spaces and shell metacharacters;
    crontab(5) additionally turns an unescaped ``%`` into a newline, so
    those are backslash-escaped on top of the shell quoting.
    """
    return shlex.quote(str(path)).replace("%", r"\%")


def build_cron_line(minute, hour, project_dir, python_path) -> str:
    """Build the daily auto-check crontab entry with shell-safe paths."""
    project_dir = Path(project_dir)
    command = (
        f"cd {quote_cron_path(project_dir)} && "
        f"{quote_cron_path(python_path)} -m memanga check --auto --quiet"
    )
    log_path = quote_cron_path(project_dir / "memanga.log")
    return f"{minute} {hour} * * * {command} >> {log_path} 2>&1"
