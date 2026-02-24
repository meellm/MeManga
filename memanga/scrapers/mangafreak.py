"""
MangaFreak.ws scraper (Simple HTML structure)
Actual domain: ww2.mangafreak.me
"""

import re
from typing import List
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class MangaFreakScraper(BaseScraper):
    """Scraper for mangafreak.ws / mangafreak.me"""
    
    name = "mangafreak"
    base_url = "https://mangafreak.ws"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        # MangaFreak uses /Find/query for search
        search_url = f"{self.base_url}/Find/{query.replace(' ', '%20')}"
        html = self._get_html(search_url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Find manga links in search results
        for link in soup.select("a[href*='/Manga/']"):
            href = link.get("href", "")
            if not href or "/Manga/" not in href:
                continue
            
            # Normalize URL
            if href.startswith("/"):
                manga_url = self.base_url + href
            else:
                manga_url = href
            
            # Get manga slug
            manga_slug = href.split("/Manga/")[-1].rstrip("/").split("/")[0]
            if manga_slug in seen or not manga_slug:
                continue
            seen.add(manga_slug)
            
            # Get title from link text or tooltip
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                # Try getting title from parent or nearby elements
                parent = link.parent
                if parent:
                    title = parent.get_text(strip=True)
            
            # Fallback to slug
            if not title or len(title) < 2:
                title = manga_slug.replace("_", " ").title()
            
            # Get cover image if available
            img = link.select_one("img")
            cover = None
            if img:
                cover = img.get("src", "")
                if cover and not cover.startswith("http"):
                    cover = "https:" + cover if cover.startswith("//") else None
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover
            ))
        
        return results[:20]  # Limit results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga."""
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /Read1_MangaName_ChapterNum)
        for link in soup.select("a[href*='/Read1_']"):
            href = link.get("href", "")
            if not href:
                continue
            
            # Extract chapter number from URL
            # Format: /Read1_Manga_Name_123
            match = re.search(r'/Read1_[^/]+_(\d+\.?\d*)/?$', href)
            if not match:
                continue
            
            num = match.group(1)
            if num in seen:
                continue
            seen.add(num)
            
            # Build full URL
            chapter_url = href if href.startswith("http") else self.base_url + href
            
            # Get chapter title from link text
            text = link.get_text(strip=True)
            title = text if text else f"Chapter {num}"
            
            chapters.append(Chapter(
                number=num,
                title=title,
                url=chapter_url
            ))
        
        return sorted(chapters, reverse=True)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # MangaFreak images are in elements like:
        # <img src="https://images.mangafreak.me/mangas/naruto/naruto_1/naruto_1_1.jpg">
        for img in soup.select("img[src*='images.mangafreak.me/mangas/']"):
            src = img.get("src", "")
            if src and src not in pages:
                pages.append(src)
        
        # Also check for lazy loaded images
        for img in soup.select("img[data-src*='images.mangafreak.me/mangas/']"):
            src = img.get("data-src", "")
            if src and src not in pages:
                pages.append(src)
        
        # Fallback: check mySlides class
        if not pages:
            for img in soup.select(".mySlides img"):
                src = img.get("src") or img.get("data-src")
                if src and "mangafreak" in src and src not in pages:
                    pages.append(src)
        
        return pages
