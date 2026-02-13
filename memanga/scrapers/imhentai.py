"""
IMHentai.xxx scraper
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class IMHentaiScraper(BaseScraper):
    """Scraper for imhentai.xxx (doujin gallery site)"""
    
    name = "imhentai"
    base_url = "https://imhentai.xxx"
    
    def search(self, query: str) -> List[Manga]:
        """Search for galleries."""
        url = f"{self.base_url}/search/?key={query}&page=1"
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
                
                # Get title
                title_el = link.select_one(".caption, .title")
                title = title_el.get_text(strip=True) if title_el else f"Gallery {gallery_id}"
                
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
        match = re.search(r"/gallery/(\d+)", chapter_url)
        if not match:
            return []
        
        gallery_id = match.group(1)
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        thumbs = soup.select(".thumb img, .gallery_thumb img, img[data-src]")
        
        for thumb in thumbs:
            src = thumb.get("data-src") or thumb.get("src")
            if src and "imhentai" in src and "/cover" not in src:
                # Convert thumbnail to full image
                # Thumbnail: m10.imhentai.xxx/031/{hash}/{page}t.jpg
                # Full: m10.imhentai.xxx/031/{hash}/{page}.webp
                full_src = re.sub(r"(\d+)t\.(jpg|png|gif)", r"\1.webp", src)
                pages.append(full_src)
        
        return pages
    
    def get_pages_via_viewer(self, chapter_url: str) -> List[str]:
        """Get pages by fetching viewer pages (more reliable but slower)."""
        match = re.search(r"/gallery/(\d+)", chapter_url)
        if not match:
            return []
        
        gallery_id = match.group(1)
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Count pages
        thumbs = soup.select(".thumb img, img[data-src*='imhentai']")
        # Filter out cover
        thumbs = [t for t in thumbs if "/cover" not in (t.get("data-src") or t.get("src") or "")]
        page_count = len(thumbs)
        
        pages = []
        for i in range(1, page_count + 1):
            view_url = f"{self.base_url}/view/{gallery_id}/{i}/"
            try:
                view_html = self._get_html(view_url)
                view_soup = BeautifulSoup(view_html, "html.parser")
                img = view_soup.select_one("img[src*='imhentai'][src$='.webp']")
                if img:
                    src = img.get("src")
                    if src:
                        pages.append(src)
            except Exception:
                continue
        
        return pages
