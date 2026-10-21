"""
Output and logging setup shared by the CLI and the desktop app (issue #226).

Library code only calls ``logging.getLogger(__name__)``; the entry points
call :func:`configure_logging` once. Diagnostics go to stderr (and an
optional rotating file), command results stay on stdout.

Levels: DEBUG for scraper internals and per-page retries, INFO for normal
progress, WARNING for degraded or fallback behaviour, ERROR for failures.

This module only uses the standard library (plus Rich, imported lazily in
:func:`make_console`) so the frozen GUI entry can import it before its
streams are repaired.
"""

import codecs
import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path
from typing import Mapping, Optional

LOG_LEVEL_ENV = "MEMANGA_LOG_LEVEL"

# Opt-in rotating diagnostics file (`memanga --log-file`), kept in the
# config directory. Not `memanga.log`: that name is the cron redirect.
LOG_FILE_NAME = "diagnostics.log"
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUPS = 3

LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"
TIMESTAMPED_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_LEVEL_NAMES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def parse_log_level(text) -> Optional[int]:
    """Level for a name (``debug``, ``WARNING``...) or number, else None."""
    if text is None:
        return None
    value = str(text).strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return _LEVEL_NAMES.get(value.upper())


def invalid_log_level_env(environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The ``MEMANGA_LOG_LEVEL`` value when it is set but not a level."""
    value = (os.environ if environ is None else environ).get(LOG_LEVEL_ENV, "")
    if value.strip() and parse_log_level(value) is None:
        return value
    return None


def resolve_log_level(verbose: int = 0, quiet: bool = False,
                      default: int = logging.WARNING,
                      environ: Optional[Mapping[str, str]] = None) -> int:
    """Pick the console log level.

    ``-v``/``-vv`` win over ``-q``, which wins over ``MEMANGA_LOG_LEVEL``,
    which wins over ``default``. An invalid environment value is ignored.
    """
    if verbose and verbose >= 2:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    if quiet:
        return logging.ERROR
    env = (os.environ if environ is None else environ).get(LOG_LEVEL_ENV)
    level = parse_log_level(env)
    return default if level is None else level


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_secrets = set()

_KEY_VALUE = re.compile(
    r"(?i)\b((?:app[_ -]?)?password|passwd|pwd|(?:access[_-]?|refresh[_-]?)?token"
    r"|secret|api[_-]?key|authorization)"
    r"([\"']?\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s&,;\"']+)"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_URL_USERINFO = re.compile(r"(://[^/\s:@]+:)[^/\s@]+@")

REDACTED = "***"


def register_secret(value) -> None:
    """Mask ``value`` wherever it appears in log output (e.g. an app password)."""
    # Short values would mask ordinary words all over the log.
    if isinstance(value, str) and len(value.strip()) >= 6:
        _secrets.add(value)


def redact(text: str) -> str:
    """Mask registered secrets and common ``password=``/token shapes."""
    for secret in sorted(_secrets, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, REDACTED)
    # Bearer first: `Authorization: Bearer x` must not leave x behind.
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return _URL_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts the whole record, tracebacks included.

    Every physical line of a multi-line record (a traceback, a message
    with newlines) repeats the record's prefix, so each line of a log
    file still starts with the timestamp and level and can be grepped.
    """

    def format(self, record: logging.LogRecord) -> str:
        text = redact(super().format(record))
        if "\n" not in text:
            return text
        first, *rest = text.split("\n")
        prefix = self._line_prefix(record)
        return "\n".join([first] + [prefix + line for line in rest])

    def _line_prefix(self, record: logging.LogRecord) -> str:
        parts = []
        if self.usesTime():
            parts.append(getattr(record, "asctime", None)
                         or self.formatTime(record, self.datefmt))
        parts.append(f"{record.levelname} {record.name}:")
        return " ".join(parts) + " "


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

# LogRecord attribute holding a Rich-markup rendering of the record
# (``logger.warning(..., extra={RICH_MARKUP: "[yellow]...[/yellow]"})``).
RICH_MARKUP = "rich_markup"

_console_renderer = None


def set_console_renderer(renderer) -> None:
    """Show records that carry :data:`RICH_MARKUP` through ``renderer``
    (called with the markup) instead of as a plain stderr line.

    The CLI sets this when stderr is an interactive terminal, so its
    warnings keep their colours there while the level still decides
    whether they appear; files and redirects get the plain record.
    ``None`` turns it off.
    """
    global _console_renderer
    _console_renderer = renderer


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever ``sys.stderr`` is at emit time.

    The GUI repairs or replaces the streams after start-up and tests
    capture them; binding the stream once would write to a stale one.
    """

    def __init__(self):
        logging.Handler.__init__(self)

    @property
    def stream(self):
        return sys.stderr

    def emit(self, record):
        if sys.stderr is None:
            return
        markup = getattr(record, RICH_MARKUP, None)
        renderer = _console_renderer
        if markup is not None and renderer is not None:
            try:
                renderer(redact(markup))
            except Exception:
                self.handleError(record)
            return
        super().emit(record)


class _OwnOrWarnings(logging.Filter):
    """Let third-party loggers through only at WARNING and above, so
    ``-vv`` shows MeManga's debug output rather than every library's."""

    def filter(self, record: logging.LogRecord) -> bool:
        return (record.levelno >= logging.WARNING
                or record.name == "memanga"
                or record.name.startswith("memanga."))


_OWN_HANDLER = "_memanga_handler"
_saved_root_level: Optional[int] = None


def _stream_is_tty(stream) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _formatter(timestamps: bool) -> RedactingFormatter:
    if timestamps:
        return RedactingFormatter(TIMESTAMPED_LOG_FORMAT, LOG_DATE_FORMAT)
    return RedactingFormatter(LOG_FORMAT)


def _own(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _OWN_HANDLER, True)
    handler.addFilter(_OwnOrWarnings())
    return handler


def _remove_own_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, _OWN_HANDLER, False):
            root.removeHandler(handler)
            handler.close()


def configure_logging(level: int, *, log_file=None,
                      timestamps: Optional[bool] = None) -> None:
    """Send log records to stderr at ``level`` and, optionally, to a file.

    Safe to call again: it replaces the handlers it installed before.
    ``timestamps`` defaults to True when stderr is not a terminal (cron,
    redirects), so persisted lines carry a time and level. The optional
    ``log_file`` rotates (:data:`LOG_FILE_MAX_BYTES`, :data:`LOG_FILE_BACKUPS`)
    and always has timestamps; it records INFO and above, or ``level`` if
    that is more verbose. Raises OSError when the file can't be opened.
    """
    global _saved_root_level
    handlers = []
    # Open the file first: if that fails, the previous setup stays.
    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = _own(logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUPS,
            encoding="utf-8",
        ))
        file_handler.setLevel(min(level, logging.INFO))
        file_handler.setFormatter(_formatter(True))
        handlers.append(file_handler)

    if timestamps is None:
        timestamps = not _stream_is_tty(sys.stderr)
    stderr_handler = _own(_StderrHandler())
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(_formatter(timestamps))
    handlers.append(stderr_handler)

    root = logging.getLogger()
    if _saved_root_level is None:
        _saved_root_level = root.level
    _remove_own_handlers(root)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(min(h.level for h in handlers))


def logging_configured() -> bool:
    """True once :func:`configure_logging` installed its handlers."""
    return any(getattr(h, _OWN_HANDLER, False)
               for h in logging.getLogger().handlers)


def reset_logging() -> None:
    """Undo :func:`configure_logging` (for tests and embedding callers)."""
    global _saved_root_level
    set_console_renderer(None)
    root = logging.getLogger()
    _remove_own_handlers(root)
    if _saved_root_level is not None:
        root.setLevel(_saved_root_level)
        _saved_root_level = None


def rotate_log_file(path, backups: int = LOG_FILE_BACKUPS) -> bool:
    """Shift ``path`` to ``path.1`` (``.1`` to ``.2``...), keeping ``backups``.

    Returns True when ``path`` is free for a new file. Best effort: a
    file another process holds open (Windows refuses to rename it) is
    left in place and False is returned, so the caller can append to it
    rather than truncate someone else's log.
    """
    path = Path(path)
    if backups < 1:
        return not path.exists()
    try:
        for i in range(backups - 1, 0, -1):
            older = path.with_name(f"{path.name}.{i}")
            if older.exists():
                os.replace(older, path.with_name(f"{path.name}.{i + 1}"))
        if path.exists():
            os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        pass
    return not path.exists()


# ---------------------------------------------------------------------------
# Plain output
# ---------------------------------------------------------------------------

# The icons MeManga's own messages use, plus box drawing (tree markers,
# rules), with any variation selector or joiner and the spacing that
# followed them. Only these are stripped: symbols in scraped data, such
# as a "♥" or "★" in a manga title, are user data and stay.
APP_DECORATION = (
    "✅⚠❌➕➖✏⏱⏰⬇⚙"
    "🩺📊📖🗑🔍📧📥🔗📚🚪📬📤📂📁🌐"
)
_DECORATION = re.compile(
    "(?:[" + APP_DECORATION + "─-╿][︎️‍]*)+[ \t]*"
)

# Wide enough that Rich never hard-wraps plain lines or table rows.
PLAIN_WIDTH = 4096


def strip_decoration(text: str) -> str:
    """Remove emoji and box-drawing characters for plain output."""
    return _DECORATION.sub("", text)


def stream_is_plain(stream, plain: bool = False,
                    environ: Optional[Mapping[str, str]] = None) -> bool:
    """True when output to ``stream`` should be plain text: ``--plain``,
    ``TERM=dumb``, or not a terminal (pipes, files, cron)."""
    if plain:
        return True
    if (os.environ if environ is None else environ).get("TERM") == "dumb":
        return True
    return not _stream_is_tty(stream)


class PlainStream:
    """File-like wrapper that strips decoration before writing.

    ``target`` is called on every write so a replaced ``sys.stdout``
    (redirection, test capture) is honoured.
    """

    def __init__(self, target):
        self._target = target

    @property
    def encoding(self) -> str:
        return getattr(self._target(), "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        stream = self._target()
        if stream is None:
            return 0
        return stream.write(strip_decoration(text))

    def flush(self) -> None:
        stream = self._target()
        if stream is not None and hasattr(stream, "flush"):
            stream.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._target().fileno()


def make_console(stderr: bool = False, plain: bool = False):
    """A Rich Console for stdout (or stderr).

    Plain consoles render no colour, no live widgets, no emoji or box
    drawing, and never hard-wrap. ``NO_COLOR`` is honoured by Rich itself.
    """
    from rich.console import Console

    if not plain:
        return Console(stderr=stderr)
    target = (lambda: sys.stderr) if stderr else (lambda: sys.stdout)
    return Console(
        file=PlainStream(target),
        color_system=None,
        no_color=True,
        force_terminal=False,
        force_interactive=False,
        soft_wrap=True,
        width=PLAIN_WIDTH,
        emoji=False,
        highlight=False,
        legacy_windows=False,
    )


def is_plain_console(console) -> bool:
    """True for a console built by ``make_console(plain=True)``."""
    return isinstance(getattr(console, "file", None), PlainStream)


def ensure_utf8_streams() -> None:
    """Reconfigure redirected stdout/stderr to UTF-8.

    A redirected stream on Windows uses the ANSI code page, so a chapter
    title or symbol outside it raised UnicodeEncodeError mid-run.
    Terminals and streams that are already UTF-8 are left alone;
    unencodable characters are replaced rather than raised.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or _stream_is_tty(stream):
            continue
        encoding = getattr(stream, "encoding", None)
        try:
            if encoding and codecs.lookup(encoding).name == "utf-8":
                continue
        except LookupError:
            pass
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, LookupError):
            pass
