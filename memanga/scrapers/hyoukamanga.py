"""
HyoukaManga scraper - hyoukamanga.com
Hyouka by Honobu Yonezawa dedicated manga site
WordPress Toivo Lite theme + Blogger CDN (blogger.googleusercontent.com)
"""

import re
import logging
from typing import List
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class HyoukaMangaScraper(BaseScraper):
    """Scraper for hyoukamanga.com - Hyouka dedicated manga site."""
    
    name = "hyoukamanga"
    base_url = "https://hyoukamanga.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            'Referer': self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns Hyouka if query matches."""
        query_lower = query.lower()
        
        # This is a Hyouka-dedicated site
        if any(x in query_lower for x in ['hyouka', 'hyoka', 'kotenbu', 'classics club', 'chitanda', 'oreki']):
            return [Manga(
                title="Hyouka",
                url=self.base_url,
                cover_url=f"{self.base_url}/wp-content/uploads/2022/10/Hyouka-Manga-Header.webp",
                description="Hyouka manga adaptation by Task Ohna, based on the novel by Honobu Yonezawa. Follow Oreki Houtarou and the Classics Club as they solve mysteries at Kamiyama High School."
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for Hyouka."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        
        # Find all chapter links
        chapter_links = soup.select('a[href*="hyouka-chapter"]')
        seen_urls = set()
        
        for link in chapter_links:
            href = link.get('href', '')
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            
            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href, re.I)
            if not match:
                continue
            
            chapter_num = match.group(1)
            title = link.get_text(strip=True) or f"Chapter {chapter_num}"
            
            chapters.append(Chapter(
                number=chapter_num,
                title=title,
                url=href if href.startswith('http') else f"{self.base_url}{href}"
            ))
        
        # Sort by chapter number descending (newest first)
        chapters.sort(key=lambda x: float(x.number), reverse=True)
        
        # Remove duplicates based on chapter number
        seen_nums = set()
        unique_chapters = []
        for ch in chapters:
            if ch.number not in seen_nums:
                seen_nums.add(ch.number)
                unique_chapters.append(ch)
        
        logger.info(f"Found {len(unique_chapters)} chapters for Hyouka")
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images for a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, 'html.parser')
        images = []
        
        # Find the content area
        content_area = soup.select_one('.entry-content') or soup.select_one('article')
        if not content_area:
            content_area = soup
        
        # Get all images from content
        for img in content_area.find_all('img'):
            # Try different src attributes
            src = img.get('data-lazy-src') or img.get('data-src') or img.get('src', '')
            
            # Skip non-manga images
            if not src or src.startswith('data:'):
                continue
            
            # Only include Blogger CDN images (actual manga pages)
            if 'blogger.googleusercontent.com' in src or 'bp.blogspot.com' in src:
                images.append(src)
        
        logger.info(f"Found {len(images)} images in chapter")
        return images
