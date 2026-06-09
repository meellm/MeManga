"""
MeManga GUI - PySide6-based graphical interface.
"""

import sys


def _is_frozen():
    return getattr(sys, 'frozen', False)


def _check_playwright_browsers():
    """True only when a Firefox build matching the *bundled* Playwright
    package's expected revision is installed on disk.

    A "is there ANY firefox-* directory under ms-playwright?" check is
    too lenient — an older Firefox build from a previous Playwright
    install (e.g. ``firefox-1466``) satisfies it, then every
    Playwright-based scraper crashes at runtime when the newer bundled
    Playwright tries to launch a different build (``firefox-1522``).
    AJAX-only paths like MangaFire's chapter list keep working, which
    produces a confusing "some sources work, others don't" pattern.

    Ask Playwright itself where it expects Firefox to live and check
    that exact path. Slightly slower at startup (~200 ms for the
    Playwright import) but correctness over speed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            try:
                expected = pw.firefox.executable_path
            except Exception:
                # `executable_path` is a property on BrowserType that
                # raises if the binary is missing on older Playwright
                # versions — treat that as "not installed".
                return False
            if not expected:
                return False
            from pathlib import Path
            return Path(expected).exists()
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

    # Strategy 1: bundled driver (node + cli.js). compute_driver_executable
    # returns a (node_path, cli_js_path) tuple on playwright >= 1.40; the
    # tuple must be unpacked into argv, not stringified, or the spawn
    # raises FileNotFoundError.
    try:
        from playwright._impl._driver import compute_driver_executable
        driver = compute_driver_executable()
        if isinstance(driver, tuple) and len(driver) == 2:
            node_path, cli_path = driver
            yield "bundled driver", [node_path, cli_path, "install", "firefox"]
        else:
            # Back-compat for older Playwright (single string).
            yield "bundled driver", [str(driver), "install", "firefox"]
    except Exception as e:  # pragma: no cover - import-time guard
        yield "bundled driver", _ImportError(f"import failed: {e}")

    # Strategy 2: system-installed `playwright` CLI (dev machines).
    playwright_bin = shutil.which("playwright")
    if playwright_bin:
        yield "system cli", [playwright_bin, "install", "firefox"]

    # Strategy 3: python -m playwright install (source-only, not frozen).
    if not _is_frozen():
        yield "python -m", [sys.executable, "-m", "playwright", "install", "firefox"]


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
    """Ensure Playwright Firefox is installed.

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
            "MeManga needs Firefox browser components to scrape manga.\n\n"
            "Download now? (~90 MB, requires internet)",
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
            "    playwright install firefox\n\n"
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


def launch_gui():
    """Launch the MeManga GUI application."""
    from PySide6.QtWidgets import QApplication
    from .app import MeMangaApp
    from . import theme as T

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

    _ensure_browsers()

    window = MeMangaApp()
    # NOTE: don't subscribe `lambda: T.apply(qapp)` here.
    # `T.set_theme(name, qapp)` already calls `apply(qapp)` BEFORE
    # notifying subscribers, so a re-subscribed apply() would run a
    # full QSS+palette+polish pass twice per theme switch — the
    # noticeable freeze the user was seeing.
    window.show()
    sys.exit(qapp.exec())
