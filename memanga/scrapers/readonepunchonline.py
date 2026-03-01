"""
Read One Punch Online Scraper
Site: read.one-punch.online
One Punch Man manga, 217+ chapters
WordPress + cache.imagemanga.online CDN
"""

import re
import cloudscraper
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class ReadOnePunchOnlineScraper(BaseScraper):
    """Scraper for read.one-punch.online - One Punch Man dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://read.one-punch.online"
        self.landing_url = "https://one-punch.online"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search returns One Punch Man if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ['one punch', 'opm', 'one-punch', 'saitama', 'onepunch']):
            return [Manga(
                title="One-Punch Man",
                url=self.base_url,
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all One Punch Man chapters."""
        # Try landing page first for chapter list
        resp = self.session.get(self.landing_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen = set()
        
        # Find all chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/manga/one-punch-man-chapter-' in href and href not in seen:
                seen.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    ch_num = match.group(1)
                    
                    # Normalize URL to read.one-punch.online
                    if 'read.one-punch.online' not in href:
                        href = f"{self.base_url}/manga/one-punch-man-chapter-{ch_num}/"
                    
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
        
        # Find images from cache.imagemanga.online CDN
        for img in soup.find_all('img'):
            src = img.get('src', img.get('data-src', ''))
            if 'cache.imagemanga.online' in src or 'imagemanga.online' in src:
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                'Referer': self.base_url,
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
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
