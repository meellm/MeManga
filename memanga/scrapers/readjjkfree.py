"""
ReadJJKFree Scraper - readjujutsukaisenfree.com

Jujutsu Kaisen main series dedicated site.
WordPress Mangosm theme + wp-content/uploads CDN.
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class ReadJJKFreeScraper(BaseScraper):
    """Scraper for readjujutsukaisenfree.com"""
    
    BASE_URL = "https://readjujutsukaisenfree.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns JJK if matching."""
        results = []
        query_lower = query.lower()
        
        if "jujutsu" in query_lower or "jjk" in query_lower or "kaisen" in query_lower:
            results.append(Manga(
                title="Jujutsu Kaisen",
                url=f"{self.BASE_URL}/",
                cover_url=f"{self.BASE_URL}/wp-content/uploads/jjk-cover.webp"
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list for JJK."""
        chapters = []
        
        resp = self.session.get(manga_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find chapter links
        pattern = re.compile(r'/comic/jujutsu-kaisen-chapter-(\d+)/?$')
        
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
        
        # Generate chapters if not found on homepage
        if not chapters:
            for i in range(1, 272):  # JJK has 271 chapters
                chapters.append(Chapter(
                    number=str(i),
                    title=f"Chapter {i}",
                    url=f"{self.BASE_URL}/comic/jujutsu-kaisen-chapter-{i}/"
                ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs for a chapter."""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        pages = []
        seen = set()
        
        # Primary: planeptune.us CDN images
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "planeptune.us" in src and src not in seen:
                seen.add(src)
                pages.append(src)
        
        # Fallback: wp-content/uploads
        if not pages:
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if "wp-content/uploads" in src and src not in seen:
                    # Skip logo/icon images
                    if any(x in src.lower() for x in ["logo", "icon", "favicon", "mangosm", "cover"]):
                        continue
                    seen.add(src)
                    pages.append(src)
        
        return pages
