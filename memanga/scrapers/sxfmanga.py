"""
SXFManga scraper (sxfmanga.net) - Spy x Family dedicated site.

Uses WordPress Madara theme, images proxied through img.spoilerhat.com to zjcdn.mangafox.me.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class SXFMangaScraper(BaseScraper):
    """Scraper for sxfmanga.net - Spy x Family manga."""
    
    name = "sxfmanga"
    base_url = "https://ww2.sxfmanga.net"
    
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
            cover_url="https://ww2.sxfmanga.net/wp-content/uploads/2022/01/20.jpg",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the manga page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/spy-x-family-chapter-X/)
        for link in soup.select("a[href*='spy-x-family-chapter-']"):
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
            
            # Extract chapter number - skip URLs without valid chapter numbers
            match = re.search(r'chapter-(\d+(?:[.-]\d+)?)', href.lower())
            if not match:
                continue
            number = match.group(1).replace("-", ".")
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from img.spoilerhat.com proxy."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find reading-content div
        reading_content = soup.select_one(".reading-content")
        if not reading_content:
            reading_content = soup
        
        # Find images with wp-manga-chapter-img class
        for img in reading_content.find_all("img", class_="wp-manga-chapter-img"):
            src = img.get("src") or img.get("data-src") or ""
            src = src.strip()
            
            if "img.spoilerhat.com" in src or "mangafox" in src:
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
