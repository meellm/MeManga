"""
AZManga scraper
https://azmanga.com

Manga/manhwa/webtoon library using WordPress Madara theme.
Chapters are loaded via AJAX POST.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class AZMangaScraper(BaseScraper):
    """Scraper for AZManga.com"""
    
    name = "azmanga"
    base_url = "https://azmanga.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        # WordPress Madara search results
        for link in soup.select(".post-title a, h3 a, h4 a"):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            
            if not href or not title or href in seen_urls:
                continue
            if "/manga/" not in href:
                continue
            seen_urls.add(href)
            
            # Get cover image from parent container
            cover_url = None
            parent = link.find_parent(class_="row") or link.find_parent(class_="c-tabs-item") or link.find_parent(class_="page-item-detail")
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=href, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga using AJAX."""
        from bs4 import BeautifulSoup
        
        # Madara theme loads chapters via AJAX POST to manga_url/ajax/chapters/
        ajax_url = manga_url.rstrip('/') + '/ajax/chapters/'
        
        try:
            response = self.session.post(
                ajax_url,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": manga_url,
                },
                timeout=30
            )
            response.raise_for_status()
            html = response.text
        except Exception as e:
            print(f"AJAX chapters failed: {e}")
            # Fallback: try to get chapters from main page
            html = self._get_html(manga_url)
        
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen_urls = set()
        
        for link in soup.select("li a, .wp-manga-chapter a"):
            href = link.get("href", "")
            
            if not href or href in seen_urls or href == "#":
                continue
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                continue
                
            seen_urls.add(href)
            chapter_text = link.get_text(strip=True)
            chapter_num = match.group(1)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=href,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # WordPress Madara reader images
        for img in soup.select(".reading-content img, .page-break img, img.wp-manga-chapter-img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if src:
                src = src.strip()
                if src not in seen and any(ext in src.lower() for ext in ['.jpg', '.png', '.webp', '.jpeg', '.gif']):
                    seen.add(src)
                    pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
