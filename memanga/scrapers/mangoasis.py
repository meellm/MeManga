"""
MangOasis Scraper

A multilingual manga aggregator with WordPress MangaVerse theme.
- URL pattern: mangoasis.com/en/manga/[slug].html
- Chapter pattern: mangoasis.com/en/[slug]/[manga]-chapter-[N].html
- CDN: cdn.mangoasis.com/cdn/english/[Manga Title]/Chapter [N]/[page].jpeg
- Features: Multiple languages, lazy loading, clean structure
"""

import re
import logging
from pathlib import Path
from typing import List, Optional
from bs4 import BeautifulSoup
import cloudscraper

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class MangOasisScraper(BaseScraper):
    """Scraper for mangoasis.com - WordPress MangaVerse manga aggregator."""
    
    BASE_URL = "https://www.mangoasis.com/en"
    
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
            'Referer': 'https://www.mangoasis.com/',
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        results = []
        
        # MangOasis uses WordPress search
        search_url = f"{self.BASE_URL}/?s={query.replace(' ', '+')}"
        
        try:
            response = self.session.get(search_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find manga links in search results
            for link in soup.select('a[href*="/manga/"]'):
                href = link.get('href', '')
                if '/manga/' in href and href.endswith('.html'):
                    title = link.get_text(strip=True)
                    if title and len(title) > 2:
                        results.append(Manga(
                            title=title,
                            url=href,
                        ))

            # Deduplicate by url
            seen = set()
            unique = []
            for manga in results:
                if manga.url not in seen:
                    seen.add(manga.url)
                    unique.append(manga)

            return unique[:20]  # Limit to 20 results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        chapters = []
        
        try:
            response = self.session.get(manga_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract manga slug for chapter URLs
            manga_match = re.search(r'/manga/([^/]+)\.html', manga_url)
            if not manga_match:
                logger.error(f"Could not extract manga slug from: {manga_url}")
                return []
            
            manga_slug = manga_match.group(1)
            
            # Find chapter links
            for link in soup.select('a[href*="-chapter-"]'):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                # Extract chapter number from URL
                chapter_match = re.search(r'-chapter-(\d+(?:\.\d+)?)', href, re.IGNORECASE)
                if chapter_match:
                    chapter_num = chapter_match.group(1)
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title or f"Chapter {chapter_num}",
                        url=href
                    ))
            
            # Sort by chapter number (descending - newest first)
            chapters.sort(key=lambda x: float(x.number) if x.number else 0, reverse=True)
            
            # Deduplicate by chapter number
            seen = set()
            unique = []
            for chapter in chapters:
                if chapter.number not in seen:
                    seen.add(chapter.number)
                    unique.append(chapter)
            
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
            
            # Find images with data-src (lazy loading) or src
            for img in soup.select('figure.wp-block-image img'):
                # Try data-src first (lazy loading), then src
                src = img.get('data-src') or img.get('src', '')
                
                # Filter out placeholder/base64 images
                if src and not src.startswith('data:') and 'cdn.mangoasis.com' in src:
                    # URL decode if needed
                    pages.append(src)
            
            # Also check noscript fallback images
            for noscript in soup.select('figure.wp-block-image noscript'):
                inner_soup = BeautifulSoup(str(noscript), 'html.parser')
                for img in inner_soup.select('img'):
                    src = img.get('src', '')
                    if src and 'cdn.mangoasis.com' in src and src not in pages:
                        pages.append(src)
            
            logger.info(f"Found {len(pages)} pages for chapter")
            return pages
            
        except Exception as e:
            logger.error(f"Failed to get pages: {e}")
            return []
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image from the CDN."""
        try:
            headers = {
                'Referer': 'https://www.mangoasis.com/',
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
