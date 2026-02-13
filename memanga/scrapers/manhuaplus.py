"""
ManhuaPlus scraper
https://manhuaplus.org

Large manhua/manhwa library with AJAX-based chapter loading.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class ManhuaPlusScraper(BaseScraper):
    """Scraper for ManhuaPlus.org"""
    
    name = "manhuaplus"
    base_url = "https://manhuaplus.org"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for link in soup.select(".post-title a"):
            title = link.get_text(strip=True)
            href = link.get("href", "")
            
            if not title or not href:
                continue
            
            # Get cover image
            cover_url = None
            parent = link.find_parent(class_="row")
            if parent:
                img = parent.find("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=href, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen_urls = set()
        
        # Find chapter links by href pattern
        for link in soup.select('a[href*="chapter-"]'):
            href = link.get("href", "")
            if not href or href in seen_urls:
                continue
            
            # Skip non-chapter links
            if "chapter-" not in href:
                continue
                
            seen_urls.add(href)
            chapter_text = link.get_text(strip=True)
            
            # Skip generic links like "Read Now"
            if chapter_text.lower() in ["read now", "read newest", "read first"]:
                continue
            
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            chapter_num = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=href,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        # First get the chapter ID from the page
        html = self._get_html(chapter_url)
        
        match = re.search(r'CHAPTER_ID\s*=\s*(\d+)', html)
        if not match:
            return []
        
        chapter_id = match.group(1)
        
        # Fetch images via AJAX endpoint
        ajax_url = f"{self.base_url}/ajax/image/list/chap/{chapter_id}"
        headers = {
            "Referer": chapter_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        
        try:
            response = self.session.get(ajax_url, headers=headers, timeout=30)
            data = response.json()
        except Exception:
            return []
        
        if not data.get("status") or not data.get("html"):
            return []
        
        # Parse HTML to get image URLs from link hrefs
        soup = BeautifulSoup(data["html"], "html.parser")
        
        pages = []
        seen = set()
        for link in soup.select("a.readImg, a[href*='.webp'], a[href*='.jpg'], a[href*='.png']"):
            href = link.get("href", "").strip()
            if href and href not in seen and any(ext in href.lower() for ext in ['.jpg', '.png', '.webp']):
                seen.add(href)
                pages.append(href)
        
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
