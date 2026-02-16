"""
ElusiveSamurai scraper for elusive-samurai.com

Dedicated The Elusive Samurai (Nige Jouzu no Wakagimi) manga reader site.
Images hosted on pic.readkakegurui.com CDN.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ElusiveSamuraiScraper(BaseScraper):
    """Scraper for elusive-samurai.com - The Elusive Samurai dedicated site."""
    
    name = "elusivesamurai"
    base_url = "https://elusive-samurai.com"
    chapter_base = "https://w4.elusive-samurai.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - single manga site so returns main series."""
        return [Manga(
            title="The Elusive Samurai",
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
            if "/manga/" not in href or "chapter" not in href.lower():
                continue
            
            # Normalize URL
            if not href.startswith("http"):
                if href.startswith("/"):
                    href = self.chapter_base + href
                else:
                    href = self.chapter_base + "/" + href
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
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
        def parse_number(n):
            try:
                return float(n)
            except:
                return 0
        chapters.sort(key=lambda c: parse_number(c.number))
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
            
            # Filter for manga page images from readkakegurui CDN
            if "readkakegurui.com" in src and src not in seen:
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
