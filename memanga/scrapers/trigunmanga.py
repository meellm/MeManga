"""
TrigunManga scraper (trigunmanga.com) - Trigun dedicated site.

Uses WordPress with Comic Easel plugin, images hosted on Blogger CDN.
Images are listed in og:image meta tags.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class TrigunMangaScraper(BaseScraper):
    """Scraper for trigunmanga.com - Trigun manga."""
    
    name = "trigunmanga"
    base_url = "https://trigunmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        # This is a single-manga site, just return the main manga
        return [Manga(
            title="Trigun",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links
        for link in soup.select("a[href*='/manga/']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text or "chapter" not in text.lower():
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text.lower())
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
        
        # Extract images from og:image meta tags (Blogger CDN URLs)
        for meta in soup.select('meta[property="og:image"]'):
            url = meta.get("content", "")
            if url and "blogger.googleusercontent.com" in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check for twitter:image
        for meta in soup.select('meta[property="twitter:image"]'):
            url = meta.get("content", "")
            if url and "blogger.googleusercontent.com" in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from Blogger CDN."""
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
