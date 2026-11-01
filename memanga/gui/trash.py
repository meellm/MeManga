"""Move files to the system trash instead of deleting them (issue #393).

Uses Qt's native implementation: the Recycle Bin on Windows, the Trash on
macOS, and the freedesktop.org Trash on Linux and other desktops. Nothing
is ever deleted permanently here: if the trash can't take a file, it stays
where it is and the caller is told.
"""

import sys
from pathlib import Path

from PySide6.QtCore import QFile


def trash_name() -> str:
    """What the platform calls its trash, for user-facing messages."""
    return "Recycle Bin" if sys.platform == "win32" else "Trash"


def move_to_trash(path: Path) -> str:
    """Move the file or folder at *path* to the system trash.

    Returns where it now lives in the trash, or "" when the platform
    doesn't report it. Raises OSError when it couldn't be moved; the file
    is then left untouched.
    """
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError(f"No such file or folder: {path}")
    # The QFile member form returns a plain bool and, on success, points
    # fileName() at the file's new place in the trash. The static form
    # returns a bare bool in PySide6, so the trash path is lost there.
    qfile = QFile(str(path))
    try:
        moved = qfile.moveToTrash()
    except Exception as exc:
        # Whatever goes wrong in the binding, the file is kept and the
        # caller hears about it the same way as a refused move.
        raise OSError(f"the {trash_name()} couldn't be used: {exc}") from exc
    if moved is not True:
        raise OSError(f"the {trash_name()} isn't available for it")
    location = qfile.fileName()
    return "" if Path(location) == path else location
