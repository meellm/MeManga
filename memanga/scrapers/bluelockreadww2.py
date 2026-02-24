"""
BlueLockReadWW2 scraper (ww2.bluelockread.com) - Blue Lock dedicated site.
Custom theme + cdn.bluelockread.com CDN.
"""

import re
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

from .base import BaseScraper, Manga, Chapter


class BlueLockReadWW2Scraper(BaseScraper):
    """Scraper for ww2.bluelockread.com - Blue Lock manga."""
    
    name = "bluelockreadww2"
    base_url = "https://ww2.bluelockread.com"
    
    def __init__(self):
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.base_url
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga - this is a Blue Lock focused site."""
        query_lower = query.lower()
        
        results = []
        
        if 'blue lock' in query_lower or 'bluelock' in query_lower:
            results.append(Manga(
                id="blue-lock",
                title="Blue Lock",
                url=f"{self.base_url}/",
                cover="https://i.imgur.com/U3gLdw0.png"
            ))
        
        if 'nagi' in query_lower or 'episode nagi' in query_lower:
            results.append(Manga(
                id="blue-lock-episode-nagi",
                title="Blue Lock: Episode Nagi",
                url=f"{self.base_url}/",
                cover=""
            ))
        
        if not results and ('blue' in query_lower or 'lock' in query_lower):
            results = [
                Manga(id="blue-lock", title="Blue Lock", url=f"{self.base_url}/", cover=""),
                Manga(id="blue-lock-episode-nagi", title="Blue Lock: Episode Nagi", url=f"{self.base_url}/", cover="")
            ]
        
        return results
    
    def get_chapters(self, manga_id: str) -> list[Chapter]:
        """Get list of chapters for a manga."""
        # Use the manga page which has the full chapter list
        if 'nagi' in manga_id:
            url = f"{self.base_url}/manga/blue-lock-episode-nagi/"
        else:
            url = f"{self.base_url}/manga/blue-lock/"
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        chapters = []
        seen_urls = set()
        
        # Determine which series we're looking for
        is_nagi = 'nagi' in manga_id
        
        # Find chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Filter by series
            if is_nagi:
                if '/chapter/blue-lock-episode-nagi-chapter-' not in href:
                    continue
            else:
                if '/chapter/blue-lock-chapter-' not in href:
                    continue
                if '/chapter/blue-lock-episode-nagi-' in href:
                    continue
            
            if href in seen_urls:
                continue
            seen_urls.add(href)
            
            # Extract chapter number
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
            if match:
                chapter_num = match.group(1)
                title = link.get_text(strip=True) or f"Chapter {chapter_num}"
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=title,
                    url=href
                ))
        
        # Sort by chapter number
        chapters.sort(key=lambda c: c.number)
        return chapters
    
    def get_pages(self, manga_id: str, chapter_number: str) -> list[str]:
        """Get list of page image URLs for a chapter."""
        # Build URL based on series
        if 'nagi' in manga_id:
            url = f"{self.base_url}/chapter/blue-lock-episode-nagi-chapter-{chapter_number}/"
        else:
            url = f"{self.base_url}/chapter/blue-lock-chapter-{chapter_number}/"
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        pages = []
        seen_urls = set()
        
        # Find images from cdn.bluelockread.com
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('src', '')
            if 'cdn.bluelockread.com' in src and src not in seen_urls:
                seen_urls.add(src)
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, chapter_url: str = None) -> bytes:
        """Download an image with proper headers."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': self.base_url
        }
        
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.content
