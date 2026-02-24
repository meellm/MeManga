"""
Toonily scraper - Korean manhwa/webtoon site (toonily.me)
Uses Playwright with stealth for bypass.

Toonily uses a React/Next.js frontend with relative links.
"""

import re
from typing import List
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class ToonilyScraper(PlaywrightScraper):
    """Scraper for Toonily (toonily.me)."""
    
    name = "toonily"
    base_url = "https://toonily.me"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/?s={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_slugs = set()
        
        # Toonily uses .book-item containers with relative links
        for item in soup.select('.book-item'):
            link = item.select_one('a[href]')
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen_slugs:
                continue
            
            # Skip non-manga pages
            if any(x in href for x in ['/chapter', '/auth/', '/genre/', '/page/']):
                continue
            
            # Get slug
            slug = href.strip('/')
            if '/' in slug or not slug:  # Skip sub-paths
                continue
            
            seen_slugs.add(href)
            
            full_url = f"{self.base_url}/{slug}"
            
            # Get title - look in title element or img alt
            title_el = item.select_one('.title, .name, h3, h4')
            title = title_el.get_text(strip=True) if title_el else ''
            
            if not title:
                # Try img alt
                img = item.select_one('img')
                if img:
                    title = img.get('alt', '') or img.get('title', '')
            
            if not title:
                # Try link title
                title = link.get('title', '')
            
            if not title:
                # Use slug as fallback
                title = slug.replace('-', ' ').title()
            
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
        
        # Fallback: look for any links that look like manga
        if not results:
            for link in soup.select('a[href^="/"]'):
                href = link.get('href', '')
                slug = href.strip('/')
                
                if not slug or '/' in slug:
                    continue
                if any(x in slug for x in ['auth', 'genre', 'page', 'chapter', 'search']):
                    continue
                if slug in seen_slugs:
                    continue
                
                seen_slugs.add(slug)
                
                img = link.select_one('img')
                title = ''
                
                if img:
                    title = img.get('alt', '') or img.get('title', '')
                
                if not title:
                    title = link.get('title', '') or slug.replace('-', ' ').title()
                
                results.append(Manga(
                    title=title,
                    url=f"{self.base_url}/{slug}",
                    cover_url=img.get('src') if img else None,
                ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Extract slug from URL for matching
        slug_match = re.search(r'toonily\.me/([^/]+)', manga_url)
        slug = slug_match.group(1) if slug_match else ''
        
        # Look for chapter links
        for link in soup.select('a[href*="chapter"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            seen.add(href)
            
            # Build full URL
            full_url = href
            if href.startswith('/'):
                full_url = f"{self.base_url}{href}"
            elif not href.startswith('http'):
                full_url = f"{self.base_url}/{href}"
            
            text = link.get('title') or link.get_text(strip=True)
            
            # Extract chapter number
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
                    url=full_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Look for chapter images in various containers
        for img in soup.select('.reading-content img, .chapter-content img, .page-break img, img[class*="chapter"]'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and src not in pages:
                # Skip non-content images
                if any(x in src.lower() for x in ['logo', 'avatar', 'icon', 'loading', 'thumb']):
                    continue
                
                # Clean up URL
                src = src.strip()
                if src.startswith('//'):
                    src = 'https:' + src
                
                pages.append(src)
        
        # Fallback: look for any large images
        if not pages:
            for img in soup.select('img'):
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                
                # Skip small images
                width = img.get('width', '')
                if width and str(width).isdigit() and int(width) < 200:
                    continue
                
                # Skip UI images
                if any(x in src.lower() for x in ['logo', 'avatar', 'icon', 'loading', 'thumb']):
                    continue
                
                if src not in pages:
                    if src.startswith('//'):
                        src = 'https:' + src
                    pages.append(src)
        
        return pages
