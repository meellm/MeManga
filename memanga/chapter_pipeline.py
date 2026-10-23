"""Process one chapter: download, recover, deliver and record it.

``check``, ``failed retry`` and GUI downloads all run every chapter
through :class:`ChapterPipeline` (issues #222, #295), so backup recovery,
partial-chapter salvage (issue #86), Kindle delivery, delete-after-send,
failure records, download history (issue #240), records of chapters
whose Kindle delivery failed (issue #360) and state cleanup cannot drift
between them.

The pipeline makes the decisions and writes state; it prints nothing.
Progress goes to a :class:`ChapterReporter` while a chapter is processed
(downloads are slow, so the user must see each step as it happens), and
the final result comes back as a :class:`ChapterOutcome`.
"""

import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .chapters import ChapterWithSource
from .downloader import (DEFAULT_PAGE_RETRIES, DownloaderError,
                         _find_chapter_on_backup, _get_sources_from_manga,
                         download_chapter)
from .email_settings import EmailSettings, manga_sends_to_kindle
from .emailer import (EmailPartError, kindle_file_error, kindle_format_error,
                      send_to_kindle)


class ChapterStatus(Enum):
    """How a chapter ended up after every recovery step."""

    COMPLETE = "complete"
    PARTIAL = "partial"   # saved with missing pages, within the threshold
    FAILED = "failed"     # nothing saved; a failure record was written


class DeliveryStatus(Enum):
    """What Kindle delivery did with a saved chapter."""

    NOT_REQUESTED = "not_requested"    # local delivery, no Kindle address,
                                       # or the manga opted out (#341)
    SKIPPED_FORMAT = "skipped_format"  # Kindle doesn't accept the saved
                                       # format: CBZ, ZIP or an image
                                       # folder (#340, #362)
    SENT = "sent"
    FAILED = "failed"                  # the file stays on disk and an
                                       # undelivered record is kept (#360)


@dataclass(frozen=True)
class PipelineOptions:
    """Download and delivery settings for one run, shared by every chapter."""

    download_dir: Path
    output_format: str
    max_retries: int = DEFAULT_PAGE_RETRIES
    post_processing: Optional[Dict[str, Any]] = None
    allow_partial: bool = False
    partial_threshold: float = 0.0
    delivery_mode: str = "local"
    email: EmailSettings = field(default_factory=EmailSettings)
    delete_after_send: bool = False
    # ``None`` uses the downloader's default file name.
    naming_template: Optional[str] = None


@dataclass(frozen=True)
class ChapterOutcome:
    """Result of processing one chapter."""

    chapter: str
    status: ChapterStatus
    path: Optional[Path] = None
    source: Optional[str] = None
    from_backup: bool = False
    # Only for PARTIAL: 1-indexed pages that are missing, and the total.
    missing_pages: List[int] = field(default_factory=list)
    total_pages: int = 0
    delivery: DeliveryStatus = DeliveryStatus.NOT_REQUESTED
    # Only when delivery FAILED: why it failed.
    delivery_error: Optional[str] = None
    # Only when SENT: the local copy was deleted afterwards (#338).
    local_copy_deleted: bool = False
    # Only for FAILED: why the primary and (when tried) backup failed.
    error: Optional[str] = None
    backup_error: Optional[str] = None

    @property
    def saved(self) -> bool:
        """True when a complete or partial chapter was saved."""
        return self.status is not ChapterStatus.FAILED

    @property
    def message(self) -> Optional[str]:
        """Why a FAILED chapter failed, naming both sources when the
        backup was tried too. This is the text of the failure record."""
        if self.backup_error is not None:
            return f"Primary: {self.error}; Backup: {self.backup_error}"
        return self.error


def manga_auto_downloads(manga: Dict[str, Any]) -> bool:
    """Whether new chapters of ``manga`` may be downloaded without the
    user asking for them (#341).

    The desktop app's ``mode: manual`` manga are only surfaced, never
    queued by a background check; any other value, or none (older
    entries), means automatic.
    """
    return manga.get("mode") != "manual"


def chapter_source(manga: Dict[str, Any], chapter) -> str:
    """The source a chapter is downloaded from, for records and events."""
    return getattr(chapter, "source", None) or manga.get("source") or "unknown"


class ChapterReporter:
    """Progress hooks called while a chapter is processed.

    Every hook does nothing by default; a front end overrides the ones it
    shows.
    """

    def downloading(self, chapter):
        """About to download ``chapter`` from its own source."""

    def progress(self, current, total):
        """``current`` of ``total`` pages fetched in the current attempt.

        Raising :class:`InterruptedError` cancels the download, like
        setting the pipeline's ``cancel_event``.
        """

    def trying_backup(self, error, backup_chapter):
        """The primary download failed with ``error``; trying the backup."""

    def backup_failed(self, error):
        """The complete download from the backup failed too."""

    def saved(self, outcome: ChapterOutcome):
        """A chapter was saved (complete or partial), before delivery."""

    def email_skipped_format(self, path: Path, reason: str):
        """``path`` is not sent: Kindle doesn't accept its format
        (``reason`` says which, as a plain sentence)."""

    def email_sending(self, path: Path):
        """About to send ``path`` to Kindle."""

    def email_part_sent(self, path: Path, part: int, total: int):
        """The mail server accepted part ``part`` of ``total`` of the
        split ``path`` (issue #364). Acceptance is not arrival on the
        Kindle."""

    def email_sent(self, path: Path):
        """``path`` reached the Kindle address."""

    def deleted_after_send(self, path: Path):
        """The local copy was deleted after sending."""

    def delete_failed(self, path: Path, error: OSError):
        """Sending worked but the local copy could not be deleted."""

    def email_failed(self, error: Exception):
        """Sending failed with ``error`` (usually an ``EmailError``, but
        any delivery problem lands here); the chapter still counts as
        saved, its file stays on disk and it is recorded as undelivered
        so it can be sent again."""

    def failed(self, outcome: ChapterOutcome):
        """Nothing could be saved; the failure has been recorded."""


def _no_app_password() -> Optional[str]:
    return None


def _size_mb(path: Optional[Path]) -> float:
    """Size of a saved chapter in MiB: the file, or every file in an image
    folder. 0 when there is no path or it cannot be read; the chapter is
    saved regardless."""
    if path is None:
        return 0.0
    try:
        if path.is_dir():
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        else:
            size = path.stat().st_size
    except OSError:
        return 0.0
    return size / (1024 * 1024)


@dataclass
class ChapterPipeline:
    """Runs chapters the same way for every command.

    The collaborators default to the real downloader and emailer; a caller
    may substitute its own (the CLI passes the names it imported, so they
    can be replaced in one place). Setting ``cancel_event`` aborts the
    download in progress with :class:`InterruptedError`.
    """

    options: PipelineOptions
    state: Any
    reporter: ChapterReporter = field(default_factory=ChapterReporter)
    download: Callable[..., Path] = download_chapter
    find_backup: Callable[..., Optional[ChapterWithSource]] = _find_chapter_on_backup
    send: Callable[..., Any] = send_to_kindle
    app_password: Callable[[], Optional[str]] = _no_app_password
    cancel_event: Optional[threading.Event] = None

    def process(self, manga: Dict[str, Any], chapter) -> ChapterOutcome:
        """Download ``chapter`` of ``manga`` and record the result.

        Tries, in order: the chapter's own source; a complete copy from a
        backup source; then, with partial tolerance on, the best partial
        (backup first, then primary) within the threshold. A saved
        chapter is delivered and marked downloaded; a chapter nothing
        could save is recorded as failed. Only :class:`DownloaderError`
        is handled here; anything else, including the
        :class:`InterruptedError` of a cancelled download, propagates to
        the caller without a record.
        """
        opts = self.options
        is_from_backup = isinstance(chapter, ChapterWithSource) and chapter.is_backup
        # Only accept a partial straight away when there's no backup to
        # try first — otherwise prefer a complete download from the
        # backup (issue #86 direction).
        has_backup = (not is_from_backup) and len(_get_sources_from_manga(manga)) > 1
        primary_allow_partial = opts.allow_partial and not has_backup

        self.reporter.downloading(chapter)
        partial = {}
        try:
            path = self._download(manga, chapter, partial,
                                  allow_partial=primary_allow_partial)
        except DownloaderError as error:
            return self._recover(manga, chapter, error,
                                 is_from_backup, primary_allow_partial)
        return self._save(
            manga, chapter, path, partial,
            from_backup=False,
            source=chapter_source(manga, chapter),
        )

    def _download(self, manga, chapter, partial, allow_partial=None):
        """One download attempt. ``partial`` collects the missing pages
        when a partial is kept; ``allow_partial=None`` asks for a
        complete chapter only."""
        opts = self.options
        kwargs = {}
        if allow_partial is not None:
            partial.clear()

            def _capture_partial(failed_pages, total):
                partial["failed_pages"] = failed_pages
                partial["total"] = total

            kwargs = dict(
                allow_partial=allow_partial,
                partial_threshold=opts.partial_threshold,
                on_partial=_capture_partial,
            )
        return self.download(
            manga, chapter, opts.download_dir, opts.output_format,
            state=self.state,
            progress_callback=self.reporter.progress,
            naming_template=opts.naming_template,
            cancel_event=self.cancel_event,
            max_retries=opts.max_retries,
            post_processing=opts.post_processing,
            **kwargs,
        )

    def _recover(self, manga, chapter, error, is_from_backup,
                 primary_allow_partial) -> ChapterOutcome:
        """The primary download failed: try the backup, then a partial,
        else record the failure."""
        title = manga["title"]
        backup_ch = None
        if not is_from_backup:
            backup_ch = self.find_backup(manga, chapter.number, self.state)

        # 1) A complete download from the backup source.
        backup_error = None
        if backup_ch:
            self.reporter.trying_backup(error, backup_ch)
            try:
                path = self._download(manga, backup_ch, {})
            except DownloaderError as be:
                backup_error = be
                self.reporter.backup_failed(be)
            else:
                return self._save(
                    manga, chapter, path, None,
                    from_backup=True,
                    source=chapter_source(manga, backup_ch),
                )

        # 2) No complete chapter anywhere. With partial tolerance on,
        #    salvage the best partial within the threshold.
        if self.options.allow_partial:
            candidates = []
            if backup_ch:
                candidates.append((backup_ch, True))
            # The primary was already tried with partial allowed above
            # when there is no backup.
            if not primary_allow_partial:
                candidates.append((chapter, False))
            for candidate, from_backup in candidates:
                partial = {}
                try:
                    path = self._download(manga, candidate, partial,
                                          allow_partial=True)
                except DownloaderError:
                    continue
                return self._save(
                    manga, chapter, path, partial,
                    from_backup=from_backup,
                    source=chapter_source(manga, candidate),
                )

        # 3) Nothing worked — record the failure.
        source = chapter_source(manga, chapter)
        if backup_error is not None:
            source = f"{source}+{chapter_source(manga, backup_ch)}"
        outcome = ChapterOutcome(
            chapter=chapter.number,
            status=ChapterStatus.FAILED,
            source=source,
            error=str(error),
            backup_error=None if backup_error is None else str(backup_error),
        )
        self.reporter.failed(outcome)
        self.state.add_failed_chapter(
            title, chapter.number, source, outcome.message,
            failed_pages=getattr(error, "failed_pages", None),
        )
        return outcome

    def _save(self, manga, chapter, path, partial, from_backup,
              source) -> ChapterOutcome:
        """Record a saved chapter, deliver it, then mark it downloaded."""
        title = manga["title"]
        if partial:
            missing = partial.get("failed_pages", [])
            total = partial.get("total", 0)
            outcome = ChapterOutcome(
                chapter=chapter.number,
                status=ChapterStatus.PARTIAL,
                path=path,
                source=source,
                from_backup=from_backup,
                missing_pages=missing,
                total_pages=total,
            )
            # Headless runs must leave a trail of which pages are missing.
            self.state.add_notification(
                "warn",
                f"'{title}' Chapter {chapter.number} saved as partial: "
                f"{len(missing)}/{total} page(s) missing (pages {missing}).",
            )
            self.state.add_partial_chapter(
                title,
                chapter.number,
                source=source,
                failed_pages=missing,
                total_pages=total,
                path=str(path),
                from_backup=from_backup,
            )
        else:
            outcome = ChapterOutcome(
                chapter=chapter.number,
                status=ChapterStatus.COMPLETE,
                path=path,
                source=source,
                from_backup=from_backup,
            )
            self.state.clear_partial_chapter(title, chapter.number)
        self.reporter.saved(outcome)

        # Measured before delivery, which may delete the local copy.
        size_mb = _size_mb(path)
        # Delivery runs before the chapter is marked downloaded (#86).
        delivery, delivery_error, deleted, parts = self._deliver(path, manga)
        outcome = replace(outcome, delivery=delivery,
                          delivery_error=delivery_error,
                          local_copy_deleted=deleted)
        # The chapter is saved either way; one that didn't reach the
        # Kindle stays on record until it does (#360).
        self._record_delivery(title, chapter.number, path, delivery,
                              delivery_error, parts)
        self.state.add_downloaded_chapter(title, chapter.number)
        self.state.clear_pending_backup(title, chapter.number)
        self.state.clear_failed_chapter(title, chapter.number)
        # The suspicious-batch guard learns batch sizes from this (#240).
        self.state.add_download_history(
            title, chapter.number, self.options.output_format,
            path="" if path is None else str(path),
            size_mb=size_mb,
            kindle_sent=outcome.delivery is DeliveryStatus.SENT,
            source=source,
            from_backup=from_backup,
            partial=outcome.status is ChapterStatus.PARTIAL,
            deleted_after_send=deleted,
        )
        return outcome

    def redeliver(self, title: str, chapter: str,
                  manga: Optional[Dict[str, Any]] = None) -> DeliveryStatus:
        """Send a saved chapter whose earlier Kindle delivery failed (#360).

        Uses the undelivered record's file and the same delivery step as
        a download, so delete-after-send still only happens once the send
        succeeded. The record is cleared when the chapter is sent and
        kept, with the new error and attempt, when it fails again or its
        file is gone. Parts of a split PDF the mail server already
        accepted are not sent again (#364). A send also updates the chapter's download-history
        entry: sent, and whether the local copy was deleted (#338). With
        email delivery not configured, or ``manga`` (the tracked entry,
        when there is one) opted out of Kindle delivery, nothing is sent
        and the record is left as it is (``NOT_REQUESTED``).
        """
        chapter = str(chapter)
        record = self.state.failures.get_undelivered(title).get(chapter)
        if record is None:
            return DeliveryStatus.NOT_REQUESTED
        if not self.delivers_to_kindle(manga):
            return DeliveryStatus.NOT_REQUESTED
        recorded = str(record.get("path") or "")
        path = Path(recorded)
        parts = None
        if not recorded or not path.is_file():
            error = FileNotFoundError(
                f"The saved file is no longer there: {recorded or '(unknown)'}")
            self.reporter.email_failed(error)
            status, delivery_error = DeliveryStatus.FAILED, str(error)
        else:
            status, delivery_error, deleted, parts = self._deliver(
                path, manga, progress=record.get("parts"))
            if status is DeliveryStatus.SENT:
                self.state.activity.mark_download_sent(
                    title, chapter, recorded, deleted_after_send=deleted)
        self._record_delivery(title, chapter, recorded, status, delivery_error,
                              parts)
        return status

    def _record_delivery(self, title, chapter, path, status,
                         error, parts=None) -> None:
        """Keep the undelivered record in step with a delivery attempt.
        ``parts`` is a split PDF's progress, kept for the retry (#364)."""
        if status is DeliveryStatus.FAILED:
            self.state.failures.add_undelivered(
                title, chapter, "" if path is None else str(path),
                error or "", parts=parts)
        elif status is DeliveryStatus.SENT:
            self.state.failures.clear_undelivered(title, chapter, reason="sent")

    def kindle_format_error(self) -> Optional[str]:
        """Why this run's chapters won't reach the Kindle although Kindle
        delivery is on, or None (#362). Lets a front end warn once,
        before anything is downloaded."""
        if not self.delivers_to_kindle():
            return None
        return kindle_format_error(self.options.output_format)

    def delivers_to_kindle(self, manga: Optional[Dict[str, Any]] = None) -> bool:
        """True when this run sends saved chapters to a Kindle address
        and, given ``manga``, that manga has not opted out (#341)."""
        opts = self.options
        if manga is not None and not manga_sends_to_kindle(manga):
            return False
        return opts.delivery_mode == "email" and bool(opts.email.kindle_email)

    def _deliver(self, path: Path, manga: Optional[Dict[str, Any]] = None,
                 progress: Optional[Dict[str, Any]] = None
                 ) -> Tuple[DeliveryStatus, Optional[str], bool,
                            Optional[Dict[str, Any]]]:
        """Send to Kindle when email delivery is configured and ``manga``
        takes part in it. Returns the status, the error text when it
        FAILED, whether the local copy was deleted after sending, and,
        when a part of a split PDF failed, which parts the mail server
        accepted (#364). ``progress`` is that value from an earlier
        attempt; its accepted parts are not sent again."""
        opts = self.options
        email = opts.email
        if not self.delivers_to_kindle(manga):
            return DeliveryStatus.NOT_REQUESTED, None, False, None
        unsupported = kindle_file_error(path)
        if unsupported:
            self.reporter.email_skipped_format(path, unsupported)
            return DeliveryStatus.SKIPPED_FORMAT, None, False, None
        self.reporter.email_sending(path)
        # The chapter is already saved, so no delivery problem may undo
        # that: besides EmailError, preparing the attachment (reading or
        # splitting the PDF into a temp folder) or reading the password
        # can raise anything. Cancellation still propagates.
        try:
            self.send(
                pdf_path=path,
                kindle_email=email.kindle_email,
                sender_email=email.sender_email,
                smtp_server=email.smtp_server,
                smtp_port=email.smtp_port,
                app_password=self.app_password(),
                timeout=email.smtp_timeout,
                progress=progress,
                on_part_sent=lambda part, total: self.reporter.email_part_sent(
                    path, part, total),
            )
        except InterruptedError:
            raise
        except Exception as error:
            self.reporter.email_failed(error)
            parts = error.progress if isinstance(error, EmailPartError) else None
            return (DeliveryStatus.FAILED, str(error) or type(error).__name__,
                    False, parts)
        self.reporter.email_sent(path)
        deleted = False
        if opts.delete_after_send:
            # The chapter reached the Kindle; a copy that can't be deleted
            # stays on disk rather than failing the chapter.
            try:
                path.unlink()
            except OSError as error:
                self.reporter.delete_failed(path, error)
            else:
                deleted = True
                self.reporter.deleted_after_send(path)
        return DeliveryStatus.SENT, None, deleted, None
