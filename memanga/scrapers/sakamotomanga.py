"""
SakamotoManga scraper for sakamotomanga.com

Dedicated Sakamoto Days manga reader site.
Images hosted on multiple CDNs (mangaclash, readkakegurui).
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class SakamotoMangaScraper(BaseScraper):
    """Scraper for sakamotomanga.com - Sakamoto Days dedicated site."""
    
    name = "sakamotomanga"
    base_url = "https://sakamotomanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - single manga site so returns main series."""
        return [Manga(
            title="Sakamoto Days",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga."""
        # Homepage only shows recent chapters, but we can probe for all
        # Based on testing, chapters go from 1 to 238+
        chapters = []
        
        # First, get chapters listed on homepage
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        seen = set()
        max_chapter = 1
        
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/chapters/" not in href:
                continue
            
            match = re.search(r'/chapters/(\d+)', href)
            if match:
                number = int(match.group(1))
                max_chapter = max(max_chapter, number)
                if str(number) not in seen:
                    seen.add(str(number))
        
        # Generate all chapters from 1 to max
        for i in range(1, max_chapter + 1):
            chapter_url = f"{self.base_url}/sakamoto-days/manga/chapters/{i}"
            chapters.append(Chapter(
                number=str(i),
                title=f"Chapter {i}",
                url=chapter_url,
            ))
        
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
            
            # Filter for manga page images from multiple CDNs
            # Older chapters: mangaclash, Newer chapters: readkakegurui
            is_manga_image = (
                "mangaclash.com" in src or
                "readkakegurui.com" in src
            )
            
            if is_manga_image and src not in seen:
                # Skip placeholder images
                if "/logo" not in src and "/pomodoro" not in src:
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
