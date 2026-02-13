"""
Manhwa18 scraper
https://manhwa18.cc

Adult manhwa/webtoon library.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class Manhwa18Scraper(BaseScraper):
    """Scraper for Manhwa18.cc"""
    
    name = "manhwa18"
    base_url = "https://manhwa18.cc"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".manga-item"):
            link = item.select_one("a")
            if not link:
                continue
            
            href = link.get("href", "")
            if not href:
                continue
            
            manga_url = f"{self.base_url}{href}" if not href.startswith("http") else href
            
            # Get title
            title_elem = item.select_one("h3, .title, .name")
            title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
            
            # Get cover image
            cover_url = None
            img = item.select_one("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
                if cover_url and not cover_url.startswith("http"):
                    cover_url = f"{self.base_url}{cover_url}"
            
            if title:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen_urls = set()
        
        for link in soup.select('a[href*="chapter-"]'):
            href = link.get("href", "")
            
            # Must have chapter-NUMBER pattern (not just "chapter" anywhere)
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                continue
            
            full_url = f"{self.base_url}{href}" if not href.startswith("http") else href
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            chapter_text = link.get_text(strip=True)
            
            # Skip generic links
            if chapter_text.lower() in ["read first", "read last", "first chapter", "last chapter"]:
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
        
        # Find images with upload URLs (manga content)
        for img in soup.select('img[src*="/uploads/"], img[data-src*="/uploads/"]'):
            src = img.get("data-src") or img.get("src")
            if src and src not in seen:
                seen.add(src)
                if not src.startswith("http"):
                    src = f"{self.base_url}{src}"
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
