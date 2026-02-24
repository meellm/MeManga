"""
D.Gray-man Online Scraper
Site: d-grayman.online
D.Gray-man manga by Katsura Hoshino, 257+ chapters
WordPress + laiond.com CDN
"""

import re
import cloudscraper
from bs4 import BeautifulSoup
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class DGraymanOnlineScraper(BaseScraper):
    """Scraper for d-grayman.online - D.Gray-man dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://d-grayman.online"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search returns D.Gray-man if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ['d.gray', 'd gray', 'dgray', 'gray-man', 'grayman']):
            return [Manga(
                id="d-gray-man",
                title="D.Gray-man",
                url=self.base_url,
                cover="",
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all D.Gray-man chapters."""
        resp = self.session.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen = set()
        
        # Find all chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/comic/d-gray-man-chapter-' in href and href not in seen:
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
        chapters.sort(key=lambda x: float(x.number) if x.number.replace('.','').isdigit() else 0)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        pages = []
        
        # Find images from laiond.com CDN
        for img in soup.find_all('img'):
            src = img.get('src', img.get('data-src', ''))
            if 'laiond.com' in src:
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
