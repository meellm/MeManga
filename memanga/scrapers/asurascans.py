"""
Asura Scans scraper - Popular for manhwa/webtoons
https://asuracomic.net (domain changes frequently)
"""

import re
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class AsuraScansScraper(BaseScraper):
    """Scraper for Asura Scans."""
    
    name = "asurascans"
    base_url = "https://asuracomic.net"
    
    def __init__(self):
        super().__init__()
        self._browser = None
        self._playwright = None
    
    def _get_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.firefox.launch(headless=True)
        return self._browser
    
    def _get_page_content(self, url: str) -> str:
        browser = self._get_browser()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            page.close()
    
    def __del__(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/series?name={query.replace(' ', '+')}"
        html = self._get_page_content(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        for item in soup.select("[href*='/series/']"):
            manga_url = item.get("href", "")
            if not manga_url or "/series/random" in manga_url:
                continue
            if not manga_url.startswith("http"):
                manga_url = self.base_url + manga_url
            
            # Skip if already seen (avoid duplicates)
            if manga_url in seen_urls:
                continue
            
            # Get title from the link text or nested elements
            title = item.get_text(strip=True)
            if not title:
                title_el = item.select_one(".title, h3, h2, span")
                title = title_el.get_text(strip=True) if title_el else ""
            
            # Skip links without titles (icon links, etc.)
            if not title or len(title) < 2:
                continue
            
            seen_urls.add(manga_url)
            
            cover_el = item.select_one("img")
            cover_url = cover_el.get("src") or cover_el.get("data-src") if cover_el else None
            
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
        
        for link in soup.select("a[href*='/chapter-'], .chapter-item a, .chap-list a"):
            chapter_url = link.get("href", "")
            if not chapter_url.startswith("http"):
                chapter_url = self.base_url + chapter_url
            
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'ch[.\s-]*(\d+\.?\d*)', chapter_url, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', chapter_text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=chapter_text,
                    url=chapter_url,
                ))
        
        # Deduplicate
        seen = set()
        unique = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique.append(ch)
        
        return sorted(unique)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Find reader images
        for img in soup.select(".reading-content img, .chapter-content img, #readerarea img"):
            src = img.get("data-src") or img.get("src")
            if src and "logo" not in src.lower():
                pages.append(src)
        
        # Fallback: look for any large images
        if not pages:
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src") or ""
                # Filter for typical manga page patterns
                if re.search(r'\d+\.(jpg|jpeg|png|webp)', src, re.I):
                    pages.append(src)
        
        return pages
