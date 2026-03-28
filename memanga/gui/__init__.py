"""
MeManga GUI - CustomTkinter-based graphical interface.
"""


def _check_playwright_browsers():
    """Check if Playwright browsers are installed. Prompt to install if missing."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Try to find Firefox (used by scrapers)
            p.firefox.launch(headless=True).close()
        return True
    except Exception:
        return False


def _install_playwright_browsers():
    """Run playwright install firefox in a subprocess."""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "firefox"],
            capture_output=True, text=True, timeout=300,
        )
        return result.returncode == 0
    except Exception:
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
            "  python -m playwright install firefox",
        )
        root.destroy()

        if answer:
            print("Installing Playwright Firefox browser...")
            if _install_playwright_browsers():
                print("Browser installed successfully!")
            else:
                print("Browser installation failed. Some scrapers may not work.")
                print("Run manually: python -m playwright install firefox")

    from .app import MeMangaApp
    app = MeMangaApp()
    app.mainloop()
