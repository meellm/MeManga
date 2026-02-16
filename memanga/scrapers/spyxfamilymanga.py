"""
SpyXFamilyManga scraper (spyxfamilymanga.org) - Spy x Family dedicated site.

Uses custom WordPress theme, images hosted on cdn3.mangaclash.com.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class SpyXFamilyMangaScraper(BaseScraper):
    """Scraper for spyxfamilymanga.org - Spy x Family manga."""
    
    name = "spyxfamilymanga"
    base_url = "https://spyxfamilymanga.org"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Spy x Family",
            url=f"{self.base_url}/",
            cover_url=f"{self.base_url}/wp-content/uploads/2025/05/cropped-spy-x-family-acrylic-coaster-act-1-osk-40769758363879-removebg-preview-192x192.png",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the manga page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/spyxfamily-chapter-X/)
        for link in soup.select("a[href*='spyxfamily-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                # Try to get text from child span
                span = link.select_one(".chapter-name")
                if span:
                    text = span.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:[.-]\d+)?)', href.lower())
            number = match.group(1).replace("-", ".") if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from cdn3.mangaclash.com."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images with manga-image class or from mangaclash CDN
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            src = src.strip()
            
            if "cdn3.mangaclash.com" in src or "mangaclash.com" in src:
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
