"""
Case Closed Online (case-closed.online)
- Case Closed / Detective Conan dedicated manga reader (English title)
- 1158+ chapters
- WordPress Zazm theme + laiond.com CDN
"""

import re
import logging
import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class CaseClosedOnlineScraper(BaseScraper):
    """Scraper for case-closed.online."""
    
    BASE_URL = "https://case-closed.online"
    SOURCE_NAME = "case-closed.online"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga. This is a dedicated Case Closed site."""
        query_lower = query.lower()
        if "case" in query_lower or "closed" in query_lower or "conan" in query_lower or "detective" in query_lower:
            return [Manga(
                title="Case Closed (Detective Conan)",
                url=f"{self.BASE_URL}/",
                cover_url="https://case-closed.online/wp-content/uploads/2026/01/case-closed-cover.jpg",
            )]
        return []
    
    def get_chapters(self, manga_id: str) -> list[Chapter]:
        """Get all chapters for Case Closed."""
        chapters = []
        
        # Fetch a chapter page to get chapter list from dropdown
        response = self.session.get(f"{self.BASE_URL}/comic/case-closed-chapter-1/")
        if response.status_code != 200:
            logger.error(f"Failed to fetch chapter list: {response.status_code}")
            return chapters
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find chapter dropdown
        select = soup.select_one("select.mangosm-manga-nav-select")
        if select:
            for option in select.find_all("option"):
                url = option.get("value", "")
                title = option.get_text(strip=True)
                
                if not url:
                    continue
                
                # Extract chapter number from URL
                match = re.search(r"chapter-(\d+(?:\.\d+)?)", url)
                if match:
                    chapter_num = match.group(1)
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title or f"Chapter {chapter_num}",
                        url=url,
                    ))
        
        # Sort by chapter number
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.','').isdigit() else 0)
        return chapters
    
    def get_pages(self, chapter_number: str, chapter_url: str = None) -> list[str]:
        """Get all page images for a chapter."""
        if not chapter_url:
            # Build URL from chapter number
            chapter_url = f"{self.BASE_URL}/comic/case-closed-chapter-{chapter_number}/"
        
        response = self.session.get(chapter_url)
        if response.status_code != 200:
            logger.error(f"Failed to fetch chapter: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        pages = []
        
        # Find all images with lazyload attribute - they use laiond.com CDN
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            
            # Skip non-manga images
            if not src or "laiond.com" not in src:
                continue
            
            # Clean URL
            src = src.strip()
            if src.startswith("//"):
                src = "https:" + src
            
            pages.append(src)
        
        logger.info(f"Found {len(pages)} pages in {chapter_url}")
        return pages
    
    def download_image(self, url: str, headers: dict = None) -> bytes:
        """Download an image with proper headers."""
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.BASE_URL,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if headers:
            req_headers.update(headers)
        
        response = self.session.get(url, headers=req_headers)
        response.raise_for_status()
        return response.content
