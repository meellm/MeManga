"""
ReadTokyoRevengers scraper (read-tokyorevengers.com) - Tokyo Revengers dedicated site.

WordPress-based with wp-content/uploads CDN for images.
Uses wp-manga-chapter-img class for page images.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadTokyoRevengersScraper(BaseScraper):
    """Scraper for read-tokyorevengers.com - Tokyo Revengers manga."""
    
    name = "readtokyorevengers"
    base_url = "https://read-tokyorevengers.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Tokyo Revengers",
            url=f"{self.base_url}/",
            cover_url="https://w5.read-tokyorevengers.com/wp-content/uploads/2023/07/TOKYO-REVENGERS-manga.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        # The site uses ww[N] subdomains, try to get redirected URL
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /manga/tokyo-manji-revengers-chapter-N/
        for link in soup.select("a[href*='/manga/tokyo-manji-revengers-chapter-']"):
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
        
        # Find images with class wp-manga-chapter-img
        for img in soup.select("img.wp-manga-chapter-img"):
            # Check src, data-src, data-lazy-src
            url = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy-src", "")
            url = url.strip()
            
            if not url or url.startswith("data:"):
                continue
            
            # Accept images from wp-content or CDN
            if "wp-content" in url or "cdn" in url or ".jpg" in url or ".png" in url or ".webp" in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check for lazy-loaded images in page-break divs
        if not pages:
            for img in soup.select("div.page-break img, div.reading-content img"):
                url = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy-src", "")
                url = url.strip()
                
                if not url or url.startswith("data:"):
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
