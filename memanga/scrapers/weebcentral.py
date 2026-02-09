"""
WeebCentral scraper - Hybrid approach
- cloudscraper for chapters (bypass Cloudflare)
- Playwright for pages (JavaScript rendering needed)
https://weebcentral.com
"""

import re
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class WeebCentralScraper(BaseScraper):
    """Scraper for WeebCentral - hybrid cloudscraper + Playwright."""
    
    name = "weebcentral"
    base_url = "https://weebcentral.com"
    
    _browser = None
    _playwright = None
    _context = None
    
    def __init__(self):
        super().__init__()
        # Use cloudscraper for chapter listing
        import cloudscraper
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False}
        )
    
    def _get_browser(self):
        """Lazy-load Playwright Firefox for page rendering."""
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.firefox.launch(headless=True)
            self._context = self._browser.new_context()
        return self._browser
    
    def __del__(self):
        if self._context:
            try: self._context.close()
            except: pass
        if self._browser:
            try: self._browser.close()
            except: pass
        if self._playwright:
            try: self._playwright.stop()
            except: pass
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga using Quick Search dropdown."""
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright
        
        results = []
        
        try:
            browser = self._get_browser()
            page = browser.new_page()
            
            # Go to homepage
            page.goto(self.base_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2000)
            
            # Find and use the Quick Search input (top-right)
            search_input = page.locator('input[placeholder*="Quick Search"], input[type="search"]').first
            search_input.fill(query)
            
            # Wait for dropdown suggestions to appear
            page.wait_for_timeout(2000)
            
            # Get the dropdown results
            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find suggestion links (they appear in a dropdown near the search)
            for link in soup.select('a[href*="/series/"]'):
                href = link.get('href', '')
                if '/series/random' in href:
                    continue
                
                title = link.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                
                if not href.startswith('http'):
                    href = self.base_url + href
                
                # Check if title is relevant to query
                if query.lower() in title.lower() or title.lower() in query.lower():
                    results.append(Manga(title=title, url=href))
            
            page.close()
            
        except Exception as e:
            print(f"[WeebCentral] Search error: {e}")
        
        # Deduplicate
        seen = set()
        unique = []
        for m in results:
            if m.url not in seen:
                seen.add(m.url)
                unique.append(m)
        
        return unique[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters using cloudscraper (no JS needed)."""
        from bs4 import BeautifulSoup
        
        match = re.search(r'(/series/[^/]+)', manga_url)
        if match:
            chapter_list_url = self.base_url + match.group(1) + "/full-chapter-list"
        else:
            chapter_list_url = manga_url
        
        html = self._get_html(chapter_list_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        for link in soup.select("a[href*='/chapters/']"):
            chapter_url = link.get("href", "")
            if not chapter_url.startswith("http"):
                chapter_url = self.base_url + chapter_url
            
            span = link.select_one("span.grow span")
            chapter_text = span.get_text(strip=True) if span else link.get_text(strip=True)
            chapter_text = re.sub(r'Last Read.*$', '', chapter_text).strip()
            
            match = re.search(r'chapter[.\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', chapter_text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=chapter_text,
                    url=chapter_url,
                ))
        
        seen = set()
        unique = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique.append(ch)
        
        return sorted(unique)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get pages using Playwright (JavaScript rendering required)."""
        self._get_browser()
        page = self._context.new_page()
        
        try:
            # Load homepage first to get cookies
            page.goto(self.base_url, timeout=30000)
            page.wait_for_timeout(2000)
            
            # Navigate to chapter
            page.goto(chapter_url, timeout=45000)
            page.wait_for_timeout(3000)
            
            # Scroll to trigger lazy loading
            for _ in range(10):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(500)
            
            # Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
            
            # Get all page images
            images = page.query_selector_all("img[alt*='Page'], main section img[src*='.png'], main section img[src*='.jpg']")
            
            pages = []
            for img in images:
                src = img.get_attribute("src")
                if src and "brand" not in src and "logo" not in src:
                    pages.append(src)
            
            return pages
            
        finally:
            page.close()
