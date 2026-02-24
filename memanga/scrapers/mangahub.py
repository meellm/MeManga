"""
MangaHub scraper
https://mangahub.io

Large manga library with clean interface.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaHubScraper(BaseScraper):
    """Scraper for MangaHub.io"""
    
    name = "mangahub"
    base_url = "https://mangahub.io"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get("href", "")
            
            # Skip chapter links and duplicates
            if not href or "chapter" in href or href in seen_urls:
                continue
            
            # Must be a manga page link
            if not re.match(r'.*/manga/[^/]+$', href):
                continue
                
            seen_urls.add(href)
            
            # Get title from link or parent
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                # Try to find title in parent element
                parent = link.find_parent(class_="media")
                if parent:
                    title_elem = parent.select_one("h4, .media-heading")
                    title = title_elem.get_text(strip=True) if title_elem else ""
            
            if not title:
                # Extract from URL
                title = href.split("/")[-1].replace("-", " ").replace("_", " ").title()
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            # Get cover image
            cover_url = None
            parent = link.find_parent(class_="media")
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen_urls = set()
        
        for link in soup.select('a[href*="chapter"]'):
            href = link.get("href", "")
            
            # Must have chapter pattern
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                continue
            
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            chapter_text = link.get_text(strip=True)
            
            # Skip generic links
            if chapter_text.lower() in ["start reading", "read first", "read last"]:
                continue
            
            chapter_num = match.group(1)
            
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
        
        # Find images from CDN
        for img in soup.select('img[src*="mghcdn.com"], img[data-src*="mghcdn.com"]'):
            src = img.get("data-src") or img.get("src")
            if src and src not in seen:
                seen.add(src)
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
