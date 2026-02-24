"""
E-Hentai.org scraper
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga


class EHentaiScraper(BaseScraper):
    """Scraper for e-hentai.org (doujin gallery site)"""
    
    name = "ehentai"
    base_url = "https://e-hentai.org"
    
    def search(self, query: str) -> List[Manga]:
        """Search for galleries."""
        url = f"{self.base_url}/?f_search={query}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        for link in soup.select("a[href*='/g/']"):
            href = link.get("href", "")
            # E-hentai URLs: /g/{id}/{token}/
            match = re.search(r"/g/(\d+)/([a-f0-9]+)", href)
            if match:
                gallery_id = match.group(1)
                if gallery_id in seen:
                    continue
                seen.add(gallery_id)
                
                # Get title
                title = link.get_text(strip=True)
                if not title or len(title) < 3:
                    # Try to find title in parent row
                    row = link.find_parent("tr")
                    if row:
                        title_cell = row.select_one(".glink, .gl3m a, .gl4t a")
                        if title_cell:
                            title = title_cell.get_text(strip=True)
                
                if not title:
                    title = f"Gallery {gallery_id}"
                
                gallery_url = href if href.startswith("http") else self.base_url + href
                results.append(Manga(title=title, url=gallery_url))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Return single chapter for gallery."""
        match = re.search(r"/g/(\d+)/", manga_url)
        if match:
            gallery_id = match.group(1)
            return [Chapter(number="1", title=f"Gallery {gallery_id}", url=manga_url)]
        return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images from a gallery.
        
        E-hentai requires fetching each page viewer to get the actual image URL.
        The image URLs are unique per request and include auth tokens.
        """
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Find all page viewer links
        page_links = []
        for link in soup.select("a[href*='/s/']"):
            href = link.get("href", "")
            if "/s/" in href and href not in page_links:
                page_links.append(href)
        
        # Also check for pagination (galleries with many pages)
        # E-hentai shows 40 thumbnails per page
        next_page = soup.select_one("a[onclick*='nl'][href*='?p=']")
        page_num = 1
        while next_page and page_num < 10:  # Limit to 400 pages
            page_num += 1
            next_url = chapter_url.rstrip("/") + f"?p={page_num-1}"
            try:
                next_html = self._get_html(next_url)
                next_soup = BeautifulSoup(next_html, "html.parser")
                for link in next_soup.select("a[href*='/s/']"):
                    href = link.get("href", "")
                    if "/s/" in href and href not in page_links:
                        page_links.append(href)
                next_page = next_soup.select_one(f"a[onclick*='nl'][href*='?p={page_num}']")
            except Exception:
                break
        
        # Fetch each page to get image URL
        pages = []
        for page_url in page_links:
            try:
                if not page_url.startswith("http"):
                    page_url = self.base_url + page_url
                page_html = self._get_html(page_url)
                page_soup = BeautifulSoup(page_html, "html.parser")
                
                # Main image is in #img or i3
                img = page_soup.select_one("#img, #i3 img")
                if img:
                    src = img.get("src")
                    if src and not src.endswith(".gif"):  # Skip loading gifs
                        pages.append(src)
            except Exception:
                continue
        
        return pages
