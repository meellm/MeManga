"""Browser lifecycle for scrapers that drive a real browser.

Importing this module registers :func:`_cleanup_at_exit` to run at exit so
browser processes opened during a run are closed when the program exits.
"""

import atexit
# Imported first so its thread join is registered before our cleanup and,
# since these exit hooks run in reverse order, runs after it.
import concurrent.futures.thread  # noqa: F401
import sys
import threading


def restart_browsers():
    """Restart any browser instances to free memory."""
    try:
        from ..scrapers.mangafire import VRFGenerator
        VRFGenerator().restart()
    except Exception:
        pass

    try:
        from ..scrapers.playwright_base import PlaywrightScraper
        PlaywrightScraper.cleanup()
    except Exception:
        pass


def _cleanup_at_exit():
    """Clean up browser resources on exit.

    Issue #250: close only what was opened, without restart_browsers()'s
    MangaFire notice, which printed to stdout on every exit and broke
    `--json` output.

    Issue #253: only a scraper module this run imported can have opened a
    browser, so the others are skipped instead of being imported (with
    Playwright) just to exit.
    """
    mangafire = sys.modules.get("memanga.scrapers.mangafire")
    if mangafire is not None:
        try:
            mangafire.cleanup_mangafire()
        except Exception:
            pass

    playwright_base = sys.modules.get("memanga.scrapers.playwright_base")
    if playwright_base is not None:
        try:
            playwright_base.PlaywrightScraper.cleanup()
        except Exception:
            pass


# Issue #235: each browser is closed on its own worker thread, and the
# interpreter stops those threads before atexit callbacks run, so an
# atexit hook could close nothing. Run before the threads are joined
# instead, the way concurrent.futures does; plain atexit is only a
# fallback for an interpreter without that hook.
getattr(threading, "_register_atexit", atexit.register)(_cleanup_at_exit)
