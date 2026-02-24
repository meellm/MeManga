"""
ManhuaFast scraper
https://manhuafast.com

Madara-based WordPress manga site - simple requests-based scraper.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class ManhuaFastScraper(BaseScraper):
    """Scraper for ManhuaFast."""
    
    name = "manhuafast"
    base_url = "https://manhuafast.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".c-tabs-item__content"):
            title_el = item.select_one(".post-title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            manga_url = title_el.get("href", "")
            
            cover_el = item.select_one("img")
            cover_url = None
            if cover_el:
                cover_url = cover_el.get("data-src") or cover_el.get("src")
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:15]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Try .chapter-item first (ManhuaFast specific)
        for item in soup.select(".chapter-item"):
            link = item.select_one("a")
            if not link:
                continue
            
            chapter_url = link.get("href", "")
            if not chapter_url or chapter_url in seen:
                continue
            seen.add(chapter_url)
            
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            chapter_num = match.group(1) if match else chapter_text
            
            chapters.append(Chapter(
                number=chapter_num,
                title=None,
                url=chapter_url,
                date=None,
            ))
        
        # Fallback to standard Madara selector
        if not chapters:
            for link in soup.select(".wp-manga-chapter a"):
                chapter_url = link.get("href", "")
                if not chapter_url or chapter_url in seen:
                    continue
                seen.add(chapter_url)
                
                chapter_text = link.get_text(strip=True)
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
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
        for img in soup.select(".reading-content img"):
            src = img.get("data-src") or img.get("src") or img.get("data-lazy-src")
            if src:
                src = src.strip()
                if src and not any(x in src.lower() for x in ["loading", "lazy", ".gif"]):
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
