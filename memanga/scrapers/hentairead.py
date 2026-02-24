"""
HentaiRead scraper - Hentai manga reader
Site: hentairead.com

Uses Playwright for JS handling.
NSFW content.
"""

import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class HentaiReadScraper(PlaywrightScraper):
    """Scraper for HentaiRead."""
    
    name = "hentairead"
    base_url = "https://hentairead.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/?s={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=6000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Search results
        for item in soup.select('.gallery, .item, article, .manga-item'):
            link = item.select_one('a[href*="/hentai/"], a[href*="/manga/"]')
            if not link:
                link = item.select_one('a[href]')
            
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' in href or '/page/' in href:
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            
            # Get title
            title_el = item.select_one('.title, h3, h4, h2')
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
        """Get chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Look for chapter links
        for link in soup.select('a[href*="/chapter"], a[href*="/read/"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            text = link.get_text(strip=True)
            
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', text)
            
            chapter_num = match.group(1) if match else "1"
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=full_url,
            ))
        
        # If no chapters found, the manga itself is the chapter (like doujin)
        if not chapters:
            chapters.append(Chapter(
                number="1",
                title="Full",
                url=manga_url,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs."""
        html = self._get_page_content(chapter_url, wait_time=6000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Look for manga page images
        for img in soup.select('.reading-content img, .page-img, .chapter-img, img[class*="page"]'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and src not in pages:
                if 'logo' in src.lower() or 'icon' in src.lower():
                    continue
                if src.startswith('//'):
                    src = 'https:' + src
                pages.append(src.strip())
        
        # Fallback: any images in reading area
        if not pages:
            for img in soup.select('img'):
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                if any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'thumb']):
                    continue
                
                # Must be a content image (usually from CDN)
                if 'cdn' in src.lower() or 'img' in src.lower() or 'manga' in src.lower():
                    if src not in pages:
                        pages.append(src)
        
        return pages
