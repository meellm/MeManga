"""Detective Conan Online scraper."""

import re
import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List
import logging

logger = logging.getLogger(__name__)


class DetectiveConanScraper(BaseScraper):
    """Scraper for detective-conan.online."""
    
    SOURCE = "detective-conan.online"
    BASE_URL = "https://detective-conan.online"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga. This site only has Detective Conan."""
        results = []
        
        query_lower = query.lower()
        keywords = ["conan", "detective", "meitantei", "case closed", "shinichi", "kudo"]
        
        if any(kw in query_lower for kw in keywords):
            results.append(Manga(
                title="Detective Conan",
                url=self.BASE_URL,
                cover_url="https://laiond.com/images/Detective%20Conan/WCEfvbOo1r9Z2Rlbi14Hl8NeBc1Gel1769518602.jpg",
                description="The adventures of Shinichi Kudo, a teenage detective who was turned into a child."
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
                if "/comic/detective-conan-chapter-" in href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number
                    match = re.search(r"chapter-(\d+(?:\.\d+)?)", href)
                    if match:
                        ch_num = match.group(1)
                        title = link.get_text(strip=True) or f"Chapter {ch_num}"
                        
                        chapters.append(Chapter(
                            number=ch_num,
                            title=title,
                            url=href,
                        ))
            
            # Sort by chapter number
            chapters = sorted(chapters, key=lambda c: float(c.number) if c.number else 0)
            
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
            
            # Find all img tags with laiond.com URLs
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "laiond.com/images" in src:
                    # Skip small icons/thumbnails
                    if any(size in src for size in ["32x32", "192x192", "180x180", "270x270"]):
                        continue
                    if src not in pages:
                        pages.append(src)
            
        except Exception as e:
            logger.error(f"Error getting pages: {e}")
        
        return pages
    
    def download_image(self, url: str) -> bytes:
        """Download an image with proper headers."""
        from urllib.parse import quote
        
        # URL-encode the path part (spaces become %20)
        if " " in url:
            # Split URL and encode the path portion
            parts = url.split("/images/", 1)
            if len(parts) == 2:
                url = parts[0] + "/images/" + quote(parts[1])
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        
        resp = self.session.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.content
