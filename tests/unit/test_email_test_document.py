"""Real email delivery test (issue #365): a tiny PDF sent the way
delivery sends chapters.

``smtplib.SMTP`` is replaced by a mock, so nothing leaves the machine.
"""

from __future__ import annotations

import io
import smtplib
from datetime import datetime
from unittest.mock import MagicMock, patch

import pikepdf
import pytest

from memanga.emailer import (TEST_DELIVERY_NOTE, TEST_DOCUMENT_NAME,
                             TEST_DOCUMENT_SUBJECT, EmailAuthError, EmailError,
                             EmailProviderError, EmailTimeoutError,
                             build_test_pdf, send_test_document)

KINDLE = "reader@kindle.example.invalid"
SENDER = "sender@example.invalid"
SERVER = "smtp.example.invalid"
PASSWORD = "test-app-pw-9876"
NOW = datetime(2026, 1, 2, 3, 4)


def _send(**overrides):
    kwargs = dict(kindle_email=KINDLE, sender_email=SENDER,
                  smtp_server=SERVER, smtp_port=587, app_password=PASSWORD,
                  now=NOW)
    kwargs.update(overrides)
    return send_test_document(**kwargs)


@pytest.fixture
def smtp_factory():
    with patch("smtplib.SMTP", return_value=MagicMock()) as factory:
        yield factory


@pytest.fixture
def smtp(smtp_factory):
    return smtp_factory.return_value


class TestTestPdf:
    def test_is_a_valid_one_page_pdf(self):
        data = build_test_pdf("2026-01-02 03:04")
        assert data.startswith(b"%PDF-")
        # Small enough for any mail server or Kindle limit.
        assert len(data) < 10_000
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert len(pdf.pages) == 1
            assert str(pdf.docinfo["/Title"]) == (
                f"{TEST_DOCUMENT_SUBJECT} 2026-01-02 03:04")
            page = pdf.pages[0]
            assert page.Resources.Font.F1.BaseFont == pikepdf.Name.Helvetica
            text = page.Contents.read_bytes()
            assert b"(Sent 2026-01-02 03:04) Tj" in text

    def test_text_is_escaped(self):
        data = build_test_pdf("a(b)c\\d")
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = pdf.pages[0].Contents.read_bytes()
        assert b"(Sent a\\(b\\)c\\\\d) Tj" in text


class TestSendTestDocument:
    def test_sends_one_pdf_to_the_kindle_address(self, smtp_factory, smtp):
        subject = _send(timeout=7)

        assert subject == f"{TEST_DOCUMENT_SUBJECT} 2026-01-02 03:04"
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=7)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(SENDER, PASSWORD)
        smtp.send_message.assert_called_once()
        msg = smtp.send_message.call_args.args[0]
        assert msg["To"] == KINDLE
        assert msg["From"] == SENDER
        assert msg["Subject"] == subject
        (attachment,) = msg.get_payload()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_filename() == TEST_DOCUMENT_NAME
        assert attachment.get_content_disposition() == "attachment"
        body = attachment.get_payload(decode=True)
        with pikepdf.open(io.BytesIO(body)) as pdf:
            assert len(pdf.pages) == 1
        smtp.quit.assert_called_once()

    def test_settings_are_stripped(self, smtp_factory, smtp):
        _send(kindle_email=f"  {KINDLE} ", sender_email=f" {SENDER}",
              smtp_server=f" {SERVER} ")
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=60)
        msg = smtp.send_message.call_args.args[0]
        assert msg["To"] == KINDLE
        assert msg["From"] == SENDER

    @pytest.mark.parametrize("field, label", [
        ("kindle_email", "Kindle email"),
        ("sender_email", "sender email"),
        ("smtp_server", "SMTP server"),
        ("app_password", "app password"),
    ])
    def test_missing_setting_fails_before_connecting(
            self, smtp_factory, field, label):
        with pytest.raises(EmailError, match=f"Missing {label}"):
            _send(**{field: "  " if field != "app_password" else ""})
        smtp_factory.assert_not_called()

    def test_refused_recipient_is_reported_without_address_or_password(
            self, smtp):
        smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused(
            {KINDLE: (550, f"5.1.1 unknown user; auth {PASSWORD}".encode())})
        with pytest.raises(EmailProviderError) as exc_info:
            _send()
        message = str(exc_info.value)
        assert "550 5.1.1 unknown user" in message
        assert KINDLE not in message
        assert PASSWORD not in message

    def test_auth_failure_sends_nothing(self, smtp):
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with pytest.raises(EmailAuthError):
            _send()
        smtp.send_message.assert_not_called()

    def test_timeout_is_reported(self, smtp):
        try:
            raise TimeoutError("timed out")
        except TimeoutError:
            try:
                raise smtplib.SMTPServerDisconnected("closed")
            except smtplib.SMTPServerDisconnected as e:
                smtp.send_message.side_effect = e
        with pytest.raises(EmailTimeoutError, match="within 5 seconds"):
            _send(timeout=5)

    def test_password_is_registered_as_secret(self, smtp, monkeypatch):
        from memanga import emailer
        registered = []
        monkeypatch.setattr(emailer, "register_secret", registered.append)
        _send()
        assert PASSWORD in registered

    def test_note_does_not_claim_kindle_delivery(self):
        assert "does not prove" in TEST_DELIVERY_NOTE
        assert "Approved Personal Document E-mail List" in TEST_DELIVERY_NOTE
        assert TEST_DOCUMENT_SUBJECT in TEST_DELIVERY_NOTE
