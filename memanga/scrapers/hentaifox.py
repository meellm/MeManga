"""
HentaiFox.com scraper
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class HentaiFoxScraper(BaseScraper):
    """Scraper for hentaifox.com (doujin gallery site)"""
    
    name = "hentaifox"
    base_url = "https://hentaifox.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for galleries."""
        url = f"{self.base_url}/search/?q={query}&page=1"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_ids = set()
        
        for link in soup.select("a[href*='/gallery/']"):
            href = link.get("href", "")
            match = re.search(r"/gallery/(\d+)", href)
            if match:
                gallery_id = match.group(1)
                if gallery_id in seen_ids:
                    continue
                seen_ids.add(gallery_id)
                
                # Get title from caption or parent
                title_el = link.select_one(".caption, .g_title")
                if not title_el:
                    title_el = link
                title = title_el.get_text(strip=True) or f"Gallery {gallery_id}"
                
                gallery_url = self.base_url + f"/gallery/{gallery_id}/"
                results.append(Manga(title=title, url=gallery_url))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Return single chapter for gallery."""
        match = re.search(r"/gallery/(\d+)", manga_url)
        if match:
            gallery_id = match.group(1)
            return [Chapter(number="1", title=f"Gallery {gallery_id}", url=manga_url)]
        return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images from a gallery."""
        # Extract gallery ID
        match = re.search(r"/gallery/(\d+)", chapter_url)
        if not match:
            return []
        
        gallery_id = match.group(1)
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        # Get page count from thumbnails
        thumbs = soup.select(".g_thumb img, .gallery_thumb img")
        
        for i, thumb in enumerate(thumbs, 1):
            src = thumb.get("data-src") or thumb.get("src")
            if src:
                # Convert thumbnail to full image
                # Thumbnail: i3.hentaifox.com/004/{id}/{page}t.jpg
                # Full: i3.hentaifox.com/004/{id}/{page}.webp (from reading page)
                # Get the reading page to find actual image URL
                pass
        
        # Alternative: fetch each reading page
        # But that's slow. Instead, use the thumbnail pattern
        # and try webp format
        for i, thumb in enumerate(thumbs, 1):
            src = thumb.get("data-src") or thumb.get("src")
            if src and "hentaifox.com" in src:
                # Try to construct full image URL
                # Pattern observed: thumbnails are {page}t.jpg, full images are {page}.webp
                full_src = re.sub(r"(\d+)t\.(jpg|png|gif)", r"\1.webp", src)
                pages.append(full_src)
        
        return pages
    
    def get_pages_slow(self, chapter_url: str) -> List[str]:
        """Get pages by fetching each reading page (slower but more reliable)."""
        match = re.search(r"/gallery/(\d+)", chapter_url)
        if not match:
            return []
        
        gallery_id = match.group(1)
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Count pages from thumbnails
        thumbs = soup.select(".g_thumb img, .gallery_thumb img")
        page_count = len(thumbs)
        
        pages = []
        for i in range(1, page_count + 1):
            page_url = f"{self.base_url}/g/{gallery_id}/{i}/"
            try:
                page_html = self._get_html(page_url)
                page_soup = BeautifulSoup(page_html, "html.parser")
                img = page_soup.select_one("img[data-src*='hentaifox'], img[src*='hentaifox']")
                if img:
                    src = img.get("data-src") or img.get("src")
                    if src:
                        pages.append(src)
            except Exception:
                continue
        
        return pages
