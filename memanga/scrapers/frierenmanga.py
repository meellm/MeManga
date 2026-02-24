"""
FrierenManga scraper (frieren-manga.com) - Frieren: Beyond Journey's End dedicated site.

Uses WordPress with Comic Easel plugin, images hosted via img.spoilerhat.com proxy
to zjcdn.mangafox.me CDN. Images are listed in og:image meta tags.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class FrierenMangaScraper(BaseScraper):
    """Scraper for frieren-manga.com - Sousou no Frieren manga."""
    
    name = "frierenmanga"
    base_url = "https://frieren-manga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        # This is a single-manga site, just return the main manga
        return [Manga(
            title="Frieren: Beyond Journey's End",
            url=f"{self.base_url}/",
            cover_url="https://frieren-manga.com/wp-content/uploads/2024/10/Frieren-Beyond-Journeys-End-Manga-2.jpg",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /manga/sousou-no-frieren-chapter-X/
        for link in soup.select("a[href*='/manga/']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            if "chapter" not in href.lower():
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
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
        
        # Extract images from og:image meta tags (img.spoilerhat.com proxy URLs)
        for meta in soup.select('meta[property="og:image"]'):
            url = meta.get("content", "")
            if url and ("img.spoilerhat.com" in url or "mangafox" in url):
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check for twitter:image
        for meta in soup.select('meta[property="twitter:image"]'):
            url = meta.get("content", "")
            if url and ("img.spoilerhat.com" in url or "mangafox" in url):
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from img.spoilerhat.com proxy."""
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
