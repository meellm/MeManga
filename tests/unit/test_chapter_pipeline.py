"""Shared chapter pipeline used by `check` and `failed retry` (issue #222).

Downloads and email are replaced with fakes; State is real so the
records each outcome leaves behind are checked as written.
"""

from __future__ import annotations

import pytest

from memanga.chapter_pipeline import (ChapterPipeline, ChapterReporter,
                                      ChapterStatus, DeliveryStatus,
                                      PipelineOptions)
from memanga.downloader import ChapterWithSource, DownloaderError
from memanga.emailer import EmailError
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
EMAIL = {"kindle_email": "reader@example.com", "sender_email": "sender@example.com"}


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

    def email_skipped_folder(self, path):
        self.events.append(("email_skipped_folder",))

    def email_sending(self, path):
        self.events.append(("email_sending",))

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

    return ChapterPipeline(
        options=PipelineOptions(download_dir=tmp_path, output_format="pdf", **opts),
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

        assert outcome.delivery is DeliveryStatus.SKIPPED_FOLDER
        assert sent == []

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

    def test_redeliver_unknown_chapter_sends_nothing(self, state, tmp_path):
        sent = []
        pipeline = _pipeline(state, tmp_path, _Downloads({}), sent=sent,
                             delivery_mode="email", email=EMAIL)

        assert pipeline.redeliver(TITLE, "71") is DeliveryStatus.NOT_REQUESTED
        assert sent == []


class TestSmtpTimeout:
    @pytest.mark.parametrize("email, expected", [
        (dict(EMAIL, smtp_timeout=15), 15),
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
