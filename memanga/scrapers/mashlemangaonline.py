"""
Mashle Manga Online Scraper
Site: mashle-manga.online
Mashle: Magic and Muscles by Hajime Komoto, 163 chapters
WordPress + wp-content/uploads CDN
"""

import re
import cloudscraper
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class MashleMangaOnlineScraper(BaseScraper):
    """Scraper for mashle-manga.online - Mashle dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://mashle-manga.online"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search returns Mashle if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ['mashle', 'magic and muscles']):
            return [Manga(
                title="Mashle: Magic and Muscles",
                url=self.base_url,
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all Mashle chapters."""
        resp = self.session.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen = set()
        
        # Find all chapter links - two patterns
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Matches /manga/mashle-magic-and-muscles-chapter-N/ or /mashle-magic-and-muscles-chapter-N/
            if 'mashle-magic-and-muscles-chapter-' in href and href not in seen:
                seen.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    ch_num = match.group(1)
                    
                    # Make sure it's full URL
                    if not href.startswith('http'):
                        href = self.base_url + href if href.startswith('/') else self.base_url + '/' + href
                    
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
        
        # Find images from wp-content/uploads
        for img in soup.find_all('img'):
            src = img.get('src', img.get('data-src', ''))
            if 'wp-content/uploads' in src:
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
