"""
Monster Manga Online scraper

Site: monster-manga.online
Type: WordPress MangaVerse theme
CDN: cdn.monster-manga.online

Features:
- Large library with popular manga (One Piece, Berserk, Hunter X Hunter, etc.)
- Direct image URLs from cdn.monster-manga.online
- Simple URL patterns
"""

import re
import logging
from typing import List, Optional
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class MonsterMangaOnlineScraper(BaseScraper):
    """Scraper for monster-manga.online."""
    
    BASE_URL = "https://www.monster-manga.online"
    SOURCE_NAME = "monster-manga.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        results = []
        
        # Try search endpoint
        search_url = f"{self.BASE_URL}/en/search"
        params = {"s": query}
        
        try:
            response = self.session.get(search_url, params=params, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Search failed: {e}")
            # Fallback: try manga list page and filter
            return self._search_manga_list(query)
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find manga items
        manga_items = soup.select("a[href*='/manga/']")
        seen = set()
        
        for item in manga_items:
            href = item.get("href", "")
            if href in seen or not href.endswith(".html"):
                continue
            seen.add(href)
            
            title = item.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            results.append(Manga(
                title=title,
                url=href if href.startswith("http") else urljoin(self.BASE_URL, href),
            ))
        
        return results[:20]
    
    def _search_manga_list(self, query: str) -> List[Manga]:
        """Search by filtering manga list."""
        results = []
        query_lower = query.lower()
        
        list_url = f"{self.BASE_URL}/en/manga/"
        try:
            response = self.session.get(list_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Manga list failed: {e}")
            return results
        
        soup = BeautifulSoup(response.text, "html.parser")
        manga_links = soup.select("a[href*='/manga/']")
        seen = set()
        
        for link in manga_links:
            href = link.get("href", "")
            title = link.get_text(strip=True)
            
            if href in seen or not href.endswith(".html") or not title:
                continue
            
            if query_lower not in title.lower():
                continue
            
            seen.add(href)
            
            results.append(Manga(
                title=title,
                url=href if href.startswith("http") else urljoin(self.BASE_URL, href),
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        chapters = []
        
        try:
            response = self.session.get(manga_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return chapters
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find chapter links
        chapter_links = soup.select("a[href*='chapter']")
        seen = set()
        
        for link in chapter_links:
            href = link.get("href", "")
            if href in seen or not href.endswith(".html"):
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            
            # Extract chapter number
            ch_match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.IGNORECASE)
            if not ch_match:
                ch_match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', text, re.IGNORECASE)
            
            if ch_match:
                chapter_num = ch_match.group(1)
            else:
                continue
            
            full_url = href if href.startswith("http") else urljoin(self.BASE_URL, href)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=full_url,
            ))
        
        # Sort by chapter number descending (newest first)
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get image URLs for a chapter."""
        pages = []
        
        try:
            response = self.session.get(chapter_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to get chapter pages: {e}")
            return pages
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find all images from cdn.monster-manga.online
        images = soup.select("img")
        
        for img in images:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            src = src.strip()
            
            # Only include images from the CDN
            if "cdn.monster-manga.online" in src:
                # Clean up URL
                if not src.startswith("http"):
                    src = "https:" + src if src.startswith("//") else src
                pages.append(src)
        
        logger.info(f"Found {len(pages)} pages in chapter")
        return pages
