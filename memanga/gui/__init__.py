"""
MeManga GUI - CustomTkinter-based graphical interface.
"""


def _is_frozen():
    """Check if running inside a PyInstaller bundle."""
    import sys
    return getattr(sys, 'frozen', False)


def _check_playwright_browsers():
    """Check if Playwright Firefox browser binary exists (without launching it)."""
    try:
        import subprocess
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--dry-run", "firefox"],
            capture_output=True, text=True, timeout=10,
        )
        # If dry-run exits 0, browsers are already installed
        return result.returncode == 0
    except Exception:
        pass
    # Fallback: check the registry directly
    try:
        from playwright._impl._driver import compute_driver_executable
        driver_exec = compute_driver_executable()
        import subprocess
        result = subprocess.run(
            [str(driver_exec), "install", "--dry-run", "firefox"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        pass
    # Final fallback: try importing and checking browser path
    try:
        from pathlib import Path
        import os
        # Playwright stores browsers in a well-known location
        if os.name == 'nt':
            browsers_path = Path.home() / "AppData" / "Local" / "ms-playwright"
        else:
            browsers_path = Path.home() / ".cache" / "ms-playwright"
        if browsers_path.exists():
            firefox_dirs = [d for d in browsers_path.iterdir() if 'firefox' in d.name.lower()]
            return len(firefox_dirs) > 0
    except Exception:
        pass
    return False


def _install_playwright_browsers():
    """Run playwright install firefox using the playwright CLI directly."""
    import subprocess
    import shutil
    # Try using 'playwright' CLI from PATH first
    playwright_bin = shutil.which("playwright")
    if playwright_bin:
        try:
            result = subprocess.run(
                [playwright_bin, "install", "firefox"],
                capture_output=True, text=True, timeout=300,
            )
            return result.returncode == 0
        except Exception:
            pass
    # Try using the bundled playwright driver
    try:
        from playwright._impl._driver import compute_driver_executable
        driver_exec = compute_driver_executable()
        result = subprocess.run(
            [str(driver_exec), "install", "firefox"],
            capture_output=True, text=True, timeout=300,
        )
        return result.returncode == 0
    except Exception:
        pass
    # Last resort: try 'python -m playwright' (won't work in frozen .exe)
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


def launch_gui():
    """Launch the MeManga GUI application."""
    import customtkinter as ctk

    # Check for Playwright browsers before starting
    if not _check_playwright_browsers():
        # Show a simple dialog asking to install
        root = ctk.CTk()
        root.withdraw()

        from tkinter import messagebox
        answer = messagebox.askyesno(
            "MeManga - First Run Setup",
            "Manga scraping requires browser components (Firefox).\n\n"
            "Download now? (~150 MB, requires internet)\n\n"
            "You can also run later:\n"
            "  playwright install firefox",
        )
        root.destroy()

        if answer:
            print("Installing Playwright Firefox browser...")
            if _install_playwright_browsers():
                print("Browser installed successfully!")
            else:
                print("Browser installation failed. Some scrapers may not work.")
                print("Run manually: playwright install firefox")

    from .app import MeMangaApp
    app = MeMangaApp()
    app.mainloop()
