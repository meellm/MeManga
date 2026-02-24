"""
MangaDNA Scraper (mangadna.com)

General manga/manhwa aggregator with clean image CDN.
- URL pattern: https://mangadna.com/manga/{slug}/chapter-{n}
- Images: https://imgXXX.mangadna.com/uploads/{manga_id}/{chapter_id}/{page}.jpg
"""

import re
import logging
import cloudscraper
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class MangaDNAScraper(BaseScraper):
    BASE_URL = "https://mangadna.com"
    SOURCE_NAME = "MangaDNA"
    
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        self.session = self.scraper
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        results = []
        url = f"{self.BASE_URL}/search"
        
        try:
            response = self.scraper.get(url, params={"q": query}, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find manga items in search results
            for item in soup.select('.list_new_item, .manga-item, .content-item'):
                try:
                    link = item.select_one('a[href*="/manga/"]')
                    if not link:
                        continue
                    
                    href = link.get('href', '')
                    if '/chapter-' in href:
                        # Extract manga URL from chapter URL
                        href = '/'.join(href.split('/')[:-1])
                    
                    title_elem = item.select_one('.item-title, h3, h4, .name, .manga-title')
                    title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
                    
                    img = item.select_one('img')
                    cover = img.get('src', '') if img else ''
                    
                    # Get slug from URL
                    slug = href.rstrip('/').split('/')[-1]
                    
                    results.append(Manga(
                        title=title,
                        url=urljoin(self.BASE_URL, href),
                        cover_url=cover,
                        source=self.SOURCE_NAME,
                        slug=slug
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing search result: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Search error: {e}")
        
        return results
    
    def get_manga_info(self, manga_url: str) -> Optional[Manga]:
        """Get manga information and chapter list."""
        try:
            response = self.scraper.get(manga_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Get title
            title_elem = soup.select_one('h1, .manga-title, .title')
            title = title_elem.get_text(strip=True) if title_elem else ''
            
            # Get cover image
            cover_elem = soup.select_one('.manga-img img, .cover img, .thumbnail img')
            cover = cover_elem.get('src', '') if cover_elem else ''
            
            # Get description
            desc_elem = soup.select_one('.desc, .description, .summary, [class*="synopsis"]')
            description = desc_elem.get_text(strip=True) if desc_elem else ''
            
            # Get slug
            slug = manga_url.rstrip('/').split('/')[-1]
            
            # Get chapters
            chapters = self.get_chapters(manga_url)
            
            return Manga(
                title=title,
                url=manga_url,
                cover_url=cover,
                description=description,
                source=self.SOURCE_NAME,
                slug=slug,
                chapters=chapters
            )
            
        except Exception as e:
            logger.error(f"Error getting manga info: {e}")
            return None
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapter list for a manga."""
        try:
            response = self.scraper.get(manga_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            chapters = []
            
            # Find chapter links
            chapter_links = soup.select('a[href*="/chapter-"]')
            
            seen = set()
            for link in chapter_links:
                try:
                    href = link.get('href', '')
                    if not href or href in seen:
                        continue
                    seen.add(href)
                    
                    chapter_url = urljoin(self.BASE_URL, href)
                    
                    # Extract chapter number from URL
                    match = re.search(r'/chapter-([0-9.]+)', href)
                    if not match:
                        continue
                    
                    chapter_num = match.group(1)
                    chapter_title = f"Chapter {chapter_num}"
                    
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=chapter_title,
                        url=chapter_url
                    ))
                    
                except Exception as e:
                    logger.debug(f"Error parsing chapter: {e}")
                    continue
            
            # Sort chapters by number (descending, newest first)
            chapters.sort(key=lambda c: float(c.number) if c.number.replace('.', '').isdigit() else 0, reverse=True)
            
            return chapters
            
        except Exception as e:
            logger.error(f"Error getting chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        try:
            response = self.scraper.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            pages = []
            seen = set()
            
            # Find all manga images - look for img tags with mangadna CDN URLs
            for img in soup.select('img[src*="mangadna.com"], img[data-src*="mangadna.com"]'):
                src = img.get('data-src') or img.get('src', '')
                
                # Filter for actual manga pages (not covers, logos, etc.)
                if '/uploads/' in src and src not in seen:
                    seen.add(src)
                    pages.append(src)
            
            # Also try to find images in chapter container
            chapter_container = soup.select_one('.chapter-content, .reader-content, .content-chapter, #chapter-content')
            if chapter_container:
                for img in chapter_container.select('img'):
                    src = img.get('data-src') or img.get('src', '')
                    if src and '/uploads/' in src and src not in seen:
                        seen.add(src)
                        pages.append(src)
            
            logger.info(f"Found {len(pages)} pages for {chapter_url}")
            return pages
            
        except Exception as e:
            logger.error(f"Error getting chapter pages: {e}")
            return []
    
    def download_image(self, image_url: str, headers: dict = None) -> bytes:
        """Download image with appropriate headers."""
        default_headers = {
            'Referer': self.BASE_URL + '/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        }
        
        if headers:
            default_headers.update(headers)
        
        response = self.scraper.get(image_url, headers=default_headers, timeout=60)
        response.raise_for_status()
        return response.content
