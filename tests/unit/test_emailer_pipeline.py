"""Deep tests for memanga.emailer — Kindle SMTP delivery.

Covers:
  - send_to_kindle wraps SMTP correctly + attaches the file
  - the Kindle message is an EmailMessage with one PDF or EPUB attachment
  - split_pdf chunks large PDFs under Kindle's attachment limit
  - check_email_config verifies SMTP credentials without sending
  - EmailError raised on bad config / missing file
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import smtplib


@pytest.fixture
def good_cfg():
    return {
        "kindle_email": "user@kindle.com",
        "sender_email": "me@gmail.com",
        "app_password": "abcd efgh ijkl mnop",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
    }


@pytest.fixture
def tiny_pdf(tmp_path):
    p = tmp_path / "ch.pdf"
    # Minimum-viable PDF
    p.write_bytes(b"%PDF-1.4\n%fake content for tests\n%%EOF\n")
    return p


def _call_send(cfg, pdf_path):
    """Adapter: unpack cfg dict into the positional-arg API."""
    from memanga.emailer import send_to_kindle
    return send_to_kindle(
        pdf_path=Path(pdf_path),
        kindle_email=cfg.get("kindle_email", ""),
        sender_email=cfg.get("sender_email", ""),
        smtp_server=cfg.get("smtp_server", "smtp.gmail.com"),
        smtp_port=cfg.get("smtp_port", 587),
        app_password=cfg.get("app_password", ""),
    )


def _call_test_cfg(cfg):
    from memanga.emailer import check_email_config
    return check_email_config(
        sender_email=cfg.get("sender_email", ""),
        smtp_server=cfg.get("smtp_server", "smtp.gmail.com"),
        smtp_port=cfg.get("smtp_port", 587),
        app_password=cfg.get("app_password", ""),
    )


def _make_smtp_mock():
    """Build a MagicMock that satisfies SMTP's context-manager protocol."""
    smtp = MagicMock()
    smtp.__enter__ = MagicMock(return_value=smtp)
    smtp.__exit__ = MagicMock(return_value=False)
    return smtp


# ─────────────────────────────────────────────────────────────────────
# send_to_kindle
# ─────────────────────────────────────────────────────────────────────


class TestSendToKindle:
    def test_calls_smtp_starttls_and_login(self, good_cfg, tiny_pdf):
        smtp = _make_smtp_mock()
        with patch("smtplib.SMTP", return_value=smtp) as mk:
            _call_send(good_cfg, tiny_pdf)
        mk.assert_called_once()
        # Either starttls + login OR SMTP_SSL — both acceptable
        called = (smtp.starttls.called and smtp.login.called) or \
                 (smtp.send_message.called or smtp.sendmail.called)
        assert called or mk.return_value.called

    def test_sends_one_message(self, good_cfg, tiny_pdf):
        smtp = _make_smtp_mock()
        with patch("smtplib.SMTP", return_value=smtp):
            _call_send(good_cfg, tiny_pdf)
        send_calls = (smtp.send_message.call_count
                       + smtp.sendmail.call_count)
        assert send_calls >= 1

    def test_missing_file_raises(self, good_cfg):
        from memanga.emailer import EmailError
        with pytest.raises((EmailError, FileNotFoundError, OSError)):
            _call_send(good_cfg, "/no/such/file.pdf")

    def test_missing_kindle_email_raises(self, tiny_pdf):
        from memanga.emailer import EmailError
        bad = {"sender_email": "x@x", "app_password": "y",
               "smtp_server": "smtp.x", "smtp_port": 587}
        with pytest.raises((EmailError, KeyError, ValueError)):
            _call_send(bad, tiny_pdf)

    @pytest.mark.parametrize("name, label", [
        ("ch.cbz", "CBZ files"),
        ("ch.zip", "ZIP files"),
        ("ch.CBZ", "CBZ files"),
        ("Chapter 71", "Image folders"),
    ])
    def test_unsupported_kindle_format_is_refused_before_smtp(
            self, good_cfg, tmp_path, name, label):
        # Issue #362: Send to Kindle rejects these; nothing is sent.
        from memanga.emailer import EmailError
        path = tmp_path / name
        if "." in name:
            path.write_bytes(b"PK")
        else:
            path.mkdir()
        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(EmailError) as exc_info:
                _call_send(good_cfg, path)
        assert str(exc_info.value) == (
            f"{label} can't be sent to Kindle; only PDF and EPUB can.")
        smtp.assert_not_called()

    def test_epub_is_sent_as_epub_attachment(self, good_cfg, tmp_path):
        epub = tmp_path / "ch.epub"
        epub.write_bytes(b"PK epub")
        smtp = _make_smtp_mock()
        with patch("smtplib.SMTP", return_value=smtp):
            assert _call_send(good_cfg, epub) is True
        msg = smtp.send_message.call_args.args[0]
        attachment = msg.get_payload()[0]
        assert attachment.get_content_type() == "application/epub+zip"
        assert attachment.get_filename() == "ch.epub"

    def test_smtp_auth_error_propagates(self, good_cfg, tiny_pdf):
        smtp = _make_smtp_mock()
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with patch("smtplib.SMTP", return_value=smtp):
            from memanga.emailer import EmailError
            with pytest.raises((EmailError, smtplib.SMTPException)):
                _call_send(good_cfg, tiny_pdf)

    def test_large_single_file_error_explains_raw_and_encoded_limits(
        self, good_cfg, tmp_path
    ):
        from memanga.emailer import EmailError, MAX_ATTACHMENT_SIZE
        epub = tmp_path / "large.epub"
        epub.write_bytes(b"0" * (MAX_ATTACHMENT_SIZE + 1024 * 1024))

        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(EmailError) as exc_info:
                _call_send(good_cfg, epub)

        msg = str(exc_info.value)
        assert "EPUB file is 19.0MB" in msg
        assert "18.0MB safe raw attachment limit" in msg
        assert "25.0MB encoded email cap" in msg
        assert "base64 encoded" in msg
        assert "exceeding the 25MB email limit" not in msg
        smtp.assert_not_called()

    def test_pdf_split_message_explains_raw_and_encoded_limits(
        self, good_cfg, tiny_pdf, capsys, caplog
    ):
        smtp = _make_smtp_mock()
        with caplog.at_level(logging.INFO, logger="memanga.emailer"):
            with patch("memanga.emailer.split_pdf", return_value=[tiny_pdf, tiny_pdf]):
                with patch("smtplib.SMTP", return_value=smtp):
                    _call_send(good_cfg, tiny_pdf)

        # Issue #226: a log record, never stdout.
        assert capsys.readouterr().out == ""
        msg = caplog.text
        assert "Split into 2 parts" in msg
        assert "18.0MB safe raw attachment limit" in msg
        assert "25.0MB" in msg
        assert "exceeded 25MB limit" not in msg

    def test_pdf_is_sent_as_pdf_attachment(self, good_cfg, tiny_pdf):
        smtp = _make_smtp_mock()
        with patch("smtplib.SMTP", return_value=smtp):
            assert _call_send(good_cfg, tiny_pdf) is True
        msg = smtp.send_message.call_args.args[0]
        (attachment,) = msg.iter_attachments()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_filename() == "ch.pdf"
        assert attachment.get_content() == tiny_pdf.read_bytes()


# ─────────────────────────────────────────────────────────────────────
# Message construction (issue #367): EmailMessage.add_attachment()
# ─────────────────────────────────────────────────────────────────────


class TestKindleMessage:
    def _message(self, path):
        from memanga.emailer import _kindle_message
        return _kindle_message(path, "user@kindle.com", "me@gmail.com",
                               "Chapter 1")

    def test_pdf_message(self, tiny_pdf):
        from email import policy
        from email.message import EmailMessage

        msg = self._message(tiny_pdf)

        assert isinstance(msg, EmailMessage)
        assert msg.policy is policy.default
        assert msg.get_content_type() == "multipart/mixed"
        assert msg["From"] == "me@gmail.com"
        assert msg["To"] == "user@kindle.com"
        assert msg["Subject"] == "Chapter 1"
        assert msg["MIME-Version"] == "1.0"
        (attachment,) = msg.iter_attachments()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_content_disposition() == "attachment"
        assert attachment.get_filename() == "ch.pdf"
        assert attachment["Content-Transfer-Encoding"] == "base64"
        assert attachment.get_content() == tiny_pdf.read_bytes()

    def test_epub_message(self, tmp_path):
        epub = tmp_path / "Vol 2.epub"
        epub.write_bytes(b"PK\x03\x04 epub \x00\xff bytes")

        msg = self._message(epub)

        (attachment,) = msg.iter_attachments()
        assert attachment.get_content_type() == "application/epub+zip"
        assert attachment.get_content_disposition() == "attachment"
        assert attachment.get_filename() == "Vol 2.epub"
        assert attachment.get_content() == epub.read_bytes()

    def test_non_ascii_filename_survives_the_wire_format(self, tmp_path):
        from email import message_from_bytes, policy

        pdf = tmp_path / "Ch 3 – Café.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        raw = self._message(pdf).as_bytes()
        raw.decode("ascii")  # every header and part is 7-bit encoded

        parsed = message_from_bytes(raw, policy=policy.default)
        assert parsed.get_all("MIME-Version") == ["1.0"]
        (attachment,) = parsed.iter_attachments()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_filename() == "Ch 3 – Café.pdf"
        assert attachment.get_content() == pdf.read_bytes()


# ─────────────────────────────────────────────────────────────────────
# Email size limit (issue #363): email.max_email_mb drives both checks
# ─────────────────────────────────────────────────────────────────────


MB = 1024 * 1024


class TestEmailSizeLimit:
    def test_default_keeps_the_18mb_raw_limit(self):
        from memanga.emailer import (EMAIL_ATTACHMENT_LIMIT,
                                     MAX_ATTACHMENT_SIZE, email_size_limit,
                                     raw_attachment_limit)
        assert email_size_limit() == EMAIL_ATTACHMENT_LIMIT == 25 * MB
        assert raw_attachment_limit(EMAIL_ATTACHMENT_LIMIT) \
            == MAX_ATTACHMENT_SIZE == 18 * MB

    def test_bounds_match_config_schema(self, isolated_home):
        from memanga.config import CONFIG_KEYS, Config
        from memanga.emailer import (DEFAULT_EMAIL_SIZE_MB, MAX_EMAIL_SIZE_MB,
                                     MIN_EMAIL_SIZE_MB)
        spec = CONFIG_KEYS["email.max_email_mb"]
        assert (spec["min"], spec["max"]) == (MIN_EMAIL_SIZE_MB,
                                              MAX_EMAIL_SIZE_MB)
        assert Config().get("email.max_email_mb") == DEFAULT_EMAIL_SIZE_MB

    @pytest.mark.parametrize("value, expected_mb", [
        (None, 25), (20, 20), (10, 10), (50, 50), (35.5, 35.5),
        # Unusable hand-edited values fall back to the default.
        (9, 25), (51, 25), (0, 25), (-20, 25), (True, 25), ("20", 25),
        (float("nan"), 25), (float("inf"), 25), (10**400, 25),
    ])
    def test_email_size_limit(self, value, expected_mb):
        from memanga.emailer import email_size_limit
        assert email_size_limit(value) == int(expected_mb * MB)

    def test_raw_limit_leaves_room_for_base64_and_headers(self):
        import base64
        from memanga.emailer import raw_attachment_limit
        for mb in (10, 20, 25, 50):
            raw = raw_attachment_limit(mb * MB)
            # base64 body in 76-character lines with CRLF line ends
            encoded = len(base64.encodebytes(b"0" * raw)) * 78 // 77
            assert encoded < mb * MB
            assert mb * MB - encoded > 64 * 1024  # room for headers

    def test_configured_limit_rejects_large_epub(self, good_cfg, tmp_path):
        from memanga.emailer import EmailError, send_to_kindle
        epub = tmp_path / "large.epub"
        epub.write_bytes(b"0" * (15 * MB))

        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(EmailError) as exc_info:
                send_to_kindle(pdf_path=epub, max_email_mb=20, **good_cfg)

        msg = str(exc_info.value)
        assert "EPUB file is 15.0MB" in msg
        assert "14.4MB safe raw attachment limit" in msg
        assert "20.0MB encoded email cap" in msg
        assert "base64 encoded" in msg
        smtp.assert_not_called()

    def test_configured_limit_lets_larger_epub_through(self, good_cfg,
                                                      tmp_path):
        from memanga.emailer import send_to_kindle
        epub = tmp_path / "big.epub"
        epub.write_bytes(b"0" * (19 * MB))
        smtp = _make_smtp_mock()

        with patch("smtplib.SMTP", return_value=smtp):
            assert send_to_kindle(pdf_path=epub, max_email_mb=50,
                                  **good_cfg) is True
        smtp.send_message.assert_called_once()

    @pytest.mark.parametrize("max_email_mb, expected", [
        (None, 18 * MB), (20, 20 * MB * 72 // 100), (999, 18 * MB)])
    def test_configured_limit_sets_the_pdf_part_size(
            self, good_cfg, tiny_pdf, max_email_mb, expected):
        from memanga.emailer import send_to_kindle
        split = MagicMock(return_value=[tiny_pdf])
        with patch("memanga.emailer.split_pdf", split):
            with patch("smtplib.SMTP", return_value=_make_smtp_mock()):
                send_to_kindle(pdf_path=tiny_pdf, max_email_mb=max_email_mb,
                               **good_cfg)

        split.assert_called_once_with(tiny_pdf, max_size=expected)

    def test_oversized_single_page_pdf_is_refused(self, good_cfg, tmp_path,
                                                  split_tmp, monkeypatch):
        # A one-page PDF can't be split, so it must not reach SMTP over
        # the limit.
        import os
        pikepdf = pytest.importorskip("pikepdf")
        from memanga import emailer
        pdf_path = tmp_path / "page.pdf"
        with pikepdf.new() as pdf:
            page = pdf.add_blank_page(page_size=(595, 842))
            page.obj.Contents = pdf.make_stream(os.urandom(4000))
            pdf.save(pdf_path, compress_streams=False)
        monkeypatch.setattr(emailer, "raw_attachment_limit",
                            lambda email_limit: 1000)

        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(emailer.EmailError) as exc_info:
                emailer.send_to_kindle(pdf_path=pdf_path, **good_cfg)

        msg = str(exc_info.value)
        assert msg.startswith("PDF file is ")
        assert "safe raw attachment limit" in msg
        assert "25.0MB encoded email cap" in msg
        assert "can't be split any smaller" in msg
        assert not isinstance(exc_info.value, emailer.EmailPartError)
        smtp.assert_not_called()
        assert pdf_path.exists()
        assert list(split_tmp.iterdir()) == []

    def test_oversized_part_after_split_is_refused_and_cleaned_up(
            self, good_cfg, three_part_pdf, split_tmp, monkeypatch):
        from memanga import emailer
        monkeypatch.setattr(emailer, "raw_attachment_limit",
                            lambda email_limit: 1000)

        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(emailer.EmailError) as exc_info:
                emailer.send_to_kindle(pdf_path=three_part_pdf, **good_cfg)

        assert str(exc_info.value).startswith("PDF part 1 of 3 is ")
        assert not isinstance(exc_info.value, emailer.EmailPartError)
        smtp.assert_not_called()
        assert three_part_pdf.exists()
        assert list(split_tmp.iterdir()) == []

    def test_split_log_names_configured_limits(self, good_cfg, tiny_pdf,
                                              caplog):
        from memanga.emailer import send_to_kindle
        with caplog.at_level(logging.INFO, logger="memanga.emailer"):
            with patch("memanga.emailer.split_pdf",
                       return_value=[tiny_pdf, tiny_pdf]):
                with patch("smtplib.SMTP", return_value=_make_smtp_mock()):
                    send_to_kindle(pdf_path=tiny_pdf, max_email_mb=20,
                                   **good_cfg)

        assert "14.4MB safe raw attachment limit" in caplog.text
        assert "encoded email cap is 20.0MB" in caplog.text


# ─────────────────────────────────────────────────────────────────────
# split_pdf — chunk huge PDFs under the attachment limit
# ─────────────────────────────────────────────────────────────────────


class TestSplitPdf:
    def test_small_pdf_returns_single_path(self, tiny_pdf):
        from memanga.emailer import split_pdf
        parts = split_pdf(tiny_pdf, max_size=10 * 1024 * 1024)
        assert len(parts) == 1
        assert Path(parts[0]).exists()

    def test_large_pdf_split_into_parts(self, tmp_path):
        try:
            import pikepdf  # optional dep
        except ImportError:
            pytest.skip("pikepdf not installed — split_pdf needs it")
        pdf_path = tmp_path / "many.pdf"
        with pikepdf.new() as pdf:
            for _ in range(20):
                pdf.add_blank_page(page_size=(595, 842))
            pdf.save(pdf_path)
        from memanga.emailer import split_pdf
        parts = split_pdf(pdf_path, max_size=1024)
        assert len(parts) >= 1
        for p in parts:
            assert Path(p).exists()


# ─────────────────────────────────────────────────────────────────────
# Split delivery (issue #364): one session, cleanup, part progress
# ─────────────────────────────────────────────────────────────────────


SUBJECTS = ["ch.01", "ch.02", "ch.03"]


@pytest.fixture
def split_tmp(tmp_path, monkeypatch):
    """Where split_pdf makes its temp folder, so leftovers can be seen."""
    import tempfile
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


def _write_three_page_pdf(path):
    """3 pages of 4000 random bytes each, stored uncompressed, so every
    file written this way has the same size but different content."""
    import os
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.new() as pdf:
        for _ in range(3):
            page = pdf.add_blank_page(page_size=(595, 842))
            page.obj.Contents = pdf.make_stream(os.urandom(4000))
        pdf.save(path, compress_streams=False)


@pytest.fixture
def three_part_pdf(tmp_path, monkeypatch):
    """A real 3-page PDF that the real split_pdf cuts into 3 parts."""
    pytest.importorskip("pikepdf")
    from memanga import emailer

    source = tmp_path / "library"
    source.mkdir()
    path = source / "ch.pdf"
    _write_three_page_pdf(path)
    real_split = emailer.split_pdf
    monkeypatch.setattr(emailer, "split_pdf",
                        lambda pdf_path, max_size=None: real_split(
                            pdf_path, max_size=6000))
    return path


def _subjects(smtp):
    return [c.args[0]["Subject"] for c in smtp.send_message.call_args_list]


def _send_split(cfg, path, smtp, **kwargs):
    from memanga.emailer import send_to_kindle
    with patch("smtplib.SMTP", return_value=smtp):
        return send_to_kindle(
            pdf_path=path,
            kindle_email=cfg["kindle_email"],
            sender_email=cfg["sender_email"],
            smtp_server=cfg["smtp_server"],
            smtp_port=cfg["smtp_port"],
            app_password=cfg["app_password"],
            **kwargs,
        )


def _failed_on_part_two(cfg, path):
    from memanga.emailer import EmailPartError
    smtp = _make_smtp_mock()
    smtp.send_message.side_effect = [
        None, smtplib.SMTPDataError(554, b"5.7.1 rejected")]
    with pytest.raises(EmailPartError) as exc_info:
        _send_split(cfg, path, smtp)
    return exc_info.value, smtp


class TestSplitDelivery:
    def test_parts_share_one_session_and_login(self, good_cfg, three_part_pdf,
                                               split_tmp):
        smtp = _make_smtp_mock()
        seen = []
        assert _send_split(good_cfg, three_part_pdf, smtp,
                           on_part_sent=lambda *a: seen.append(a)) is True

        # Every connection would use this mock: one STARTTLS, login and
        # QUIT mean one session.
        assert smtp.starttls.call_count == 1
        assert smtp.login.call_count == 1
        assert smtp.quit.call_count == 1
        assert _subjects(smtp) == SUBJECTS
        attachments = [c.args[0].get_payload()[0].get_filename()
                       for c in smtp.send_message.call_args_list]
        assert attachments == ["ch.01.pdf", "ch.02.pdf", "ch.03.pdf"]
        assert seen == [(1, 3), (2, 3), (3, 3)]
        assert list(split_tmp.iterdir()) == []
        assert three_part_pdf.exists()

    def test_failed_part_stops_reports_and_cleans_up(self, good_cfg,
                                                     three_part_pdf, split_tmp):
        from memanga.emailer import EmailProviderError
        error, smtp = _failed_on_part_two(good_cfg, three_part_pdf)

        # Part 3 is not tried after part 2 failed.
        assert _subjects(smtp) == SUBJECTS[:2]
        assert smtp.login.call_count == 1
        assert (error.part, error.total, error.accepted) == (2, 3, (1,))
        assert error.progress["accepted"] == [1]
        assert str(error).startswith(
            "Part 2 of 3 not sent (parts accepted by the mail server: 1): "
            "SMTP error from smtp.gmail.com:587: 554 5.7.1 rejected")
        assert isinstance(error.__cause__, EmailProviderError)
        assert error.__cause__.smtp_code == 554
        assert list(split_tmp.iterdir()) == []
        assert three_part_pdf.exists()

    def test_retry_sends_only_parts_not_accepted(self, good_cfg,
                                                 three_part_pdf, split_tmp):
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        smtp = _make_smtp_mock()
        seen = []

        assert _send_split(good_cfg, three_part_pdf, smtp,
                           progress=error.progress,
                           on_part_sent=lambda *a: seen.append(a)) is True

        assert _subjects(smtp) == SUBJECTS[1:]
        assert seen == [(2, 3), (3, 3)]
        assert list(split_tmp.iterdir()) == []

    def test_retry_failure_keeps_earlier_parts_accepted(self, good_cfg,
                                                        three_part_pdf, split_tmp):
        from memanga.emailer import EmailPartError
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        smtp = _make_smtp_mock()
        smtp.send_message.side_effect = [None, smtplib.SMTPServerDisconnected("gone")]

        with pytest.raises(EmailPartError) as exc_info:
            _send_split(good_cfg, three_part_pdf, smtp, progress=error.progress)

        assert (exc_info.value.part, exc_info.value.accepted) == (3, (1, 2))
        assert "parts accepted by the mail server: 1, 2" in str(exc_info.value)

    def test_every_part_accepted_earlier_sends_nothing(self, good_cfg,
                                                       three_part_pdf, split_tmp):
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        progress = dict(error.progress, accepted=[1, 2, 3])
        smtp = _make_smtp_mock()

        assert _send_split(good_cfg, three_part_pdf, smtp, progress=progress) is True
        smtp.starttls.assert_not_called()
        smtp.login.assert_not_called()
        assert list(split_tmp.iterdir()) == []

    @pytest.mark.parametrize("change", [
        {"source_mtime_ns": 1}, {"source_size": 1}, {"total": 4},
        {"part_limit": 1}, {"accepted": "1"},
        {"source_sha256": "0" * 64}, {"recipient_sha256": "0" * 64},
        {"source_sha256": None},
    ])
    def test_progress_of_another_file_or_split_resends_every_part(
            self, good_cfg, three_part_pdf, split_tmp, change):
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        smtp = _make_smtp_mock()

        _send_split(good_cfg, three_part_pdf, smtp,
                    progress=dict(error.progress, **change))

        assert _subjects(smtp) == SUBJECTS

    def test_progress_records_the_configured_part_limit(
            self, good_cfg, three_part_pdf, split_tmp):
        # Issue #363: a changed email.max_email_mb is a different split,
        # so a retry under the new limit sends every part.
        from memanga.emailer import MAX_ATTACHMENT_SIZE, EmailPartError
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        assert error.progress["part_limit"] == MAX_ATTACHMENT_SIZE

        smtp = _make_smtp_mock()
        smtp.send_message.side_effect = [
            None, smtplib.SMTPDataError(554, b"5.7.1 rejected")]
        with pytest.raises(EmailPartError) as exc_info:
            _send_split(good_cfg, three_part_pdf, smtp,
                        progress=error.progress, max_email_mb=20)
        assert exc_info.value.progress["part_limit"] == 20 * 1024 * 1024 * 72 // 100
        assert _subjects(smtp) == SUBJECTS[:2]

    def test_rewritten_file_resends_every_part(self, good_cfg, three_part_pdf,
                                               split_tmp):
        import os
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        stat = three_part_pdf.stat()
        os.utime(three_part_pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        smtp = _make_smtp_mock()

        _send_split(good_cfg, three_part_pdf, smtp, progress=error.progress)

        assert _subjects(smtp) == SUBJECTS

    def test_progress_names_content_and_recipient_by_digest(
            self, good_cfg, three_part_pdf, split_tmp):
        import hashlib
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)

        assert error.progress["source_sha256"] == hashlib.sha256(
            three_part_pdf.read_bytes()).hexdigest()
        assert error.progress["recipient_sha256"] == hashlib.sha256(
            good_cfg["kindle_email"].encode()).hexdigest()
        # The address itself is not kept in the progress.
        assert good_cfg["kindle_email"] not in repr(error.progress)

    def test_other_recipient_resends_every_part(self, good_cfg, three_part_pdf,
                                                split_tmp):
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        smtp = _make_smtp_mock()
        other_recipient = "someone-else" + "@" + "kindle.com"
        other = dict(good_cfg, kindle_email=other_recipient)

        _send_split(other, three_part_pdf, smtp, progress=error.progress)

        assert _subjects(smtp) == SUBJECTS
        assert {c.args[0]["To"] for c in smtp.send_message.call_args_list} == {
            other["kindle_email"]}

    def test_same_size_and_mtime_new_content_resends_every_part(
            self, good_cfg, three_part_pdf, split_tmp):
        import os
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        stat = three_part_pdf.stat()
        _write_three_page_pdf(three_part_pdf)
        os.utime(three_part_pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replaced = three_part_pdf.stat()
        assert (replaced.st_size, replaced.st_mtime_ns) == (
            stat.st_size, stat.st_mtime_ns)
        smtp = _make_smtp_mock()

        _send_split(good_cfg, three_part_pdf, smtp, progress=error.progress)

        assert _subjects(smtp) == SUBJECTS

    def test_source_that_cannot_be_hashed_resends_every_part(
            self, good_cfg, three_part_pdf, split_tmp, monkeypatch):
        from memanga import emailer
        error, _ = _failed_on_part_two(good_cfg, three_part_pdf)
        monkeypatch.setattr(emailer, "_file_sha256", lambda path: None)
        smtp = _make_smtp_mock()

        _send_split(good_cfg, three_part_pdf, smtp,
                    progress=dict(error.progress, source_sha256=None))

        assert _subjects(smtp) == SUBJECTS

    def test_login_failure_reports_first_part_and_cleans_up(
            self, good_cfg, three_part_pdf, split_tmp):
        from memanga.emailer import EmailAuthError, EmailPartError
        smtp = _make_smtp_mock()
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")

        with pytest.raises(EmailPartError) as exc_info:
            _send_split(good_cfg, three_part_pdf, smtp)

        assert exc_info.value.part == 1
        assert str(exc_info.value).startswith(
            "Part 1 of 3 not sent (no parts accepted by the mail server): "
            "SMTP authentication failed")
        assert isinstance(exc_info.value.__cause__, EmailAuthError)
        smtp.send_message.assert_not_called()
        assert list(split_tmp.iterdir()) == []

    def test_unexpected_error_is_an_email_error_and_cleans_up(
            self, good_cfg, three_part_pdf, split_tmp):
        from memanga.emailer import EmailPartError
        smtp = _make_smtp_mock()
        smtp.send_message.side_effect = [None, RuntimeError("boom")]

        with pytest.raises(EmailPartError) as exc_info:
            _send_split(good_cfg, three_part_pdf, smtp)

        assert str(exc_info.value).endswith("Failed to send email: boom")
        assert list(split_tmp.iterdir()) == []

    def test_interrupt_propagates_and_cleans_up(self, good_cfg, three_part_pdf,
                                                split_tmp):
        smtp = _make_smtp_mock()
        smtp.send_message.side_effect = KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            _send_split(good_cfg, three_part_pdf, smtp)

        assert list(split_tmp.iterdir()) == []

    def test_unreadable_part_is_not_a_connection_error(
            self, good_cfg, three_part_pdf, split_tmp, monkeypatch):
        from memanga import emailer
        real_message = emailer._kindle_message

        def message(path, *args):
            if path.name == "ch.02.pdf":
                raise PermissionError("denied")
            return real_message(path, *args)

        monkeypatch.setattr(emailer, "_kindle_message", message)
        smtp = _make_smtp_mock()
        with pytest.raises(emailer.EmailPartError) as exc_info:
            _send_split(good_cfg, three_part_pdf, smtp)

        assert exc_info.value.accepted == (1,)
        assert type(exc_info.value.__cause__) is emailer.EmailError
        assert "Could not read ch.02.pdf: denied" in str(exc_info.value)
        assert list(split_tmp.iterdir()) == []

    def test_single_file_errors_are_not_part_errors(self, good_cfg, tiny_pdf):
        from memanga.emailer import EmailPartError, EmailProviderError
        smtp = _make_smtp_mock()
        smtp.send_message.side_effect = smtplib.SMTPDataError(554, b"no")

        with pytest.raises(EmailProviderError) as exc_info:
            _send_split(good_cfg, tiny_pdf, smtp)

        assert not isinstance(exc_info.value, EmailPartError)

    def test_failed_split_leaves_no_temp_folder(self, good_cfg, three_part_pdf,
                                                split_tmp, monkeypatch):
        from memanga import emailer

        def broken(pdf, pdf_path, temp_dir, *args):
            (temp_dir / "ch.01.pdf").write_bytes(b"%PDF")
            raise OSError("No space left on device")

        monkeypatch.setattr(emailer, "_write_parts", broken)
        with pytest.raises(OSError, match="No space left"):
            emailer.split_pdf(three_part_pdf)  # max_size=6000, see fixture
        assert list(split_tmp.iterdir()) == []

    def test_parts_outside_a_split_folder_are_never_removed(self, good_cfg,
                                                            tiny_pdf):
        other = tiny_pdf.parent / "other.pdf"
        other.write_bytes(tiny_pdf.read_bytes())
        smtp = _make_smtp_mock()
        with patch("memanga.emailer.split_pdf", return_value=[tiny_pdf, other]):
            _send_split(good_cfg, tiny_pdf, smtp)

        assert tiny_pdf.exists() and other.exists()


# ─────────────────────────────────────────────────────────────────────
# check_email_config — verify credentials without delivery
# ─────────────────────────────────────────────────────────────────────


class TestEmailConfigCheck:
    def test_returns_true_on_successful_login(self, good_cfg):
        smtp = _make_smtp_mock()
        with patch("smtplib.SMTP", return_value=smtp):
            ok = _call_test_cfg(good_cfg)
        # The function returns a plain bool
        assert ok is True

    def test_returns_false_on_auth_failure(self, good_cfg):
        smtp = _make_smtp_mock()
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with patch("smtplib.SMTP", return_value=smtp):
            ok = _call_test_cfg(good_cfg)
        assert ok is False
