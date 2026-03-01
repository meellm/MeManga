"""
ReadKingdomFree Scraper

Dedicated Kingdom manga reader site with WordPress.
- URL: readkingdomfree.com
- CDN: scans-hot.planeptune.us
- Architecture: WordPress lazy-load with data-src images
"""

import re
import logging
from pathlib import Path
from typing import List, Optional
from bs4 import BeautifulSoup
import cloudscraper

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class ReadKingdomFreeScraper(BaseScraper):
    """Scraper for readkingdomfree.com - Kingdom manga dedicated reader."""
    
    BASE_URL = "https://www.readkingdomfree.com"
    
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
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': f'{self.BASE_URL}/',
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search is limited since this is a single-manga site."""
        if 'kingdom' in query.lower():
            return [Manga(
                title="Kingdom",
                url=f"{self.BASE_URL}/",
                slug="kingdom",
                source="readkingdomfree.com"
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        chapters = []
        
        try:
            # For this site, the main page lists all chapters
            response = self.session.get(self.BASE_URL, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all chapter links
            for link in soup.select('a[href*="-chapter-"]'):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+|-\d+)?)', href, re.IGNORECASE)
                if match:
                    chapter_num = match.group(1).replace('-', '.')
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title or f"Chapter {chapter_num}",
                        url=href
                    ))
            
            # Deduplicate by chapter number
            seen = set()
            unique = []
            for chapter in chapters:
                key = chapter.number
                if key not in seen:
                    seen.add(key)
                    unique.append(chapter)
            
            # Sort by chapter number (descending - newest first)
            unique.sort(key=lambda x: float(x.number.replace('-', '.')) if x.number else 0, reverse=True)
            
            logger.info(f"Found {len(unique)} chapters")
            return unique
            
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        pages = []
        
        try:
            response = self.session.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find images with data-src (lazy loading)
            for img in soup.select('img[data-src]'):
                src = img.get('data-src', '').strip()
                
                # Filter valid manga images from planeptune.us CDN
                if src and ('planeptune.us' in src or 'manga' in src.lower()):
                    if not src.startswith('data:'):
                        pages.append(src)
            
            # Also check regular src attributes as fallback
            if not pages:
                for img in soup.select('img[src*="planeptune"]'):
                    src = img.get('src', '').strip()
                    if src and not src.startswith('data:'):
                        pages.append(src)
            
            logger.info(f"Found {len(pages)} pages")
            return pages
            
        except Exception as e:
            logger.error(f"Failed to get pages: {e}")
            return []
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image."""
        try:
            headers = {
                'Referer': f'{self.BASE_URL}/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            }

            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            if len(response.content) < 1000:
                logger.warning(f"Image too small ({len(response.content)} bytes): {url}")
                return False

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(response.content)

            return True

        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False
