"""
ReadBlackLagoon scraper (readblacklagoon.com) - Black Lagoon dedicated site.

Uses WordPress Mangosm theme, images hosted on img.mangarchive.com.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadBlackLagoonScraper(BaseScraper):
    """Scraper for readblacklagoon.com - Black Lagoon manga."""
    
    name = "readblacklagoon"
    base_url = "https://readblacklagoon.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Black Lagoon",
            url=f"{self.base_url}/",
            cover_url="https://mangarchive.com/wp-content/uploads/2025/09/227037l.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from homepage."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links in the select dropdown or navigation
        for link in soup.select("option[value*='black-lagoon-chapter'], a[href*='black-lagoon-chapter']"):
            href = link.get("value") or link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                if not href.startswith("/"):
                    href = "/" + href
                href = self.base_url + href
            
            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
            number = match.group(1) if match else "0"
            
            chapters.append(Chapter(
                number=number,
                title=text if text else f"Chapter {number}",
                url=href,
            ))
        
        # Also try to find chapters in any chapter list
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            if "/comic/black-lagoon-chapter-" in href:
                seen.add(href)
                
                text = link.get_text(strip=True)
                if not text:
                    continue
                
                if not href.startswith("http"):
                    href = self.base_url + href
                
                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
                number = match.group(1) if match else "0"
                
                chapters.append(Chapter(
                    number=number,
                    title=text if text else f"Chapter {number}",
                    url=href,
                ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images from img.mangarchive.com
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            
            if "img.mangarchive.com" in src or "mangarchive.com/images" in src:
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
