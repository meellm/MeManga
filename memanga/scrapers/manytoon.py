"""
ManyToon scraper - Adult manhwa/webtoons
Site: manytoon.com

Uses Playwright for JS chapter loading.
Adult content warning.
"""

import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class ManyToonScraper(PlaywrightScraper):
    """Scraper for ManyToon."""
    
    name = "manytoon"
    base_url = "https://manytoon.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/?s={quote(query)}&post_type=wp-manga"
        
        html = self._get_page_content(search_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Search results in various formats
        for item in soup.select('.c-tabs-item__content, .search-wrap, .page-item-detail, .manga-item'):
            link = item.select_one('a[href*="/comic/"], a[href*="/manga/"]')
            if not link:
                link = item.select_one('a[href]')
            
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' in href or not ('comic' in href or 'manga' in href):
                continue
            
            seen.add(href)
            
            # Get title
            title_el = item.select_one('.post-title, h3, h4, .item-title, .series-title')
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
                cover_url = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            
            results.append(Manga(
                title=title,
                url=href,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=6000)  # Extra wait for JS
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Chapter links
        for link in soup.select('.wp-manga-chapter a, .chapter-link, a[href*="chapter"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            if '/chapter' not in href.lower():
                continue
            
            seen.add(href)
            text = link.get_text(strip=True)
            
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
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
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=6000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        for img in soup.select('.reading-content img, .page-break img, .wp-manga-chapter-img, .chapter-images img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and src not in pages:
                if 'logo' in src.lower() or 'icon' in src.lower():
                    continue
                if src.startswith('//'):
                    src = 'https:' + src
                pages.append(src.strip())
        
        return pages
