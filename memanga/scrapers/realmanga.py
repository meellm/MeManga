"""Real Manga Online scraper - Real by Takehiko Inoue (wheelchair basketball manga)."""

import re
import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class RealMangaScraper(BaseScraper):
    """Scraper for real-manga.online (Real by Takehiko Inoue)."""
    
    SOURCE = "real-manga.online"
    BASE_URL = "https://real-manga.online"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga. This site only has Real."""
        results = []
        
        try:
            resp = self.session.get(self.BASE_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Extract the main manga info
            title = "Real"
            
            # Check if query matches
            if query.lower() in title.lower() or query.lower() in "takehiko inoue" or query.lower() in "wheelchair basketball":
                results.append(Manga(
                    title="Real",
                    url=self.BASE_URL,
                    cover_url="https://laiond.com/images/GTFDWKhZTtnQMjYQlQNuTTXc96A5sa1703173161.jpg",
                ))
        except Exception as e:
            logger.error(f"Search error: {e}")
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list from the homepage."""
        chapters = []
        
        try:
            resp = self.session.get(self.BASE_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find all chapter links
            # Pattern: https://real-manga.online/manga/real-chapter-N/
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "/manga/real-chapter-" in href:
                    # Extract chapter number from URL
                    match = re.search(r"real-chapter-(\d+(?:\.\d+)?(?:-\d+)?)", href)
                    if match:
                        ch_num = match.group(1)
                        # Handle special cases like "1-2" (chapter 1 version 2)
                        ch_num = ch_num.replace("-", ".")
                        
                        # Skip duplicates
                        if any(c.url == href for c in chapters):
                            continue
                        
                        title = link.get_text(strip=True) or f"Chapter {ch_num}"
                        
                        chapters.append(Chapter(
                            number=ch_num,
                            title=title,
                            url=href,
                        ))
            
            # Sort by chapter number (ascending)
            chapters = sorted(chapters, key=lambda c: float(c.number.split(".")[0]) if c.number else 0)
            
        except Exception as e:
            logger.error(f"Error getting chapters: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs from a chapter."""
        pages = []
        
        try:
            resp = self.session.get(chapter_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find all images in <p> tags (WordPress Comic Easel pattern)
            for p in soup.find_all("p"):
                for img in p.find_all("img"):
                    src = img.get("src", "")
                    if src and "laiond.com" in src:
                        if src not in pages:
                            pages.append(src)
            
            # Also check for lazy-loaded images
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src and "laiond.com" in src:
                    if src not in pages:
                        pages.append(src)
            
        except Exception as e:
            logger.error(f"Error getting pages: {e}")
        
        return pages
    
    def download_image(self, url: str) -> bytes:
        """Download an image with proper headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        
        resp = self.session.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.content
