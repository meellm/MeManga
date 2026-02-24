"""
ReadSlamDunkOnline scraper (read-slamdunk.online) - Slam Dunk dedicated site.

WordPress-based with cdn.mangaclash.com CDN for images.
Uses wp-manga-chapter-img class for page images.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadSlamDunkOnlineScraper(BaseScraper):
    """Scraper for read-slamdunk.online - Slam Dunk manga."""
    
    name = "readslamdunkonline"
    base_url = "https://read-slamdunk.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title="Slam Dunk",
            url=f"{self.base_url}/",
            cover_url="https://read-slamdunk.online/wp-content/uploads/2023/03/cropped-339-3392153_sakuragi-hanamichi-slam-dunk-removebg-preview-192x192.png",
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - format: /manga/slam-dunk-chapter-N/
        for link in soup.select("a[href*='/manga/slam-dunk-chapter-']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            text = link.get_text(strip=True)
            if not text:
                continue
            
            # Make absolute
            if not href.startswith("http"):
                href = self.base_url + href if href.startswith("/") else self.base_url + "/" + href
            
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            number = match.group(1) if match else "0"
            
            # Clean up title
            title = text.strip()
            if not title or "Chapter" not in title:
                title = f"Chapter {number}"
            
            chapters.append(Chapter(
                number=number,
                title=title,
                url=href,
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from the chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find images with class wp-manga-chapter-img
        for img in soup.select("img.wp-manga-chapter-img"):
            # Check src, data-src, data-lazy-src
            url = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy-src", "")
            url = url.strip()
            
            if not url or url.startswith("data:"):
                continue
            
            # Only accept images from mangaclash CDN
            if "mangaclash.com" in url or "cdn." in url:
                if url not in seen:
                    seen.add(url)
                    pages.append(url)
        
        # Fallback: try og:image meta tag
        if not pages:
            for meta in soup.select('meta[property="og:image"]'):
                url = meta.get("content", "").strip()
                if url and "mangaclash.com" in url:
                    if url not in seen:
                        seen.add(url)
                        pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image from CDN."""
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
