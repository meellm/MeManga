"""
Mangakatana scraper - Uses Playwright to bypass Cloudflare
https://mangakatana.com

Uses ThreadPoolExecutor to avoid asyncio conflicts with rich library.
"""

import re
import threading
from typing import List, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from .base import BaseScraper, Chapter, Manga


# Thread-local storage for browser instances
_thread_local = threading.local()


class MangakatanataScraper(BaseScraper):
    """Scraper for Mangakatana using Playwright."""
    
    name = "mangakatana"
    base_url = "https://mangakatana.com"
    
    # Shared thread pool for Playwright operations
    _executor = ThreadPoolExecutor(max_workers=1)
    
    def __init__(self):
        super().__init__()
    
    def _get_browser_in_thread(self):
        """Get or create browser instance in the current thread."""
        if not hasattr(_thread_local, 'mk_playwright'):
            from playwright.sync_api import sync_playwright
            _thread_local.mk_playwright = sync_playwright().start()
            _thread_local.mk_browser = _thread_local.mk_playwright.firefox.launch(headless=True)
        return _thread_local.mk_browser
    
    def _fetch_page_content(self, url: str) -> str:
        """Internal: fetch page content (runs in thread)."""
        browser = self._get_browser_in_thread()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            page.close()
    
    def _get_page_content(self, url: str) -> str:
        """Get page content using Playwright (thread-safe)."""
        future = self._executor.submit(self._fetch_page_content, url)
        return future.result(timeout=60)
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header for Mangakatana."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://mangakatana.com/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            from pathlib import Path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/?search={query.replace(' ', '+')}&search_by=book_name"
        html = self._get_page_content(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".item"):
            title_el = item.select_one(".title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            manga_url = title_el.get("href", "")
            
            cover_el = item.select_one("img")
            cover_url = cover_el.get("src") if cover_el else None
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        for row in soup.select(".chapters tbody tr"):
            link = row.select_one("a")
            if not link:
                continue
            
            chapter_url = link.get("href", "")
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            chapter_num = match.group(1) if match else chapter_text
            
            # Get title if exists
            title = None
            title_span = row.select_one(".chapter-title")
            if title_span:
                title = title_span.get_text(strip=True)
            
            # Get date
            date = None
            date_el = row.select_one(".update_time")
            if date_el:
                date = date_el.get_text(strip=True)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=title,
                url=chapter_url,
                date=date,
            ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Method 1: Images in reading area
        for img in soup.select("#imgs img"):
            src = img.get("data-src") or img.get("src")
            if src and not src.endswith("loading.gif"):
                pages.append(src)
        
        # Method 2: Script array
        if not pages:
            import json
            for script in soup.find_all("script"):
                text = script.string or ""
                if "ytaw" in text or "data_url" in text:
                    # Extract image URLs from JavaScript
                    urls = re.findall(r'https?://[^\s"\',]+\.(?:jpg|png|webp)', text)
                    pages.extend(urls)
        
        return pages
