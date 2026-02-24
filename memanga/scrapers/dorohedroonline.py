"""
DorohedoroOnline Scraper
Site: dorohedoro.online  
Architecture: WordPress + Blogger CDN
167 chapters of Dorohedoro by Q Hayashida
"""

import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class DorohedoroOnlineScraper(BaseScraper):
    """Scraper for dorohedoro.online"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://dorohedoro.online"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search returns the single manga if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ["dorohedoro", "caiman", "hole"]):
            return [Manga(
                title="Dorohedoro",
                url=self.base_url,
                cover_url="https://dorohedoro.online/wp-content/uploads/2022/06/Dorohedoro-Manga-Volume-1.webp",
                description="In a city called Hole, a dark fantasy unfolds. Caiman, a man with a reptilian head, seeks to undo the magic that transformed him."
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get all chapters from the home page."""
        response = self.session.get(self.base_url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        chapters = []
        
        # Find all chapter links
        chapter_links = soup.select("a[href*='/manga/dorohedoro-chapter-']")
        
        for link in chapter_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # Extract chapter number from href
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            if match:
                chapter_num = match.group(1)
                chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                # Parse chapter title
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
        
        # Find all images - Blogger CDN pattern
        images = soup.select("img[src*='blogger.googleusercontent.com']")
        
        for img in images:
            src = img.get("src", "")
            if src and "blogger.googleusercontent.com" in src:
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
