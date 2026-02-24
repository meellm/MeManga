"""
DrStoneManga scraper for drstonemanga.com

Dedicated Dr. Stone manga reader site.
Images hosted on assets.drstonemanga.com CDN.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class DrStoneMangaScraper(BaseScraper):
    """Scraper for drstonemanga.com - Dr. Stone dedicated site."""
    
    name = "drstonemanga"
    base_url = "https://drstonemanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - single manga site so returns main series."""
        # This is a dedicated site for Dr. Stone only
        return [Manga(
            title="Dr. Stone",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find all chapter links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/chapter/" not in href:
                continue
            
            # Normalize URL
            if href.startswith("/"):
                href = self.base_url + href
            elif not href.startswith("http"):
                href = self.base_url + "/" + href
            
            # Extract chapter number
            match = re.search(r'/chapter/(\d+)', href)
            if match:
                number = match.group(1)
                if number not in seen:
                    seen.add(number)
                    chapters.append(Chapter(
                        number=number,
                        title=f"Chapter {number}",
                        url=href,
                    ))
        
        # Sort by chapter number (ascending)
        chapters.sort(key=lambda c: int(c.number))
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            src = src.strip()
            
            # Filter for manga page images from assets CDN
            if "assets.drstonemanga.com" in src and src not in seen:
                seen.add(src)
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper Referer header."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
