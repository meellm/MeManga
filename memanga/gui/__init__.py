"""
MeManga GUI - CustomTkinter-based graphical interface.
"""


def _is_frozen():
    """Check if running inside a PyInstaller bundle."""
    import sys
    return getattr(sys, 'frozen', False)


def _check_playwright_browsers():
    """Check if Playwright Firefox browser binary exists on disk."""
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
    """Run playwright install firefox. Returns True on success."""
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
        import sys
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "firefox"],
                capture_output=True, text=True, timeout=300,
            )
            return result.returncode == 0
        except Exception:
            pass
    return False


def _ensure_browsers(app):
    """Ensure Playwright Firefox is installed. Blocks until installed or user quits."""
    # Already installed — nothing to do
    if _check_playwright_browsers():
        return True

    from tkinter import messagebox
    import sys

    while True:
        answer = messagebox.askyesno(
            "MeManga - Browser Required",
            "MeManga needs Firefox browser components to scrape manga.\n\n"
            "Download now? (~150 MB, requires internet)",
        )

        if not answer:
            # User said No — can't run without browsers
            quit_answer = messagebox.askyesno(
                "MeManga",
                "MeManga cannot work without browser components.\n\n"
                "Quit the application?",
            )
            if quit_answer:
                app.destroy()
                sys.exit(0)
            # User chose not to quit — loop back and ask again
            continue

        # User said Yes — try to install
        # Show a "please wait" info (non-blocking isn't possible with messagebox,
        # so just run the install and show result after)
        installed = _install_playwright_browsers()

        if installed:
            messagebox.showinfo("Success", "Browser components installed successfully!")
            return True

        # Install failed — let user retry or quit
        retry = messagebox.askretrycancel(
            "Installation Failed",
            "Browser installation failed.\n\n"
            "Make sure you have an internet connection and try again.\n\n"
            "You can also install manually:\n"
            "  playwright install firefox",
        )
        if not retry:
            app.destroy()
            sys.exit(0)
        # retry=True → loop back


def launch_gui():
    """Launch the MeManga GUI application."""
    from .app import MeMangaApp
    app = MeMangaApp()

    # Ensure browsers are installed — blocks until done or user quits
    _ensure_browsers(app)

    app.mainloop()
