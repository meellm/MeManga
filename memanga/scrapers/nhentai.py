"""
NHentai.net scraper
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class NHentaiScraper(BaseScraper):
    """Scraper for nhentai.net (doujin gallery site)"""
    
    name = "nhentai"
    base_url = "https://nhentai.net"
    
    def search(self, query: str) -> List[Manga]:
        """Search for galleries."""
        url = f"{self.base_url}/search/?q={query}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for gallery in soup.select(".gallery a.cover"):
            href = gallery.get("href", "")
            caption = gallery.select_one(".caption")
            title = caption.get_text(strip=True) if caption else ""
            
            if href and title:
                gallery_url = self.base_url + href if href.startswith("/") else href
                # Extract cover image
                cover_img = gallery.select_one("img")
                cover = None
                if cover_img:
                    cover = cover_img.get("data-src") or cover_img.get("src")
                    if cover and cover.startswith("//"):
                        cover = "https:" + cover
                
                results.append(Manga(title=title, url=gallery_url, cover_url=cover))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """For doujin sites, return a single 'chapter' representing the gallery."""
        # Extract gallery ID from URL
        match = re.search(r"/g/(\d+)", manga_url)
        if match:
            gallery_id = match.group(1)
            return [Chapter(number="1", title=f"Gallery {gallery_id}", url=manga_url)]
        return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images from a gallery."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        # Find thumbnails and convert to full images
        # Thumbnail: t{n}.nhentai.net/galleries/{id}/{page}t.{ext}
        # Full: i{n}.nhentai.net/galleries/{id}/{page}.{ext}
        
        for img in soup.select(".thumb-container img, .gallerythumb img"):
            src = img.get("data-src") or img.get("src")
            if src and "nhentai.net" in src:
                # Convert thumbnail URL to full image URL
                # Replace t{n} with i{n} and remove 't' before extension
                full_src = re.sub(r"//t(\d+)\.", r"//i\1.", src)
                full_src = re.sub(r"(\d+)t\.(jpg|png|gif|webp)", r"\1.\2", full_src)
                # Remove double extensions like .webp.webp
                full_src = re.sub(r"\.(webp|jpg|png)\.\1", r".\1", full_src)
                
                if full_src.startswith("//"):
                    full_src = "https:" + full_src
                pages.append(full_src)
        
        return pages
