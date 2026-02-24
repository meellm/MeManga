"""
DragonBallSuperOnline scraper (thedragonballsuper.online) - Dragon Ball Super dedicated site.

WordPress-based with wp-content/uploads CDN for images.
Uses data-src lazy loading for page images.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class DragonBallSuperOnlineScraper(BaseScraper):
    """Scraper for thedragonballsuper.online - Dragon Ball Super manga."""
    
    name = "dragonballsuperonline"
    base_url = "https://thedragonballsuper.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Dragon Ball Super",
            url=f"{self.base_url}/",
            cover_url="https://thedragonballsuper.online/wp-content/uploads/2024/08/thumb-350-330775.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /dragon-ball-super-manga-chapter-N/
        for link in soup.select("a[href*='dragon-ball-super-manga-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            number = match.group(1) if match else "0"
            
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
        
        # Find images with data-src (lazy loaded) in reading content
        for img in soup.select("div.reading-content img, div.page-break img, div.entry-content img"):
            # Check src, data-src, data-lazy-src
            url = img.get("data-src", "") or img.get("data-lazy-src", "") or img.get("src", "")
            url = url.strip()
            
            if not url or url.startswith("data:"):
                continue
            
            # Accept images from wp-content or with common image extensions
            if "wp-content" in url or any(ext in url for ext in [".jpg", ".png", ".webp"]):
                # Skip thumbnail/cover images
                if "thumb" in url.lower():
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
