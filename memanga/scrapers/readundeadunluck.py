"""
ReadUndeadUnluck scraper (readundeadunluck.com) - Undead Unluck dedicated site.

Uses WordPress with Blogger CDN images (blogger.googleusercontent.com).
Images use data-lazy-src attribute in separator divs.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadUndeadUnluckScraper(BaseScraper):
    """Scraper for readundeadunluck.com - Undead Unluck manga."""
    
    name = "readundeadunluck"
    base_url = "https://readundeadunluck.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Undead Unluck",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links
        for link in soup.find_all("a", href=re.compile(r'undead-unluck-chapter', re.I)):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            
            # Skip if no chapter text
            if not text:
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href, re.I)
                text = f"Chapter {match.group(1)}" if match else "Chapter"
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number
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
        
        # Find images in separator divs - they use data-lazy-src
        for div in soup.find_all("div", class_="separator"):
            for img in div.find_all("img"):
                # Try data-lazy-src first, then src
                src = img.get("data-lazy-src") or img.get("src") or ""
                src = src.strip()
                
                # Skip placeholder images
                if "data:image" in src or not src:
                    continue
                
                # Accept images from Blogger CDN
                if "blogger.googleusercontent.com" in src and src not in seen:
                    seen.add(src)
                    pages.append(src)
        
        # If separator divs didn't work, try all images
        if not pages:
            for img in soup.find_all("img"):
                src = img.get("data-lazy-src") or img.get("src") or ""
                src = src.strip()
                
                if "data:image" in src or not src:
                    continue
                
                if "blogger.googleusercontent.com" in src and src not in seen:
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
