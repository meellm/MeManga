"""
One Punch Man Read (onepunchmanread.com)
- One Punch Man dedicated manga reader (Yusuke Murata art)
- 211+ chapters
- WordPress Elementor + cdn.mangadistrict.com CDN
"""

import re
import logging
import cloudscraper
from pathlib import Path
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class OnePunchManReadScraper(BaseScraper):
    """Scraper for onepunchmanread.com."""
    
    BASE_URL = "https://onepunchmanread.com"
    SOURCE_NAME = "onepunchmanread.com"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga. This is a dedicated One Punch Man site."""
        query_lower = query.lower()
        if "one" in query_lower or "punch" in query_lower or "saitama" in query_lower or "opm" in query_lower:
            return [Manga(
                title="One Punch Man (Murata)",
                url=f"{self.BASE_URL}/",
                cover_url="https://onepunchmanread.com/wp-content/uploads/2025/10/EOdQ7x.jpg",
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get all chapters for One Punch Man."""
        chapters = []
        
        # Fetch homepage to get chapter list
        response = self.session.get(self.BASE_URL)
        if response.status_code != 200:
            logger.error(f"Failed to fetch homepage: {response.status_code}")
            return chapters
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find chapter links in the widgets
        for link in soup.select("a[href*='/manga/one-punch-man-chapter-']"):
            url = link.get("href", "")
            title = link.get_text(strip=True)
            
            if not url or not title:
                continue
            
            # Extract chapter number from URL
            match = re.search(r"chapter-(\d+(?:\.\d+)?)", url)
            if match:
                chapter_num = match.group(1)
                chapters.append(Chapter(
                    number=chapter_num,
                    title=title,
                    url=url,
                ))
        
        # Deduplicate by chapter number
        seen = set()
        unique_chapters = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique_chapters.append(ch)
        
        # Sort by chapter number
        unique_chapters.sort(key=lambda x: float(x.number) if x.number.replace('.','').isdigit() else 0)
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all page images for a chapter."""
        response = self.session.get(chapter_url)
        if response.status_code != 200:
            logger.error(f"Failed to fetch chapter: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        pages = []
        
        # Find all images with data-src attribute (lazy loaded)
        for img in soup.find_all("img"):
            # Check data-src first (lazy loading)
            src = img.get("data-src", "") or img.get("src", "")
            
            # Skip non-manga images (base64 placeholders, icons, etc.)
            if not src or src.startswith("data:") or "cropped-" in src:
                continue
            
            # Filter for CDN images only
            if "mangadistrict.com" in src or "cdn." in src:
                src = src.strip()
                pages.append(src)
        
        logger.info(f"Found {len(pages)} pages in {chapter_url}")
        return pages
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": self.BASE_URL,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            if len(response.content) < 1000:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
