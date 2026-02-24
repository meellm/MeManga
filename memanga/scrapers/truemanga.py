"""
TrueManga scraper
https://truemanga.com (chapters on mangamonk.com)

Manga library with chapters hosted on mangamonk.com CDN.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class TrueMangaScraper(BaseScraper):
    """Scraper for TrueManga.com"""
    
    name = "truemanga"
    base_url = "https://truemanga.com"
    
    def search(self, query: str) -> List[Manga]:
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Find manga links
        for link in soup.select('a[href*="/manga/"], .manga-item a, .list-item a'):
            href = link.get("href", "")
            if not href or "chapter" in href or href in seen:
                continue
            if "/manga/" not in href and self.base_url not in href:
                continue
            seen.add(href)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            cover_url = None
            parent = link.find_parent(class_=["item", "manga-item", "list-item"])
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        for link in soup.select('a[href*="chapter"]'):
            href = link.get("href", "")
            
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                continue
            
            if href in seen:
                continue
            seen.add(href)
            
            chapter_text = link.get_text(strip=True)
            chapter_num = match.group(1)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=href,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images - check for CDN URLs
        for img in soup.select('img[src*="cdn"], img[data-src*="cdn"], .reading-content img'):
            src = img.get("data-src") or img.get("src")
            if src and src not in seen:
                src = src.strip()
                # Filter out non-manga images
                if any(x in src.lower() for x in ['.jpg', '.png', '.webp', 'manga', 'chapter', 'res/']):
                    seen.add(src)
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mangamonk.com/"}
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed: {e}")
            return False
