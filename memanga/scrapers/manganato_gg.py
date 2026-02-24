"""
Manganato.gg scraper - Manga aggregator  
Site: manganato.gg (new domain, has Cloudflare challenge)

Uses Playwright for Cloudflare bypass.
"""

import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class ManganatoGGScraper(PlaywrightScraper):
    """Scraper for Manganato.gg (new domain with Cloudflare)."""
    
    name = "manganato_gg"
    base_url = "https://manganato.gg"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        # Manganato uses query string search
        search_url = f"{self.base_url}/search/story/{quote(query.replace(' ', '_'))}"
        
        html = self._get_page_content(search_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Search results in various containers
        for item in soup.select('.search-story-item, .content-genres-item, .panel-content-genres'):
            link = item.select_one('a[href*="manga-"]')
            if not link:
                link = item.select_one('a[href*="/manga/"]')
            if not link:
                link = item.select_one('a.item-title, a.a-h')
            
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' in href:
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            
            # Get title
            title_el = item.select_one('.item-title, h3, .a-h')
            title = title_el.get_text(strip=True) if title_el else ''
            
            if not title:
                title = link.get('title', '') or link.get_text(strip=True)
            
            title = title.strip()
            if not title or len(title) < 2:
                continue
            
            # Get cover
            img = item.select_one('img')
            cover_url = None
            if img:
                cover_url = img.get('src') or img.get('data-src')
            
            results.append(Manga(
                title=title,
                url=full_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        for link in soup.select('.chapter-name, a.chapter-name, .row-content-chapter a'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' not in href.lower() and 'chapter-' not in href.lower():
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            text = link.get('title') or link.get_text(strip=True)
            
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text or f"Chapter {chapter_num}",
                    url=full_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        for img in soup.select('.container-chapter-reader img, .reader-content img, img[src*="chapmanganato"], img[src*="manganato"]'):
            src = img.get('src') or img.get('data-src')
            if src and src not in pages:
                if 'logo' in src.lower():
                    continue
                pages.append(src)
        
        return pages
