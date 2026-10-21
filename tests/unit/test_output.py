"""Output and logging setup (issue #226): levels, redaction, plain output,
log files and stream handling in memanga.output."""

from __future__ import annotations

import io
import logging
import logging.handlers
import re
import sys

import pytest

from memanga import output

TIMESTAMPED = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [A-Z]+ \S+: ")


class _Stream(io.StringIO):
    """StringIO with a settable isatty() and encoding."""

    def __init__(self, tty=False, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._encoding = encoding
        self.reconfigured = None

    def isatty(self):
        return self._tty

    @property
    def encoding(self):
        return self._encoding

    def reconfigure(self, **kwargs):
        self.reconfigured = kwargs


# ─────────────────────────────────────────────────────────────────────
# Levels
# ─────────────────────────────────────────────────────────────────────


class TestLevels:
    @pytest.mark.parametrize("text, level", [
        ("debug", logging.DEBUG), ("INFO", logging.INFO),
        ("warn", logging.WARNING), (" Warning ", logging.WARNING),
        ("error", logging.ERROR), ("CRITICAL", logging.CRITICAL),
        ("10", 10),
    ])
    def test_parse_accepts_names_and_numbers(self, text, level):
        assert output.parse_log_level(text) == level

    @pytest.mark.parametrize("text", [None, "", "  ", "loud", "-1"])
    def test_parse_rejects_others(self, text):
        assert output.parse_log_level(text) is None

    def test_default_without_flags_or_env(self):
        assert output.resolve_log_level(environ={}) == logging.WARNING
        assert output.resolve_log_level(default=logging.INFO,
                                        environ={}) == logging.INFO

    def test_env_sets_the_level(self):
        env = {output.LOG_LEVEL_ENV: "info"}
        assert output.resolve_log_level(environ=env) == logging.INFO

    def test_flags_override_env(self):
        env = {output.LOG_LEVEL_ENV: "error"}
        assert output.resolve_log_level(verbose=1, environ=env) == logging.INFO
        assert output.resolve_log_level(verbose=2, environ=env) == logging.DEBUG
        env = {output.LOG_LEVEL_ENV: "debug"}
        assert output.resolve_log_level(quiet=True, environ=env) == logging.ERROR

    def test_verbose_wins_over_quiet(self):
        assert output.resolve_log_level(verbose=1, quiet=True,
                                        environ={}) == logging.INFO

    def test_invalid_env_is_ignored_and_reported(self):
        env = {output.LOG_LEVEL_ENV: "loud"}
        assert output.resolve_log_level(environ=env) == logging.WARNING
        assert output.invalid_log_level_env(env) == "loud"
        assert output.invalid_log_level_env({output.LOG_LEVEL_ENV: "info"}) is None
        assert output.invalid_log_level_env({}) is None


# ─────────────────────────────────────────────────────────────────────
# Redaction
# ─────────────────────────────────────────────────────────────────────


class TestRedaction:
    @pytest.fixture(autouse=True)
    def _no_registered_secrets(self, monkeypatch):
        # Other tests (the emailer) register their passwords too.
        monkeypatch.setattr(output, "_secrets", set())

    def test_registered_secret_is_masked(self):
        output.register_secret("abcd efgh ijkl mnop")
        assert output.redact("login with abcd efgh ijkl mnop failed") == \
            "login with *** failed"

    def test_short_values_are_not_registered(self):
        output.register_secret("abcde")
        assert output.redact("abcdef") == "abcdef"

    @pytest.mark.parametrize("text, expected", [
        ("password=hunter22 next", "password=*** next"),
        ("app_password: 'hunter 22'", "app_password: ***"),
        ('{"token": "xyz123"}', '{"token": ***}'),
        ("GET /api?access_token=abc&x=1", "GET /api?access_token=***&x=1"),
        ("api-key=K-1", "api-key=***"),
        ("Authorization: Bearer abc.def", "Authorization: *** ***"),
        ("bearer abc.def", "bearer ***"),
        ("https://me:s3cret@host/x", "https://me:***@host/x"),
    ])
    def test_common_shapes_are_masked(self, text, expected):
        assert output.redact(text) == expected

    def test_ordinary_text_is_untouched(self):
        text = "Starting the browser used to mint API tokens..."
        assert output.redact(text) == text

    def test_formatter_redacts_tracebacks(self):
        output.register_secret("tb-secret-value")
        try:
            raise RuntimeError("auth failed for tb-secret-value")
        except RuntimeError:
            record = logging.LogRecord("memanga.x", logging.ERROR, __file__, 1,
                                       "failed", None, sys.exc_info())
        line = output.RedactingFormatter("%(message)s").format(record)
        assert "tb-secret-value" not in line
        assert "auth failed for ***" in line


# ─────────────────────────────────────────────────────────────────────
# configure_logging
# ─────────────────────────────────────────────────────────────────────


class TestConfigureLogging:
    def test_records_go_to_stderr_never_stdout(self, capsys):
        output.configure_logging(logging.WARNING, timestamps=False)
        logging.getLogger("memanga.scrapers.example").warning(
            "Search request failed: %s", "boom")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "WARNING memanga.scrapers.example: Search request failed: boom\n")

    def test_level_filters_records(self, capsys):
        output.configure_logging(logging.WARNING, timestamps=False)
        log = logging.getLogger("memanga.x")
        log.info("progress")
        log.debug("detail")
        assert capsys.readouterr().err == ""
        output.configure_logging(logging.DEBUG, timestamps=False)
        log.debug("detail")
        assert "DEBUG memanga.x: detail" in capsys.readouterr().err

    def test_redirected_stderr_lines_have_time_and_level(self, capsys):
        # capsys' stderr is not a terminal: timestamps default on.
        output.configure_logging(logging.INFO)
        logging.getLogger("memanga.x").info("one")
        logging.getLogger("memanga.x").error("two")
        lines = capsys.readouterr().err.splitlines()
        assert len(lines) == 2
        assert all(TIMESTAMPED.match(line) for line in lines)
        assert " INFO memanga.x: one" in lines[0]
        assert " ERROR memanga.x: two" in lines[1]

    def test_third_party_debug_is_dropped(self, capsys):
        output.configure_logging(logging.DEBUG, timestamps=False)
        logging.getLogger("urllib3.connectionpool").debug("noise")
        logging.getLogger("urllib3.connectionpool").warning("real problem")
        err = capsys.readouterr().err
        assert "noise" not in err
        assert "real problem" in err

    def test_reconfigure_replaces_handlers(self, capsys):
        output.configure_logging(logging.WARNING, timestamps=False)
        output.configure_logging(logging.WARNING, timestamps=False)
        logging.getLogger("memanga.x").warning("once")
        assert capsys.readouterr().err.count("once") == 1

    def test_log_file_lines_have_time_and_level(self, tmp_path, capsys):
        path = tmp_path / "logs" / output.LOG_FILE_NAME
        output.configure_logging(logging.ERROR, log_file=path)
        log = logging.getLogger("memanga.x")
        log.info("progress line")
        log.debug("debug line")
        log.error("password=hunter22")
        for handler in logging.getLogger().handlers:
            handler.flush()
        lines = path.read_text(encoding="utf-8").splitlines()
        # The file keeps INFO even when the console only shows errors.
        assert len(lines) == 2
        assert all(TIMESTAMPED.match(line) for line in lines)
        assert lines[0].endswith("INFO memanga.x: progress line")
        assert lines[1].endswith("ERROR memanga.x: password=***")
        assert "progress line" not in capsys.readouterr().err

    def test_log_file_exception_lines_all_have_time_and_level(self, tmp_path):
        path = tmp_path / output.LOG_FILE_NAME
        output.configure_logging(logging.WARNING, log_file=path)
        try:
            raise ValueError("token=abc123 broke\nsecond line")
        except ValueError:
            logging.getLogger("memanga.x").exception("download failed")
        for handler in logging.getLogger().handlers:
            handler.flush()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 3
        assert all(TIMESTAMPED.match(line) for line in lines), lines
        assert all(" ERROR memanga.x: " in line for line in lines)
        assert any("Traceback (most recent call last):" in line for line in lines)
        assert any(line.endswith("ERROR memanga.x: second line") for line in lines)
        assert "abc123" not in "\n".join(lines)

    def test_multiline_message_on_stderr_keeps_prefix(self, capsys):
        output.configure_logging(logging.WARNING, timestamps=False)
        logging.getLogger("memanga.x").warning("one\ntwo")
        assert capsys.readouterr().err.splitlines() == [
            "WARNING memanga.x: one", "WARNING memanga.x: two"]

    def test_records_with_markup_use_console_renderer(self, tmp_path, capsys):
        path = tmp_path / output.LOG_FILE_NAME
        output.configure_logging(logging.WARNING, log_file=path)
        rendered = []
        output.set_console_renderer(rendered.append)
        log = logging.getLogger("memanga.cli")
        log.warning("plain %s", "text",
                    extra={output.RICH_MARKUP: "[yellow]rich password=abcdef here[/yellow]"})
        log.info("hidden", extra={output.RICH_MARKUP: "[dim]hidden[/dim]"})
        log.warning("no markup")
        for handler in logging.getLogger().handlers:
            handler.flush()
        # The terminal gets the Rich rendering, at the console level only.
        assert rendered == ["[yellow]rich password=*** here[/yellow]"]
        err = capsys.readouterr().err
        assert "plain text" not in err
        assert "WARNING memanga.cli: no markup" in err
        # The file always gets the plain record.
        text = path.read_text(encoding="utf-8")
        assert "WARNING memanga.cli: plain text" in text
        assert "INFO memanga.cli: hidden" in text

    def test_reset_turns_console_renderer_off(self, capsys):
        output.set_console_renderer(lambda markup: None)
        output.reset_logging()
        output.configure_logging(logging.WARNING, timestamps=False)
        logging.getLogger("memanga.x").warning(
            "shown", extra={output.RICH_MARKUP: "[b]x[/b]"})
        assert "WARNING memanga.x: shown" in capsys.readouterr().err

    def test_logging_configured(self):
        assert not output.logging_configured()
        output.configure_logging(logging.WARNING)
        assert output.logging_configured()
        output.reset_logging()
        assert not output.logging_configured()

    def test_log_file_rotates(self, tmp_path):
        path = tmp_path / output.LOG_FILE_NAME
        output.configure_logging(logging.WARNING, log_file=path)
        handlers = [h for h in logging.getLogger().handlers
                    if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(handlers) == 1
        assert handlers[0].maxBytes == output.LOG_FILE_MAX_BYTES
        assert handlers[0].backupCount == output.LOG_FILE_BACKUPS

    def test_unopenable_log_file_keeps_previous_setup(self, tmp_path, capsys):
        output.configure_logging(logging.WARNING, timestamps=False)
        blocker = tmp_path / "file"
        blocker.write_text("x")
        with pytest.raises(OSError):
            output.configure_logging(logging.WARNING,
                                     log_file=blocker / "diagnostics.log")
        logging.getLogger("memanga.x").warning("still logged")
        assert "still logged" in capsys.readouterr().err

    def test_reset_restores_root(self):
        root = logging.getLogger()
        before = root.level
        output.configure_logging(logging.DEBUG)
        assert root.level == logging.DEBUG
        output.reset_logging()
        assert root.level == before
        assert not [h for h in root.handlers
                    if getattr(h, "_memanga_handler", False)]


# ─────────────────────────────────────────────────────────────────────
# Rotating the GUI runtime log
# ─────────────────────────────────────────────────────────────────────


def test_rotate_log_file_keeps_backups(tmp_path):
    path = tmp_path / "runtime.log"
    for name, text in (("runtime.log", "s4"), ("runtime.log.1", "s3"),
                       ("runtime.log.2", "s2"), ("runtime.log.3", "s1")):
        (tmp_path / name).write_text(text)

    output.rotate_log_file(path, backups=3)

    assert not path.exists()
    assert (tmp_path / "runtime.log.1").read_text() == "s4"
    assert (tmp_path / "runtime.log.2").read_text() == "s3"
    assert (tmp_path / "runtime.log.3").read_text() == "s2"
    assert not (tmp_path / "runtime.log.4").exists()


def test_rotate_log_file_without_existing_file(tmp_path):
    assert output.rotate_log_file(tmp_path / "runtime.log") is True
    assert list(tmp_path.iterdir()) == []


def test_rotate_log_file_reports_a_file_it_could_not_move(tmp_path,
                                                          monkeypatch):
    # Windows refuses to rename a file another process has open.
    path = tmp_path / "runtime.log"
    path.write_text("running instance")

    def _refuse(src, dst):
        raise PermissionError(13, "in use")
    monkeypatch.setattr(output.os, "replace", _refuse)

    assert output.rotate_log_file(path, backups=3) is False
    assert path.read_text() == "running instance"


# ─────────────────────────────────────────────────────────────────────
# Plain output
# ─────────────────────────────────────────────────────────────────────


class TestPlainOutput:
    @pytest.mark.parametrize("text, expected", [
        ("     ✅ Saved: x.pdf", "     Saved: x.pdf"),
        ("⚠️  3 chapter(s) failed", "3 chapter(s) failed"),
        ("  └─ No new chapters", "  No new chapters"),
        ("📊 Summary: 1/1", "Summary: 1/1"),
        ("⬇️  Downloading", "Downloading"),
        ("a — b → c · d", "a — b → c · d"),
        # Symbols in scraped titles are user data, not decoration.
        ("Love♥Live ★ ☆ ♪ ⭐ 🔥", "Love♥Live ★ ☆ ♪ ⭐ 🔥"),
    ])
    def test_strip_decoration(self, text, expected):
        assert output.strip_decoration(text) == expected

    def test_every_cli_icon_is_stripped(self):
        # A new icon in a CLI message must be added to APP_DECORATION,
        # or plain output would start carrying it.
        from pathlib import Path

        src = (Path(output.__file__).parent / "cli.py").read_text(encoding="utf-8")
        icons = {ch for ch in src
                 if ord(ch) >= 0x2300 and ch not in "\ufe0e\ufe0f\u200d"}
        assert icons
        for icon in sorted(icons):
            assert output.strip_decoration(icon) == "", repr(icon)

    def test_stream_is_plain(self):
        assert output.stream_is_plain(_Stream(tty=False), environ={})
        assert not output.stream_is_plain(_Stream(tty=True), environ={})
        assert output.stream_is_plain(_Stream(tty=True), plain=True, environ={})
        assert output.stream_is_plain(_Stream(tty=True),
                                      environ={"TERM": "dumb"})

    def test_plain_console_has_no_colour_emoji_or_wrapping(self, capsys):
        console = output.make_console(plain=True)
        assert output.is_plain_console(console)
        long = "word " * 60
        console.print(f"[bold red]✅ Saved[/bold red] {long}")
        out = capsys.readouterr().out
        assert "\x1b[" not in out
        assert "✅" not in out
        assert out.count("\n") == 1
        assert out.startswith("Saved word word")

    def test_plain_console_follows_replaced_stream(self, monkeypatch):
        console = output.make_console(stderr=True, plain=True)
        replaced = io.StringIO()
        monkeypatch.setattr(sys, "stderr", replaced)
        console.print("⚠️  late")
        assert replaced.getvalue() == "late\n"

    def test_rich_console_kept_when_not_plain(self):
        console = output.make_console(plain=False)
        assert not output.is_plain_console(console)

    def test_no_color_turns_colour_off(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert output.make_console(plain=False).no_color is True


# ─────────────────────────────────────────────────────────────────────
# Windows redirected-output safety
# ─────────────────────────────────────────────────────────────────────


class TestUtf8Streams:
    def test_redirected_non_utf8_stream_is_reconfigured(self, monkeypatch):
        out, err = _Stream(encoding="cp1252"), _Stream(encoding="ascii")
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        output.ensure_utf8_streams()
        assert out.reconfigured == {"encoding": "utf-8", "errors": "replace"}
        assert err.reconfigured == {"encoding": "utf-8", "errors": "replace"}

    def test_terminals_and_utf8_streams_are_left_alone(self, monkeypatch):
        tty, utf8 = _Stream(tty=True, encoding="cp1252"), _Stream(encoding="UTF8")
        monkeypatch.setattr(sys, "stdout", tty)
        monkeypatch.setattr(sys, "stderr", utf8)
        output.ensure_utf8_streams()
        assert tty.reconfigured is None
        assert utf8.reconfigured is None
