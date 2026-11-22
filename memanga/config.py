"""
Configuration management for MeManga
"""

import logging
import math
import os
import sys
import threading
import yaml
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, List, Mapping, Optional

from .perf import timed
from .persist import atomic_write_text
from .process_lock import ConfigDirBusy, ConfigDirLock, ConfigDirLockError
from .schema import (SCHEMA_VERSION_KEY, SchemaVersionError, add_schema_version,
                     migrate as migrate_schema)

logger = logging.getLogger(__name__)

APP_DIR_NAME = "memanga"

# Issue #221: `--config-dir DIR` wins over $MEMANGA_CONFIG_DIR, which
# wins over the platform default (issue #249). The CLI and the desktop
# app select the directory the same way.
CONFIG_DIR_ENV = "MEMANGA_CONFIG_DIR"

# Files that mark a directory as holding a user's MeManga data. Logs,
# the lock file and the cover cache alone do not count.
DATA_FILES = ("config.yaml", "state.json", "config.yaml.bak", "state.json.bak")

# Left in the old directory after it was moved (issue #249).
MOVED_NOTE = "MOVED.txt"

# Issue #409: layout version of config.yaml (see memanga.schema). When
# it is bumped, register ``old_version: migrate_fn`` below.
CONFIG_SCHEMA_VERSION = 1
_CONFIG_MIGRATIONS = {
    0: add_schema_version,
}


def platform_config_dir(platform=None, environ=None, home=None) -> Path:
    """The platform's per-user config root for MeManga (issue #249).

    - Windows: ``%APPDATA%\\memanga`` (the roaming application data
      folder; ``~\\AppData\\Roaming`` when APPDATA is unset).
    - macOS: ``~/Library/Application Support/memanga``.
    - Linux and other systems: ``$XDG_CONFIG_HOME/memanga``, or
      ``~/.config/memanga`` when the variable is unset, empty or not an
      absolute path (XDG Base Directory Specification).

    The arguments exist for tests; by default the running system is used.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        base = environ.get("APPDATA")
        root = Path(base) if base and os.path.isabs(base) else home / "AppData" / "Roaming"
    elif platform == "darwin":
        root = home / "Library" / "Application Support"
    else:
        base = environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base and os.path.isabs(base) else home / ".config"
    return root / APP_DIR_NAME


def legacy_config_dir(home=None) -> Path:
    """Where every platform kept config and state before issue #249."""
    home = Path.home() if home is None else Path(home)
    return home / ".config" / APP_DIR_NAME


def explicit_config_dir(cli_value=None) -> Optional[Path]:
    """The directory chosen with ``--config-dir`` (``cli_value``) or
    ``$MEMANGA_CONFIG_DIR``, or None when neither is set."""
    value = cli_value or os.environ.get(CONFIG_DIR_ENV)
    if not value:
        return None
    return Path(value).expanduser().absolute()


def selected_config_dir(cli_value=None) -> Path:
    """The config root for this run: an explicit directory as is, else
    :func:`default_config_dir`. An explicit directory never moves the
    legacy folder."""
    return explicit_config_dir(cli_value) or default_config_dir()


def default_config_dir() -> Path:
    """Config root used when none is selected (issue #249).

    The platform directory (see :func:`platform_config_dir`) is used,
    unless only the legacy ``~/.config/memanga`` holds data: that
    directory is then moved there once by
    :func:`migrate_legacy_config_dir`, or kept in use if it cannot be
    moved safely. ``--config-dir`` and ``$MEMANGA_CONFIG_DIR`` bypass this.
    """
    native = platform_config_dir()
    legacy = legacy_config_dir()
    if _same_dir(native, legacy) or has_config_data(native) or not has_config_data(legacy):
        return native
    return migrate_legacy_config_dir(legacy, native)


def default_root_moved(root) -> bool:
    """True when ``root`` is the legacy folder that default_config_dir()
    returned, but another process has since moved it to the platform
    folder: it holds no data any more and the platform folder does. A
    root selected this way must not be loaded or saved (issue #249)."""
    native = platform_config_dir()
    legacy = legacy_config_dir()
    return (_same_dir(root, legacy) and not _same_dir(native, legacy)
            and not has_config_data(legacy) and has_config_data(native))


def has_config_data(directory) -> bool:
    """True when ``directory`` holds MeManga config or state files."""
    directory = Path(directory)
    return any((directory / name).is_file() for name in DATA_FILES)


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _refers_to_itself(directory: Path) -> bool:
    """True when config.yaml or state.json names a path inside the legacy
    directory (for example a download folder there), which a move would
    break. Errs on the side of True."""
    for name in ("config.yaml", "state.json"):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        except OSError:
            return True
        # Fold YAML/JSON backslash escapes and Windows separators.
        text = text.lower().replace("\\\\", "/").replace("\\", "/")
        if f".config/{APP_DIR_NAME}" in text:
            return True
    return False


def migrate_legacy_config_dir(legacy, native) -> Path:
    """Move ``legacy`` to ``native`` once; return the directory to use.

    The move is a single directory rename taken under the legacy
    directory's process lock (issue #244), so nothing is copied, merged
    or deleted and no other MeManga process can write during it. The
    legacy directory is kept in use, unchanged, when:

    - another process holds its lock (an older MeManga may be running);
    - ``native`` already exists and is not an empty directory;
    - its config or state names a path inside it;
    - the rename fails (another drive, permissions, open files).

    After a move, ``legacy`` is recreated with only a short note, so
    scheduled checks installed before the move still find their working
    and log directory.
    """
    legacy, native = Path(legacy), Path(native)
    lock = ConfigDirLock(legacy)
    try:
        lock.acquire()
    except (ConfigDirBusy, ConfigDirLockError):
        # Another process may be moving it right now.
        return native if has_config_data(native) else legacy
    try:
        # Re-check under the lock: another process may have moved it.
        if has_config_data(native) or not has_config_data(legacy):
            return native
        # This process already uses the legacy directory.
        if lock.joined:
            return legacy
        if _refers_to_itself(legacy):
            return legacy
        if native.exists():
            if not native.is_dir() or any(native.iterdir()):
                return legacy
            native.rmdir()
        native.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            # Windows cannot rename a folder with an open file in it; a
            # process that opens the lock now makes the rename fail.
            lock.release()
        os.rename(legacy, native)
    except OSError:
        return legacy
    finally:
        lock.release()
    _leave_moved_note(legacy, native)
    return native


def _leave_moved_note(legacy: Path, native: Path):
    try:
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / MOVED_NOTE).write_text(
            "MeManga now keeps its settings and library in:\n"
            f"{native}\n\n"
            "This folder is kept so scheduled checks installed earlier keep "
            "working. After reinstalling the daily check (Settings in the "
            "app, or `memanga cron install`), it can be deleted.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


class ConfigError(Exception):
    """The config file exists but cannot be loaded."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PostProcessingSettings:
    """The checked ``delivery.post_processing`` settings (issue #293).

    A value of the wrong type counts as unset, so a quoted ``"false"``
    can never turn the command on.
    """

    enabled: bool = False
    # Often holds paths or tokens, so it is not part of the repr.
    command: str = field(default="", repr=False)
    fail_on_error: bool = False

    @classmethod
    def from_mapping(cls, raw: Any) -> "PostProcessingSettings":
        """The settings in ``raw``, a ``delivery.post_processing`` value."""
        if not isinstance(raw, Mapping):
            return cls()
        values = {}
        for item in fields(cls):
            value = raw.get(item.name)
            key = f"delivery.post_processing.{item.name}"
            if value is not None and config_value_problem(key, value) is None:
                values[item.name] = value
        return cls(**values)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliverySettings:
    """The checked ``delivery.*`` settings at one moment (issue #293).

    Read it from :attr:`Config.delivery` each time: it does not follow
    later changes. Keys it does not cover stay available through
    :meth:`Config.get`. ``download_dir`` is None when the configured
    path cannot be resolved (``~name`` for an unknown user).
    """

    mode: str
    download_dir: Optional[Path]
    delete_after_send: bool
    output_format: str
    naming_template: str
    post_processing: PostProcessingSettings


class Config:
    """Manages configuration file.

    Thread-safe: a single ``_lock`` serializes both `_data` mutations from
    background threads (cover backfill, cover fetch on add) and the YAML
    write itself. Writes are atomic via tempfile + os.replace so a crash
    mid-save can never truncate the user's config.

    With ``tolerate_errors=True`` an unreadable or invalid config file
    does not raise: defaults are loaded, the problem is kept in
    ``load_error`` and ``save()`` refuses to write, so the broken file is
    never overwritten. The CLI uses this so `memanga doctor` can still
    report the problem.

    Issue #293: a known section that is not a mapping makes the file
    invalid, since merging defaults over it would lose it on the next
    save. A single bad value does not: it stays in the file, is listed
    by ``validation_problems``, and typed access (``delivery``) uses the
    default instead. Keys outside the schema are kept as they are and
    remain available through ``get`` and ``set``.
    """

    def __init__(self, config_dir=None, tolerate_errors=False):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = default_config_dir()

        self.config_path = self.config_dir / "config.yaml"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tolerate_errors = tolerate_errors
        self.load_error = None
        self._data = self._load()
    
    def _load(self):
        """Load config from file."""
        self.load_error = None
        if self.config_path.exists():
            try:
                # Explicit UTF-8: titles are arbitrary Unicode and the
                # platform default encoding may not represent them.
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    raise ConfigError("config file does not contain a YAML mapping")
                # Issue #409: upgrade an older layout before the defaults
                # are merged in; refuse a config from a newer MeManga.
                try:
                    data = migrate_schema(data, CONFIG_SCHEMA_VERSION,
                                          _CONFIG_MIGRATIONS, "config")
                except SchemaVersionError as e:
                    raise ConfigError(str(e)) from None
                # Issue #293: checked before defaults are merged over them.
                # An empty section is what commenting out its keys leaves.
                broken = config_section_problems(data, allow_empty=True)
                if broken:
                    raise ConfigError("; ".join(broken))
            except (OSError, UnicodeDecodeError, yaml.YAMLError, ConfigError) as e:
                if not self._tolerate_errors:
                    raise
                self.load_error = str(e)
                return self._default_config()
            # Merge with defaults to ensure new fields exist
            _fill_defaults(data, self._default_config())
            return data
        return self._default_config()

    def _default_config(self):
        """Return default configuration."""
        return {
            SCHEMA_VERSION_KEY: CONFIG_SCHEMA_VERSION,
            "manga": [],
            "delivery": {
                "mode": "local",  # "local" or "email"
                "download_dir": str(Path.home() / "Downloads" / "MeManga"),
                "delete_after_send": False,  # Delete file after sending to Kindle
                "output_format": "pdf",  # "pdf", "epub", "cbz", "zip", "jpg", "png", or "webp"
                "naming_template": "{title} - Chapter {chapter}",  # File naming pattern
                "post_processing": {
                    # Optional command run after each chapter's output
                    # file/folder is created. Disabled by default. See docs
                    # for available placeholders/env vars.
                    "enabled": False,
                    "command": "",
                    "fail_on_error": False,  # True marks the chapter failed
                },
            },
            "email": {
                "kindle_email": "",
                "sender_email": "",
                "smtp_server": "smtp.gmail.com",
                "smtp_port": 587,
                # "auto": implicit TLS on port 465, STARTTLS otherwise
                "smtp_tls": "auto",
                "smtp_timeout": 60,  # seconds per SMTP operation
                "max_email_mb": 25,  # mail provider's email size limit
                "app_password": "",
            },
            "cron": {
                "enabled": False,
                "time": "06:00",
            },
            "gui": {
                "sort_by": "title",
                "auto_check": True,
                "auto_check_interval": 3600,
                # Reader prefetch (issue #107). Off by default: while
                # reading a manual-mode manga, the reader quietly queues
                # the immediate next available chapter in the background.
                "reader_prefetch_next": False,
                # Desktop network behaviour (issue #337). The connectivity
                # check opens a bare TCP connection (no data sent) to the
                # first reachable host so the app can tell when it is
                # offline; an empty host list means the built-in hosts in
                # gui/network_status.py.
                "network_check": True,
                "network_check_hosts": [],
                # Look up missing or broken covers on MangaDex. Also skipped
                # whenever mangadex.org is turned off in Sources.
                "mangadex_cover_fallback": True,
                # Chapter-count chips on Search (issue #405): one
                # chapter-list fetch per result, retried when it fails.
                "search_chapter_counts": True,
                # Size limit of the cover image cache on disk, in MB
                # (issue #404). Past it, the covers used longest ago are
                # removed; they are fetched again when needed.
                "cover_cache_max_mb": 200,
            },
            # Built-in reader behaviour (issue #104). Kept separate from
            # delivery.delete_after_send, which is tied to email delivery —
            # this is reader-driven local cleanup. Off by default: a chapter
            # stays on disk after it is read unless the user opts in.
            "reader": {
                "remove_after_read": False,
            },
            "mangadex": {
                "data_saver": False,
                "removed_group_ids": [],
            },
            # Partial-chapter tolerance (issue #86). Off by default: any
            # missing page still aborts the chapter and discards output.
            # When enabled, a chapter whose failure rate is within
            # threshold_percent is kept with only the pages that succeeded.
            "partial_chapters": {
                "enabled": False,
                "threshold_percent": 5,  # max % of pages allowed to fail
            },
        }
    
    def reload(self):
        """Re-read config from disk, discarding any in-memory changes.

        Useful when another process (e.g. the CLI) has updated the file
        and this instance needs to pick up the changes.
        """
        with self._lock:
            self._data = self._load()

    def get(self, key, default=None):
        """Get a config value."""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value
    
    def set(self, key, value):
        """Set a config value. Thread-safe (holds ``_lock``)."""
        keys = key.split(".")
        with self._lock:
            data = self._data
            for k in keys[:-1]:
                if k not in data or not isinstance(data[k], dict):
                    data[k] = {}
                data = data[k]
            data[keys[-1]] = value
    
    @timed("config.save")
    def save(self):
        """Save config to file atomically. Thread-safe.

        Snapshots `_data` under the lock, then writes to a temp file and
        atomically replaces the live file. Concurrent saves serialize on
        the lock instead of fighting over the same file descriptor.
        """
        if self.load_error:
            raise ConfigError(
                f"Refusing to overwrite {self.config_path}, which could not "
                f"be loaded: {self.load_error}"
            )
        with self._lock:
            payload = yaml.dump(
                self._data, default_flow_style=False, allow_unicode=True,
            )

        # Issue #243: keep the previous config as config.yaml.bak.
        atomic_write_text(self.config_path, payload,
                          backup_path=self.config_dir / "config.yaml.bak")

    def update_manga(self, title, mutator):
        """Atomically mutate the manga entry with the given title.

        ``mutator`` is called with the entry dict while the lock is held;
        any return value is ignored. Saves automatically when the mutator
        returns truthy (or returns ``None``, the common "I mutated in
        place" case). Returns True if an entry was found.
        """
        with self._lock:
            for entry in self._data.get("manga", []):
                if entry.get("title") == title:
                    result = mutator(entry)
                    # None == "I mutated in place"; False == "skip save"
                    needs_save = result is None or bool(result)
                    break
            else:
                return False
        if needs_save:
            self.save()
        return True
    
    def reset(self):
        """Reset to default config and save it. Thread-safe: the lock is
        held across both, so no other thread's change lands in between."""
        with self._lock:
            self._data = self._default_config()
            self.save()
    
    @property
    def validation_problems(self) -> List[str]:
        """Known settings with an invalid value, as ``key: reason``.

        Never contains the value, which may be a secret (issue #293).
        """
        with self._lock:
            return config_problems(self._data)

    @property
    def validation_notice(self) -> Optional[str]:
        """What to tell the user about invalid settings, or None."""
        problems = self.validation_problems
        if not problems:
            return None
        lines = "\n".join(f"  {problem}" for problem in problems)
        return (f"Some settings in {self.config_path} are not valid and may "
                f"be ignored:\n{lines}\nFix them in that file, or run "
                "`memanga config edit`.")

    def _known(self, key):
        """The stored value of schema key ``key``, or its default when it
        is unset or invalid."""
        value = self.get(key)
        if value is not None and config_value_problem(key, value) is None:
            return value
        node = self._default_config()
        for part in key.split("."):
            node = node[part]
        return node

    @property
    def delivery(self) -> DeliverySettings:
        """The checked ``delivery.*`` settings, read now (issue #293)."""
        with self._lock:
            try:
                download_dir = self.download_dir
            except (RuntimeError, ValueError):
                # Reading another setting must not fail over this one.
                download_dir = None
            return DeliverySettings(
                mode=self.delivery_mode,
                download_dir=download_dir,
                delete_after_send=self._known("delivery.delete_after_send"),
                output_format=self.output_format,
                naming_template=self._known("delivery.naming_template"),
                post_processing=PostProcessingSettings.from_mapping(
                    self.get("delivery.post_processing")),
            )

    # Convenience properties
    @property
    def delivery_mode(self):
        return self._known("delivery.mode")

    @property
    def download_dir(self):
        value = self.get("delivery.download_dir")
        # Issue #293: an empty path would mean the current directory.
        if value is None or config_value_problem("delivery.download_dir", value):
            value = str(self.config_dir / "downloads")
        return Path(value).expanduser()

    @property
    def email_enabled(self):
        # bool() matters: `and` would otherwise leak the kindle_email
        # string, which Qt setters like setChecked() reject (issue #55).
        return self.delivery_mode == "email" and bool(self.get("email.kindle_email"))

    @property
    def output_format(self):
        # An unknown format has always been saved as a PDF, the default.
        return self._known("delivery.output_format")

    @property
    def partial_enabled(self):
        """Whether partial-chapter tolerance is turned on (issue #86)."""
        return bool(self.get("partial_chapters.enabled", False))

    @property
    def partial_threshold(self):
        """Max share of pages allowed to fail before a partial is refused,
        as a percentage clamped to [0, 100]. Falls back to 5 for garbage or
        out-of-range values persisted by an older/hand-edited config."""
        try:
            value = float(self.get("partial_chapters.threshold_percent", 5))
        except (OverflowError, TypeError, ValueError):
            return 5.0
        # Clamping would turn NaN or infinity into 100: every page
        # allowed to fail.
        if not math.isfinite(value):
            return 5.0
        return max(0.0, min(100.0, value))

    @property
    def reader_prefetch_enabled(self):
        """Whether the reader prefetches the next manual-mode chapter
        while reading (issue #107)."""
        return bool(self.get("gui.reader_prefetch_next", False))

    @property
    def reader_remove_after_read(self) -> bool:
        """Whether a finished chapter is removed (issue #104). Only a
        real ``true`` turns it on: text like ``"no"`` is truthy (#293)."""
        return self._known("reader.remove_after_read")

    @property
    def cron_enabled(self) -> bool:
        """``cron.enabled`` as a real boolean, for a checkbox (#293)."""
        return self._known("cron.enabled")


_KEYRING_SERVICE = "memanga"
_KEYRING_KEY = "app_password"

# Issue #247: headless and container installs inject the app password
# instead of storing it. Either variable wins over the keyring and
# config.yaml; setting both is an error (as with Docker's *_FILE
# convention). A password from them is never written anywhere.
SMTP_PASSWORD_ENV = "MEMANGA_SMTP_PASSWORD"
SMTP_PASSWORD_FILE_ENV = "MEMANGA_SMTP_PASSWORD_FILE"

# A password file larger than this is not a password file.
_PASSWORD_FILE_MAX_BYTES = 4096


class AppPasswordError(Exception):
    """$MEMANGA_SMTP_PASSWORD(_FILE) is set but cannot be used. The
    message never contains the password.

    Messages built from it must not put a colon right after the word
    "password" ("App password: ..."): log redaction (memanga.output)
    treats that as a secret and masks the next word.
    """


def app_password_override(environ=None):
    """The app password injected through the environment (issue #247).

    Returns ``(variable_name, password)``, or None when neither
    variable is set (an empty value counts as unset). Raises
    AppPasswordError when both are set or the file cannot be used.
    """
    environ = os.environ if environ is None else environ
    value = environ.get(SMTP_PASSWORD_ENV) or None
    file_name = environ.get(SMTP_PASSWORD_FILE_ENV) or None
    if value and file_name:
        raise AppPasswordError(
            f"{SMTP_PASSWORD_ENV} and {SMTP_PASSWORD_FILE_ENV} are both set; "
            "set only one")
    if value:
        return SMTP_PASSWORD_ENV, value
    if not file_name:
        return None
    invalid_path = AppPasswordError(
        f"{SMTP_PASSWORD_FILE_ENV} path {file_name!r} is not a valid file path")
    try:
        path = Path(file_name).expanduser()
    except RuntimeError:
        # "~name" for an unknown user, or no home folder at all.
        raise AppPasswordError(
            f"cannot resolve the home folder in {SMTP_PASSWORD_FILE_ENV} "
            f"path {file_name!r}") from None
    except ValueError:
        # A NUL in "~name" fails the user lookup on POSIX.
        raise invalid_path from None
    try:
        with open(path, "rb") as f:
            raw = f.read(_PASSWORD_FILE_MAX_BYTES + 1)
    except OSError as e:
        raise AppPasswordError(
            f"cannot read {SMTP_PASSWORD_FILE_ENV} file {path} "
            f"({e.strerror or type(e).__name__})") from None
    except ValueError:
        # An embedded NUL character, for example.
        raise invalid_path from None
    if len(raw) > _PASSWORD_FILE_MAX_BYTES:
        raise AppPasswordError(
            f"{SMTP_PASSWORD_FILE_ENV} file {path} is too large to be a password")
    try:
        # Secret files usually end with a newline; the password does not.
        password = raw.decode("utf-8-sig").rstrip("\r\n")
    except UnicodeDecodeError:
        raise AppPasswordError(
            f"{SMTP_PASSWORD_FILE_ENV} file {path} is not UTF-8 text") from None
    if not password:
        raise AppPasswordError(f"{SMTP_PASSWORD_FILE_ENV} file {path} is empty")
    return SMTP_PASSWORD_FILE_ENV, password


def get_app_password(cfg: Config) -> str:
    """Get the app password: $MEMANGA_SMTP_PASSWORD or the file named by
    $MEMANGA_SMTP_PASSWORD_FILE, else the keyring, else the config file.

    Never raises. When an override is set but unusable, the problem is
    logged and "" is returned: a stored password is not used in its
    place, so delivery fails visibly instead of with a stale password.
    """
    try:
        override = app_password_override()
    except AppPasswordError as e:
        logger.warning("App password not available: %s", e)
        return ""
    if override:
        return override[1]
    try:
        import keyring
        password = keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)
        if password:
            return password
    except Exception:
        pass
    return cfg.get("email.app_password", "")


def set_app_password(cfg: Config, password: str) -> str:
    """Store the app password in the keyring, falling back to the config
    file. Saves config. Returns where it went: "keyring" or "config".

    A "config" result means the password is now in plain text in
    ``cfg.config_path``; callers tell the user (see
    :func:`plaintext_password_notice`).
    """
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, password)
        # A backend that discards secrets does not raise; read it back.
        if keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY) != password:
            raise RuntimeError("keyring did not keep the password")
        # Clear plaintext from config if keyring succeeded
        if cfg.get("email.app_password"):
            cfg.set("email.app_password", "")
            cfg.save()
        return "keyring"
    except Exception as e:
        # The type only: a backend's message is not worth the risk.
        logger.debug("Keyring unavailable (%s); using the config file",
                     type(e).__name__)
    # Fallback: store in config
    cfg.set("email.app_password", password)
    cfg.save()
    return "config"


def plaintext_password_notice(cfg: Config) -> str:
    """What to tell the user after set_app_password() returned "config"."""
    return (
        "No usable system keyring, so the app password was saved in plain "
        f"text in {cfg.config_path}. Keep that file private (on Linux and "
        "macOS it should be readable only by you, e.g. chmod 600). On "
        f"servers and in containers, set {SMTP_PASSWORD_FILE_ENV} or "
        f"{SMTP_PASSWORD_ENV} instead."
    )


# ============================================================================
# Keys the `config get/set` commands accept (issue #353)
# ============================================================================

OUTPUT_FORMATS = ("pdf", "epub", "cbz", "zip", "jpg", "png", "webp")

_TRUE_WORDS = {"true", "yes", "on", "1"}
_FALSE_WORDS = {"false", "no", "off", "0"}


class UnknownConfigKey(KeyError):
    """The dotted key is not one `config get/set` knows."""


# kind: bool | int | float | choice | str | time | list
# secret: never printed; read_only: owned by another command.
CONFIG_KEYS = {
    "delivery.mode": {"kind": "choice", "choices": ("local", "email")},
    "delivery.download_dir": {"kind": "str", "required": True},
    "delivery.delete_after_send": {"kind": "bool"},
    "delivery.output_format": {"kind": "choice", "choices": OUTPUT_FORMATS},
    "delivery.naming_template": {"kind": "str", "required": True},
    "delivery.post_processing.enabled": {"kind": "bool"},
    "delivery.post_processing.command": {"kind": "str"},
    "delivery.post_processing.fail_on_error": {"kind": "bool"},
    "email.kindle_email": {"kind": "str"},
    "email.sender_email": {"kind": "str"},
    "email.smtp_server": {"kind": "str", "required": True},
    "email.smtp_port": {"kind": "int", "min": 1, "max": 65535},
    # Choices match SMTP_TLS_MODES in emailer.py.
    "email.smtp_tls": {"kind": "choice",
                       "choices": ("auto", "starttls", "implicit")},
    "email.smtp_timeout": {"kind": "int", "min": 1, "max": 600},
    # Bounds match MIN/MAX_EMAIL_SIZE_MB in emailer.py.
    "email.max_email_mb": {"kind": "int", "min": 10, "max": 50},
    "email.app_password": {"kind": "str", "secret": True},
    # Issue #345: choices match KINDLE_SCOPES in email_settings.py. Not in
    # the defaults: unset keeps the pre-#345 "all" for existing configs.
    "email.kindle_scope": {"kind": "choice", "choices": ("all", "selected")},
    "cron.enabled": {"kind": "bool", "read_only": "memanga cron install/remove"},
    "cron.time": {"kind": "time", "read_only": "memanga cron install --time HH:MM"},
    "gui.sort_by": {"kind": "choice", "choices": (
        "title", "last_updated", "recently_added", "chapter_count", "status")},
    "gui.auto_check": {"kind": "bool"},
    "gui.auto_check_interval": {"kind": "int", "min": 60},
    "gui.reader_prefetch_next": {"kind": "bool"},
    "gui.network_check": {"kind": "bool"},
    "gui.network_check_hosts": {
        "kind": "list", "items": "host_port", "read_only": "memanga config edit"},
    "gui.mangadex_cover_fallback": {"kind": "bool"},
    "gui.search_chapter_counts": {"kind": "bool"},
    # Bounds match MIN/MAX_DISK_LIMIT_MB in gui/cache.py.
    "gui.cover_cache_max_mb": {"kind": "int", "min": 10, "max": 10000},
    "reader.remove_after_read": {"kind": "bool"},
    "mangadex.data_saver": {"kind": "bool"},
    "mangadex.removed_group_ids": {
        "kind": "list", "read_only": "memanga config --mangadex-remove-group"},
    "partial_chapters.enabled": {"kind": "bool"},
    "partial_chapters.threshold_percent": {"kind": "float", "min": 0, "max": 100},
}


def config_key_spec(key):
    """Return the schema entry for ``key``; raise UnknownConfigKey."""
    try:
        return CONFIG_KEYS[key]
    except KeyError:
        raise UnknownConfigKey(key) from None


def _is_hhmm(value) -> bool:
    parts = str(value).split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    return 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59


def parse_host_port(text):
    """``"host:port"`` (or ``"[v6]:port"``) as ``(host, port)``, or None.

    Only a bare host and port: URLs, paths and whitespace are rejected.
    """
    if not isinstance(text, str):
        return None
    host, sep, port = text.strip().rpartition(":")
    if not sep or not port.isdigit() or not 1 <= int(port) <= 65535:
        return None
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(c.isspace() or c in "/@[]" for c in host):
        return None
    if ":" in host and not text.strip().startswith("["):
        return None  # IPv6 needs brackets so the port is unambiguous
    return host, int(port)


def _range_problem(spec, value):
    low, high = spec.get("min"), spec.get("max")
    if low is not None and value < low:
        return f"must be at least {low:g}"
    if high is not None and value > high:
        return f"must be at most {high:g}"
    return None


def parse_config_value(key, text):
    """Turn the command-line ``text`` for ``key`` into the stored value.

    Raises UnknownConfigKey for keys outside CONFIG_KEYS and ValueError
    with a short reason for values the key does not accept.
    """
    spec = config_key_spec(key)
    kind = spec["kind"]
    text = str(text)
    if kind == "bool":
        word = text.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise ValueError("expected true or false")
    if kind in ("int", "float"):
        try:
            value = int(text.strip()) if kind == "int" else float(text.strip())
        except ValueError:
            raise ValueError("expected a whole number" if kind == "int"
                             else "expected a number") from None
        if kind == "float" and value != value:  # NaN
            raise ValueError("expected a number")
        problem = _range_problem(spec, value)
        if problem:
            raise ValueError(problem)
        return value
    if kind == "choice":
        word = text.strip().lower()
        if word not in spec["choices"]:
            raise ValueError("expected one of: " + ", ".join(spec["choices"]))
        return word
    if kind == "time":
        if not _is_hhmm(text.strip()):
            raise ValueError("expected HH:MM")
        hour, minute = text.strip().split(":")
        return f"{int(hour):02d}:{int(minute):02d}"
    if kind == "str":
        if spec.get("required") and not text.strip():
            raise ValueError("must not be empty")
        return text
    raise ValueError("cannot be set from the command line")


def config_section_problems(data, *, allow_empty=False):
    """Sections on the way to a known key that are not mappings.

    ``data`` is the raw YAML mapping, before defaults are merged in, so
    a section that is not a mapping is still visible. With
    ``allow_empty``, a section with no value (YAML null) is accepted.
    """
    problems = []
    for key in CONFIG_KEYS:
        parts = key.split(".")
        node = data
        for depth, part in enumerate(parts[:-1], start=1):
            if part not in node:
                break
            node = node[part]
            if node is None and allow_empty:
                break
            if not isinstance(node, dict):
                problem = f"{'.'.join(parts[:depth])}: expected a section"
                if problem not in problems:
                    problems.append(problem)
                break
    return problems


def config_problems(data) -> List[str]:
    """Every problem with the known keys in ``data``, as ``key: reason``.

    Unset keys and keys outside CONFIG_KEYS are not problems. The text
    never contains a value, which may be a secret (issue #293).
    """
    problems = config_section_problems(data)
    for key in CONFIG_KEYS:
        node = data
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            continue
        problem = config_value_problem(key, node)
        if problem:
            problems.append(f"{key}: {problem}")
    return problems


def _fill_defaults(data, defaults) -> None:
    """Add what ``data`` lacks from ``defaults``, at every level. A value
    already there is kept; only an empty section takes its default."""
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
        elif isinstance(value, dict):
            if isinstance(data[key], dict):
                _fill_defaults(data[key], value)
            else:
                data[key] = value


def config_value_problem(key, value):
    """Why the stored ``value`` is not valid for ``key``, or None.

    Used after a hand edit, where values arrive already typed by YAML.
    """
    spec = config_key_spec(key)
    kind = spec["kind"]
    if kind == "bool":
        return None if isinstance(value, bool) else "expected true or false"
    if kind in ("int", "float"):
        types = (int,) if kind == "int" else (int, float)
        if isinstance(value, bool) or not isinstance(value, types):
            return "expected a whole number" if kind == "int" else "expected a number"
        if isinstance(value, float) and not math.isfinite(value):
            return "expected a number"
        return _range_problem(spec, value)
    if kind == "choice":
        if value not in spec["choices"]:
            return "expected one of: " + ", ".join(spec["choices"])
        return None
    if kind == "time":
        return None if isinstance(value, str) and _is_hhmm(value) else "expected HH:MM"
    if kind == "list":
        if not isinstance(value, list):
            return "expected a list"
        if spec.get("items") == "host_port":
            for item in value:
                if parse_host_port(item) is None:
                    return "expected host:port entries"
        return None
    if not isinstance(value, str):
        return "expected text"
    if spec.get("required") and not value.strip():
        return "must not be empty"
    return None
