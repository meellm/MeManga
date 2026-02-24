"""
MangaBall scraper - Multi-language manga aggregator
Site: mangaball.net

Uses Playwright for JS rendering.
Note: Search is broken (redirects to 404), but direct manga URLs work.
Users must provide manga URL directly.
"""

import re
from typing import List
from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class MangaBallScraper(PlaywrightScraper):
    """Scraper for MangaBall."""
    
    name = "mangaball"
    base_url = "https://mangaball.net"
    
    def search(self, query: str) -> List[Manga]:
        """
        Search for manga.
        Note: MangaBall's search is JS-heavy and often fails.
        Returns results from homepage instead.
        """
        html = self._get_page_content(self.base_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Find manga links on homepage
        for link in soup.select('a[href*="title-detail"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            # Normalize URL
            if href.startswith('/'):
                href = self.base_url + href
            elif href.startswith('http://'):
                href = href.replace('http://', 'https://')
            
            seen.add(href)
            
            # Get title
            title = link.get('title', '') or link.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            # Filter by query if provided
            if query and query.lower() not in title.lower():
                continue
            
            # Get cover
            img = link.select_one('img')
            cover_url = None
            if img:
                cover_url = img.get('src') or img.get('data-src')
            
            results.append(Manga(
                title=title,
                url=href,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        # Normalize URL
        if manga_url.startswith('http://'):
            manga_url = manga_url.replace('http://', 'https://')
        
        html = self._get_page_content(manga_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # MangaBall structure: .chapter-block contains .chapter-number and links
        for block in soup.select('.chapter-block'):
            # Get chapter number from .chapter-number element
            num_el = block.select_one('.chapter-number')
            if not num_el:
                continue
            
            num_text = num_el.get_text(strip=True)
            match = re.search(r'ch\.?\s*(\d+\.?\d*)', num_text, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', num_text)
            
            chapter_num = match.group(1) if match else None
            if not chapter_num:
                continue
            
            # Get the first chapter-detail link in this block
            link = block.select_one('a[href*="/chapter-detail/"]')
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            # Normalize URL
            if href.startswith('/'):
                href = self.base_url + href
            elif href.startswith('http://'):
                href = href.replace('http://', 'https://')
            
            seen.add(href)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=f"Chapter {chapter_num}",
                url=href,
            ))
        
        # Remove duplicates by chapter number (keep first)
        unique = {}
        for ch in chapters:
            if ch.number not in unique:
                unique[ch.number] = ch
        
        return sorted(unique.values(), key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        # Normalize URL
        if chapter_url.startswith('http://'):
            chapter_url = chapter_url.replace('http://', 'https://')
        
        html = self._get_page_content(chapter_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Find manga page images
        for img in soup.select('img'):
            src = img.get('src') or img.get('data-src')
            if not src:
                continue
            
            # Filter for actual manga pages (from CDN)
            if 'poke-black-and-white.net' in src or re.search(r'-\d{3}\.webp', src):
                if src not in pages:
                    pages.append(src.strip())
        
        return pages
