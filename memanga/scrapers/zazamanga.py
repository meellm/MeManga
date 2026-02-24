"""
ZazaManga scraper - Manga aggregator
Site: zazamanga.com

Uses Playwright for JS rendering.
Multiple series-specific domains redirect here (death note, fairy tail, gintama, etc.)
"""

import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class ZazaMangaScraper(PlaywrightScraper):
    """Scraper for ZazaManga."""
    
    name = "zazamanga"
    base_url = "https://www.zazamanga.com"
    
    # Aliases - series-specific domains that redirect here
    aliases = [
        "deathnotemanga.com",
        "death-note-online.com",
        "fairytail100yearsquest.com",
        "gintama.site",
        "initialdmanga.com",
        "inuyasha.net",
        "onepunchmanmanga.org",
        "readhellsing.com",
        "readoverlord.com",
    ]
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/?s={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Find all manga links
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' in href:
                continue
            
            # Normalize URL
            if href.startswith('/'):
                href = self.base_url + href
            
            seen.add(href)
            
            # Get title from various sources
            title = None
            title_el = link.select_one('.tt, .title, h3, h4')
            if title_el:
                title = title_el.get_text(strip=True)
            if not title:
                title = link.get('title', '') or link.get_text(strip=True)
            
            title = title.strip()
            if not title or len(title) < 2:
                continue
            
            # Get cover
            img = link.select_one('img') or link.find_parent().select_one('img') if link.find_parent() else None
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
        html = self._get_page_content(manga_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - various selectors
        for link in soup.select('a[href*="chapter"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '.css' in href:  # Skip CSS files
                continue
            
            # Normalize URL
            if href.startswith('/'):
                href = self.base_url + href
            
            seen.add(href)
            text = link.get_text(strip=True)
            
            # Extract chapter number from URL or text
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', text, re.I)
            if not match:
                match = re.search(r'ch\.?\s*(\d+\.?\d*)', text, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text or f"Chapter {chapter_num}",
                    url=href,
                ))
        
        # Remove duplicates by chapter number
        unique = {}
        for ch in chapters:
            if ch.number not in unique:
                unique[ch.number] = ch
        
        return sorted(unique.values(), key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Find manga page images
        for img in soup.select('img'):
            src = img.get('src') or img.get('data-src')
            if not src:
                continue
            
            # Filter for actual manga pages (usually from CDN)
            if 'zinmanga' in src or '/chapter/' in src or re.search(r'/\d+\.webp', src):
                if src not in pages:
                    if src.startswith('//'):
                        src = 'https:' + src
                    pages.append(src.strip())
        
        # Also check for any numbered images (1.webp, 2.webp, etc.)
        if not pages:
            for img in soup.select('img'):
                src = img.get('src') or img.get('data-src')
                if src and re.search(r'/\d+\.(webp|jpg|png)', src):
                    if src not in pages:
                        if src.startswith('//'):
                            src = 'https:' + src
                        pages.append(src.strip())
        
        return pages
