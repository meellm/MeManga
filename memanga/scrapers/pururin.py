"""
Pururin scraper - Doujin/hentai gallery site
Site: pururin.to

Uses Playwright for JS redirect handling.
NSFW content.
"""

import re
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class PururinScraper(PlaywrightScraper):
    """Scraper for Pururin (doujin gallery)."""
    
    name = "pururin"
    base_url = "https://pururin.to"
    
    def search(self, query: str) -> List[Manga]:
        """Search for doujin."""
        search_url = f"{self.base_url}/search?q={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Gallery items
        for item in soup.select('.gallery-item, .gallery, .card'):
            link = item.select_one('a[href*="/gallery/"]')
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            
            # Get title
            title_el = item.select_one('.title, h3, h4, .card-title')
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
        """
        Get chapters - for gallery sites, each gallery is one "chapter".
        Returns a single chapter representing the full gallery.
        """
        # Extract gallery ID from URL
        match = re.search(r'/gallery/(\d+)', manga_url)
        gallery_id = match.group(1) if match else "1"
        
        return [Chapter(
            number="1",
            title="Full Gallery",
            url=manga_url,
        )]
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a gallery."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Try to find gallery images
        for img in soup.select('.gallery-image img, .page-img, img[data-src*="cdn"]'):
            src = img.get('src') or img.get('data-src')
            if src and src not in pages:
                pages.append(src)
        
        # If no direct images, look for thumbnail links to full images
        if not pages:
            for link in soup.select('a[href*="/read/"], a[href*="/view/"]'):
                href = link.get('href', '')
                if href:
                    # Try to extract full image URL from page
                    full_url = href if href.startswith('http') else f"{self.base_url}{href}"
                    try:
                        page_html = self._get_page_content(full_url, wait_time=2000)
                        page_soup = BeautifulSoup(page_html, 'html.parser')
                        img = page_soup.select_one('img[src*="cdn"], .main-image img')
                        if img:
                            src = img.get('src') or img.get('data-src')
                            if src and src not in pages:
                                pages.append(src)
                    except:
                        pass
        
        return pages
