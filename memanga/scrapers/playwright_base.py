"""
Base class for Playwright-based scrapers with stealth mode.

Uses ThreadPoolExecutor to run Playwright sync API in a separate thread,
avoiding conflicts with asyncio event loops (e.g., from rich library).
"""

import time
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import threading
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Thread-local storage for browser instances
_thread_local = threading.local()


def cleanup_browsers():
    """Close all thread-local Playwright browser instances."""
    if hasattr(_thread_local, 'context'):
        try:
            _thread_local.context.close()
        except Exception:
            pass
        del _thread_local.context

    if hasattr(_thread_local, 'browser'):
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        del _thread_local.browser

    if hasattr(_thread_local, 'playwright'):
        try:
            _thread_local.playwright.stop()
        except Exception:
            pass
        del _thread_local.playwright


class PlaywrightScraper(BaseScraper):
    """Base class for scrapers that need Playwright with stealth mode."""

    # NOTE: do NOT define `_executor`/`_executor_lock` on this base class.
    # `__init_subclass__` below gives every subclass its OWN dedicated pair
    # so WeebCentral, Comick, MangaKatana, MangaClash, MangaHere etc.
    # can run their search/get_chapters/get_pages calls in PARALLEL inside
    # the search worker's 8-slot pool.
    #
    # A single shared `ThreadPoolExecutor(max_workers=1)` on the base
    # class would serialise every Playwright-based source through one
    # browser thread — with 5+ such sources in the popular set, the
    # slow ones starve the rest and the search appears to hang.

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Skip if a subclass explicitly defines its own executor (e.g.
        # MangaFire's VRFGenerator pattern). Only create one when the
        # subclass would otherwise fall back to a shared one.
        if "_executor" not in cls.__dict__:
            cls._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"pw-{cls.__name__}",
            )
        if "_executor_lock" not in cls.__dict__:
            cls._executor_lock = threading.Lock()

    @classmethod
    def _run_serialized(cls, fn, *args, timeout: float, **kwargs):
        """Submit ``fn`` to this class's dedicated executor under its lock.

        ``Future.result(timeout=N)`` measures wall-clock from the ``submit``
        call, which means a queued task can blow its budget while waiting
        for the prior task to finish — a real bug when downloading many
        chapters in parallel. Holding the lock around submit + wait
        guarantees the timeout reflects actual work time only.
        """
        with cls._executor_lock:
            future = cls._executor.submit(fn, *args, **kwargs)
            return future.result(timeout=timeout)

    def _get_browser_in_thread(self):
        """Get or create the thread-local browser.

        ATOMIC: if `firefox.launch()` fails, we don't leave a half-
        initialised `_thread_local` behind. The old code set
        `_thread_local.playwright = sync_playwright().start()` first,
        and if the next line (`firefox.launch(...)`) raised, the next
        call to this function would see `hasattr(_thread_local,
        'playwright')` → True, skip the init block, and crash on
        `return _thread_local.browser` with AttributeError. That
        cascading failure took out unrelated scrapers in the same
        worker thread.
        """
        # Hot path: everything already up.
        if (hasattr(_thread_local, 'browser')
                and hasattr(_thread_local, 'context')
                and hasattr(_thread_local, 'playwright')):
            return _thread_local.browser, _thread_local.context

        # Clear any dangling state from a previous partial init before
        # retrying — otherwise sync_playwright().start() raises
        # "already started" on the second attempt in this thread.
        cleanup_browsers()

        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser = pw.firefox.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            )
        except Exception:
            # Roll back the Playwright start so the next call can retry
            # cleanly instead of inheriting half-broken state.
            try:
                pw.stop()
            except Exception:
                pass
            raise

        # Commit all three at once — never leave half-set thread-local.
        _thread_local.playwright = pw
        _thread_local.browser = browser
        _thread_local.context = context
        return browser, context

    def _fetch_page_content(self, url: str, wait_time: int = 2000, cookies: list = None) -> str:
        """Internal: fetch page content (runs in thread) with retry."""
        from playwright_stealth import Stealth

        last_error = None
        for attempt in range(1, 4):
            browser, context = self._get_browser_in_thread()
            page = context.new_page()
            try:
                Stealth().apply_stealth_sync(page)

                if cookies:
                    context.add_cookies(cookies)

                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                if wait_time > 0:
                    page.wait_for_timeout(wait_time)

                return page.content()
            except Exception as e:
                last_error = e
                if attempt < 3:
                    delay = attempt * 2
                    logger.debug(f"Playwright fetch attempt {attempt}/3 failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
            finally:
                page.close()

        raise last_error

    def _get_page_content(self, url: str, wait_time: int = 2000, cookies: list = None) -> str:
        """
        Get page content using Playwright with stealth.
        Runs in a separate thread to avoid asyncio conflicts.

        Args:
            url: URL to fetch
            wait_time: Extra wait time in ms after load
            cookies: Optional list of cookies to set
        """
        return self._run_serialized(
            self._fetch_page_content, url, wait_time, cookies, timeout=60,
        )

    def _run_js_in_thread(self, url: str, script: str, wait_time: int = 2000):
        """Internal: execute JS on page (runs in thread) with retry."""
        from playwright_stealth import Stealth

        last_error = None
        for attempt in range(1, 4):
            browser, context = self._get_browser_in_thread()
            page = context.new_page()
            try:
                Stealth().apply_stealth_sync(page)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                if wait_time > 0:
                    page.wait_for_timeout(wait_time)

                return page.evaluate(script)
            except Exception as e:
                last_error = e
                if attempt < 3:
                    delay = attempt * 2
                    logger.debug(f"Playwright JS attempt {attempt}/3 failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
            finally:
                page.close()

        raise last_error

    def _execute_js(self, url: str, script: str, wait_time: int = 2000):
        """
        Execute JavaScript on a page and return result.
        Runs in a separate thread to avoid asyncio conflicts.

        Args:
            url: URL to navigate to
            script: JavaScript to execute
            wait_time: Wait time before executing
        """
        return self._run_serialized(
            self._run_js_in_thread, url, script, wait_time, timeout=60,
        )

    @classmethod
    def cleanup(cls):
        """Cleanup browser instances in every subclass's executor thread.

        Each PlaywrightScraper subclass owns its own executor (see
        `__init_subclass__`), so a single base-class cleanup would
        miss the real per-subclass browsers. Walk the subclass tree
        and run cleanup_browsers in each dedicated thread.
        """
        seen: set = set()
        def _walk(c):
            for sub in c.__subclasses__():
                if sub in seen:
                    continue
                seen.add(sub)
                if "_executor" in sub.__dict__:
                    try:
                        sub._run_serialized(cleanup_browsers, timeout=10)
                    except Exception:
                        pass
                _walk(sub)
        _walk(cls)
