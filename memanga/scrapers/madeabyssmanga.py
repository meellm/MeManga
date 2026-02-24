"""
MadeAbyssManga scraper (madeabyss.com) - Made in Abyss dedicated site.

Uses Nuxt.js with SSR, images hosted on assets.madeabyss.com.
Same network/platform as punpunmanga.com.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class MadeAbyssMangaScraper(BaseScraper):
    """Scraper for madeabyss.com - Made in Abyss manga."""
    
    name = "madeabyssmanga"
    base_url = "https://madeabyss.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Made in Abyss",
            url=f"{self.base_url}/",
            cover_url="https://madeabyss.com/volume-covers3/madeinabyss.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /chapter/N/
        for link in soup.select("a[href*='/chapter/']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href.rstrip("/") + "/"
            
            # Extract chapter number from URL
            match = re.search(r'/chapter/(\d+(?:\.\d+)?)', href)
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
        """Get all page image URLs from the SSR HTML."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images with class "l" (lazy/loaded) inside .images container
        for img in soup.select("div.images img, img.l"):
            url = img.get("src", "")
            if not url:
                continue
            # Only accept images from the assets CDN
            if "assets.madeabyss.com" in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check og:image as fallback
        if not pages:
            for meta in soup.select('meta[property="og:image"]'):
                url = meta.get("content", "")
                if url and "assets.madeabyss.com" in url:
                    if url not in seen:
                        seen.add(url)
                        pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from assets CDN."""
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
