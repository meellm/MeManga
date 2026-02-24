"""
BlueExorcistManga scraper (blueexorcistmanga.com) - Blue Exorcist / Ao no Exorcist dedicated site.

Uses WordPress with manga theme, images hosted on cdn.readkakegurui.com.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BlueExorcistMangaScraper(BaseScraper):
    """Scraper for blueexorcistmanga.com - Blue Exorcist manga."""
    
    name = "blueexorcistmanga"
    base_url = "https://blueexorcistmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Blue Exorcist (Ao no Exorcist)",
            url=f"{self.base_url}/home/",
            cover_url=f"{self.base_url}/wp-content/uploads/2023/10/Blue-Exorcist-cover.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the manga page."""
        html = self._get_html(f"{self.base_url}/home/")
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/ao-no-exorcist-chapter-X/)
        for link in soup.select("a[href*='ao-no-exorcist-chapter']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:[.-]\d+)?)', href.lower())
            number = match.group(1).replace("-", ".") if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from cdn.readkakegurui.com."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images from cdn.readkakegurui.com in separator divs
        for div in soup.select("div.separator"):
            img = div.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or ""
                src = src.strip()
                
                if "cdn.readkakegurui.com" in src:
                    if src not in seen:
                        seen.add(src)
                        pages.append(src)
        
        # Fallback: check all images
        if not pages:
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                src = src.strip()
                
                if "cdn.readkakegurui.com" in src:
                    if src not in seen:
                        seen.add(src)
                        pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
