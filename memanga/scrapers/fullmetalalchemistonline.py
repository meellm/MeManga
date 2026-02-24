"""
Fullmetal Alchemist Online Scraper
Site: full-metal-alchemist.online
FMA manga by Hiromu Arakawa, 110 chapters
WordPress + Blogger CDN
"""

import re
import cloudscraper
from bs4 import BeautifulSoup
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class FullmetalAlchemistOnlineScraper(BaseScraper):
    """Scraper for full-metal-alchemist.online - FMA dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://w9.full-metal-alchemist.online"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search returns Fullmetal Alchemist if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ['fullmetal', 'full metal', 'fma', 'hagane', 'alchemist']):
            return [Manga(
                id="fullmetal-alchemist",
                title="Fullmetal Alchemist",
                url=self.base_url,
                cover="",
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all FMA chapters."""
        resp = self.session.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen = set()
        
        # Find all chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/manga/fullmetal-alchemist-chapter-' in href and href not in seen:
                seen.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    ch_num = match.group(1)
                    chapters.append(Chapter(
                        number=ch_num,
                        title=f"Chapter {ch_num}",
                        url=href,
                    ))
        
        # Sort by chapter number
        def sort_key(ch):
            try:
                return float(ch.number)
            except ValueError:
                return 0
        
        chapters.sort(key=sort_key)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        pages = []
        seen = set()
        
        # Find images from Blogger CDN
        for img in soup.find_all('img'):
            src = img.get('src', img.get('data-src', ''))
            if 'blogger.googleusercontent.com' in src and src not in seen:
                seen.add(src)
                # Normalize to high quality
                if '/s1200/' in src:
                    src = src.replace('/s1200/', '/s1600/')
                if '/s1400/' in src:
                    src = src.replace('/s1400/', '/s1600/')
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, chapter_url: str = None) -> bytes:
        """Download image with proper headers."""
        headers = {
            'Referer': chapter_url or self.base_url,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content
