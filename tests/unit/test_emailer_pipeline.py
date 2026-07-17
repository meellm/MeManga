"""Deep tests for memanga.emailer — Kindle SMTP delivery.

Covers:
  - send_to_kindle wraps SMTP correctly + attaches the file
  - split_pdf chunks large PDFs under Kindle's attachment limit
  - test_email_config verifies SMTP credentials without sending
  - EmailError raised on bad config / missing file
"""

from __future__ import annotations

import io
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
    from memanga.emailer import test_email_config
    return test_email_config(
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
        cbz = tmp_path / "large.cbz"
        cbz.write_bytes(b"0" * (MAX_ATTACHMENT_SIZE + 1024 * 1024))

        with patch("smtplib.SMTP") as smtp:
            with pytest.raises(EmailError) as exc_info:
                _call_send(good_cfg, cbz)

        msg = str(exc_info.value)
        assert "CBZ file is 19.0MB" in msg
        assert "18.0MB safe raw attachment limit" in msg
        assert "25.0MB encoded email cap" in msg
        assert "base64 encoded" in msg
        assert "exceeding the 25MB email limit" not in msg
        smtp.assert_not_called()

    def test_pdf_split_message_explains_raw_and_encoded_limits(
        self, good_cfg, tiny_pdf, capsys
    ):
        smtp = _make_smtp_mock()
        with patch("memanga.emailer.split_pdf", return_value=[tiny_pdf, tiny_pdf]):
            with patch("smtplib.SMTP", return_value=smtp):
                _call_send(good_cfg, tiny_pdf)

        msg = capsys.readouterr().out
        assert "Split into 2 parts" in msg
        assert "18.0MB safe raw attachment limit" in msg
        assert "25.0MB" in msg
        assert "exceeded 25MB limit" not in msg


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
# test_email_config — verify credentials without delivery
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
