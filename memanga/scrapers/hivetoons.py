"""
Hivetoons.org scraper (Void Scans network).

Uses Playwright to handle JS-rendered content.
URL patterns:
- Series: https://hivetoons.org/series/{slug}
- Chapter: https://hivetoons.org/series/{slug}/chapter-{num}
- Images: storage.hivetoon.com
"""

import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)


class HivetoonsScraper(PlaywrightScraper):
    """Scraper for hivetoons.org (Void Scans network)."""
    
    name = "hivetoons"
    domains = ["hivetoons.org", "hivetoon.com"]
    base_url = "https://hivetoons.org"
    
    def search(self, query: str) -> list[dict]:
        """
        Search for manga by browsing the homepage.
        Hivetoons doesn't have a search endpoint, so we filter from all series.
        """
        try:
            content = self._get_page_content(self.base_url, wait_time=5000)
            soup = BeautifulSoup(content, 'html.parser')
            
            results = []
            query_lower = query.lower()
            
            # Find all series links
            for link in soup.find_all('a', href=re.compile(r'/series/[^/]+$')):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                if not title or not href:
                    continue
                
                # Filter by query
                if query_lower in title.lower():
                    url = href if href.startswith('http') else f"{self.base_url}{href}"
                    
                    # Try to get cover image
                    cover = None
                    img = link.find('img')
                    if img:
                        cover = img.get('src') or img.get('data-src')
                    
                    results.append({
                        'title': title,
                        'url': url,
                        'cover': cover
                    })
            
            logger.info(f"Found {len(results)} results for '{query}'")
            return results[:20]  # Limit results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_chapters(self, manga_url: str) -> list[dict]:
        """Get all chapters for a manga."""
        try:
            content = self._get_page_content(manga_url, wait_time=4000)
            soup = BeautifulSoup(content, 'html.parser')
            
            chapters = []
            
            # Find chapter links
            for link in soup.find_all('a', href=re.compile(r'/series/[^/]+/chapter-\d+')):
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                if not href:
                    continue
                
                url = href if href.startswith('http') else f"{self.base_url}{href}"
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                chapter_num = match.group(1) if match else "0"
                
                # Get title or construct one
                title = text if text else f"Chapter {chapter_num}"
                
                chapters.append({
                    'title': title,
                    'url': url,
                    'chapter': chapter_num
                })
            
            # Remove duplicates and sort
            seen_urls = set()
            unique_chapters = []
            for ch in chapters:
                if ch['url'] not in seen_urls:
                    seen_urls.add(ch['url'])
                    unique_chapters.append(ch)
            
            # Sort by chapter number descending
            unique_chapters.sort(key=lambda x: float(x.get('chapter', 0) or 0), reverse=True)
            
            logger.info(f"Found {len(unique_chapters)} chapters for {manga_url}")
            return unique_chapters
            
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all images for a chapter."""
        try:
            content = self._get_page_content(chapter_url, wait_time=5000)
            soup = BeautifulSoup(content, 'html.parser')
            
            images = []
            
            # Find all images from storage
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                
                # Only include content images (from storage)
                if 'storage.hivetoon' in src or 'upload/series' in src:
                    # Skip logos and non-content images
                    if 'logo' in src.lower():
                        continue
                    
                    images.append(src)
            
            logger.info(f"Found {len(images)} images for {chapter_url}")
            return images
            
        except Exception as e:
            logger.error(f"Failed to get images: {e}")
            return []
