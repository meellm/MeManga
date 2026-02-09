"""
Base class for Playwright-based scrapers with stealth mode.

Uses ThreadPoolExecutor to run Playwright sync API in a separate thread,
avoiding conflicts with asyncio event loops (e.g., from rich library).
"""

from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import threading
from .base import BaseScraper


# Thread-local storage for browser instances
_thread_local = threading.local()


class PlaywrightScraper(BaseScraper):
    """Base class for scrapers that need Playwright with stealth mode."""
    
    # Shared thread pool for all Playwright operations
    _executor = ThreadPoolExecutor(max_workers=1)
    
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
        """Internal: fetch page content (runs in thread)."""
        from playwright_stealth import Stealth
        
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
        finally:
            page.close()
    
    def _get_page_content(self, url: str, wait_time: int = 2000, cookies: list = None) -> str:
        """
        Get page content using Playwright with stealth.
        Runs in a separate thread to avoid asyncio conflicts.
        
        Args:
            url: URL to fetch
            wait_time: Extra wait time in ms after load
            cookies: Optional list of cookies to set
        """
        future = self._executor.submit(self._fetch_page_content, url, wait_time, cookies)
        return future.result(timeout=60)
    
    def _run_js_in_thread(self, url: str, script: str, wait_time: int = 2000):
        """Internal: execute JS on page (runs in thread)."""
        from playwright_stealth import Stealth
        
        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        
        try:
            Stealth().apply_stealth_sync(page)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            if wait_time > 0:
                page.wait_for_timeout(wait_time)
            
            return page.evaluate(script)
        finally:
            page.close()
    
    def _execute_js(self, url: str, script: str, wait_time: int = 2000):
        """
        Execute JavaScript on a page and return result.
        Runs in a separate thread to avoid asyncio conflicts.
        
        Args:
            url: URL to navigate to
            script: JavaScript to execute
            wait_time: Wait time before executing
        """
        future = self._executor.submit(self._run_js_in_thread, url, script, wait_time)
        return future.result(timeout=60)
