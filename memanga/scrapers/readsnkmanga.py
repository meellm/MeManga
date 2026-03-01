"""
ReadSNKManga Scraper

Site: readsnkmanga.com
Type: Dedicated manga reader (Attack on Titan / Shingeki no Kyojin)
CDN: Blogger CDN (blogger.googleusercontent.com)
"""

import re
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Manga, Chapter

logger = logging.getLogger(__name__)


class ReadSNKMangaScraper(BaseScraper):
    """Scraper for readsnkmanga.com - Attack on Titan dedicated site."""
    
    name = "readsnkmanga.com"
    base_url = "https://readsnkmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (only Attack on Titan available)."""
        results = []
        
        keywords = ['attack', 'titan', 'snk', 'shingeki', 'kyojin']
        if any(kw in query.lower() for kw in keywords):
            results.append(Manga(
                title="Shingeki no Kyojin / Attack on Titan",
                url=f"{self.base_url}/",
                cover_url="",
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga."""
        chapters = []
        
        try:
            response = self.session.get(self.base_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find chapter links - pattern: /manga/shingeki-no-kyojin-chapter-N/
            links = soup.find_all('a', href=True)
            seen_urls = set()
            
            for link in links:
                href = link['href']
                if 'chapter' in href.lower() and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number
                    match = re.search(r'chapter-(\d+(?:\.\d+)?(?:-\d+)?)', href)
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
            logger.info(f"Found {len(chapters)} chapters")
            
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
            
            # Find images from Blogger CDN
            imgs = soup.find_all('img')
            
            for img in imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
                src = src.strip()
                
                # Filter for Blogger CDN images
                if 'blogger.googleusercontent.com' in src or 'blogspot.com' in src:
                    if src not in pages:
                        pages.append(src)
            
            logger.info(f"Found {len(pages)} pages in chapter")
            
        except Exception as e:
            logger.error(f"Error getting pages from {chapter_url}: {e}")
        
        return pages
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Referer': self.base_url,
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
