"""
VinlandSagaManga scraper (vinlandsagamanga.net) - Vinland Saga dedicated site.

WordPress Madara theme with img.spoilerhat.com proxy to zjcdn.mangafox.me CDN.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class VinlandSagaMangaScraper(BaseScraper):
    """Scraper for vinlandsagamanga.net - Vinland Saga manga."""
    
    name = "vinlandsagamanga"
    base_url = "https://ww3.vinlandsagamanga.net"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Vinland Saga",
            url=f"{self.base_url}/manga/vinland-saga/",
            cover_url="https://vinlandsagamanga.net/wp-content/uploads/2022/01/vinland-saga-manga-vol.jpg",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the manga page."""
        # Use the manga list page
        url = f"{self.base_url}/manga/vinland-saga/"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /manga/vinland-saga-chapter-N/
        for link in soup.select("a[href*='vinland-saga-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            if not match:
                continue
            number = match.group(1)
            
            # Clean up title
            title = text.strip() if text else f"Chapter {number}"
            if not title or title.isdigit():
                title = f"Chapter {number}"
            
            chapters.append(Chapter(
                number=number,
                title=title,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from the chapter."""
        html = self._get_html(chapter_url)
        
        pages = []
        seen = set()
        
        # Find all spoilerhat proxy URLs in the HTML
        # Pattern: https://img.spoilerhat.com/img/?url=https://zjcdn.mangafox.me/...
        for match in re.finditer(r'https://img\.spoilerhat\.com/img/\?url=[^"\s]+\.(?:jpg|png|webp)', html):
            url = match.group(0)
            if url not in seen:
                seen.add(url)
                pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from CDN."""
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
