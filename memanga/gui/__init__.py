"""
MeManga GUI - PySide6-based graphical interface.
"""

import sys


def _is_frozen():
    return getattr(sys, 'frozen', False)


def _check_playwright_browsers():
    from pathlib import Path
    import os
    if os.name == 'nt':
        browsers_path = Path.home() / "AppData" / "Local" / "ms-playwright"
    else:
        browsers_path = Path.home() / ".cache" / "ms-playwright"
    if browsers_path.exists():
        firefox_dirs = [d for d in browsers_path.iterdir()
                        if d.is_dir() and 'firefox' in d.name.lower()]
        return len(firefox_dirs) > 0
    return False


def _install_playwright_browsers():
    """Try every install strategy we know about.

    Returns ``(ok, error_text)``. ``error_text`` is a short human-readable
    string the caller can drop into a dialog so the user sees *why* the
    install failed instead of a generic "try again" message.
    """
    import os
    import subprocess
    import shutil

    errors: list[str] = []

    def _run(cmd, label):
        try:
            env = dict(os.environ)
            # Force the standard user cache dir so `_check_playwright_browsers`
            # on next launch finds the freshly-installed browser.
            env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, env=env,
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

    # Strategy 1: bundled driver (node + cli.js). compute_driver_executable
    # returns a (node_path, cli_js_path) tuple on playwright >= 1.40 —
    # previously we were passing str(tuple) as argv[0], which always
    # raised FileNotFoundError and got swallowed.
    try:
        from playwright._impl._driver import compute_driver_executable
        driver = compute_driver_executable()
        if isinstance(driver, tuple) and len(driver) == 2:
            node_path, cli_path = driver
            ok, _ = _run([node_path, cli_path, "install", "firefox"], "bundled driver")
        else:
            # Back-compat for older Playwright (single string).
            ok, _ = _run([str(driver), "install", "firefox"], "bundled driver")
        if ok:
            return True, ""
    except Exception as e:
        errors.append(f"[bundled driver] import failed: {e}")

    # Strategy 2: system-installed `playwright` CLI (dev machines).
    playwright_bin = shutil.which("playwright")
    if playwright_bin:
        ok, _ = _run([playwright_bin, "install", "firefox"], "system cli")
        if ok:
            return True, ""

    # Strategy 3: python -m playwright install (source-only, not frozen).
    if not _is_frozen():
        ok, _ = _run(
            [sys.executable, "-m", "playwright", "install", "firefox"],
            "python -m",
        )
        if ok:
            return True, ""

    return False, "\n".join(errors) if errors else "no install strategy available"


def _ensure_browsers():
    """Ensure Playwright Firefox is installed. Uses Qt message boxes."""
    if _check_playwright_browsers():
        return True

    from PySide6.QtWidgets import QMessageBox

    while True:
        answer = QMessageBox.question(
            None, "MeManga - Browser Required",
            "MeManga needs Firefox browser components to scrape manga.\n\n"
            "Download now? (~150 MB, requires internet)",
        )

        if answer != QMessageBox.StandardButton.Yes:
            quit_answer = QMessageBox.question(
                None, "MeManga",
                "MeManga cannot work without browser components.\n\nQuit?",
            )
            if quit_answer == QMessageBox.StandardButton.Yes:
                sys.exit(0)
            continue

        installed, error_text = _install_playwright_browsers()

        if installed:
            QMessageBox.information(None, "Success", "Browser components installed!")
            return True

        # Surface the actual error to the user — previously they got a
        # generic "try again" and had no idea whether it was a network
        # issue, missing driver, permission problem, or the tuple bug.
        detail = (error_text or "unknown error")[:1200]
        retry = QMessageBox.question(
            None, "Installation Failed",
            "Browser installation failed.\n\n"
            "Make sure you have internet and try again.\n\n"
            "You can also install manually:\n  playwright install firefox\n\n"
            f"--- details ---\n{detail}",
        )
        if retry != QMessageBox.StandardButton.Yes:
            sys.exit(0)


def launch_gui():
    """Launch the MeManga GUI application."""
    from PySide6.QtWidgets import QApplication
    from .app import MeMangaApp
    from . import theme as T

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")

    qapp.setStyleSheet(T.generate_stylesheet())

    _ensure_browsers()

    window = MeMangaApp()
    window.show()
    sys.exit(qapp.exec())
