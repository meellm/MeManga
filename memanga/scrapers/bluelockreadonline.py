"""
BlueLockReadOnline scraper (bluelockread.online) - Blue Lock dedicated site.

Uses WordPress, images hosted on wp-content/uploads.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BlueLockReadOnlineScraper(BaseScraper):
    """Scraper for bluelockread.online - Blue Lock manga."""
    
    name = "bluelockreadonline"
    base_url = "https://bluelockread.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Blue Lock",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /blue-lock-chapter-X/)
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
        """Get all page image URLs."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find entry-content container
        entry = soup.find(class_="entry-content")
        if not entry:
            entry = soup
        
        # Find images - check data-src first, then src
        for img in entry.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            src = src.strip()
            
            # Skip placeholder images
            if "data:image" in src or not src:
                continue
            
            # Accept images from wp-content/uploads
            if "wp-content/uploads" in src and src not in seen:
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
