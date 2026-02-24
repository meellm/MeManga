"""
ReadKenganAshura scraper (read-kengan-ashura.com) - Kengan Ashura dedicated site.

Uses WordPress Comic Easel plugin with Toivo Lite theme, images hosted on Blogger CDN.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadKenganAshuraScraper(BaseScraper):
    """Scraper for read-kengan-ashura.com - Kengan Ashura manga."""
    
    name = "readkenganashura"
    base_url = "https://read-kengan-ashura.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site - Kengan Ashura)."""
        return [Manga(
            title="Kengan Ashura",
            url=f"{self.base_url}/manga/kengan-ashura/",
            cover_url="https://read-kengan-ashura.com/wp-content/uploads/2022/06/kengan-ashura-1.jpg",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        # Home page has all chapters, manga page only shows recent
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - pattern: /comic/kengan-ashura-manga-vol-XX-chapter-XX-title/
        # Also match chapter-X-asura patterns (like chapter-1-asura)
        for link in soup.find_all("a", href=re.compile(r'comic/kengan-ashura.*chapter', re.I)):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            
            # Skip non-chapter URLs
            if "oembed" in href or "tag/" in href:
                continue
            
            seen.add(href)
            
            text = link.get_text(strip=True)
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href
            
            # Extract chapter number - handle formats like:
            # chapter-236-finale, chapter-229-5-eating, chapter-1-asura
            match = re.search(r'chapter-(\d+(?:-\d+)?)', href.lower())
            if match:
                raw = match.group(1)
                # Convert chapter-229-5 to 229.5
                if '-' in raw:
                    parts = raw.split('-')
                    number = f"{parts[0]}.{parts[1]}"
                else:
                    number = raw
            else:
                number = "0"
            
            if not text:
                text = f"Chapter {number}"
            
            chapters.append(Chapter(
                number=number,
                title=text,
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
        
        # Find images - WordPress Comic Easel stores images in entry-content
        # Images are on Blogger CDN (bp.blogspot.com)
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            src = src.strip()
            
            # Skip placeholder/ad images
            if not src or "data:image" in src:
                continue
            
            # Accept images from blogspot CDN
            if "blogspot.com" in src and src not in seen:
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
