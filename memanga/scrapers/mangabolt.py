"""
MangaBolt scraper
https://mangabolt.com

Simple HTML-based manga site focused on popular Jump manga.
Similar to readonepiece/readnaruto but with more titles.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaBoltScraper(BaseScraper):
    """Scraper for MangaBolt.com"""
    
    name = "mangabolt"
    base_url = "https://mangabolt.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        # MangaBolt doesn't have a search API - get manga list page
        url = f"{self.base_url}/storage/manga-list.html"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        query_lower = query.lower()
        
        # Find all manga links
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            
            if not title or not href:
                continue
            
            # Filter by query
            if query_lower in title.lower():
                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                results.append(Manga(
                    title=title,
                    url=full_url,
                    cover_url=None,
                ))
        
        # If list page doesn't work, try homepage
        if not results:
            html = self._get_html(self.base_url)
            soup = BeautifulSoup(html, "html.parser")
            
            for link in soup.select('a[href*="/manga/"]'):
                href = link.get("href", "")
                title = link.get_text(strip=True)
                
                if not title or not href:
                    continue
                
                if query_lower in title.lower():
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    results.append(Manga(
                        title=title,
                        url=full_url,
                        cover_url=None,
                    ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        for link in soup.select('a[href*="/chapter/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            chapter_text = link.get_text(strip=True)
            
            # Skip "Read" button links
            if chapter_text.lower() == "read":
                continue
            
            # Extract chapter number from text or URL
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            
            chapter_num = match.group(1) if match else chapter_text[:30]
            
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
        import re
        
        html = self._get_html(chapter_url)
        
        # Find image URLs in HTML (they're in img tags or JSON)
        pages = []
        seen = set()
        
        # Match URLs to cdn.mangabolt.com
        pattern = r'"(https://cdn\.mangabolt\.com/[^"]+\.(jpg|jpeg|png|webp))"'
        matches = re.findall(pattern, html, re.I)
        
        for url, ext in matches:
            if url not in seen:
                seen.add(url)
                pages.append(url)
        
        # Also try direct img tags
        if not pages:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            for img in soup.select("img"):
                src = img.get("src") or img.get("data-src")
                if src and "mangabolt" in src.lower():
                    if src not in seen:
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
