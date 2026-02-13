"""
MGeko scraper
https://mgeko.cc

Simple requests-based scraper for manga reading.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MGekoScraper(BaseScraper):
    """Scraper for MGeko."""
    
    name = "mgeko"
    base_url = "https://mgeko.cc"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search/?search={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".novel-item"):
            link = item.select_one("a")
            title_el = item.select_one(".novel-title")
            
            if not link or not title_el:
                continue
            
            href = link.get("href", "")
            manga_url = f"{self.base_url}{href}" if href.startswith("/") else href
            title = title_el.get_text(strip=True)
            
            cover_el = item.select_one("img")
            cover_url = None
            if cover_el:
                cover_url = cover_el.get("data-src") or cover_el.get("src")
                if cover_url and cover_url.startswith("/"):
                    cover_url = f"{self.base_url}{cover_url}"
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        # Try all-chapters page first
        if not manga_url.endswith("/"):
            manga_url += "/"
        all_chapters_url = manga_url + "all-chapters/"
        
        try:
            html = self._get_html(all_chapters_url)
        except:
            html = self._get_html(manga_url)
        
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        for link in soup.select('a[href*="/reader/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            chapter_url = f"{self.base_url}{href}" if href.startswith("/") else href
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number from URL or text
            match = re.search(r'chapter[_-]?(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', chapter_text)
            
            chapter_num = match.group(1) if match else chapter_text
            
            chapters.append(Chapter(
                number=chapter_num,
                title=None,
                url=chapter_url,
                date=None,
            ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        for img in soup.select("img"):
            src = img.get("data-src") or img.get("src", "")
            # Look for manga page images (usually from CDN)
            if src and ("cdn" in src or "imgsrv" in src or "chapter" in src.lower()):
                if not src.endswith((".gif", "logo")):
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://mgeko.cc/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
