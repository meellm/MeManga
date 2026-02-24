"""Tomie Manga scraper (Junji Ito)."""

import re
import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List
import logging

logger = logging.getLogger(__name__)


class TomieScraper(BaseScraper):
    """Scraper for tomie-manga.com (mangarchive.com CDN)."""
    
    SOURCE = "tomie-manga.com"
    BASE_URL = "https://w12.tomie-manga.com"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga. This site only has Tomie."""
        results = []
        
        query_lower = query.lower()
        keywords = ["tomie", "junji ito", "junji", "ito", "horror manga"]
        
        if any(kw in query_lower for kw in keywords):
            results.append(Manga(
                title="Tomie",
                url=self.BASE_URL,
                cover_url="https://img.mangarchive.com/images/Tomie/zRmniOlt9ZA3OkOJvKZOISesleslGS1750519535.webp",
                description="Horror manga by Junji Ito about an immortal girl who drives men to obsession and murder."
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
                if "/manga/tomie-chapter-" in href and href not in seen_urls:
                    seen_urls.add(href)
                    
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
            
            # Find all mangarchive.com images
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "mangarchive.com" in src:
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
