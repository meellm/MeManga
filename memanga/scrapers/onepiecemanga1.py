"""
OnePieceManga1 scraper (1piecemanga.com) - One Piece dedicated site.

WordPress-based with Contabo storage CDN for images.
Uses direct img tags in content.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class OnePieceManga1Scraper(BaseScraper):
    """Scraper for 1piecemanga.com - One Piece manga."""
    
    name = "onepiecemanga1"
    base_url = "https://w064.1piecemanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="One Piece",
            url=f"{self.base_url}/",
            cover_url="https://w064.1piecemanga.com/wp-content/uploads/2024/08/One_Piece_Chapter_1.png",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /manga/one-piece-chapter-N/
        for link in soup.select("a[href*='one-piece-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            if not match:
                continue
            number = match.group(1)
            
            # Clean up title
            title = text.strip()
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
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images in content - Contabo storage CDN
        for img in soup.select("div.entry-content img, article img, p img"):
            url = img.get("src", "").strip()
            
            if not url or url.startswith("data:"):
                continue
            
            # Accept images from Contabo storage or with common image extensions
            if "contabostorage.com" in url or any(ext in url.lower() for ext in [".jpg", ".png", ".webp"]):
                # Skip WordPress emoji and small images
                if "wp-includes" in url or "emoji" in url.lower():
                    continue
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
