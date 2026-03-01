"""
ReadJJK.com Scraper

JJK (Jujutsu Kaisen) dedicated manga site.
- WordPress Kadence Blocks theme with LiteSpeed cache
- Images hosted on img.read-jjk.com CDN
- All 271 chapters of JJK manga
"""

import re
import cloudscraper
from pathlib import Path
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadJJKComScraper(BaseScraper):
    """Scraper for read-jjk.com - Jujutsu Kaisen dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://read-jjk.com"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga (JJK only site)."""
        results = []
        if any(term in query.lower() for term in ["jujutsu", "kaisen", "jjk", "gojo", "sukuna", "itadori"]):
            results.append(Manga(
                title="Jujutsu Kaisen",
                url=f"{self.base_url}/",
                cover_url="https://img.read-jjk.com/uploads/cropped-jjk-cover-yuji-192x192.webp",
            ))
        return results
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get list of chapters."""
        chapters = []
        
        # Fetch homepage to get chapter list
        resp = self.session.get(self.base_url)
        if resp.status_code != 200:
            return chapters
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find chapter links - they're in article elements with href to /manga/jujutsu-kaisen-chapter-N/
        for article in soup.select("article.kt-blocks-post-grid-item"):
            link = article.select_one("a[href*='/manga/jujutsu-kaisen-chapter-']")
            if link:
                title = link.get_text(strip=True)
                url = link.get("href", "")
                
                # Extract chapter number from title or URL
                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', title, re.IGNORECASE) or \
                        re.search(r'chapter-(\d+(?:\.\d+)?)', url)
                if match:
                    chapter_num = match.group(1)
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title or f"Chapter {chapter_num}",
                        url=url,
                    ))
        
        # Remove duplicates and sort
        seen = set()
        unique_chapters = []
        for ch in chapters:
            if ch.url not in seen:
                seen.add(ch.url)
                unique_chapters.append(ch)
        
        # Sort by chapter number (ascending)
        unique_chapters.sort(key=lambda c: float(c.number) if c.number else 0)
        
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get list of page image URLs for a chapter."""
        pages = []
        
        resp = self.session.get(chapter_url)
        if resp.status_code != 200:
            return pages
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Images are in Kadence gallery items with lazy loading
        # Look for data-src, data-full-image, or src attributes
        for gallery_item in soup.select(".kadence-blocks-gallery-item img"):
            # Try different attributes for the image URL
            img_url = (
                gallery_item.get("data-src") or
                gallery_item.get("data-full-image") or
                gallery_item.get("src")
            )
            
            if img_url and "img.read-jjk.com" in img_url:
                pages.append(img_url)
        
        # Also check for images with data-lazyloaded attribute
        if not pages:
            for img in soup.select("img[data-src*='img.read-jjk.com']"):
                img_url = img.get("data-src")
                if img_url:
                    pages.append(img_url)
        
        return pages
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            if len(resp.content) < 1000:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(resp.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
