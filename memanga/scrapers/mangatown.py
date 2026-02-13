"""
MangaTown scraper
https://www.mangatown.com

Large manga library, shares CDN with MangaHere.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaTownScraper(BaseScraper):
    """Scraper for MangaTown.com"""
    
    name = "mangatown"
    base_url = "https://www.mangatown.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?name={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get("href", "")
            
            # Skip chapter links and non-manga pages
            if not href or "/c" in href.split("/")[-1] or "chapter" in href:
                continue
            
            # Normalize URL
            if href.endswith("'"):
                href = href[:-1]
            if not href.endswith("/"):
                href += "/"
                
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            manga_url = f"{self.base_url}{href}" if href.startswith("/") else href
            
            # Get title
            title = link.get_text(strip=True)
            if not title:
                # Extract from URL
                title = href.split("/")[-2].replace("_", " ").title()
            
            # Get cover image
            cover_url = None
            parent = link.find_parent("li") or link.find_parent("div")
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("src")
                    if cover_url and cover_url.startswith("//"):
                        cover_url = f"https:{cover_url}"
            
            if title:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract manga slug from URL
        slug = manga_url.rstrip("/").split("/")[-1]
        
        chapters = []
        seen_urls = set()
        
        for link in soup.select(f'a[href*="/{slug}/c"]'):
            href = link.get("href", "")
            
            # Must have chapter number pattern
            match = re.search(r'/c(\d+\.?\d*)', href)
            if not match:
                continue
            
            # Skip comments
            if "comments" in href:
                continue
            
            # Normalize URL
            if href.endswith("'"):
                href = href[:-1]
            if not href.endswith("/"):
                href += "/"
                
            full_url = f"{self.base_url}{href}" if href.startswith("/") else href
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            chapter_num = match.group(1)
            chapter_text = link.get_text(strip=True)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=full_url,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find reader images
        for img in soup.select('.read_img img, #image'):
            src = img.get("data-src") or img.get("src")
            if src and src not in seen:
                seen.add(src)
                # Fix protocol-relative URLs
                if src.startswith("//"):
                    src = f"https:{src}"
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
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
