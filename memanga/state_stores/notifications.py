"""Notification log shown in the GUI's notification panel."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..output import DETAIL_MAX_CHARS, redact_diagnostic
from ..persist import SaveError, atomic_write_text
from ._base import StateDomain, snapshot

logger = logging.getLogger(__name__)

# Side files hold only names this store generates; anything else read
# back from state.json is ignored (no paths, no traversal).
_DETAILS_FILE = re.compile(r"[0-9a-f]{32}\.txt")

# Chip buckets of the notification panel, by stored notification ``type``.
_BUCKETS = {
    "new":       {"check"},
    "downloads": {"download", "kindle"},
    "system":    {"error", "warn", "system"},
}


class NotificationStore(StateDomain):
    """The capped notification log (newest kept, oldest dropped)."""

    __slots__ = ()

    MAX_NOTIFICATIONS = 100

    # Issue #342: details longer than the inline preview are kept whole in
    # <config dir>/error-details/, one private file per notification and
    # deleted with it. Only the newest MAX_DETAIL_FILES long errors keep a
    # file (older ones keep their preview and say so), each at most
    # FULL_DETAILS_MAX_CHARS: at most 2,000,000 characters on disk, about
    # 2 MB for ASCII text and never more than 8 MB (4-byte UTF-8). The
    # details view holds at most one file's text in memory.
    DETAILS_DIR = "error-details"
    FULL_DETAILS_MAX_CHARS = 100_000
    MAX_DETAIL_FILES = 20

    def add(self, ntype: str, message: str,
            details: Optional[str] = None) -> None:
        """Add a notification to the log.

        ``message`` is the short line the list shows. ``details`` (issue
        #342) is the complete error behind it, stored redacted (see
        :func:`memanga.output.redact_diagnostic`) for the details view.
        Up to ``DETAIL_MAX_CHARS`` go inline as ``details``; longer text
        also records ``details_chars`` and a ``details_file`` holding the
        whole text (see :meth:`full_details`).

        Writing that file, recording the entry and deleting files no entry
        needs any more all happen under the state lock, so a concurrent
        add or clear can never delete the file of an entry being added.
        The lock is the only one taken here (it is reentrant), so this
        cannot deadlock; it is held for one small file write at most.
        """
        entry = {
            "type": ntype,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }
        # Redaction (regex work) stays outside the lock.
        safe = redact_diagnostic(details, limit=None) if details else ""
        if len(safe) > DETAIL_MAX_CHARS:
            entry["details"] = safe[:DETAIL_MAX_CHARS]
            entry["details_chars"] = len(safe)
        elif safe:
            entry["details"] = safe
        with self._backend._locked() as data:
            if "details_chars" in entry:
                name = self._write_details(safe)
                if name:
                    entry["details_file"] = name
            if "notifications" not in data:
                data["notifications"] = []
            data["notifications"].append(entry)
            dropped = data["notifications"][:-self.MAX_NOTIFICATIONS]
            data["notifications"] = data["notifications"][-self.MAX_NOTIFICATIONS:]
            self._backend._mark_dirty()
            if entry.get("details_file") or any(
                    n.get("details_file") for n in dropped):
                self._prune_details_locked(data)

    def full_details(self, notif: Dict[str, Any]) -> Tuple[str, bool]:
        """The longest kept details of ``notif`` and whether they are
        complete. Reads the side file when there is one; falls back to
        the inline preview (then incomplete) when it is gone."""
        details = notif.get("details", "") or ""
        total = notif.get("details_chars")
        if not isinstance(total, int) or total <= len(details):
            return details, True
        path = self._details_path(notif.get("details_file"))
        if path is not None:
            # Under the lock so a prune can't delete it mid-read.
            with self._backend._locked():
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = None
            if text:
                return text, len(text) >= total
        return details, False

    def _details_dir(self) -> Optional[Path]:
        root = getattr(self._backend, "config_dir", None)
        return Path(root) / self.DETAILS_DIR if root else None

    def _details_path(self, name) -> Optional[Path]:
        folder = self._details_dir()
        if folder is None or not isinstance(name, str):
            return None
        if not _DETAILS_FILE.fullmatch(name):
            return None
        return folder / name

    def _write_details(self, text: str) -> Optional[str]:
        """Write the whole redacted text to a new side file; its name, or
        None when it could not be written (the preview still stands)."""
        folder = self._details_dir()
        if folder is None:
            return None
        name = f"{uuid.uuid4().hex}.txt"
        try:
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            # atomic_write_text creates the file owner-only (mkstemp).
            atomic_write_text(folder / name,
                              text[:self.FULL_DETAILS_MAX_CHARS])
        except (OSError, SaveError) as e:
            logger.warning("Could not keep full error details: %s", e)
            return None
        return name

    def _prune_details_locked(self, data: Dict[str, Any]) -> None:
        """Keep side files only for the newest ``MAX_DETAIL_FILES``
        entries that have one; older entries lose their reference (they
        then show their preview as partial). Caller holds the lock."""
        folder = self._details_dir()
        if folder is None or not folder.is_dir():
            return
        keep = set()
        for n in reversed(data.get("notifications", [])):
            name = n.get("details_file")
            if not name:
                continue
            if len(keep) < self.MAX_DETAIL_FILES:
                keep.add(name)
            else:
                n.pop("details_file", None)
                self._backend._mark_dirty()
        try:
            for path in folder.iterdir():
                if _DETAILS_FILE.fullmatch(path.name) and path.name not in keep:
                    path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not tidy full error details: %s", e)

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent notifications, newest first. Items are copies —
        mark_all_read mutates the stored dicts in place, so live references
        would race."""
        with self._backend._locked() as data:
            return snapshot(
                list(reversed(data.get("notifications", [])[-limit:])))

    def get_unread_count(self) -> int:
        """Count unread notifications."""
        with self._backend._locked() as data:
            return sum(1 for n in data.get("notifications", []) if not n.get("read"))

    def mark_all_read(self) -> None:
        """Mark all notifications as read."""
        with self._backend._locked() as data:
            for n in data.get("notifications", []):
                n["read"] = True
            self._backend._mark_dirty()

    def clear(self) -> None:
        """Wipe all notifications. Used by the GUI's 'Clear all' button."""
        with self._backend._locked() as data:
            data["notifications"] = []
            self._backend._mark_dirty()
            self._prune_details_locked(data)

    def filter(self, kind: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return notifications filtered by category.

        Categories collapse the granular `type` values into the four chip
        buckets used in the UI:
            all       — everything
            new       — new-chapter findings ("check")
            downloads — download-complete / kindle-sent events
            system    — errors, warnings, generic system events
        """
        all_notifs = self.get_recent(limit)
        if kind == "all":
            return all_notifs
        targets = _BUCKETS.get(kind, set())
        return [n for n in all_notifs if n.get("type") in targets]
