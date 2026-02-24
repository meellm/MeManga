"""
ReadIchiTheWitch scraper (readichithewitch.com) - Ichi the Witch dedicated site.

Uses custom CDN at cdn.readichithewitch.com/file/mangap/...
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadIchiTheWitchScraper(BaseScraper):
    """Scraper for readichithewitch.com - Ichi the Witch manga."""
    
    name = "readichithewitch"
    base_url = "https://ww1.readichithewitch.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Ichi the Witch",
            url=f"{self.base_url}/manga/ichi-the-witch/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        manga_page = f"{self.base_url}/manga/ichi-the-witch/"
        html = self._get_html(manga_page)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /chapter/ichi-the-witch-chapter-X/)
        for link in soup.select("a[href*='ichi-the-witch-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href.lower())
            number = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from CDN."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images from cdn.readichithewitch.com
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            src = src.strip()
            
            # Accept cdn.readichithewitch.com images
            if "cdn.readichithewitch.com" in src:
                if src not in seen:
                    seen.add(src)
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
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
