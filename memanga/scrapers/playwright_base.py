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

    # Shared thread pool for all Playwright operations.
    # max_workers=1 keeps a single browser instance per process (memory),
    # but means submitted tasks queue serially. Pair with _executor_lock so
    # callers wait OUTSIDE the timeout window — see `_run_serialized`.
    _executor = ThreadPoolExecutor(max_workers=1)
    _executor_lock = threading.Lock()

    @classmethod
    def _run_serialized(cls, fn, *args, timeout: float, **kwargs):
        """Submit ``fn`` to the shared executor under the class lock.

        ``Future.result(timeout=N)`` measures wall-clock from the ``submit``
        call, which means a queued task can blow its budget while waiting
        for the prior task to finish — a real bug when downloading many
        chapters in parallel. Holding the lock around submit + wait
        guarantees the timeout reflects actual work time only.

        Subclasses with their own ``_executor`` should also override
        ``_executor_lock`` so the pair stays consistent.
        """
        with cls._executor_lock:
            future = cls._executor.submit(fn, *args, **kwargs)
            return future.result(timeout=timeout)

    def _get_browser_in_thread(self):
        """Get or create browser instance in the current thread."""
        if not hasattr(_thread_local, 'playwright'):
            from playwright.sync_api import sync_playwright

            _thread_local.playwright = sync_playwright().start()
            # Use Firefox - better at bypassing bot detection than Chromium
            _thread_local.browser = _thread_local.playwright.firefox.launch(headless=True)
            _thread_local.context = _thread_local.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            )
        return _thread_local.browser, _thread_local.context

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
        """Cleanup browser instances in the executor thread."""
        try:
            cls._run_serialized(cleanup_browsers, timeout=10)
        except Exception:
            pass
