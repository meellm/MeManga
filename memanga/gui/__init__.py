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
    import subprocess
    import shutil
    try:
        from playwright._impl._driver import compute_driver_executable
        driver_exec = compute_driver_executable()
        result = subprocess.run(
            [str(driver_exec), "install", "firefox"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    playwright_bin = shutil.which("playwright")
    if playwright_bin:
        try:
            result = subprocess.run(
                [playwright_bin, "install", "firefox"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
    if not _is_frozen():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "firefox"],
                capture_output=True, text=True, timeout=300,
            )
            return result.returncode == 0
        except Exception:
            pass
    return False


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

        installed = _install_playwright_browsers()

        if installed:
            QMessageBox.information(None, "Success", "Browser components installed!")
            return True

        retry = QMessageBox.question(
            None, "Installation Failed",
            "Browser installation failed.\n\n"
            "Make sure you have internet and try again.\n\n"
            "You can also install manually:\n  playwright install firefox",
        )
        if retry != QMessageBox.StandardButton.Yes:
            sys.exit(0)


def launch_gui():
    """Launch the MeManga GUI application."""
    from PySide6.QtWidgets import QApplication
    from .app import MeMangaApp
    from ..config import Config
    from . import theme as T

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")

    # Load theme preference from config
    config = Config()
    mode = config.get("gui.theme", "dark")
    T.apply_theme(mode)
    qapp.setStyleSheet(T.generate_stylesheet(mode))

    _ensure_browsers()

    window = MeMangaApp()
    window.show()
    sys.exit(qapp.exec())
