"""
Chapter-pipeline adapter for GUI downloads (issue #295).

GUI downloads run through the same :class:`ChapterPipeline` as
`memanga check` and `failed retry`. This module turns the pipeline's
progress hooks and final outcome into the EventBus events the pages
already listen to. It has no Qt dependency.

The worker imports it only when a download runs, like the downloader
itself, so an import problem surfaces as a download error rather than
breaking the app at start-up.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict

from ..chapter_pipeline import ChapterOutcome, ChapterReporter, ChapterStatus
from .events import EventBus

logger = logging.getLogger(__name__)


class GuiChapterReporter(ChapterReporter):
    """Publishes one queued download's progress on the event bus and
    logs what the user would otherwise not see (issue #226)."""

    def __init__(self, events: EventBus, task_id: str, manga: Dict[str, Any],
                 chapter, cancel: threading.Event,
                 delete_after_send: bool = False):
        self._events = events
        self._task_id = task_id
        self._title = manga["title"]
        self._chapter = chapter
        self._cancel = cancel
        self._delete_after_send = delete_after_send

    def _label(self) -> str:
        return f"{self._title} Ch.{self._chapter.number}"

    def downloading(self, chapter):
        self._events.publish("download_started", {
            "task_id": self._task_id,
            "title": self._title,
            "chapter": self._chapter.number,
        })

    def progress(self, current, total):
        if self._cancel.is_set():
            raise InterruptedError("Download cancelled")
        try:
            self._events.publish("download_progress", {
                "task_id": self._task_id,
                "current": current,
                "total": total,
            })
        except Exception:
            pass

    def trying_backup(self, error, backup_chapter):
        logger.warning("Primary failed (%s), trying backup (%s) for %s",
                       error, backup_chapter.source, self._label())

    def backup_failed(self, error):
        logger.warning("Backup also failed for %s: %s", self._label(), error)

    def saved(self, outcome: ChapterOutcome):
        if outcome.status is ChapterStatus.PARTIAL:
            src = " from backup" if outcome.from_backup else ""
            logger.warning("Partial kept%s: %s — %d/%d page(s) missing %s",
                           src, self._label(), len(outcome.missing_pages),
                           outcome.total_pages, outcome.missing_pages)
        elif outcome.from_backup:
            logger.info("Completed from backup: %s", self._label())

    def email_skipped_format(self, path: Path, reason: str):
        logger.warning("Kindle skipped (%s): %s", reason, path)
        # Issues #340, #362: tell the user, as the CLI does, rather than
        # only logging it.
        self._events.publish("kindle_skipped", {
            "task_id": self._task_id,
            "title": self._title,
            "chapter": self._chapter.number,
            "path": str(path),
            "reason": reason,
        })

    def _publish_sent(self, path: Path, **local_copy):
        self._events.publish("kindle_sent", {
            "task_id": self._task_id, "path": str(path),
            "title": self._title, "chapter": self._chapter.number,
            **local_copy,
        })

    def email_sent(self, path: Path):
        # Issue #338: with delete-after-send on, the pipeline reports the
        # deletion right after this; one event then says both what was
        # sent and what happened to the local copy.
        if not self._delete_after_send:
            self._publish_sent(path)

    def deleted_after_send(self, path: Path):
        logger.info("Deleted local copy after sending: %s", path)
        self._publish_sent(path, local_copy="deleted")

    def delete_failed(self, path: Path, error: OSError):
        logger.warning("Could not delete local copy after sending: %s", error)
        self._publish_sent(path, local_copy="kept", delete_error=str(error))

    def email_failed(self, error):
        # The chapter stays recorded as undelivered (issue #360); the
        # Detail page offers to send it again.
        self._events.publish("kindle_error", {
            "task_id": self._task_id, "error": str(error),
            "title": self._title, "chapter": self._chapter.number,
        })

    def failed(self, outcome: ChapterOutcome):
        logger.error("%s: %s", self._label(), outcome.message)


def download_complete_payload(task_id: str, manga: Dict[str, Any],
                              outcome: ChapterOutcome) -> Dict[str, Any]:
    """The ``download_complete`` event for a saved chapter. An accepted
    partial (issue #86) carries its missing pages under ``partial``."""
    payload = {
        "task_id": task_id,
        "path": str(outcome.path) if outcome.path else None,
        "title": manga["title"],
        "chapter": outcome.chapter,
        "from_backup": outcome.from_backup,
        "source": outcome.source,
    }
    if outcome.status is ChapterStatus.PARTIAL:
        payload["partial"] = {
            "failed_pages": list(outcome.missing_pages),
            "total": outcome.total_pages,
        }
    return payload


def download_error_payload(task_id: str, manga: Dict[str, Any],
                           outcome: ChapterOutcome) -> Dict[str, Any]:
    """The ``download_error`` event for a chapter nothing could save."""
    return {
        "task_id": task_id,
        "error": outcome.message,
        "title": manga["title"],
        "chapter": outcome.chapter,
    }
