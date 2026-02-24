"""
DemonSlayerManga scraper (demonslayermanga.com) - Demon Slayer / Kimetsu no Yaiba dedicated site.

Uses custom CDN at cdn.demonslayermanga.com/file/mangap/...
Supports multiple Demon Slayer manga: main series, colored, Kimetsu Gakuen, Kimetsu no Aima.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class DemonSlayerMangaScraper(BaseScraper):
    """Scraper for demonslayermanga.com - Demon Slayer / Kimetsu no Yaiba manga."""
    
    name = "demonslayermanga"
    base_url = "https://ww9.demonslayermanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (multi-manga site)."""
        results = [
            Manga(
                title="Demon Slayer: Kimetsu no Yaiba",
                url=f"{self.base_url}/manga/demon-slayer-kimetsu-no-yaiba/",
                cover_url=None,
            ),
            Manga(
                title="Kimetsu no Yaiba - Digital Colored Comics",
                url=f"{self.base_url}/manga/kimetsu-no-yaiba-digital-colored-comics/",
                cover_url=None,
            ),
            Manga(
                title="Kimetsu Gakuen!",
                url=f"{self.base_url}/manga/kimetsu-gakuen/",
                cover_url=None,
            ),
            Manga(
                title="Kimetsu no Aima!",
                url=f"{self.base_url}/manga/kimetsu-no-aima/",
                cover_url=None,
            ),
        ]
        
        # Filter by query if provided
        query_lower = query.lower()
        if query_lower:
            results = [r for r in results if query_lower in r.title.lower()]
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        # Default to main Demon Slayer manga if no URL provided
        if not manga_url or manga_url == '':
            manga_url = f"{self.base_url}/manga/demon-slayer-kimetsu-no-yaiba/"
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links
        for link in soup.select("a[href*='/chapter/']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text or "chapter" not in href.lower():
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href.lower())
            number = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from CDN."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images from cdn.demonslayermanga.com
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            src = src.strip()
            
            # Accept cdn.demonslayermanga.com images
            if "cdn.demonslayermanga.com" in src:
                if src not in seen:
                    seen.add(src)
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
