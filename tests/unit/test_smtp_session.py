"""Shared SMTP session (issue #361): bounded timeouts, error mapping and
cleanup for delivery, the Settings test and `doctor`. Issue #366: the
choice between STARTTLS and implicit TLS.

Most tests replace ``smtplib.SMTP`` / ``smtplib.SMTP_SSL`` with a mock.
The timeout regressions use a real loopback listener that accepts the
connection but never sends the SMTP greeting, with a sub-second timeout.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
import threading
import time
from contextlib import closing
from unittest.mock import MagicMock, patch

import pytest

from memanga.emailer import (DEFAULT_SMTP_TIMEOUT, MAX_SMTP_TIMEOUT,
                             SMTP_TLS_MODES, EmailAuthError,
                             EmailConnectionError, EmailError,
                             EmailProviderError, EmailTimeoutError,
                             send_test_document, send_to_kindle, smtp_login,
                             smtp_session, smtp_timeout, smtp_tls_mode)
from memanga.emailer import check_email_config

SERVER = "smtp.example.invalid"


def _login(**kwargs):
    smtp_login("sender@example.invalid", kwargs.pop("server", SERVER),
               kwargs.pop("port", 587), kwargs.pop("password", "test-app-password"),
               **kwargs)


def _send(pdf, **kwargs):
    return send_to_kindle(
        pdf_path=pdf,
        kindle_email="reader@kindle.example.invalid",
        sender_email="sender@example.invalid",
        smtp_server=kwargs.pop("server", SERVER),
        smtp_port=kwargs.pop("port", 587),
        app_password="test-app-password",
        **kwargs,
    )


def _disconnected_after_timeout():
    """What smtplib raises when a read or send times out."""
    try:
        raise TimeoutError("timed out")
    except TimeoutError:
        try:
            raise smtplib.SMTPServerDisconnected(
                "Connection unexpectedly closed: timed out")
        except smtplib.SMTPServerDisconnected as e:
            return e


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "ch.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake content for tests\n%%EOF\n")
    return path


@pytest.fixture
def smtp_factory():
    """smtplib.SMTP replaced by a mock returning a mock connection."""
    with patch("smtplib.SMTP", return_value=MagicMock()) as factory:
        yield factory


@pytest.fixture
def smtp(smtp_factory):
    return smtp_factory.return_value


@pytest.fixture
def silent_port():
    """A loopback port that accepts connections but never greets."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        yield srv.getsockname()[1]


@pytest.fixture
def closed_port():
    """A loopback port nothing listens on."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as srv:
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
    return port


class TestTimeoutValue:
    @pytest.mark.parametrize("value, expected", [
        (None, DEFAULT_SMTP_TIMEOUT),
        (0, DEFAULT_SMTP_TIMEOUT),
        (-5, DEFAULT_SMTP_TIMEOUT),
        (True, DEFAULT_SMTP_TIMEOUT),
        ("30", DEFAULT_SMTP_TIMEOUT),
        (float("nan"), DEFAULT_SMTP_TIMEOUT),
        (float("inf"), DEFAULT_SMTP_TIMEOUT),
        (15, 15),
        (2.5, 2.5),
        (600, 600),
        (600.5, DEFAULT_SMTP_TIMEOUT),
        (601, DEFAULT_SMTP_TIMEOUT),
        (86400, DEFAULT_SMTP_TIMEOUT),
        (float("-inf"), DEFAULT_SMTP_TIMEOUT),
        # Too large for a float (YAML integers are unbounded).
        (10**400, DEFAULT_SMTP_TIMEOUT),
        (-10**400, DEFAULT_SMTP_TIMEOUT),
    ])
    def test_only_numbers_within_bounds_are_used(self, value, expected):
        assert smtp_timeout(value) == expected

    def test_huge_integer_timeout_uses_default_for_login(self, smtp_factory):
        with pytest.raises(OverflowError):
            float(10**400)  # what a float conversion would hit
        _login(timeout=10**400)
        smtp_factory.assert_called_once_with(SERVER, 587,
                                             timeout=DEFAULT_SMTP_TIMEOUT)

    def test_default_is_finite(self):
        assert 0 < DEFAULT_SMTP_TIMEOUT <= MAX_SMTP_TIMEOUT < float("inf")

    def test_bound_matches_config_schema(self):
        from memanga.config import CONFIG_KEYS
        spec = CONFIG_KEYS["email.smtp_timeout"]
        assert (spec["min"], spec["max"]) == (1, MAX_SMTP_TIMEOUT)

    @pytest.mark.parametrize("stored, expected", [
        (600, 600), (3600, DEFAULT_SMTP_TIMEOUT),
        (10**400, DEFAULT_SMTP_TIMEOUT)])
    def test_hand_edited_config_is_bounded(self, config, smtp_factory,
                                           stored, expected):
        # Loading config.yaml does not validate values, so the runtime
        # bound is what keeps a hand-edited timeout within the limit.
        from memanga.config import Config
        config.config_path.parent.mkdir(parents=True, exist_ok=True)
        config.config_path.write_text(
            f"email:\n  smtp_timeout: {stored}\n", encoding="utf-8")
        loaded = Config(config.config_dir)
        assert loaded.get("email.smtp_timeout") == stored
        _login(timeout=loaded.get("email.smtp_timeout"))
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=expected)

    @pytest.mark.parametrize("timeout, expected", [
        (None, DEFAULT_SMTP_TIMEOUT), (7, 7)])
    def test_login_passes_timeout_to_smtp(self, smtp_factory, timeout, expected):
        _login(timeout=timeout)
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=expected)

    def test_delivery_passes_timeout_to_smtp(self, smtp_factory, smtp, pdf):
        assert _send(pdf, timeout=9) is True
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=9)
        assert smtp.send_message.call_count == 1

    def test_config_check_passes_timeout_to_smtp(self, smtp_factory):
        assert check_email_config("sender@example.invalid", SERVER, 587,
                                 "test-app-password", timeout=3) is True
        smtp_factory.assert_called_once_with(SERVER, 587, timeout=3)


class TestSilentServer:
    """The reported hang: the server never sends its greeting."""

    def test_login_times_out(self, silent_port):
        start = time.monotonic()
        with pytest.raises(EmailTimeoutError) as exc_info:
            _login(server="127.0.0.1", port=silent_port, timeout=0.5)
        assert time.monotonic() - start < 10
        assert "did not respond within 0.5 seconds" in str(exc_info.value)
        assert exc_info.value.__cause__ is not None

    def test_delivery_times_out_as_email_error(self, silent_port, pdf):
        start = time.monotonic()
        with pytest.raises(EmailError) as exc_info:
            _send(pdf, server="127.0.0.1", port=silent_port, timeout=0.5)
        assert time.monotonic() - start < 10
        assert isinstance(exc_info.value, EmailTimeoutError)

    def test_config_check_returns_false(self, silent_port):
        start = time.monotonic()
        assert check_email_config("sender@example.invalid", "127.0.0.1",
                                 silent_port, "test-app-password", timeout=0.5) is False
        assert time.monotonic() - start < 10

    def test_refused_connection_is_a_connection_error(self, closed_port):
        with pytest.raises(EmailConnectionError) as exc_info:
            _login(server="127.0.0.1", port=closed_port, timeout=5)
        assert f"127.0.0.1:{closed_port}" in str(exc_info.value)


class TestSessionFlow:
    def test_starttls_with_verifying_context_before_login(self, smtp):
        _login()
        names = [call[0] for call in smtp.method_calls]
        assert names.index("starttls") < names.index("login") < names.index("quit")
        ctx = smtp.starttls.call_args.kwargs["context"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        # Issue #366: RFC 8314 asks for TLS 1.2 or later.
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
        smtp.login.assert_called_once_with("sender@example.invalid", "test-app-password")

    @pytest.mark.parametrize("quit_error", [
        smtplib.SMTPServerDisconnected("gone"),
        smtplib.SMTPResponseException(421, b"closing"),
        TimeoutError("timed out"),
    ])
    def test_failed_quit_after_send_still_succeeds(self, smtp, pdf, quit_error):
        # The server already accepted the message; failing here would
        # record it undelivered and send it again.
        smtp.quit.side_effect = quit_error
        assert _send(pdf) is True
        smtp.close.assert_called_once()

    def test_transport_failure_closes_without_quit(self, smtp):
        smtp.login.side_effect = _disconnected_after_timeout()
        with pytest.raises(EmailTimeoutError):
            _login()
        smtp.quit.assert_not_called()
        smtp.close.assert_called_once()

    def test_rejection_ends_session_politely(self, smtp):
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with pytest.raises(EmailAuthError):
            _login()
        smtp.quit.assert_called_once()

    def test_other_errors_in_block_propagate_and_close(self, smtp):
        with pytest.raises(ValueError):
            with smtp_session("sender@example.invalid", SERVER, 587, "test-app-password"):
                raise ValueError("not an SMTP problem")
        smtp.quit.assert_not_called()
        smtp.close.assert_called_once()


class TestErrorMapping:
    @pytest.mark.parametrize("step, error, expected, text", [
        ("login", smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted"),
         EmailAuthError, "535 5.7.8 Username and Password not accepted"),
        ("login", _disconnected_after_timeout(),
         EmailTimeoutError, "within 60 seconds"),
        ("starttls", TimeoutError("_ssl.c:1011: The handshake operation timed out"),
         EmailTimeoutError, f"{SERVER}:587"),
        ("starttls", ssl.SSLCertVerificationError(
            1, "certificate verify failed: Hostname mismatch"),
         EmailConnectionError, "certificate verify failed"),
        ("starttls", smtplib.SMTPNotSupportedError(
            "STARTTLS extension not supported by server."),
         EmailProviderError, "STARTTLS extension not supported"),
        ("login", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
         EmailConnectionError, "Connection unexpectedly closed"),
        ("login", ConnectionResetError(104, "Connection reset by peer"),
         EmailConnectionError, "Connection reset by peer"),
        ("send_message", smtplib.SMTPDataError(552, b"5.3.4 Message too big"),
         EmailProviderError, "552 5.3.4 Message too big"),
        ("send_message", _disconnected_after_timeout(),
         EmailTimeoutError, "did not respond"),
    ])
    def test_failures_map_to_structured_errors(self, smtp, pdf, step, error,
                                               expected, text):
        getattr(smtp, step).side_effect = error
        with pytest.raises(expected) as exc_info:
            _send(pdf)
        assert isinstance(exc_info.value, EmailError)
        assert text in str(exc_info.value)
        # The original exception stays attached for diagnostics.
        assert exc_info.value.__cause__ is error

    @pytest.mark.parametrize("error", [
        smtplib.SMTPConnectError(554, b"no SMTP service here"),
        socket.gaierror(-2, "Name or service not known"),
    ])
    def test_connect_failures_are_connection_errors(self, error):
        with patch("smtplib.SMTP", side_effect=error):
            with pytest.raises(EmailConnectionError) as exc_info:
                _login()
        assert f"{SERVER}:587" in str(exc_info.value)
        assert exc_info.value.__cause__ is error

    @pytest.mark.parametrize("step, error, code", [
        ("send_message", smtplib.SMTPDataError(552, b"5.3.4 Message too big"), 552),
        ("send_message", smtplib.SMTPSenderRefused(
            550, b"5.7.1 Sender rejected", "sender@example.invalid"), 550),
        ("starttls", smtplib.SMTPNotSupportedError(
            "STARTTLS extension not supported by server."), None),
    ])
    def test_server_replies_are_provider_errors(self, smtp, pdf, step, error,
                                                code):
        # SMTPException subclasses OSError; a server reply is still not a
        # connection failure.
        assert isinstance(error, OSError)
        getattr(smtp, step).side_effect = error
        with pytest.raises(EmailProviderError) as exc_info:
            _send(pdf)
        assert not isinstance(exc_info.value, (EmailConnectionError,
                                               EmailTimeoutError))
        assert exc_info.value.smtp_code == code
        assert exc_info.value.__cause__ is error
        # The connection still works, so the session ends with QUIT.
        smtp.quit.assert_called_once()

    @pytest.mark.parametrize("error, expected", [
        (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
         EmailConnectionError),
        (ConnectionResetError(104, "Connection reset by peer"),
         EmailConnectionError),
        (_disconnected_after_timeout(), EmailTimeoutError),
    ])
    def test_dropped_connections_are_not_provider_errors(self, smtp, pdf,
                                                         error, expected):
        smtp.send_message.side_effect = error
        with pytest.raises(expected) as exc_info:
            _send(pdf)
        assert not isinstance(exc_info.value, EmailProviderError)
        smtp.quit.assert_not_called()
        smtp.close.assert_called_once()

    def test_refused_kindle_recipient_keeps_code_and_reply(self, smtp, pdf):
        # SMTPRecipientsRefused has no smtp_code; the code is per recipient.
        kindle = "reader@kindle.example.invalid"
        error = smtplib.SMTPRecipientsRefused(
            {kindle: (550, b"5.1.1 The email account does not exist")})
        smtp.send_message.side_effect = error
        with pytest.raises(EmailProviderError) as exc_info:
            _send(pdf)
        assert exc_info.value.smtp_code == 550
        assert "550 5.1.1 The email account does not exist" in str(exc_info.value)
        assert exc_info.value.recipients == {
            kindle: (550, "5.1.1 The email account does not exist")}
        assert exc_info.value.__cause__ is error
        smtp.quit.assert_called_once()

    def test_auth_error_keeps_existing_wording(self, smtp):
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with pytest.raises(EmailAuthError) as exc_info:
            _login()
        assert str(exc_info.value).startswith(
            "SMTP authentication failed. Check email/password.")

    def test_password_is_masked_in_errors(self, smtp):
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"credentials app-pw-1234 rejected")
        with pytest.raises(EmailAuthError) as exc_info:
            _login(password="app-pw-1234")
        assert "app-pw-1234" not in str(exc_info.value)

    def test_password_is_registered_as_secret(self, smtp, monkeypatch):
        from memanga import emailer
        registered = []
        monkeypatch.setattr(emailer, "register_secret", registered.append)
        _login(password="app-pw-5678")
        assert registered == ["app-pw-5678"]


@pytest.fixture
def ssl_factory():
    """smtplib.SMTP_SSL replaced by a mock returning a mock connection."""
    with patch("smtplib.SMTP_SSL", return_value=MagicMock()) as factory:
        yield factory


@pytest.fixture
def greeting_port():
    """A loopback port that greets in plain SMTP, as a STARTTLS port
    does, then waits."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    srv.settimeout(10)
    done = threading.Event()
    conns = []

    def serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        conns.append(conn)
        try:
            conn.sendall(b"220 smtp.example.invalid ESMTP ready\r\n")
        except OSError:
            pass
        done.wait(10)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield srv.getsockname()[1]
    finally:
        done.set()
        thread.join(5)
        for conn in conns:
            conn.close()
        srv.close()


class TestTlsMode:
    """Issue #366: implicit TLS (port 465) or STARTTLS (port 587)."""

    @pytest.mark.parametrize("value, port, expected", [
        (None, 465, "implicit"),
        ("auto", 465, "implicit"),
        ("auto", "465", "implicit"),
        ("auto", 587, "starttls"),
        ("auto", 25, "starttls"),
        ("auto", 2525, "starttls"),
        (None, None, "starttls"),
        ("starttls", 465, "starttls"),
        ("implicit", 587, "implicit"),
        (" Implicit ", 2465, "implicit"),
        ("STARTTLS", 587, "starttls"),
    ])
    def test_mode_for_setting_and_port(self, value, port, expected):
        assert smtp_tls_mode(value, port) == expected

    def test_modes_match_config_schema(self):
        from memanga.config import CONFIG_KEYS
        assert CONFIG_KEYS["email.smtp_tls"]["choices"] == SMTP_TLS_MODES

    @pytest.mark.parametrize("platform_floor, expected", [
        # Unset by the platform: raised to the RFC 8314 floor.
        (ssl.TLSVersion.MINIMUM_SUPPORTED, ssl.TLSVersion.TLSv1_2),
        # A stricter platform policy is never lowered.
        (ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3),
    ])
    @pytest.mark.parametrize("tls, port", [("starttls", 587),
                                           ("implicit", 465)])
    def test_both_modes_get_the_tls_floor(self, smtp_factory, ssl_factory,
                                          smtp, monkeypatch, platform_floor,
                                          expected, tls, port):
        from memanga import emailer
        made = ssl.create_default_context

        def platform_context(*a, **k):
            ctx = made(*a, **k)
            ctx.minimum_version = platform_floor
            return ctx
        monkeypatch.setattr(emailer.ssl, "create_default_context",
                            platform_context)
        _login(port=port, smtp_tls=tls)
        if tls == "implicit":
            ctx = ssl_factory.call_args.kwargs["context"]
        else:
            ctx = smtp.starttls.call_args.kwargs["context"]
        assert ctx.minimum_version == expected
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    @pytest.mark.parametrize("value", ["ssl", "tls", "none", "", True, 465])
    def test_invalid_mode_is_refused_before_connecting(
            self, smtp_factory, ssl_factory, value):
        # Never guess: a typo must not change how the password travels.
        with pytest.raises(EmailError, match="email.smtp_tls") as exc_info:
            _login(port=465, smtp_tls=value)
        assert "auto, starttls, implicit" in str(exc_info.value)
        smtp_factory.assert_not_called()
        ssl_factory.assert_not_called()

    def test_port_465_uses_implicit_tls_by_default(self, smtp_factory,
                                                   ssl_factory):
        _login(port=465)
        smtp_factory.assert_not_called()
        args, kwargs = ssl_factory.call_args
        assert args == (SERVER, 465)
        assert kwargs["timeout"] == DEFAULT_SMTP_TIMEOUT
        ctx = kwargs["context"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
        conn = ssl_factory.return_value
        names = [call[0] for call in conn.method_calls]
        assert "starttls" not in names
        assert names.index("login") < names.index("quit")
        conn.login.assert_called_once_with("sender@example.invalid",
                                           "test-app-password")

    @pytest.mark.parametrize("port", [587, 25, 2525])
    def test_other_ports_keep_starttls(self, smtp_factory, ssl_factory, smtp,
                                       port):
        _login(port=port)
        ssl_factory.assert_not_called()
        smtp_factory.assert_called_once_with(SERVER, port,
                                             timeout=DEFAULT_SMTP_TIMEOUT)
        smtp.starttls.assert_called_once()

    def test_implicit_setting_on_another_port(self, smtp_factory, ssl_factory):
        _login(port=2465, smtp_tls="implicit", timeout=7)
        smtp_factory.assert_not_called()
        assert ssl_factory.call_args.args == (SERVER, 2465)
        assert ssl_factory.call_args.kwargs["timeout"] == 7

    def test_starttls_setting_on_port_465(self, smtp_factory, ssl_factory,
                                          smtp):
        _login(port=465, smtp_tls="starttls")
        ssl_factory.assert_not_called()
        smtp_factory.assert_called_once_with(SERVER, 465,
                                             timeout=DEFAULT_SMTP_TIMEOUT)
        smtp.starttls.assert_called_once()

    def test_missing_starttls_never_logs_in_unencrypted(self, smtp):
        smtp.starttls.side_effect = smtplib.SMTPNotSupportedError(
            "STARTTLS extension not supported by server.")
        with pytest.raises(EmailProviderError):
            _login(port=587)
        smtp.login.assert_not_called()

    def test_delivery_uses_implicit_tls(self, smtp_factory, ssl_factory, pdf):
        assert _send(pdf, port=465) is True
        smtp_factory.assert_not_called()
        ssl_factory.return_value.send_message.assert_called_once()

    def test_split_delivery_uses_the_mode(self, smtp_factory, ssl_factory,
                                          pdf, tmp_path, monkeypatch):
        from memanga import emailer
        parts = []
        for number in (1, 2):
            part = tmp_path / f"ch_part{number}.pdf"
            part.write_bytes(pdf.read_bytes())
            parts.append(part)
        monkeypatch.setattr(emailer, "split_pdf",
                            lambda path, max_size: parts)
        assert _send(pdf, port=2465, smtp_tls="implicit") is True
        smtp_factory.assert_not_called()
        ssl_factory.assert_called_once()  # one session for both parts
        assert ssl_factory.return_value.send_message.call_count == 2

    def test_login_check_and_test_document_pass_the_mode(self, smtp_factory,
                                                         ssl_factory):
        assert check_email_config("sender@example.invalid", SERVER, 2465,
                                  "test-app-password",
                                  smtp_tls="implicit") is True
        send_test_document("reader@kindle.example.invalid",
                           "sender@example.invalid", SERVER, 2465,
                           "test-app-password", smtp_tls="implicit")
        smtp_factory.assert_not_called()
        assert ssl_factory.call_count == 2
        ssl_factory.return_value.send_message.assert_called_once()

    @pytest.mark.parametrize("error, expected, text", [
        (ssl.SSLCertVerificationError(
            1, "certificate verify failed: Hostname mismatch"),
         EmailConnectionError, "certificate verify failed"),
        (ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number"),
         EmailConnectionError, "wrong version number"),
        (TimeoutError("_ssl.c:1011: The handshake operation timed out"),
         EmailTimeoutError, f"{SERVER}:465"),
        (ConnectionRefusedError(111, "Connection refused"),
         EmailConnectionError, f"{SERVER}:465"),
    ])
    def test_implicit_tls_failures_map_to_structured_errors(
            self, error, expected, text):
        with patch("smtplib.SMTP_SSL", side_effect=error):
            with pytest.raises(expected) as exc_info:
                _login(port=465)
        assert text in str(exc_info.value)
        assert exc_info.value.__cause__ is error
        assert "normally uses" not in str(exc_info.value)

    def test_auth_failure_over_implicit_tls_ends_politely(self, ssl_factory):
        conn = ssl_factory.return_value
        conn.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with pytest.raises(EmailAuthError):
            _login(port=465)
        conn.quit.assert_called_once()

    def test_starttls_on_port_465_says_how_to_fix_it(self):
        # The reported failure: a server on 465 waits for TLS, smtplib
        # waits for a greeting, and the user only saw a timeout.
        with patch("smtplib.SMTP", side_effect=TimeoutError("timed out")):
            with pytest.raises(EmailTimeoutError) as exc_info:
                _login(port=465, smtp_tls="starttls")
        assert str(exc_info.value) == (
            f"SMTP server {SERVER}:465 did not respond within 60 seconds. "
            "Port 465 normally uses implicit TLS, but email.smtp_tls is "
            "starttls; set it to auto or implicit.")

    def test_implicit_tls_on_port_587_says_how_to_fix_it(self):
        error = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")
        with patch("smtplib.SMTP_SSL", side_effect=error):
            with pytest.raises(EmailConnectionError) as exc_info:
                _login(port=587, smtp_tls="implicit")
        message = str(exc_info.value)
        assert "wrong version number" in message
        assert message.endswith(
            "Port 587 normally uses STARTTLS, but email.smtp_tls is "
            "implicit; set it to auto or starttls.")

    def test_matching_mode_keeps_the_plain_message(self):
        with patch("smtplib.SMTP", side_effect=TimeoutError("timed out")):
            with pytest.raises(EmailTimeoutError) as exc_info:
                _login(port=587)
        assert str(exc_info.value) == (
            f"SMTP server {SERVER}:587 did not respond within 60 seconds")

    def test_implicit_tls_to_silent_server_times_out(self, silent_port):
        start = time.monotonic()
        with pytest.raises(EmailTimeoutError):
            _login(server="127.0.0.1", port=silent_port, timeout=0.5,
                   smtp_tls="implicit")
        assert time.monotonic() - start < 10

    def test_implicit_tls_to_plain_smtp_server_fails_fast(self, greeting_port):
        # A STARTTLS port answers the TLS handshake with a plain greeting.
        start = time.monotonic()
        with pytest.raises(EmailConnectionError) as exc_info:
            _login(server="127.0.0.1", port=greeting_port, timeout=5,
                   smtp_tls="implicit")
        assert time.monotonic() - start < 10
        assert isinstance(exc_info.value.__cause__, ssl.SSLError)
