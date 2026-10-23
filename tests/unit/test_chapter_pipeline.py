"""Shared chapter pipeline used by `check` and `failed retry` (issue #222).

Downloads and email are replaced with fakes; State is real so the
records each outcome leaves behind are checked as written.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from memanga.chapter_pipeline import (ChapterPipeline, ChapterReporter,
                                      ChapterStatus, DeliveryStatus,
                                      PipelineOptions, manga_auto_downloads,
                                      manga_sends_to_kindle)
from memanga.downloader import ChapterWithSource, DownloaderError
from memanga.email_settings import EmailSettings
from memanga.emailer import EmailError, EmailPartError
from memanga.scrapers.base import Chapter


TITLE = "Vinland Saga"
SINGLE = {"title": TITLE, "source": "primary.test", "url": "https://primary.test/vs"}
WITH_BACKUP = {
    "title": TITLE,
    "sources": [
        {"source": "primary.test", "url": "https://primary.test/vs"},
        {"source": "backup.test", "url": "https://backup.test/vs"},
    ],
}
EMAIL = EmailSettings(kindle_email="reader@example.com",
                      sender_email="sender@example.com")


def _primary(number="71"):
    return ChapterWithSource(Chapter(number=number, url=f"https://primary.test/c/{number}"),
                             "primary.test", "https://primary.test/vs")


def _backup(number="71"):
    return ChapterWithSource(Chapter(number=number, url=f"https://backup.test/c/{number}"),
                             "backup.test", "https://backup.test/vs", is_backup=True)


class _Recorder(ChapterReporter):
    def __init__(self):
        self.events = []

    def downloading(self, chapter):
        self.events.append(("downloading", chapter.source))

    def progress(self, current, total):
        self.events.append(("progress", current, total))

    def trying_backup(self, error, backup_chapter):
        self.events.append(("trying_backup", str(error), backup_chapter.source))

    def backup_failed(self, error):
        self.events.append(("backup_failed", str(error)))

    def saved(self, outcome):
        self.events.append(("saved", outcome.status, outcome.from_backup))

    def email_skipped_format(self, path, reason):
        self.events.append(("email_skipped_format", reason))

    def email_sending(self, path):
        self.events.append(("email_sending",))

    def email_part_sent(self, path, part, total):
        self.events.append(("email_part_sent", part, total))

    def email_sent(self, path):
        self.events.append(("email_sent",))

    def deleted_after_send(self, path):
        self.events.append(("deleted_after_send",))

    def delete_failed(self, path, error):
        self.events.append(("delete_failed", str(error)))

    def email_failed(self, error):
        self.events.append(("email_failed", str(error)))

    def failed(self, outcome):
        self.events.append(("failed", outcome.error))


class _Downloads:
    """Fake `download_chapter`. `results` maps (source, partial_allowed)
    to a path, a DownloaderError, or ("partial", path, missing, total)."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, manga, chapter, output_dir, output_format, **kwargs):
        allow_partial = kwargs.get("allow_partial")
        self.calls.append((chapter.source, allow_partial))
        result = self.results.get((chapter.source, bool(allow_partial)))
        if result is None:
            result = self.results[(chapter.source, False)]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, tuple):
            _, path, missing, total = result
            kwargs["on_partial"](missing, total)
            return path
        return result


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "chapter.pdf"
    path.write_bytes(b"%PDF")
    return path


def _pipeline(state, tmp_path, downloads, backup=None, sent=None, **opts):
    def _send(**kwargs):
        if isinstance(sent, Exception):
            raise sent
        if sent is not None:
            sent.append(kwargs["pdf_path"])
            # Delivery happens before the chapter is marked downloaded.
            assert not state.is_chapter_downloaded(TITLE, "71")

    opts.setdefault("output_format", "pdf")
    return ChapterPipeline(
        options=PipelineOptions(download_dir=tmp_path, **opts),
        state=state,
        reporter=_Recorder(),
        download=downloads,
        find_backup=lambda manga, number, state: backup,
        send=_send,
        app_password=lambda: "pw",
    )


class TestPrimarySuccess:
    def test_complete_save_marks_downloaded_and_clears_records(
            self, state, tmp_path, pdf):
        state.add_failed_chapter(TITLE, "71", "primary.test", "timeout")
        state.add_partial_chapter(TITLE, "71", source="primary.test",
                                  failed_pages=[3], total_pages=20)
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.status is ChapterStatus.COMPLETE
        assert outcome.saved
        assert outcome.path == pdf
        assert outcome.source == "primary.test"
        assert not outcome.from_backup
        assert outcome.delivery is DeliveryStatus.NOT_REQUESTED
        assert downloads.calls == [("primary.test", False)]
        assert state.is_chapter_downloaded(TITLE, "71")
        assert state.get_failed_chapters(TITLE) == {}
        assert state.get_partial_chapter(TITLE, "71") is None
        assert pipeline.reporter.events == [
            ("downloading", "primary.test"),
            ("saved", ChapterStatus.COMPLETE, False),
        ]

    def test_single_source_accepts_partial_on_first_attempt(
            self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", True): ("partial", pdf, [7], 40)})
        pipeline = _pipeline(state, tmp_path, downloads,
                             allow_partial=True, partial_threshold=10)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.status is ChapterStatus.PARTIAL
        assert outcome.saved
        assert (outcome.missing_pages, outcome.total_pages) == ([7], 40)
        # No backup to prefer, so no second attempt.
        assert downloads.calls == [("primary.test", True)]
        assert state.get_partial_chapter(TITLE, "71")["failed_pages"] == [7]
        assert state.is_chapter_downloaded(TITLE, "71")
        assert any("saved as partial" in n["message"]
                   for n in state.get("notifications", []))

    def test_with_backup_primary_does_not_accept_partial_first(
            self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             allow_partial=True, partial_threshold=10)

        pipeline.process(WITH_BACKUP, _primary())

        assert downloads.calls == [("primary.test", False)]


class TestBackupRecovery:
    def test_backup_complete_is_emailed_then_marked_downloaded(
            self, state, tmp_path, pdf):
        state.add_failed_chapter(TITLE, "71", "primary.test", "timeout")
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary broke"),
            ("backup.test", False): pdf,
        })
        sent = []
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             sent=sent, delivery_mode="email", email=EMAIL)

        outcome = pipeline.process(WITH_BACKUP, _primary())

        assert outcome.status is ChapterStatus.COMPLETE
        assert outcome.from_backup
        assert outcome.source == "backup.test"
        assert outcome.delivery is DeliveryStatus.SENT
        assert sent == [pdf]
        # The complete backup attempt does not ask for a partial.
        assert downloads.calls == [("primary.test", False), ("backup.test", None)]
        assert state.is_chapter_downloaded(TITLE, "71")
        assert state.get_failed_chapters(TITLE) == {}
        assert pipeline.reporter.events == [
            ("downloading", "primary.test"),
            ("trying_backup", "primary broke", "backup.test"),
            ("saved", ChapterStatus.COMPLETE, True),
            ("email_sending",),
            ("email_sent",),
        ]

    def test_partial_salvage_prefers_backup(self, state, tmp_path, pdf):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary incomplete"),
            ("backup.test", False): DownloaderError("backup incomplete"),
            ("backup.test", True): ("partial", pdf, [7], 40),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             allow_partial=True, partial_threshold=10)

        outcome = pipeline.process(WITH_BACKUP, _primary())

        assert outcome.status is ChapterStatus.PARTIAL
        assert outcome.from_backup
        assert downloads.calls == [
            ("primary.test", False), ("backup.test", None), ("backup.test", True),
        ]
        record = state.get_partial_chapter(TITLE, "71")
        assert record["failed_pages"] == [7]
        assert record["source"] == "backup.test"
        assert state.is_chapter_downloaded(TITLE, "71")

    def test_partial_salvage_falls_back_to_primary(self, state, tmp_path, pdf):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary incomplete"),
            ("primary.test", True): ("partial", pdf, [2], 20),
            ("backup.test", False): DownloaderError("backup incomplete"),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             allow_partial=True, partial_threshold=10)

        outcome = pipeline.process(WITH_BACKUP, _primary())

        assert outcome.status is ChapterStatus.PARTIAL
        assert not outcome.from_backup
        assert outcome.source == "primary.test"
        assert downloads.calls[-1] == ("primary.test", True)

    def test_chapter_already_from_backup_skips_backup_lookup(
            self, state, tmp_path):
        downloads = _Downloads({("backup.test", False): DownloaderError("gone")})
        looked_up = []
        pipeline = _pipeline(state, tmp_path, downloads)
        pipeline.find_backup = lambda *a: looked_up.append(a)

        outcome = pipeline.process(WITH_BACKUP, _backup())

        assert outcome.status is ChapterStatus.FAILED
        assert looked_up == []
        assert state.get_failed_chapters(TITLE)["71"]["source"] == "backup.test"


class TestFailure:
    def test_both_sources_fail_records_combined_failure(self, state, tmp_path):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary broke",
                                                     failed_pages=[4], total_pages=9),
            ("backup.test", False): DownloaderError("backup broke"),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup())

        outcome = pipeline.process(WITH_BACKUP, _primary())

        assert outcome.status is ChapterStatus.FAILED
        assert not outcome.saved
        assert outcome.path is None
        assert (outcome.error, outcome.backup_error) == ("primary broke", "backup broke")
        record = state.get_failed_chapters(TITLE)["71"]
        assert record["source"] == "primary.test+backup.test"
        assert record["error"] == "Primary: primary broke; Backup: backup broke"
        assert outcome.message == record["error"]
        assert record["failed_pages"] == [4]
        assert not state.is_chapter_downloaded(TITLE, "71")
        assert pipeline.reporter.events[-2:] == [
            ("backup_failed", "backup broke"),
            ("failed", "primary broke"),
        ]

    def test_no_backup_records_primary_failure(self, state, tmp_path):
        downloads = _Downloads({("primary.test", False): DownloaderError("HTTP 503")})
        pipeline = _pipeline(state, tmp_path, downloads)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.status is ChapterStatus.FAILED
        assert outcome.backup_error is None
        record = state.get_failed_chapters(TITLE)["71"]
        assert (record["source"], record["error"]) == ("primary.test", "HTTP 503")
        assert outcome.message == "HTTP 503"

    def test_plain_chapter_is_recorded_under_the_manga_source(
            self, state, tmp_path):
        def download(*args, **kwargs):
            raise DownloaderError("HTTP 503")

        pipeline = _pipeline(state, tmp_path, download)
        pipeline.reporter = ChapterReporter()  # the recorder reads .source

        pipeline.process(SINGLE, Chapter(number="71", url="https://primary.test/c/71"))

        assert state.get_failed_chapters(TITLE)["71"]["source"] == "primary.test"

    def test_other_errors_propagate_without_records(self, state, tmp_path):
        downloads = _Downloads({("primary.test", False): RuntimeError("bug")})
        pipeline = _pipeline(state, tmp_path, downloads)

        with pytest.raises(RuntimeError):
            pipeline.process(SINGLE, _primary())
        assert state.get_failed_chapters(TITLE) == {}
        assert not state.is_chapter_downloaded(TITLE, "71")


class TestDelivery:
    def test_delete_after_send_removes_local_copy(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=[],
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert outcome.local_copy_deleted is True
        assert not pdf.exists()
        assert pipeline.reporter.events[-1] == ("deleted_after_send",)
        assert state.is_chapter_downloaded(TITLE, "71")

    def test_sent_without_delete_keeps_local_copy(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=[],
                             delivery_mode="email", email=EMAIL)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert outcome.local_copy_deleted is False
        assert pdf.exists()
        assert state.get_download_history()[0]["deleted_after_send"] is False

    def test_email_failure_keeps_file_and_still_counts_as_saved(
            self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=EmailError("SMTP down"),
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.status is ChapterStatus.COMPLETE
        assert outcome.delivery is DeliveryStatus.FAILED
        assert outcome.delivery_error == "SMTP down"
        assert pdf.exists()
        assert pipeline.reporter.events[-1] == ("email_failed", "SMTP down")
        assert state.is_chapter_downloaded(TITLE, "71")
        # Issue #360: the chapter stays retryable for delivery.
        record = state.failures.get_undelivered(TITLE)["71"]
        assert (record["path"], record["error"], record["attempts"]) == (
            str(pdf), "SMTP down", 1)

    def test_attachment_preparation_error_is_a_failed_delivery(
            self, state, tmp_path, pdf):
        # Splitting a large PDF needs a temp folder; an OSError there is
        # not an EmailError but must not fail the saved chapter.
        state.add_failed_chapter(TITLE, "71", "primary.test", "timeout")
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=OSError("No space left on device"),
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.status is ChapterStatus.COMPLETE
        assert outcome.saved
        assert outcome.delivery is DeliveryStatus.FAILED
        assert pdf.exists()
        assert pipeline.reporter.events[-2:] == [
            ("email_sending",), ("email_failed", "No space left on device"),
        ]
        assert state.is_chapter_downloaded(TITLE, "71")
        assert state.get_failed_chapters(TITLE) == {}

    def test_app_password_error_is_a_failed_delivery(
            self, state, tmp_path, pdf):
        def no_keyring():
            raise RuntimeError("keyring locked")

        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=[],
                             delivery_mode="email", email=EMAIL)
        pipeline.app_password = no_keyring

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.FAILED
        assert pipeline.reporter.events[-1] == ("email_failed", "keyring locked")
        assert state.is_chapter_downloaded(TITLE, "71")

    def test_cancel_during_send_still_propagates(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=InterruptedError("Download cancelled"),
                             delivery_mode="email", email=EMAIL)

        with pytest.raises(InterruptedError):
            pipeline.process(SINGLE, _primary())
        assert pdf.exists()
        assert not state.is_chapter_downloaded(TITLE, "71")

    def test_image_folder_is_not_emailed(self, state, tmp_path):
        folder = tmp_path / "Chapter 71"
        folder.mkdir()
        sent = []
        downloads = _Downloads({("primary.test", False): folder})
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="email", email=EMAIL)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SKIPPED_FORMAT
        assert sent == []
        assert pipeline.reporter.events[-1] == (
            "email_skipped_format",
            "Image folders can't be sent to Kindle; only PDF and EPUB can.")
        assert state.failures.get_all_undelivered() == {}

    @pytest.mark.parametrize("suffix", ["pdf", "epub", "PDF"])
    def test_kindle_formats_are_sent(self, state, tmp_path, suffix):
        # Issue #362: PDF and EPUB are what Send to Kindle accepts.
        path = tmp_path / f"chapter.{suffix}"
        path.write_bytes(b"data")
        sent = []
        downloads = _Downloads({("primary.test", False): path})
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="email", email=EMAIL,
                             output_format=suffix.lower())

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert sent == [path]

    @pytest.mark.parametrize("suffix", ["cbz", "zip", "CBZ"])
    def test_archives_are_saved_but_not_sent(self, state, tmp_path, suffix):
        # Issue #362: Kindle rejects CBZ and ZIP, so they are never
        # emailed; the chapter is saved, kept and not left undelivered,
        # and delete-after-send never removes it.
        path = tmp_path / f"chapter.{suffix}"
        path.write_bytes(b"PK")
        sent = []
        downloads = _Downloads({("primary.test", False): path})
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="email", email=EMAIL,
                             output_format=suffix.lower(),
                             delete_after_send=True)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SKIPPED_FORMAT
        assert outcome.saved
        assert sent == []
        assert path.exists()
        assert pipeline.reporter.events[-1] == (
            "email_skipped_format",
            f"{suffix.upper()} files can't be sent to Kindle; "
            "only PDF and EPUB can.")
        assert state.is_chapter_downloaded(TITLE, "71")
        assert state.failures.get_all_undelivered() == {}
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (False, False)

    @pytest.mark.parametrize("fmt, expected", [
        ("pdf", None),
        ("epub", None),
        ("cbz", "CBZ files can't be sent to Kindle; only PDF and EPUB can."),
        ("zip", "ZIP files can't be sent to Kindle; only PDF and EPUB can."),
        ("jpg", "Image folders (JPG) can't be sent to Kindle; "
                "only PDF and EPUB can."),
        ("png", "Image folders (PNG) can't be sent to Kindle; "
                "only PDF and EPUB can."),
        ("webp", "Image folders (WEBP) can't be sent to Kindle; "
                 "only PDF and EPUB can."),
    ])
    def test_run_level_format_check(self, state, tmp_path, fmt, expected):
        # Issue #362: lets a front end warn before anything is downloaded.
        pipeline = _pipeline(state, tmp_path, _Downloads({}),
                             delivery_mode="email", email=EMAIL,
                             output_format=fmt)
        assert pipeline.kindle_format_error() == expected

    def test_run_level_format_check_needs_kindle_delivery(
            self, state, tmp_path):
        local = _pipeline(state, tmp_path, _Downloads({}),
                          output_format="cbz")
        no_address = _pipeline(state, tmp_path, _Downloads({}),
                               delivery_mode="email", email=EmailSettings(),
                               output_format="cbz")
        assert local.kindle_format_error() is None
        assert no_address.kindle_format_error() is None

    def test_local_delivery_never_emails(self, state, tmp_path, pdf):
        sent = []
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="local", email=EMAIL)

        assert pipeline.process(SINGLE, _primary()).delivery is DeliveryStatus.NOT_REQUESTED
        assert sent == []


class TestProgressAndCancellation:
    """Inputs only the GUI uses (issue #295): page progress, a cancel
    event and the file naming template reach every download attempt."""

    def test_reach_primary_and_backup_attempts(self, state, tmp_path, pdf):
        import threading

        calls = []

        def download(manga, chapter, output_dir, output_format, **kwargs):
            calls.append(kwargs)
            if not chapter.is_backup:
                raise DownloaderError("primary broke")
            kwargs["progress_callback"](3, 3)
            return pdf

        cancel = threading.Event()
        pipeline = _pipeline(state, tmp_path, download, backup=_backup(),
                             naming_template="{title} {chapter}")
        pipeline.cancel_event = cancel

        outcome = pipeline.process(WITH_BACKUP, _primary())

        assert outcome.from_backup
        assert [k["cancel_event"] for k in calls] == [cancel, cancel]
        assert [k["naming_template"] for k in calls] == ["{title} {chapter}"] * 2
        assert ("progress", 3, 3) in pipeline.reporter.events

    def test_cancel_during_backup_propagates_without_records(
            self, state, tmp_path):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary broke"),
            ("backup.test", False): InterruptedError("Download cancelled"),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             allow_partial=True, partial_threshold=10)

        with pytest.raises(InterruptedError):
            pipeline.process(WITH_BACKUP, _primary())
        # Cancelling is not a failure: no record, and no partial salvage.
        assert downloads.calls == [("primary.test", False), ("backup.test", None)]
        assert state.get_failed_chapters(TITLE) == {}
        assert not state.is_chapter_downloaded(TITLE, "71")


class TestDeleteFailure:
    def test_failed_delete_keeps_file_and_counts_as_sent(
            self, state, tmp_path, pdf, monkeypatch):
        def refuse(self, *args, **kwargs):
            raise PermissionError("in use")

        monkeypatch.setattr(type(pdf), "unlink", refuse)
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=[],
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert outcome.local_copy_deleted is False
        assert pdf.exists()
        assert pipeline.reporter.events[-2:] == [
            ("email_sent",), ("delete_failed", "in use"),
        ]
        assert state.is_chapter_downloaded(TITLE, "71")
        # Issue #338: the history says sent, not deleted.
        entry = state.get_download_history()[0]
        assert entry["kindle_sent"] is True
        assert entry["deleted_after_send"] is False


class TestDownloadHistory:
    """Every saved chapter is logged to the download history, which the
    suspicious-batch guard learns batch sizes from (issue #240)."""

    def _entry(self, state):
        history = state.get_download_history()
        assert len(history) == 1
        return history[0]

    def test_primary_complete_is_logged(self, state, tmp_path):
        path = tmp_path / "chapter.pdf"
        path.write_bytes(b"0" * (512 * 1024))
        downloads = _Downloads({("primary.test", False): path})
        pipeline = _pipeline(state, tmp_path, downloads)

        pipeline.process(SINGLE, _primary())

        entry = self._entry(state)
        assert (entry["title"], entry["chapter"], entry["format"]) == (TITLE, "71", "pdf")
        assert entry["path"] == str(path)
        assert entry["size_mb"] == 0.5
        assert entry["source"] == "primary.test"
        assert not entry["from_backup"]
        assert not entry["partial"]
        assert not entry["kindle_sent"]
        assert entry["deleted_after_send"] is False
        assert entry["timestamp"]

    def test_backup_complete_sent_and_deleted_keeps_measured_size(
            self, state, tmp_path):
        path = tmp_path / "chapter.pdf"
        path.write_bytes(b"0" * (512 * 1024))
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary broke"),
            ("backup.test", False): path,
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             sent=[], delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        pipeline.process(WITH_BACKUP, _primary())

        assert not path.exists()
        entry = self._entry(state)
        assert entry["source"] == "backup.test"
        assert entry["from_backup"]
        assert not entry["partial"]
        assert entry["kindle_sent"]
        # Issue #338: the history records that the local copy is gone.
        assert entry["deleted_after_send"] is True
        assert entry["size_mb"] == 0.5

    def test_failed_delivery_is_not_marked_sent(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=EmailError("SMTP down"),
                             delivery_mode="email", email=EMAIL)

        pipeline.process(SINGLE, _primary())

        entry = self._entry(state)
        assert not entry["kindle_sent"]
        assert entry["deleted_after_send"] is False

    def test_backup_partial_is_logged_as_partial(self, state, tmp_path, pdf):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary incomplete"),
            ("backup.test", False): DownloaderError("backup incomplete"),
            ("backup.test", True): ("partial", pdf, [7], 40),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup(),
                             allow_partial=True, partial_threshold=10)

        pipeline.process(WITH_BACKUP, _primary())

        entry = self._entry(state)
        assert entry["source"] == "backup.test"
        assert entry["from_backup"]
        assert entry["partial"]

    def test_primary_partial_is_logged_as_partial(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", True): ("partial", pdf, [7], 40)})
        pipeline = _pipeline(state, tmp_path, downloads,
                             allow_partial=True, partial_threshold=10)

        pipeline.process(SINGLE, _primary())

        entry = self._entry(state)
        assert entry["source"] == "primary.test"
        assert not entry["from_backup"]
        assert entry["partial"]

    def test_image_folder_size_counts_its_files(self, state, tmp_path):
        folder = tmp_path / "Chapter 71"
        folder.mkdir()
        (folder / "001.jpg").write_bytes(b"0" * (256 * 1024))
        (folder / "002.jpg").write_bytes(b"0" * (256 * 1024))
        downloads = _Downloads({("primary.test", False): folder})
        pipeline = _pipeline(state, tmp_path, downloads)

        pipeline.process(SINGLE, _primary())

        assert self._entry(state)["size_mb"] == 0.5

    def test_missing_output_is_logged_with_zero_size(self, state, tmp_path):
        downloads = _Downloads({("primary.test", False): tmp_path / "gone.pdf"})
        pipeline = _pipeline(state, tmp_path, downloads)

        pipeline.process(SINGLE, _primary())

        assert self._entry(state)["size_mb"] == 0

    def test_saved_without_a_path_is_logged_without_one(self, state, tmp_path):
        # A download collaborator may report success without a location
        # (the GUI worker tests do); the chapter still counts as saved.
        downloads = _Downloads({("primary.test", False): None})
        pipeline = _pipeline(state, tmp_path, downloads)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.saved
        assert outcome.path is None
        assert state.is_chapter_downloaded(TITLE, "71")
        entry = self._entry(state)
        assert (entry["path"], entry["size_mb"]) == ("", 0)

    def test_failure_is_not_logged(self, state, tmp_path):
        downloads = _Downloads({
            ("primary.test", False): DownloaderError("primary broke"),
            ("backup.test", False): DownloaderError("backup broke"),
        })
        pipeline = _pipeline(state, tmp_path, downloads, backup=_backup())

        pipeline.process(WITH_BACKUP, _primary())

        assert state.get_download_history() == []

    def test_cancel_during_send_is_not_logged(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=InterruptedError("cancelled"),
                             delivery_mode="email", email=EMAIL)

        with pytest.raises(InterruptedError):
            pipeline.process(SINGLE, _primary())
        assert state.get_download_history() == []

    def test_history_stays_capped(self, state, tmp_path, pdf):
        for i in range(195):
            state.add_download_history("Other", str(i), "pdf")
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads)

        for number in range(1, 11):
            pipeline.process(SINGLE, _primary(str(number)))

        history = state.get_download_history(limit=1000)
        assert len(history) == 200
        assert history[0]["chapter"] == "10"


class TestUndeliveredChapters:
    """Issue #360: a saved chapter whose Kindle delivery failed is kept on
    record until a later send reaches the Kindle."""

    def _failed_delivery(self, state, tmp_path, pdf, **opts):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=EmailError("SMTP down"),
                             delivery_mode="email", email=EMAIL, **opts)
        pipeline.process(SINGLE, _primary())
        return pipeline

    def test_record_survives_a_restart(self, state, tmp_path, pdf):
        from memanga.state import State

        self._failed_delivery(state, tmp_path, pdf)
        state.flush()

        reloaded = State(config_dir=state.config_dir)
        assert list(reloaded.failures.get_all_undelivered()) == [TITLE]
        assert reloaded.failures.get_undelivered(TITLE)["71"]["path"] == str(pdf)
        assert reloaded.get_failed_chapters(TITLE) == {}

    def test_sent_download_clears_an_old_record(self, state, tmp_path, pdf):
        state.failures.add_undelivered(TITLE, "71", str(pdf), "SMTP down")
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads, sent=[],
                             delivery_mode="email", email=EMAIL)

        pipeline.process(SINGLE, _primary())

        assert state.failures.get_undelivered(TITLE) == {}

    def test_local_delivery_leaves_no_record(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads)

        pipeline.process(SINGLE, _primary())

        assert state.failures.get_all_undelivered() == {}

    def test_redeliver_sends_then_deletes_and_clears(self, state, tmp_path, pdf):
        pipeline = self._failed_delivery(state, tmp_path, pdf,
                                         delete_after_send=True)
        assert pdf.exists()
        sent = []

        def send(**kwargs):
            # Delete-after-send only runs once the send returned.
            assert kwargs["pdf_path"].exists()
            sent.append(kwargs["pdf_path"])

        pipeline.send = send
        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.SENT
        assert sent == [pdf]
        assert not pdf.exists()
        assert state.failures.get_undelivered(TITLE) == {}
        resolved = state.get_manga_state(TITLE)["resolved_deliveries"]["71"]
        assert resolved["reason"] == "sent"
        assert pipeline.reporter.events[-2:] == [("email_sent",),
                                                 ("deleted_after_send",)]
        assert state.is_chapter_downloaded(TITLE, "71")
        # Issue #338: the download's history entry now says sent and
        # deleted; no second entry is logged.
        history = state.get_download_history()
        assert len(history) == 1
        assert (history[0]["path"], history[0]["kindle_sent"],
                history[0]["deleted_after_send"]) == (str(pdf), True, True)

    def test_redeliver_without_delete_marks_history_sent_only(
            self, state, tmp_path, pdf):
        pipeline = self._failed_delivery(state, tmp_path, pdf)
        assert state.get_download_history()[0]["kindle_sent"] is False
        pipeline.send = lambda **kwargs: None

        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.SENT
        assert pdf.exists()
        history = state.get_download_history()
        assert len(history) == 1
        assert (history[0]["kindle_sent"],
                history[0]["deleted_after_send"]) == (True, False)

    def test_redeliver_with_failed_delete_marks_history_sent_not_deleted(
            self, state, tmp_path, pdf, monkeypatch):
        pipeline = self._failed_delivery(state, tmp_path, pdf,
                                         delete_after_send=True)
        pipeline.send = lambda **kwargs: None
        real_unlink = type(pdf).unlink

        def refuse(self, *args, **kwargs):
            if self == pdf:
                raise PermissionError("in use")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(type(pdf), "unlink", refuse)
        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.SENT
        assert pdf.exists()
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, False)

    def test_redeliver_failure_keeps_file_and_counts_attempt(
            self, state, tmp_path, pdf):
        pipeline = self._failed_delivery(state, tmp_path, pdf,
                                         delete_after_send=True)

        def send(**kwargs):
            raise EmailError("Mailbox full")

        pipeline.send = send
        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.FAILED
        assert pdf.exists()
        record = state.failures.get_undelivered(TITLE)["71"]
        assert (record["error"], record["attempts"]) == ("Mailbox full", 2)
        # The history entry still says not sent and not deleted.
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (False, False)

    def test_redeliver_missing_file_is_reported_not_sent(
            self, state, tmp_path, pdf):
        pipeline = self._failed_delivery(state, tmp_path, pdf)
        pdf.unlink()
        sent = []
        pipeline.send = lambda **kwargs: sent.append(kwargs)

        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.FAILED
        assert sent == []
        record = state.failures.get_undelivered(TITLE)["71"]
        assert record["attempts"] == 2
        assert record["path"] == str(pdf)
        assert "no longer there" in record["error"]

    def test_redeliver_without_email_delivery_changes_nothing(
            self, state, tmp_path, pdf):
        self._failed_delivery(state, tmp_path, pdf)
        before = state.failures.get_undelivered(TITLE)
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent)

        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.NOT_REQUESTED
        assert sent == []
        assert state.failures.get_undelivered(TITLE) == before

    def test_redeliver_unsupported_record_is_skipped_and_kept(
            self, state, tmp_path):
        # Issue #362: a CBZ recorded before the format rule existed is
        # not sent again; its record stays until the user clears it.
        cbz = tmp_path / "chapter.cbz"
        cbz.write_bytes(b"PK")
        state.failures.add_undelivered(TITLE, "71", str(cbz), "SMTP down")
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL)

        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.SKIPPED_FORMAT
        assert sent == []
        assert cbz.exists()
        assert state.failures.get_undelivered(TITLE)["71"]["path"] == str(cbz)

    def test_redeliver_unknown_chapter_sends_nothing(self, state, tmp_path):
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL)

        assert pipeline.redeliver(TITLE, "71") is DeliveryStatus.NOT_REQUESTED
        assert sent == []


class TestSplitPartDelivery:
    """Issue #364: which parts of a split PDF the mail server accepted is
    kept on the undelivered record, so a retry sends only the rest."""

    PROGRESS = {"total": 3, "accepted": [1], "source_size": 4,
                "source_mtime_ns": 1, "part_limit": 18 * 1024 * 1024}

    def _part_error(self, progress=None):
        return EmailPartError(2, 3, dict(progress or self.PROGRESS),
                              "SMTP error from smtp.test:587: 554 rejected")

    def _failed_part(self, state, tmp_path, pdf, **opts):
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             sent=self._part_error(),
                             delivery_mode="email", email=EMAIL, **opts)
        outcome = pipeline.process(SINGLE, _primary())
        return pipeline, outcome

    def test_failed_part_records_accepted_parts(self, state, tmp_path, pdf):
        _, outcome = self._failed_part(state, tmp_path, pdf,
                                       delete_after_send=True)

        assert outcome.delivery is DeliveryStatus.FAILED
        assert outcome.delivery_error.startswith(
            "Part 2 of 3 not sent (parts accepted by the mail server: 1)")
        record = state.failures.get_undelivered(TITLE)["71"]
        assert record["parts"] == self.PROGRESS
        assert record["error"] == outcome.delivery_error
        # Not every part was sent, so the local copy stays.
        assert pdf.exists()
        assert state.is_chapter_downloaded(TITLE, "71")

    def test_progress_survives_a_restart(self, state, tmp_path, pdf):
        from memanga.state import State

        self._failed_part(state, tmp_path, pdf)
        state.flush()

        reloaded = State(config_dir=state.config_dir)
        assert reloaded.failures.get_undelivered(TITLE)["71"]["parts"] == self.PROGRESS

    def test_redeliver_passes_progress_then_clears(self, state, tmp_path, pdf):
        pipeline, _ = self._failed_part(state, tmp_path, pdf,
                                        delete_after_send=True)
        calls = []

        def send(**kwargs):
            calls.append(kwargs["progress"])
            kwargs["on_part_sent"](2, 3)
            kwargs["on_part_sent"](3, 3)

        pipeline.send = send
        status = pipeline.redeliver(TITLE, "71")

        assert status is DeliveryStatus.SENT
        assert calls == [self.PROGRESS]
        assert state.failures.get_undelivered(TITLE) == {}
        assert not pdf.exists()
        assert pipeline.reporter.events[-4:] == [
            ("email_part_sent", 2, 3), ("email_part_sent", 3, 3),
            ("email_sent",), ("deleted_after_send",)]

    def test_redeliver_part_failure_replaces_progress(self, state, tmp_path, pdf):
        pipeline, _ = self._failed_part(state, tmp_path, pdf)
        later = dict(self.PROGRESS, accepted=[1, 2])

        def send(**kwargs):
            raise EmailPartError(3, 3, dict(later), "timed out")

        pipeline.send = send
        assert pipeline.redeliver(TITLE, "71") is DeliveryStatus.FAILED

        record = state.failures.get_undelivered(TITLE)["71"]
        assert (record["parts"], record["attempts"]) == (later, 2)
        assert record["error"].startswith("Part 3 of 3 not sent")

    @pytest.mark.parametrize("missing_file", [False, True])
    def test_failure_before_any_part_keeps_progress(self, state, tmp_path,
                                                    pdf, missing_file):
        pipeline, _ = self._failed_part(state, tmp_path, pdf)

        def send(**kwargs):
            raise EmailError("App password not configured")

        pipeline.send = send
        if missing_file:
            pdf.unlink()
        assert pipeline.redeliver(TITLE, "71") is DeliveryStatus.FAILED

        record = state.failures.get_undelivered(TITLE)["71"]
        assert (record["parts"], record["attempts"]) == (self.PROGRESS, 2)

    def test_download_without_record_passes_no_progress(self, state,
                                                        tmp_path, pdf):
        calls = []
        downloads = _Downloads({("primary.test", False): pdf})
        pipeline = _pipeline(state, tmp_path, downloads,
                             delivery_mode="email", email=EMAIL)
        pipeline.send = lambda **kwargs: calls.append(kwargs["progress"])

        assert pipeline.process(SINGLE, _primary()).delivery is DeliveryStatus.SENT
        assert calls == [None]


class TestPerMangaPolicy:
    """Issue #341: per-manga mode and Kindle settings, shared by the CLI
    and the desktop app; missing fields keep the old behavior."""

    @pytest.mark.parametrize("manga, expected", [
        ({}, True),
        ({"mode": "auto"}, True),
        ({"mode": None}, True),
        ({"mode": "manual"}, False),
    ])
    def test_auto_downloads(self, manga, expected):
        assert manga_auto_downloads(manga) is expected

    @pytest.mark.parametrize("manga, expected", [
        ({}, True),
        ({"send_to_kindle": True}, True),
        ({"send_to_kindle": False}, False),
    ])
    def test_sends_to_kindle(self, manga, expected):
        assert manga_sends_to_kindle(manga) is expected

    def test_opted_out_manga_is_saved_but_never_sent(
            self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        sent = []
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        outcome = pipeline.process({**SINGLE, "send_to_kindle": False},
                                   _primary())

        assert outcome.status is ChapterStatus.COMPLETE
        assert outcome.delivery is DeliveryStatus.NOT_REQUESTED
        assert sent == []
        # Nothing was sent, so nothing is deleted or left to resend.
        assert pdf.exists()
        assert state.failures.get_all_undelivered() == {}
        assert state.is_chapter_downloaded(TITLE, "71")
        assert ("email_sending",) not in pipeline.reporter.events
        # #338: History says neither sent nor deleted.
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (False, False)

    def test_missing_field_still_sends(self, state, tmp_path, pdf):
        downloads = _Downloads({("primary.test", False): pdf})
        sent = []
        pipeline = _pipeline(state, tmp_path, downloads, sent=sent,
                             delivery_mode="email", email=EMAIL)

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert sent == [pdf]

    def test_delivers_to_kindle_checks_the_manga(self, state, tmp_path):
        pipeline = _pipeline(state, tmp_path, _Downloads({}),
                             delivery_mode="email", email=EMAIL)

        assert pipeline.delivers_to_kindle()
        assert pipeline.delivers_to_kindle(SINGLE)
        assert not pipeline.delivers_to_kindle({**SINGLE, "send_to_kindle": False})

    def test_redeliver_skips_opted_out_manga_and_keeps_record(
            self, state, tmp_path, pdf):
        state.add_download_history(TITLE, "71", "pdf", str(pdf), 0.1)
        state.failures.add_undelivered(TITLE, "71", str(pdf), "SMTP down")
        before = state.failures.get_undelivered(TITLE)
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL,
                             delete_after_send=True)

        status = pipeline.redeliver(TITLE, "71",
                                    {**SINGLE, "send_to_kindle": False})

        assert status is DeliveryStatus.NOT_REQUESTED
        assert sent == []
        assert pdf.exists()
        assert state.failures.get_undelivered(TITLE) == before
        # #338: the history entry is left unsent and not deleted.
        entry = state.get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (False, False)

    def test_redeliver_with_tracked_manga_still_sends(
            self, state, tmp_path, pdf):
        state.failures.add_undelivered(TITLE, "71", str(pdf), "SMTP down")
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL)

        assert pipeline.redeliver(TITLE, "71", SINGLE) is DeliveryStatus.SENT
        assert sent == [pdf]
        assert state.failures.get_undelivered(TITLE) == {}


class TestSmtpTimeout:
    @pytest.mark.parametrize("email, expected", [
        (replace(EMAIL, smtp_timeout=15), 15),
        (EMAIL, None),  # unset: the emailer default applies
    ])
    def test_delivery_passes_configured_timeout(self, state, tmp_path, pdf,
                                                email, expected):
        # Issue #361: delivery honours email.smtp_timeout.
        calls = []
        pipeline = ChapterPipeline(
            options=PipelineOptions(download_dir=tmp_path, output_format="pdf",
                                    delivery_mode="email", email=email),
            state=state,
            reporter=_Recorder(),
            download=_Downloads({("primary.test", False): pdf}),
            find_backup=lambda manga, number, state: None,
            send=lambda **kwargs: calls.append(kwargs),
            app_password=lambda: "pw",
        )

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.SENT
        assert [c["timeout"] for c in calls] == [expected]

    @pytest.mark.parametrize("email, expected", [
        (replace(EMAIL, max_email_mb=20), 20),
        (EMAIL, None),  # unset: the emailer default applies
    ])
    def test_delivery_passes_configured_email_size_limit(
            self, state, tmp_path, pdf, email, expected):
        # Issue #363: delivery honours email.max_email_mb.
        calls = []
        pipeline = ChapterPipeline(
            options=PipelineOptions(download_dir=tmp_path, output_format="pdf",
                                    delivery_mode="email", email=email),
            state=state,
            reporter=_Recorder(),
            download=_Downloads({("primary.test", False): pdf}),
            find_backup=lambda manga, number, state: None,
            send=lambda **kwargs: calls.append(kwargs),
            app_password=lambda: "pw",
        )

        pipeline.process(SINGLE, _primary())

        assert [c["max_email_mb"] for c in calls] == [expected]

    def test_delivery_passes_the_smtp_settings(self, state, tmp_path, pdf):
        # Issue #296: every setting comes from the one EmailSettings.
        calls = []
        email = replace(EMAIL, smtp_server="smtp.example.test", smtp_port=2525,
                        smtp_tls="implicit")
        pipeline = ChapterPipeline(
            options=PipelineOptions(download_dir=tmp_path, output_format="pdf",
                                    delivery_mode="email", email=email),
            state=state,
            reporter=_Recorder(),
            download=_Downloads({("primary.test", False): pdf}),
            find_backup=lambda manga, number, state: None,
            send=lambda **kwargs: calls.append(kwargs),
            app_password=lambda: "pw",
        )

        pipeline.process(SINGLE, _primary())

        (call,) = calls
        assert {key: call[key] for key in (
            "kindle_email", "sender_email", "smtp_server", "smtp_port",
            "smtp_tls", "app_password")} == {
            "kindle_email": "reader@example.com",
            "sender_email": "sender@example.com",
            "smtp_server": "smtp.example.test",
            "smtp_port": 2525,
            "smtp_tls": "implicit",  # issue #366
            "app_password": "pw",
        }

    def test_default_settings_never_email(self, state, tmp_path, pdf):
        # No Kindle address: email mode alone does not deliver.
        sent = []
        pipeline = _pipeline(state, tmp_path,
                             _Downloads({("primary.test", False): pdf}),
                             sent=sent, delivery_mode="email")

        outcome = pipeline.process(SINGLE, _primary())

        assert outcome.delivery is DeliveryStatus.NOT_REQUESTED
        assert sent == []


class TestSendSaved:
    """Issue #355: sending an already saved chapter on request uses the
    same delivery step as a download and never adds a pending record."""

    def _saved(self, state, tmp_path, pdf, sent, **opts):
        """A chapter downloaded with local delivery, then a pipeline that
        emails; returns that pipeline. ``sent`` collects the sent paths,
        or is the error every send raises."""
        downloads = _Downloads({("primary.test", False): pdf})
        _pipeline(state, tmp_path, downloads).process(SINGLE, _primary())
        pipeline = _pipeline(state, tmp_path, _Downloads({}),
                             delivery_mode="email", email=EMAIL, **opts)

        def send(**kwargs):
            if isinstance(sent, Exception):
                raise sent
            sent.append(kwargs["pdf_path"])

        pipeline.send = send
        return pipeline

    def test_sends_marks_history_and_keeps_the_file(self, state, tmp_path, pdf):
        sent = []
        pipeline = self._saved(state, tmp_path, pdf, sent)

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.SENT

        assert sent == [pdf]
        assert pdf.exists()
        history = state.get_download_history()
        assert len(history) == 1
        assert (history[0]["kindle_sent"], history[0]["deleted_after_send"]) == (True, False)
        assert state.failures.get_all_undelivered() == {}

    def test_delete_after_send_deletes_once_sent(self, state, tmp_path, pdf):
        sent = []
        pipeline = self._saved(state, tmp_path, pdf, sent, delete_after_send=True)

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.SENT

        assert not pdf.exists()
        assert state.get_download_history()[0]["deleted_after_send"] is True

    def test_already_sent_chapter_is_sent_again(self, state, tmp_path, pdf):
        sent = []
        pipeline = self._saved(state, tmp_path, pdf, sent)
        pipeline.send_saved(TITLE, "71", pdf, SINGLE)

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.SENT

        assert sent == [pdf, pdf]
        assert len(state.get_download_history()) == 1

    def test_failure_keeps_the_file_and_records_it_undelivered(
            self, state, tmp_path, pdf):
        pipeline = self._saved(state, tmp_path, pdf, EmailError("Mailbox full"),
                               delete_after_send=True)

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.FAILED

        assert pdf.exists()
        record = state.failures.get_undelivered(TITLE)["71"]
        assert (record["path"], record["error"], record["attempts"]) == (
            str(pdf), "Mailbox full", 1)
        assert state.get_download_history()[0]["kindle_sent"] is False
        assert pipeline.reporter.events[-1][0] == "email_failed"

    def test_failed_part_is_kept_and_a_later_send_skips_accepted_parts(
            self, state, tmp_path, pdf):
        """#364 on this path: part 1 accepted, part 2 failed; the next
        send passes that progress on and the record is cleared."""
        progress = {"total": 3, "accepted": [1], "source_size": 4,
                    "source_mtime_ns": 1, "part_limit": 18 * 1024 * 1024}
        pipeline = self._saved(state, tmp_path, pdf, EmailPartError(
            2, 3, dict(progress), "SMTP error from smtp.test:587: 554 rejected"))

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.FAILED
        assert state.failures.get_undelivered(TITLE)["71"]["parts"] == progress

        calls = []
        pipeline.send = lambda **kwargs: calls.append(kwargs["progress"])
        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.SENT

        assert calls == [progress]
        assert state.failures.get_undelivered(TITLE) == {}
        assert state.get_download_history()[0]["kindle_sent"] is True

    def test_progress_of_another_file_is_not_reused(self, state, tmp_path, pdf):
        other = tmp_path / "other.pdf"
        other.write_bytes(b"%PDF")
        state.failures.add_undelivered(TITLE, "71", str(other), "SMTP down",
                                       parts={"total": 3, "accepted": [1]})
        calls = []
        pipeline = self._saved(state, tmp_path, pdf, calls)
        pipeline.send = lambda **kwargs: calls.append(kwargs["progress"])

        assert pipeline.send_saved(TITLE, "71", pdf, SINGLE) is DeliveryStatus.SENT
        assert calls == [None]

    def test_unsupported_format_is_not_sent(self, state, tmp_path):
        cbz = tmp_path / "chapter.cbz"
        cbz.write_bytes(b"PK")
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL)

        assert pipeline.send_saved(TITLE, "71", cbz, SINGLE) is DeliveryStatus.SKIPPED_FORMAT
        assert sent == []

    def test_opted_out_manga_is_not_sent(self, state, tmp_path, pdf):
        sent = []
        pipeline = self._saved(state, tmp_path, pdf, sent)
        manga = dict(SINGLE, send_to_kindle=False)

        assert pipeline.send_saved(TITLE, "71", pdf, manga) is DeliveryStatus.NOT_REQUESTED
        assert sent == []
