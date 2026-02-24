"""
BananaFishManga scraper (bananafishmanga.com) - Banana Fish dedicated site.

Uses WordPress with a custom theme, images hosted on official.lowee.us CDN.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BananaFishMangaScraper(BaseScraper):
    """Scraper for bananafishmanga.com - Banana Fish manga."""
    
    name = "bananafishmanga"
    base_url = "https://www.bananafishmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Banana Fish",
            url=f"{self.base_url}/",
            cover_url="https://www.bananafishmanga.com/wp-content/uploads/2026/01/banana-fish-cover-1-1.webp",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links (format: /manga/banana-fish-chapter-X/)
        for link in soup.select("a[href*='banana-fish-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                # Extract from URL
                match = re.search(r'chapter-(\d+)', href.lower())
                if match:
                    text = f"Chapter {match.group(1)}"
                else:
                    continue
            
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
        """Get all page image URLs from og:image meta tags and data-src."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # First check og:image meta tags (most reliable for this site)
        for meta in soup.select('meta[property="og:image"]'):
            url = meta.get("content", "")
            if url and "lowee.us" in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Also check data-src attributes (lazy-loaded images)
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            src = src.strip()
            
            if "lowee.us" in src:
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
