"""
ReadJJKManga Scraper - readjujutsukaisenmanga.com

JJK dedicated site with main series + Jujutsu Kaisen Modulo (sequel).
WordPress-based with wp-content/uploads CDN.
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class ReadJJKMangaScraper(BaseScraper):
    """Scraper for readjujutsukaisenmanga.com"""
    
    BASE_URL = "https://readjujutsukaisenmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns predefined JJK results."""
        results = []
        query_lower = query.lower()
        
        # Main series
        if "jujutsu" in query_lower or "jjk" in query_lower or "kaisen" in query_lower:
            results.append(Manga(
                title="Jujutsu Kaisen",
                url=f"{self.BASE_URL}/jujutsu-kaisen-manga/",
                cover_url=f"{self.BASE_URL}/wp-content/uploads/2024/01/jujutsu-kaisen-cover.jpg"
            ))
        
        # Modulo (sequel)
        if "modulo" in query_lower or "jujutsu" in query_lower or "jjk" in query_lower or "sequel" in query_lower:
            results.append(Manga(
                title="Jujutsu Kaisen Modulo",
                url=f"{self.BASE_URL}/jujutsu-kaisen-modulo/",
                cover_url=f"{self.BASE_URL}/wp-content/uploads/2024/01/jjk-modulo-cover.jpg"
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list for a manga."""
        chapters = []
        
        # Determine if it's Modulo based on URL
        is_modulo = "modulo" in manga_url.lower()
        
        resp = self.session.get(manga_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find chapter links
        if is_modulo:
            pattern = re.compile(r'jujutsu-kaisen-modulo-chapter-(\d+)/?$')
        else:
            pattern = re.compile(r'jujutsu-kaisen-chapter-(\d+)/?$')
        
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
        
        # If no chapters found on index page, generate list
        if not chapters:
            # Generate based on known chapter counts
            max_ch = 271 if not is_modulo else 23
            for i in range(1, max_ch + 1):
                if is_modulo:
                    ch_url = f"{self.BASE_URL}/jujutsu-kaisen-modulo-chapter-{i}/"
                else:
                    ch_url = f"{self.BASE_URL}/jujutsu-kaisen-chapter-{i}/"
                chapters.append(Chapter(
                    number=str(i),
                    title=f"Chapter {i}",
                    url=ch_url
                ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs for a chapter."""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images in wp-content/uploads
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "wp-content/uploads" in src and src not in seen:
                # Skip logo, icon, and thumbnail images
                if any(x in src.lower() for x in ["logo", "icon", "favicon", "avatar", "cropped-"]):
                    continue
                # Only include chapter images
                if any(x in src.lower() for x in ["chapter", "page", "image-"]):
                    seen.add(src)
                    pages.append(src)
        
        # Also check data-src for lazy loading
        for img in soup.find_all("img", {"data-src": True}):
            src = img["data-src"]
            if "wp-content/uploads" in src and src not in seen:
                if any(x in src.lower() for x in ["logo", "icon", "favicon", "avatar", "cropped-"]):
                    continue
                if any(x in src.lower() for x in ["chapter", "page", "image-"]):
                    seen.add(src)
                    pages.append(src)
        
        return pages
