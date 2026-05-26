"""
Subprocess helpers for the GUI app.

PyInstaller's `console=False` builds (the release exe) lose their parent
console, so every `subprocess.run`/`subprocess.Popen` call would get
Windows to allocate a fresh `cmd.exe` window for the child — even when
the child is `explorer.exe` or the headless Playwright driver. The
window flashes for a frame and disappears, but it's noticeable enough
to look broken to a normal user.

This module exports `no_window_kwargs()` which returns the right
kwargs to pass to `subprocess.*` so no console pops:

    >>> import subprocess
    >>> from memanga.gui._subprocess import no_window_kwargs
    >>> subprocess.run(["explorer", "C:/Users"], **no_window_kwargs())

On every non-Windows platform it returns `{}` — no-op.
"""

from __future__ import annotations

import os
import subprocess


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
