"""
Skip Beat Manga Online Scraper

Site: skip-beat-manga.online
Type: Dedicated manga reader (Skip Beat by Yoshiki Nakamura)
CDN: laiond.com
"""

import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Manga, Chapter

logger = logging.getLogger(__name__)


class SkipBeatMangaOnlineScraper(BaseScraper):
    """Scraper for skip-beat-manga.online - Skip Beat dedicated site."""
    
    name = "skip-beat-manga.online"
    base_url = "https://skip-beat-manga.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (only Skip Beat available)."""
        results = []
        
        if 'skip' in query.lower() or 'beat' in query.lower():
            # Return the main series
            results.append(Manga(
                title="Skip Beat!",
                url=f"{self.base_url}/",
                cover_url="",
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga."""
        chapters = []
        
        try:
            # Get the main page
            response = self.session.get(self.base_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find chapter links - pattern: /comic/skip-beat-chapter-N/
            links = soup.find_all('a', href=True)
            seen_urls = set()
            
            for link in links:
                href = link['href']
                if '/comic/skip-beat-chapter-' in href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number
                    match = re.search(r'chapter-(\d+(?:-\d+)?)', href)
                    if match:
                        ch_num = match.group(1).replace('-', '.')
                        
                        full_url = urljoin(self.base_url, href)
                        title = link.get_text(strip=True) or f"Chapter {ch_num}"
                        
                        chapters.append(Chapter(
                            number=ch_num,
                            title=title,
                            url=full_url,
                        ))
            
            # Sort by chapter number
            chapters.sort(key=lambda x: x.numeric)
            logger.info(f"Found {len(chapters)} chapters for Skip Beat")
            
        except Exception as e:
            logger.error(f"Error getting chapters: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page URLs for a chapter."""
        pages = []
        
        try:
            response = self.session.get(chapter_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find images - typically from laiond.com CDN
            imgs = soup.find_all('img')
            
            for img in imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
                src = src.strip()
                
                # Filter for chapter images (laiond.com or similar CDN)
                if 'laiond.com' in src or 'skip' in src.lower():
                    if src not in pages and not src.startswith('data:'):
                        pages.append(src)
            
            # If no laiond images, try broader pattern
            if not pages:
                for img in imgs:
                    src = img.get('src') or img.get('data-src') or ''
                    src = src.strip()
                    if src and not src.startswith('data:'):
                        if '.jpg' in src.lower() or '.png' in src.lower() or '.webp' in src.lower():
                            # Check if it looks like a manga page
                            if re.search(r'\d+\.(jpg|png|webp|jpeg)', src, re.I):
                                pages.append(src)
            
            logger.info(f"Found {len(pages)} pages in chapter")
            
        except Exception as e:
            logger.error(f"Error getting pages from {chapter_url}: {e}")
        
        return pages
    
    def download_image(self, url: str, headers: Optional[dict] = None) -> bytes:
        """Download an image with proper headers."""
        dl_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': self.base_url,
        }
        if headers:
            dl_headers.update(headers)
        
        response = self.session.get(url, headers=dl_headers, timeout=30)
        response.raise_for_status()
        return response.content
