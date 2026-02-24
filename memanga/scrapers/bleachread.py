"""
BleachRead scraper (bleach-read.com) - Bleach dedicated site.

Uses WordPress, images hosted on Blogger CDN (blogger.googleusercontent.com).
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BleachReadScraper(BaseScraper):
    """Scraper for bleach-read.com - Bleach manga."""
    
    name = "bleachread"
    base_url = "https://w38.bleach-read.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Bleach",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/bleach-chapter-X/)
        for link in soup.select("a[href*='bleach-chapter-']"):
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
            
            # Extract chapter number (format: bleach-chapter-687)
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href.lower())
            number = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from Blogger CDN."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images inside div.separator (Blogger-style layout)
        for div in soup.select("div.separator"):
            # Get high-res version from the anchor link
            a = div.find("a")
            if a:
                href = a.get("href", "")
                if "blogger.googleusercontent.com" in href:
                    if href not in seen:
                        seen.add(href)
                        pages.append(href)
                    continue
            
            # Fallback to img src
            img = div.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if "blogger.googleusercontent.com" in src:
                    if src not in seen:
                        seen.add(src)
                        pages.append(src)
        
        # Also check for any direct img tags with blogger URLs
        if not pages:
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if "blogger.googleusercontent.com" in src:
                    if src not in seen:
                        seen.add(src)
                        pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from Blogger CDN."""
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
