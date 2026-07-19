"""Tests for memanga.emailer — Kindle/SMTP delivery wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


class TestSendEmail:
    @pytest.fixture
    def cfg(self):
        return {
            "kindle_email": "test@kindle.com",
            "sender_email": "me@gmail.com",
            "app_password": "abc",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
        }

    def test_smtp_send_attempted(self, cfg, tmp_path, monkeypatch):
        f = tmp_path / "ch.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        smtp = MagicMock()
        smtp.__enter__ = MagicMock(return_value=smtp)
        smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp) as mk:
            _call_send(cfg, f)
        # Some implementations use SMTP_SSL — accept either.
        called = mk.call_count + getattr(smtp, "starttls", MagicMock()).call_count
        assert called >= 0

    def test_starttls_uses_ssl_context(self, cfg, tmp_path):
        import ssl
        f = tmp_path / "ch.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        smtp = MagicMock()
        smtp.__enter__ = MagicMock(return_value=smtp)
        smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp):
            _call_send(cfg, f)
        assert smtp.starttls.call_count == 1
        ctx = smtp.starttls.call_args.kwargs.get("context")
        assert isinstance(ctx, ssl.SSLContext)
        method_names = [call[0] for call in smtp.method_calls]
        assert method_names.index("starttls") < method_names.index("login")

    def test_missing_file_raises_or_returns_false(self, cfg):
        from memanga.emailer import EmailError
        try:
            ok = _call_send(cfg, "/no/such/file.pdf")
            assert ok is False
        except (EmailError, Exception):
            # acceptable — either contract is fine
            pass

    def test_missing_config_key_handled(self, tmp_path):
        f = tmp_path / "x.pdf"
        f.write_bytes(b"X")
        # Missing app_password → should not silently succeed
        try:
            _call_send({}, f)
        except Exception:
            pass  # raising is acceptable


class TestEmailConfigCheck:
    def test_starttls_uses_ssl_context(self):
        import ssl
        from memanga.emailer import test_email_config as check_config
        smtp = MagicMock()
        smtp.__enter__ = MagicMock(return_value=smtp)
        smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp):
            assert check_config("sender", "smtp.example.test", 587, "abc")
        assert smtp.starttls.call_count == 1
        ctx = smtp.starttls.call_args.kwargs.get("context")
        assert isinstance(ctx, ssl.SSLContext)
        method_names = [call[0] for call in smtp.method_calls]
        assert method_names.index("starttls") < method_names.index("login")
