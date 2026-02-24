"""
MonsterManga scraper (monstermanga.org) - Monster (Naoki Urasawa) dedicated site.

Uses WordPress, images hosted on official.lowee.us.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class MonsterMangaScraper(BaseScraper):
    """Scraper for monstermanga.org - Monster manga by Naoki Urasawa."""
    
    name = "monstermanga"
    base_url = "https://www.monstermanga.org"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Monster",
            url=f"{self.base_url}/",
            cover_url=f"{self.base_url}/wp-content/uploads/2025/07/monster-cover-1.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/monster-chapter-X-0/)
        for link in soup.select("a[href*='monster-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number (format: monster-chapter-162-0)
            match = re.search(r'monster-chapter-(\d+(?:\.\d+)?)', href.lower())
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
        """Get all page image URLs."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images from official.lowee.us
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            
            if "official.lowee.us" in src:
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
