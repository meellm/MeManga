"""
GutsBerserk scraper (gutsberserk.com) - Berserk dedicated site.
WordPress Madara theme + img.spoilerhat.com proxy CDN.
"""

import re
from urllib.parse import urljoin, unquote
import cloudscraper
from bs4 import BeautifulSoup

from .base import BaseScraper, Manga, Chapter


class GutsBerserkScraper(BaseScraper):
    """Scraper for gutsberserk.com - Berserk manga."""
    
    name = "gutsberserk"
    base_url = "https://www.gutsberserk.com"
    
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
        """Search for manga - this is a single-manga site."""
        query_lower = query.lower()
        
        # This site only has Berserk
        if 'berserk' in query_lower or 'guts' in query_lower:
            return [Manga(
                id="berserk",
                title="Berserk",
                url=f"{self.base_url}/",
                cover="https://gutsberserk.com/wp-content/uploads/2022/01/Berserk_manga-1-e1643227429361.png"
            )]
        
        return []
    
    def get_chapters(self, manga_id: str) -> list[Chapter]:
        """Get list of chapters for a manga."""
        url = f"{self.base_url}/"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        chapters = []
        seen_urls = set()
        
        # Find chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/manga/berserk-chapter-' in href and href not in seen_urls:
                seen_urls.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    chapter_num = match.group(1)
                    title = link.get_text(strip=True) or f"Chapter {chapter_num}"
                    
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title if title != chapter_num else f"Chapter {chapter_num}",
                        url=href
                    ))
        
        # Sort by chapter number (descending to ascending)
        chapters.sort(key=lambda c: c.number)
        return chapters
    
    def get_pages(self, manga_id: str, chapter_number: str) -> list[str]:
        """Get list of page image URLs for a chapter."""
        # Build chapter URL
        url = f"{self.base_url}/manga/berserk-chapter-{chapter_number}/"
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        pages = []
        
        # Find images from img.spoilerhat.com proxy
        for img in soup.find_all('img', src=True):
            src = img['src']
            if 'img.spoilerhat.com' in src or 'mangafox' in src:
                # Decode the URL if it's a proxy URL
                if 'img.spoilerhat.com/img/?url=' in src:
                    # Extract the actual image URL
                    match = re.search(r'url=([^&]+)', src)
                    if match:
                        actual_url = unquote(match.group(1))
                        pages.append(actual_url)
                else:
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
