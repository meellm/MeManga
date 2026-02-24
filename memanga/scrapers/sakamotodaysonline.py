"""
SakamotoDaysOnline Scraper
Site: sakamoto-days.online
Architecture: PHP with attachment CDN
218 chapters of Sakamoto Days
"""

import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class SakamotoDaysOnlineScraper(BaseScraper):
    """Scraper for sakamoto-days.online"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://sakamoto-days.online"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search returns the single manga if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ["sakamoto", "days", "sakamoto days"]):
            return [Manga(
                title="Sakamoto Days",
                url=self.base_url,
                description="Taro Sakamoto, once the world's strongest assassin, now runs a convenience store with his family."
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get all chapters from the home page."""
        response = self.session.get(self.base_url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        chapters = []
        
        # Find all chapter links
        chapter_links = soup.select("a[href^='/chapter/']")
        
        for link in chapter_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # Extract chapter number from href
            match = re.search(r'/chapter/(\d+)', href)
            if match:
                chapter_num = match.group(1)
                chapter_url = f"{self.base_url}{href}"
                
                # Parse chapter title from link text
                title_match = re.search(r'Chapter\s+(\d+)', text)
                if title_match:
                    title = f"Chapter {title_match.group(1)}"
                else:
                    title = f"Chapter {chapter_num}"
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=title,
                    url=chapter_url
                ))
        
        # Remove duplicates and sort by chapter number
        seen = set()
        unique_chapters = []
        for ch in chapters:
            if ch.url not in seen:
                seen.add(ch.url)
                unique_chapters.append(ch)
        
        unique_chapters.sort(key=lambda c: float(c.number) if c.number.replace('.', '').isdigit() else 0)
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all page images from a chapter."""
        response = self.session.get(chapter_url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        pages = []
        
        # Find all manga page images
        images = soup.select("img.manga-page-img, img[id='mangaPage']")
        
        for img in images:
            src = img.get("src", "")
            if src and "/attachment/comic/" in src:
                # Handle relative URLs
                if src.startswith("/"):
                    src = f"{self.base_url}{src}"
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path: str) -> bool:
        """Download an image to the specified path."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            if len(response.content) < 1000:
                return False
            
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Error downloading {url}: {e}")
            return False
