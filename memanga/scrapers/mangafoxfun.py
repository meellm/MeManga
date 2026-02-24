"""
MangaFox.fun scraper
https://mangafox.fun

React-based manga site with api.mghcdn.com backend.
Part of the MangaHub network (same as mangapanda.onl, mangahub.us).
Uses cloudscraper for Cloudflare bypass.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaFoxFunScraper(BaseScraper):
    """Scraper for MangaFox.fun"""
    
    name = "mangafoxfun"
    base_url = "https://mangafox.fun"
    
    def __init__(self):
        super().__init__()
        try:
            import cloudscraper
            self.session = cloudscraper.create_scraper()
        except ImportError:
            import requests
            self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        resp = self.session.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        results = []
        seen_urls = set()
        
        # Find all links containing /manga/
        for link in soup.select('a'):
            href = link.get("href", "")
            if not href:
                continue
            if "/manga/" not in href:
                continue
            if "/chapter/" in href:
                continue
            
            title = link.get("title") or link.get_text(strip=True)
            if not title:
                continue
            
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            if full_url in seen_urls:
                continue
            
            # Skip navigation elements
            if title.lower() in ["directory", "popular", "updates", "new", "home", "search"]:
                continue
            
            seen_urls.add(full_url)
            
            # Get cover image
            img = link.find("img")
            cover_url = None
            if img:
                cover_url = img.get("src") or img.get("data-src")
            
            results.append(Manga(
                title=title,
                url=full_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        resp = self.session.get(manga_url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        chapters = []
        seen = set()
        
        for link in soup.select('a[href*="/chapter/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'#?\s*(\d+\.?\d*)', chapter_text)
            if match:
                chapter_num = match.group(1)
            else:
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
                chapter_num = match.group(1) if match else chapter_text[:20]
            
            # Clean up URL
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            chapters.append(Chapter(
                number=chapter_num,
                title=None,
                url=full_url,
                date=None,
            ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        resp = self.session.get(chapter_url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        pages = []
        seen = set()
        
        # Look for manga images (mghcdn.com is their CDN)
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            
            src = src.strip()
            if src in seen:
                continue
            
            # Filter for actual manga pages
            if "mghcdn" in src.lower() or "imgx" in src.lower():
                if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    seen.add(src)
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
