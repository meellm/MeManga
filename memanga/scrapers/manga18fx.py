"""
Manga18fx.com scraper (WordPress Madara theme)
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class Manga18fxScraper(BaseScraper):
    """Scraper for manga18fx.com"""
    
    name = "manga18fx"
    base_url = "https://manga18fx.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        url = f"{self.base_url}/?s={query}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        for link in soup.select("a[href*='/manga/']"):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            # Skip navigation/chapter links, only get manga title links
            if not href or "/manga/" not in href:
                continue
            # Normalize URL and skip duplicates
            manga_slug = href.split("/manga/")[-1].rstrip("/").split("/")[0]
            if manga_slug in seen or not manga_slug:
                continue
            seen.add(manga_slug)
            # Clean title (often has chapter info prepended)
            if title and "Chapter" in title:
                title = title.split("Chapter")[0].strip() or manga_slug.replace("-", " ").title()
            if href and title:
                manga_url = href if href.startswith("http") else self.base_url + href
                results.append(Manga(title=title, url=manga_url))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga."""
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract manga slug from URL
        manga_slug = manga_url.rstrip("/").split("/")[-1]
        
        chapters = []
        seen = set()
        for link in soup.select(f"a[href*='/{manga_slug}/chapter']"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r"chapter[- ]?(\d+\.?\d*)", text, re.I)
            if match:
                num = match.group(1)
            else:
                match = re.search(r"(\d+\.?\d*)", text)
                num = match.group(1) if match else text
            
            if href and num not in seen:
                seen.add(num)
                chapter_url = href if href.startswith("http") else self.base_url + href
                chapters.append(Chapter(number=num, title=text, url=chapter_url))
        
        return sorted(chapters, reverse=True)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        for img in soup.select(".page-break img, img[data-src*='manga18fx']"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if src and not src.startswith("data:"):
                src = src.strip()
                if not src.startswith("http"):
                    src = "https:" + src if src.startswith("//") else self.base_url + src
                pages.append(src)
        
        return pages
