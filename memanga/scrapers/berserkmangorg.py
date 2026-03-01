"""
BerserkMangOrg scraper (berserkmang.org) - Berserk dedicated site.
WordPress theme + mangaread.org CDN.
"""

import re
from pathlib import Path
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

from .base import BaseScraper, Manga, Chapter


class BerserkMangOrgScraper(BaseScraper):
    """Scraper for berserkmang.org - Berserk manga."""
    
    name = "berserkmangorg"
    base_url = "https://www.berserkmang.org"
    
    def __init__(self):
        super().__init__()
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
        
        if 'berserk' in query_lower or 'guts' in query_lower:
            return [Manga(
                title="Berserk",
                url=f"{self.base_url}/",
            )]
        
        return []
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
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
                match = re.search(r'chapter-(\d+(?:\.\d+)?(?:-\d+)?)', href)
                if match:
                    chapter_str = match.group(1)
                    # Handle chapter-379-2 format
                    if '-' in chapter_str:
                        parts = chapter_str.split('-')
                        chapter_num = float(parts[0]) + float(parts[1]) / 10
                    else:
                        chapter_num = float(chapter_str)
                    
                    title = link.get_text(strip=True) or f"Chapter {chapter_str}"
                    
                    chapters.append(Chapter(
                        number=chapter_str,
                        title=title if title != chapter_str else f"Chapter {chapter_str}",
                        url=href
                    ))
        
        # Sort by chapter number
        chapters.sort(key=lambda c: c.number)
        return chapters
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get list of page image URLs for a chapter."""
        response = self.session.get(chapter_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        pages = []
        
        # Find images in data-src (lazy loading)
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
            if 'mangaread.org/wp-content/uploads' in src:
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Referer': self.base_url
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            if len(response.content) < 1000:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
