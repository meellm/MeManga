"""
Gantz Manga Free scraper (gantzmangafree.com) - Gantz dedicated site.

Uses WordPress with Comic Easel plugin, images hosted on Blogger CDN.
Images are listed in og:image meta tags.
Note: This is a mirrored/static site (HTTrack), uses relative URLs.
Uses cloudscraper for Cloudflare bypass.
"""

import re
from typing import List
from bs4 import BeautifulSoup
import cloudscraper
from .base import BaseScraper, Chapter, Manga


class GantzMangaFreeScraper(BaseScraper):
    """Scraper for gantzmangafree.com - Gantz manga by Hiroya Oku."""
    
    name = "gantzmangafree"
    base_url = "https://www.gantzmangafree.com"
    
    def __init__(self):
        super().__init__()
        # Use cloudscraper for Cloudflare bypass
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "Referer": self.base_url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Gantz",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - handles both relative and absolute URLs
        for link in soup.select("a[href*='gantz-chapter']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute URL - handle relative paths like "manga/gantz-chapter-1/index.html"
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = self.base_url + href
            else:
                full_url = f"{self.base_url}/{href}"
            
            # Ensure index.html is present (required by this site)
            if not full_url.endswith("/index.html"):
                if full_url.endswith("/"):
                    full_url = full_url + "index.html"
                else:
                    full_url = full_url + "/index.html"
            
            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text.lower())
            number = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=full_url,
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
            if url and ("bp.blogspot.com" in url or "blogger.googleusercontent.com" in url):
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check for twitter:image
        for meta in soup.select('meta[property="twitter:image"]'):
            url = meta.get("content", "")
            if url and ("bp.blogspot.com" in url or "blogger.googleusercontent.com" in url):
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
