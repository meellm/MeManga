"""
MangaPark scraper
https://mangapark.io

Vast manga collection.
"""

import re
from typing import List
from pathlib import Path
from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class MangaParkScraper(PlaywrightScraper):
    """Scraper for MangaPark.io (uses Playwright due to JS rendering)"""
    
    name = "mangapark"
    base_url = "https://mangapark.to"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?word={query.replace(' ', '+')}"
        html = self._get_page_content(url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".item, .manga-item, a[href*='/comic/']"):
            if item.name == "a":
                link = item
            else:
                link = item.find("a")
            
            if not link:
                continue
            
            href = link.get("href", "")
            if not href or "/comic/" not in href:
                continue
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            # Get title
            title_elem = item.select_one(".title, h3, h2")
            title = title_elem.get_text(strip=True) if title_elem else ""
            
            if not title:
                title = link.get("title", "") or link.get_text(strip=True)
            
            if not title:
                img = item.find("img")
                title = img.get("alt", "") if img else href.split("/")[-1].replace("-", " ").title()
            
            # Get cover
            cover_url = None
            img = item.find("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
            
            if title and manga_url not in [r.url for r in results]:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(manga_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        for link in soup.select("a[href*='/chapter/'], .chapter-list a, .chap-item a"):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'ch[_\s.-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'/chapter/(\d+)', href, re.I)
            
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
        
        html = self._get_page_content(chapter_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        for img in soup.select(".reader-img img, .page-img, img[data-src]"):
            src = img.get("data-src") or img.get("src")
            if src and (".jpg" in src.lower() or ".png" in src.lower() or ".webp" in src.lower()):
                if not src.startswith("http"):
                    src = f"https:{src}" if src.startswith("//") else f"{self.base_url}{src}"
                if src not in pages:
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
