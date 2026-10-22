"""
MeManga GUI - PySide6-based graphical interface.
"""

import logging
import sys

logger = logging.getLogger(__name__)


def _is_frozen():
    return getattr(sys, 'frozen', False)


# Playwright browsers the scrapers launch. Firefox drives most
# Playwright sources; Chromium is needed by MangaPark, whose Cloudflare
# check blocks Firefox. Both are installed and verified together.
_REQUIRED_BROWSERS = ("firefox", "chromium")


def _check_playwright_browsers():
    """True only when every required browser build matching the *bundled*
    Playwright package's expected revision is installed on disk.

    A "is there ANY firefox-* directory under ms-playwright?" check is
    too lenient — an older Firefox build from a previous Playwright
    install (e.g. ``firefox-1466``) satisfies it, then every
    Playwright-based scraper crashes at runtime when the newer bundled
    Playwright tries to launch a different build (``firefox-1522``).
    AJAX-only paths like MangaFire's chapter list keep working, which
    produces a confusing "some sources work, others don't" pattern.

    Ask Playwright itself where it expects each browser to live and
    check those exact paths. Slightly slower at startup (~200 ms for the
    Playwright import) but correctness over speed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        from pathlib import Path
        with sync_playwright() as pw:
            for name in _REQUIRED_BROWSERS:
                try:
                    expected = getattr(pw, name).executable_path
                except Exception:
                    # `executable_path` is a property on BrowserType that
                    # raises if the binary is missing on older Playwright
                    # versions — treat that as "not installed".
                    return False
                if not expected or not Path(expected).exists():
                    return False
            return True
    except Exception:
        return False


def _resolve_install_strategies():
    """Yield ``(label, argv)`` for each Playwright install strategy.

    Tried in order at launch time. Centralised here so both the
    blocking `_install_playwright_browsers` and the streaming
    `_install_playwright_browsers_stream` share the same resolution
    logic.
    """
    import shutil

    browsers = list(_REQUIRED_BROWSERS)

    # Strategy 1: bundled driver (node + cli.js). compute_driver_executable
    # returns a (node_path, cli_js_path) tuple on playwright >= 1.40; the
    # tuple must be unpacked into argv, not stringified, or the spawn
    # raises FileNotFoundError.
    try:
        from playwright._impl._driver import compute_driver_executable
        driver = compute_driver_executable()
        if isinstance(driver, tuple) and len(driver) == 2:
            node_path, cli_path = driver
            yield "bundled driver", [node_path, cli_path, "install", *browsers]
        else:
            # Back-compat for older Playwright (single string).
            yield "bundled driver", [str(driver), "install", *browsers]
    except Exception as e:  # pragma: no cover - import-time guard
        yield "bundled driver", _ImportError(f"import failed: {e}")

    # Strategy 2: system-installed `playwright` CLI (dev machines).
    playwright_bin = shutil.which("playwright")
    if playwright_bin:
        yield "system cli", [playwright_bin, "install", *browsers]

    # Strategy 3: python -m playwright install (source-only, not frozen).
    if not _is_frozen():
        yield "python -m", [sys.executable, "-m", "playwright", "install", *browsers]


class _ImportError:
    """Sentinel for a strategy whose argv couldn't be resolved."""
    def __init__(self, msg: str):
        self.msg = msg


def _install_playwright_browsers():
    """Run the install non-streaming. Used by the legacy QMessageBox path.

    Returns ``(ok, error_text)``. ``error_text`` is a short human-readable
    string the caller can drop into a dialog so the failure cause is
    visible instead of a generic "try again" message.
    """
    import os
    import subprocess

    errors: list[str] = []

    def _run(cmd, label):
        try:
            # Pass the environment through unchanged. The frozen entry
            # point pins PLAYWRIGHT_BROWSERS_PATH to the per-user cache
            # dir, and the install target must match the path the driver
            # resolves at launch time. Popping the variable here made the
            # installer write to the platform default while the running
            # process kept resolving to the empty bundle ("0"), so every
            # Playwright launch failed until the app was restarted.
            env = dict(os.environ)
            # no_window_kwargs() prevents Windows from flashing a cmd
            # window for the install subprocess — release builds use
            # console=False so any naked subprocess would otherwise pop
            # its own console.
            from ._subprocess import no_window_kwargs
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, env=env,
                **no_window_kwargs(),
            )
            if result.returncode == 0:
                return True, ""
            err = (result.stderr or result.stdout or "").strip()
            errors.append(f"[{label}] exit {result.returncode}: {err[:400]}")
            return False, err
        except FileNotFoundError as e:
            errors.append(f"[{label}] not found: {e}")
        except subprocess.TimeoutExpired:
            errors.append(f"[{label}] timed out after 600s")
        except Exception as e:
            errors.append(f"[{label}] {type(e).__name__}: {e}")
        return False, ""

    for label, argv in _resolve_install_strategies():
        if isinstance(argv, _ImportError):
            errors.append(f"[{label}] {argv.msg}")
            continue
        ok, _ = _run(argv, label)
        if ok:
            return True, ""

    return False, "\n".join(errors) if errors else "no install strategy available"


def _install_playwright_browsers_stream(on_line, cancelled):
    """Streaming variant — calls ``on_line(text)`` per stdout line.

    ``cancelled`` is a callable returning ``True`` when the operation
    should abort; checked between lines. Returns ``(ok, error_text)``
    with the same semantics as the blocking variant. Used by the
    FirefoxInstallDialog progress UI.
    """
    import os
    import subprocess

    errors: list[str] = []

    def _stream(cmd, label):
        try:
            # Environment passed through unchanged — install target must
            # match the driver's launch-time lookup (see the blocking
            # variant above for the full rationale).
            env = dict(os.environ)
            from ._subprocess import no_window_kwargs
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                **no_window_kwargs(),
            )
            tail: list[str] = []
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                if cancelled():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return False, "cancelled by user"
                tail.append(line)
                # Keep memory bounded — only the most recent 200 lines
                # are needed for failure diagnostics.
                if len(tail) > 200:
                    del tail[: len(tail) - 200]
                try:
                    on_line(line)
                except Exception:
                    # Never let a UI hiccup take down the install.
                    pass
            proc.stdout.close()
            rc = proc.wait()
            if rc == 0:
                return True, ""
            err = "".join(tail[-20:]).strip()
            errors.append(f"[{label}] exit {rc}: {err[:400]}")
            return False, err
        except FileNotFoundError as e:
            errors.append(f"[{label}] not found: {e}")
        except Exception as e:
            errors.append(f"[{label}] {type(e).__name__}: {e}")
        return False, ""

    for label, argv in _resolve_install_strategies():
        if cancelled():
            return False, "cancelled by user"
        if isinstance(argv, _ImportError):
            errors.append(f"[{label}] {argv.msg}")
            continue
        ok, _ = _stream(argv, label)
        if ok:
            return True, ""
        # If `_stream` returned because Cancel was clicked mid-
        # download, don't quietly fall through to the next strategy
        # and kick off another (potentially long) attempt — surface
        # the cancel.
        if cancelled():
            return False, "cancelled by user"

    return False, "\n".join(errors) if errors else "no install strategy available"


def _ensure_browsers():
    """Ensure the Playwright browsers (Firefox and Chromium) are installed.

    Drives the install via the streaming progress dialog
    (:class:`FirefoxInstallDialog`). If the install fails, the dialog
    surfaces the captured subprocess log so the failure cause is
    diagnosable; the surrounding loop offers a retry/quit choice.
    """
    if _check_playwright_browsers():
        return True

    from PySide6.QtWidgets import QMessageBox
    from .components.firefox_install_dialog import FirefoxInstallDialog

    while True:
        confirm = QMessageBox.question(
            None, "MeManga — Browser Required",
            "MeManga needs Firefox and Chromium browser components to "
            "scrape manga.\n\n"
            "Download now? (~250 MB, requires internet)",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            quit_answer = QMessageBox.question(
                None, "MeManga",
                "MeManga cannot work without browser components.\n\nQuit?",
            )
            if quit_answer == QMessageBox.StandardButton.Yes:
                sys.exit(0)
            continue

        dlg = FirefoxInstallDialog()
        ok, error_text = dlg.run_install()
        if ok:
            return True

        # The dialog already surfaced the captured log in its own UI;
        # offer a retry-or-quit choice and loop.
        detail = (error_text or "unknown error")[:1200]
        retry = QMessageBox.question(
            None, "Installation Failed",
            "Browser installation failed.\n\n"
            "Check your internet connection and try again.\n\n"
            "You can also install manually with:\n"
            "    playwright install firefox chromium\n\n"
            f"--- details ---\n{detail}",
        )
        if retry != QMessageBox.StandardButton.Yes:
            sys.exit(0)


def _load_app_icon():
    """Return a multi-resolution :class:`QIcon` for the app, or ``None``.

    Looks up ``memanga/gui/assets/icon/icon-{32,64,128,256,512}.png``
    bundled alongside the package; works for both source installs and
    PyInstaller-frozen builds (PyInstaller stages the assets directory
    under ``sys._MEIPASS``).
    """
    from PySide6.QtGui import QIcon
    from pathlib import Path

    # When frozen, PyInstaller stages bundled data under sys._MEIPASS.
    # Source install: assets live next to this module.
    base = Path(getattr(sys, "_MEIPASS", "")) if _is_frozen() else None
    candidates = []
    if base is not None:
        candidates.append(base / "memanga" / "gui" / "assets" / "icon")
    candidates.append(Path(__file__).resolve().parent / "assets" / "icon")

    icon_dir = next((c for c in candidates if c.exists()), None)
    if icon_dir is None:
        return None

    icon = QIcon()
    found = False
    # Adding multiple sizes lets Qt pick the sharpest for the task bar
    # / dock / window title / about box without resampling. addFile
    # detects the native size from the PNG itself.
    for size in (16, 32, 48, 64, 128, 256, 512):
        p = icon_dir / f"icon-{size}.png"
        if p.exists():
            icon.addFile(str(p))
            found = True
    return icon if found else None


def _set_windows_app_user_model_id():
    """Tell Windows this process is its own application identity so
    the taskbar groups it under our custom icon rather than the
    default Python launcher icon.

    Without an explicit AppUserModelID, a PyInstaller-frozen Qt app
    on Windows inherits the python.exe AppID and the taskbar shows
    the generic Python feather even when the window itself has a
    custom QIcon set. No-op on non-Windows.
    """
    import os
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MeManga.MeManga.GUI.1"
        )
    except Exception:
        pass


# Issue #226: the windowed entry (gui/__main__.py) opens runtime.log in
# the config folder it selected, under that folder's lock, and registers
# how to move both to the folder the window ends up locking, should
# another process have moved the legacy folder in between (#249).
_runtime_log_mover = None


def set_runtime_log_mover(mover) -> None:
    """Register ``mover(config_dir)``; ``None`` removes it."""
    global _runtime_log_mover
    _runtime_log_mover = mover


def _follow_runtime_log(config_dir) -> None:
    """Keep runtime.log, and its lock, with the folder the window locked."""
    mover = _runtime_log_mover
    if mover is None:
        return
    try:
        mover(config_dir)
    except Exception:
        # A diagnostic log must never stop the window from opening.
        logger.exception("Could not move runtime.log to %s", config_dir)


def _lock_problem(error):
    """Dialog text for a config directory the GUI could not lock (#244)."""
    from ..process_lock import ConfigDirBusy
    if isinstance(error, ConfigDirBusy):
        return (
            "MeManga is already running for this library:\n"
            f"{error.config_dir}\n\n"
            "Another window, a running check or another memanga command "
            "is using it. Close it or wait for it to finish, then start "
            "MeManga again."
        )
    return (
        f"MeManga could not lock its folder:\n{error.config_dir}\n\n"
        f"{error.error.strerror or error.error}\n\n"
        "MeManga needs a folder on a file system that supports file locks."
    )


def _startup_problem(config, state):
    """Message for a config or state file the GUI cannot run on, or None.

    Issue #243: the window used to crash on a broken config.yaml, and a
    state file that cannot be loaded must not be overwritten.
    """
    if config.load_error:
        return (
            f"MeManga could not load its config file:\n{config.config_path}"
            f"\n\n{config.load_error}\n\n"
            "Fix or move the file, then start MeManga again."
        )
    if state.load_error:
        return (
            f"MeManga could not load its state file:\n\n{state.load_error}"
            "\n\nFix or move the file, then start MeManga again."
        )
    return None


def _ensure_logging() -> None:
    """Give a direct start the same redacting log setup as the others.

    ``memanga --gui`` and ``python -m memanga.gui`` (and the frozen
    builds) configure logging before calling :func:`launch_gui`; the
    ``memanga-gui`` script and other direct callers did not, so records
    went out through Python's fallback handler without
    :class:`memanga.output.RedactingFormatter` and printed URL
    credentials, tokens and passwords as they were (issue #342). Setup
    done by a caller wins: its level, log file and handlers are kept, and
    no second set of handlers is added.
    """
    from ..output import configure_logging, logging_configured, resolve_log_level
    if logging_configured():
        return
    # Same defaults as the module entry point (gui/__main__.py).
    configure_logging(resolve_log_level(default=logging.INFO), timestamps=True)


def launch_gui(config=None, state=None, explicit_config_dir=None):
    """Launch the MeManga GUI application.

    ``config`` and ``state`` are the already loaded objects when the CLI
    starts the GUI; otherwise they are loaded here, in the directory the
    CLI would select (issue #249): ``explicit_config_dir``, else
    ``$MEMANGA_CONFIG_DIR``, else the platform default.
    ``explicit_config_dir`` is the directory chosen with ``--config-dir``
    or ``$MEMANGA_CONFIG_DIR`` (None for the default), so the daily check
    set up from Settings runs on the same directory.
    """
    # Before anything can log, imports included (issue #342).
    _ensure_logging()

    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer
    from .app import MeMangaApp
    from . import theme as T
    from ..config import (Config, default_config_dir, default_root_moved,
                          explicit_config_dir as _explicit)
    from ..process_lock import ConfigDirBusy, ConfigDirLock, ConfigDirLockError
    from ..state import State

    # Must run before QApplication() so the taskbar honours our icon.
    _set_windows_app_user_model_id()

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")

    # Apply the persisted theme (dark by default). Switching themes from
    # Settings re-runs T.apply(qapp) without a restart.
    T.apply(qapp)

    # Set the app icon globally — covers the window title bar, dock /
    # task bar entry, and the About dialog without any per-window
    # plumbing. setWindowIcon on QApplication is the global fallback;
    # individual top-level windows inherit it (and MeMangaApp also
    # re-applies it on its own window for the Windows edge case).
    app_icon = _load_app_icon()
    if app_icon is not None:
        qapp.setWindowIcon(app_icon)

    # Issue #244: the window keeps config and state loaded and saves
    # them for the whole session, so it holds the config directory lock
    # until the process exits. Taken before loading; under `memanga --gui`
    # the CLI already holds it and this only joins that lock.
    if config is not None:
        config_dir = config.config_dir
    else:
        explicit_config_dir = _explicit(explicit_config_dir)
        config_dir = explicit_config_dir or default_config_dir()
    def _lock(directory):
        lock = ConfigDirLock(directory)
        try:
            lock.acquire()
        except (ConfigDirBusy, ConfigDirLockError) as e:
            QMessageBox.critical(None, "MeManga", _lock_problem(e))
            sys.exit(1)
        return lock

    lock = _lock(config_dir)
    # Issue #249: another process may have moved the legacy folder to the
    # platform folder between default_config_dir() and the lock, so this
    # lock is on a recreated, empty legacy folder. Switch to the platform
    # folder before loading anything, as the CLI does.
    if config is None and explicit_config_dir is None and default_root_moved(config_dir):
        lock.release()
        moved_from = config_dir
        config_dir = default_config_dir()
        if default_root_moved(config_dir):
            QMessageBox.critical(
                None, "MeManga",
                f"MeManga's folder was just moved from:\n{moved_from}\n\n"
                "Nothing was changed. Start MeManga again.")
            sys.exit(1)
        lock = _lock(config_dir)
    _follow_runtime_log(config_dir)

    if config is None:
        config = Config(config_dir, tolerate_errors=True)
    if state is None:
        state = State(config_dir)
    problem = _startup_problem(config, state)
    if problem:
        QMessageBox.critical(None, "MeManga", problem)
        sys.exit(1)

    _ensure_browsers()

    window = MeMangaApp(config=config, app_state=state,
                        explicit_config_dir=explicit_config_dir)
    # NOTE: don't subscribe `lambda: T.apply(qapp)` here.
    # `T.set_theme(name, qapp)` already calls `apply(qapp)` BEFORE
    # notifying subscribers, so a re-subscribed apply() would run a
    # full QSS+palette+polish pass twice per theme switch — the
    # noticeable freeze the user was seeing.
    window.show()
    if state.recovery_notice:
        notice = state.recovery_notice
        QTimer.singleShot(
            0, lambda: QMessageBox.warning(window, "MeManga", notice))
    sys.exit(qapp.exec())
