"""
RecordOfRagnarokManga scraper (record-of-ragnarok-manga.com) - Record of Ragnarok dedicated site.

Uses WordPress, images hosted on Blogger CDN (blogger.googleusercontent.com).
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class RecordOfRagnarokMangaScraper(BaseScraper):
    """Scraper for record-of-ragnarok-manga.com - Record of Ragnarok manga."""
    
    name = "recordofragnarokmanga"
    base_url = "https://record-of-ragnarok-manga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Record of Ragnarok",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        # Site redirects to w1 subdomain
        actual_url = "https://w1.record-of-ragnarok-manga.com/"
        html = self._get_html(actual_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links
        for link in soup.find_all("a", href=re.compile(r'chapter-\d+', re.I)):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                match = re.search(r'chapter-(\d+)', href, re.I)
                text = f"Chapter {match.group(1)}" if match else "Chapter"
            
            # Make absolute
            if not href.startswith("http"):
                href = "https://w1.record-of-ragnarok-manga.com" + href
            
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
        """Get all page image URLs."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find all images from Blogger CDN
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            src = src.strip()
            
            # Accept images from blogger.googleusercontent.com
            if "blogger.googleusercontent.com" in src and src not in seen:
                # Convert to high-res version
                if "/s1600/" not in src:
                    src = re.sub(r'/s\d+/', '/s1600/', src)
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
