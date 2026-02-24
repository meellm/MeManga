"""Dorohedoro Online scraper."""

import re
import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List
import logging

logger = logging.getLogger(__name__)


class DorohedoroScraper(BaseScraper):
    """Scraper for dorohedoro.online (Blogger CDN)."""
    
    SOURCE = "dorohedoro.online"
    BASE_URL = "https://dorohedoro.online"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga. This site only has Dorohedoro."""
        results = []
        
        query_lower = query.lower()
        keywords = ["dorohedoro", "caiman", "nikaidou", "q hayashida", "hole"]
        
        if any(kw in query_lower for kw in keywords):
            results.append(Manga(
                title="Dorohedoro",
                url=self.BASE_URL,
                cover_url="https://dorohedoro.online/wp-content/uploads/2022/06/dorohedoro.jpg",
                description="Dark fantasy manga set in Hole, where magic users prey on the weak. Caiman hunts them to restore his memories."
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list from the homepage."""
        chapters = []
        seen_urls = set()
        
        try:
            resp = self.session.get(self.BASE_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find all chapter links
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "/manga/dorohedoro-chapter-" in href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number (handles X.5 chapters)
                    match = re.search(r"chapter-(\d+(?:-\d+)?)", href)
                    if match:
                        ch_num = match.group(1).replace("-", ".")
                        title = link.get_text(strip=True) or f"Chapter {ch_num}"
                        
                        chapters.append(Chapter(
                            number=ch_num,
                            title=title,
                            url=href,
                        ))
            
            # Sort by chapter number
            def sort_key(c):
                try:
                    return float(c.number)
                except:
                    return 0
            chapters = sorted(chapters, key=sort_key)
            
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
            
            # Find all Blogger CDN images
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "blogger.googleusercontent.com" in src or "blogspot.com" in src:
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
