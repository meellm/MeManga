"""
Subprocess helpers for the GUI app.

PyInstaller's `console=False` builds (the release exe) lose their parent
console, so a `subprocess.run`/`subprocess.Popen` call for a console
child (e.g. `schtasks`, `crontab`) makes Windows allocate a fresh
`cmd.exe` window that flashes for a frame. `no_window_kwargs()` returns
the kwargs that suppress that:

    >>> import subprocess
    >>> from memanga.gui._subprocess import no_window_kwargs
    >>> subprocess.run(["schtasks", "/query"], **no_window_kwargs())

Those flags must NOT be used to launch a GUI process such as Windows
Explorer: the same `SW_HIDE`/`CREATE_NO_WINDOW` that hides a console
also suppresses Explorer's own window, so the folder never opens. To
reveal a folder in the OS file manager use `open_in_file_manager()`.

On every non-Windows platform `no_window_kwargs()` returns `{}` — no-op.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def no_window_kwargs() -> dict:
    """Return subprocess kwargs that prevent a cmd window from
    flashing on Windows.

    Uses both `creationflags=CREATE_NO_WINDOW` (Windows ≥ Vista,
    Python ≥ 3.7) and a hidden `STARTUPINFO` so we cover both Python
    builds that don't expose CREATE_NO_WINDOW and the rare cases where
    Windows ignores it.
    """
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": flags, "startupinfo": si}


def open_in_file_manager(directory) -> bool:
    """Open ``directory`` in the OS file manager.

    The directory is created when missing so the action isn't a silent
    no-op on a download folder that hasn't been written to yet. Callers
    that hold a file path should pass its parent.

    Windows uses ``os.startfile`` rather than launching ``explorer`` as
    a subprocess: spawning Explorer with the console-hiding flags from
    ``no_window_kwargs()`` suppresses its window, which is why the
    folder buttons did nothing in the windowed release exe.

    Returns ``True`` if the file manager was invoked, ``False`` if the
    target couldn't be created or opened.
    """
    target = Path(directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not target.is_dir():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
        return True
    except Exception:
        return False
