"""
Manganato scraper
https://manganato.com (also chapmanganato.to)

Same network as Mangakakalot, large library.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class ManganatoScraper(BaseScraper):
    """Scraper for Manganato.com"""
    
    name = "manganato"
    base_url = "https://manganato.com"
    alt_urls = ["https://chapmanganato.to", "https://readmanganato.com"]
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search/story/{query.replace(' ', '_')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".search-story-item, .content-genres-item, .panel-search-story .item"):
            link = item.find("a")
            if not link:
                continue
            
            href = link.get("href", "")
            if not href:
                continue
            
            manga_url = href  # Manganato uses full URLs
            
            # Get title
            title_elem = item.select_one(".item-title, h3 a, .story_name")
            title = title_elem.get_text(strip=True) if title_elem else ""
            
            if not title:
                title = link.get("title", "")
            
            if not title:
                img = item.find("img")
                title = img.get("alt", "") if img else href.split("/")[-1].replace("-", " ").title()
            
            # Get cover
            cover_url = None
            img = item.find("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
            
            if title:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        for link in soup.select(".row-content-chapter a, .chapter-list a, a.chapter-name"):
            href = link.get("href", "")
            if not href or "chapter" not in href.lower():
                continue
            
            chapter_url = href  # Full URLs
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_url not in [c.url for c in chapters]:
                chapters.append(Chapter(
                    number=chapter_num,
                    title=chapter_text,
                    url=chapter_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        for img in soup.select(".container-chapter-reader img, .reading-content img"):
            src = img.get("data-src") or img.get("src")
            if src and (".jpg" in src.lower() or ".png" in src.lower() or ".webp" in src.lower()):
                if src not in pages:
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://manganato.com/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
