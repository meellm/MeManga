"""
MangaDistrict scraper
https://mangadistrict.com

Manga library using WordPress Manga theme.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaDistrictScraper(BaseScraper):
    """Scraper for MangaDistrict.com"""
    
    name = "mangadistrict"
    base_url = "https://mangadistrict.com"
    
    def search(self, query: str) -> List[Manga]:
        from bs4 import BeautifulSoup
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        for link in soup.select(".post-title a"):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not href or not title or href in seen:
                continue
            seen.add(href)
            cover_url = None
            parent = link.find_parent(class_="row")
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            results.append(Manga(title=title, url=href, cover_url=cover_url))
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        from bs4 import BeautifulSoup
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        for link in soup.select(".wp-manga-chapter a"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                continue
            seen.add(href)
            chapters.append(Chapter(
                number=match.group(1),
                title=link.get_text(strip=True) or f"Chapter {match.group(1)}",
                url=href,
            ))
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        from bs4 import BeautifulSoup
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        for img in soup.select(".reading-content img, .page-break img"):
            src = img.get("data-src") or img.get("src")
            if src:
                src = src.strip()
                if src not in seen:
                    seen.add(src)
                    pages.append(src)
        return pages
    
    def download_image(self, url: str, path) -> bool:
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Referer": f"{self.base_url}/"}
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed: {e}")
            return False
