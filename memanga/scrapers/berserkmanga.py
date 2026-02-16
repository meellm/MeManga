"""
BerserkManga scraper (berserk-manga.com) - Berserk dedicated site.

Uses WordPress with Comic Easel plugin, images hosted on cdn3.mangaclash.com CDN.
Images are listed in og:image meta tags.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BerserkMangaScraper(BaseScraper):
    """Scraper for berserk-manga.com - Berserk manga by Kentaro Miura."""
    
    name = "berserkmanga"
    base_url = "https://w3.berserk-manga.com"
    chapter_base = "https://w4.berserk-manga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Berserk",
            url=f"{self.base_url}/",
            cover_url="https://www.berserk-manga.com/wp-content/uploads/2025/04/Berserk-manga-715x1024.jpg",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links in ceo_latest_comics_widget
        for link in soup.select("a[href*='/manga/berserk-chapter']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.chapter_base + href
            
            # Extract chapter number from URL
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
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
        """Get all page image URLs from og:image meta tags."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Extract images from og:image meta tags (mangaclash CDN)
        for meta in soup.select('meta[property="og:image"]'):
            url = meta.get("content", "")
            if url and ("mangaclash.com" in url or "cdn" in url.lower()):
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check twitter:image
        for meta in soup.select('meta[property="twitter:image"]'):
            url = meta.get("content", "")
            if url and ("mangaclash.com" in url or "cdn" in url.lower()):
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
