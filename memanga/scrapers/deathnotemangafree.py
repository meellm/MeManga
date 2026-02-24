"""
Death Note Manga Free Scraper
Site: deathnotemangafree.com
Death Note by Tsugumi Ohba & Takeshi Obata, 108+ chapters
Static HTML + deathnote-manga.online wp-content CDN
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class DeathNoteMangaFreeScraper(BaseScraper):
    """Scraper for deathnotemangafree.com - Death Note dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://www.deathnotemangafree.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search returns Death Note if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ['death note', 'deathnote', 'death-note', 'light yagami', 'kira']):
            return [Manga(
                id="death-note",
                title="Death Note",
                url=self.base_url,
                cover="",
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all Death Note chapters."""
        resp = self.session.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen = set()
        
        # Find all chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'death-note-chapter-' in href and href not in seen:
                seen.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    ch_num = match.group(1)
                    # Build full URL if relative
                    if not href.startswith('http'):
                        href = f"{self.base_url}/{href}"
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
        
        # Find images from wp-content/uploads
        for img in soup.find_all('img'):
            src = img.get('src', img.get('data-src', ''))
            if 'wp-content/uploads' in src and src not in seen:
                seen.add(src)
                # Handle relative URLs - resolve relative to deathnotemangafree.com
                if src.startswith('../../'):
                    src = f"{self.base_url}/{src.replace('../../', '')}"
                elif src.startswith('../'):
                    src = f"{self.base_url}/{src.replace('../', '')}"
                elif not src.startswith('http'):
                    src = f"{self.base_url}/{src}"
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
