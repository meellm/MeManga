"""
DandadanAnim Scraper - w1.dandadananim.com

Dandadan dedicated site with mangageko.com CDN.
WordPress-based manga reader.
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class DandadanAnimScraper(BaseScraper):
    """Scraper for w1.dandadananim.com"""
    
    BASE_URL = "https://w1.dandadananim.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns Dandadan if matching."""
        results = []
        query_lower = query.lower()
        
        if "dandadan" in query_lower or "ddd" in query_lower or "okarun" in query_lower or "momo" in query_lower:
            results.append(Manga(
                title="Dandadan",
                url=f"{self.BASE_URL}/",
                cover_url=f"{self.BASE_URL}/wp-content/uploads/2024/12/cropped-cropped-ddd529ac-d84e-4d55-b808-c83b41c9dc75.jpg"
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list for Dandadan."""
        chapters = []
        
        resp = self.session.get(manga_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find chapter links
        pattern = re.compile(r'/manga/dandadan-chapter-(\d+)/?$')
        
        seen = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            match = pattern.search(href)
            if match:
                chapter_num = match.group(1)
                if chapter_num not in seen:
                    seen.add(chapter_num)
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=f"Chapter {chapter_num}",
                        url=href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    ))
        
        # Generate remaining chapters if list is incomplete
        if chapters:
            max_found = max(float(c.number) for c in chapters)
            existing_nums = {c.number for c in chapters}
            for i in range(1, int(max_found)):
                if str(i) not in existing_nums:
                    chapters.append(Chapter(
                        number=str(i),
                        title=f"Chapter {i}",
                        url=f"{self.BASE_URL}/manga/dandadan-chapter-{i}/"
                    ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs for a chapter."""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        pages = []
        seen = set()
        
        # Primary: Find images from cdn.mangageko.com
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "cdn.mangageko.com" in src and src not in seen:
                seen.add(src)
                pages.append(src)
        
        # Also check data-src for lazy loading
        for img in soup.find_all("img", {"data-src": True}):
            src = img["data-src"]
            if "cdn.mangageko.com" in src and src not in seen:
                seen.add(src)
                pages.append(src)
        
        # Fallback: wp-content images
        if not pages:
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if "wp-content/uploads" in src and src not in seen:
                    # Skip logo/icon images
                    if any(x in src.lower() for x in ["logo", "icon", "favicon", "cropped-"]):
                        continue
                    if "coming-soon" not in src.lower():
                        seen.add(src)
                        pages.append(src)
        
        return pages
