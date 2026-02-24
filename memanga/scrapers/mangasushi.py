"""
MangaSushi scraper - WordPress Madara with AJAX chapter loading.
Requires Playwright for JS rendering.

Site: https://mangasushi.org
"""

import re
from typing import List
from .playwright_base import PlaywrightScraper
from .base import Manga, Chapter
from bs4 import BeautifulSoup


class MangaSushiScraper(PlaywrightScraper):
    """Scraper for mangasushi.org - WordPress Madara theme."""
    
    name = "MangaSushi"
    domains = ["mangasushi.org"]
    base_url = "https://mangasushi.org"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        search_url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_page_content(search_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen = set()
        
        # Madara search results - find manga items
        for item in soup.select('.c-tabs-item__content, .row.c-tabs-item, .page-item-detail'):
            # Get title and URL
            title_elem = item.select_one('.post-title a, h3 a, h4 a')
            if not title_elem:
                continue
                
            title = title_elem.get_text(strip=True)
            url = title_elem.get('href', '')
            
            if not url or '/manga/' not in url:
                continue
            
            if url in seen:
                continue
            seen.add(url)
            
            # Get cover
            cover = None
            img = item.select_one('img')
            if img:
                cover = img.get('data-src') or img.get('src', '')
            
            results.append(Manga(
                title=title,
                url=url,
                cover_url=cover,
            ))
        
        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga. Uses Playwright to wait for AJAX loading."""
        # Use longer wait time for AJAX chapter loading
        html = self._get_page_content(manga_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Madara chapter list items
        for item in soup.select('.wp-manga-chapter, li.chapter-li, .main.version-chap li'):
            link = item.select_one('a')
            if not link:
                continue
                
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Skip non-chapter links
            if '/manga/' not in href:
                continue
            
            # Extract chapter number
            match = re.search(r'chapter[- _]?([\d.]+)', href, re.I)
            if not match:
                match = re.search(r'([\d.]+)/?$', href)
            
            if match:
                chapter_num = match.group(1)
            else:
                # Try extracting from text
                text_match = re.search(r'chapter[- _]?([\d.]+)', text, re.I)
                if text_match:
                    chapter_num = text_match.group(1)
                else:
                    continue
            
            if chapter_num in seen:
                continue
            seen.add(chapter_num)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=href,
            ))
        
        # Sort by chapter number
        chapters.sort(key=lambda x: x.numeric)
        
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        # Use Playwright to load the page
        html = self._get_page_content(chapter_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")
        
        images = []
        
        # Madara reader images - multiple selectors
        selectors = [
            '.wp-manga-chapter-img',
            '.reading-content img',
            '.page-break img',
            'img.wp-manga-chapter-img',
            '#readerarea img',
        ]
        
        for selector in selectors:
            for img in soup.select(selector):
                # Get image URL - check multiple attributes
                src = img.get('data-src') or img.get('src') or img.get('data-lazy-src', '')
                
                if not src:
                    continue
                
                # Clean URL
                src = src.strip()
                
                # Skip placeholder/loading images
                if any(x in src.lower() for x in ['loading', 'placeholder', 'avatar', 'icon', 'logo', 'data:image']):
                    continue
                
                # Skip very small images (likely icons)
                width = img.get('width', '')
                if width and width.isdigit() and int(width) < 100:
                    continue
                
                # Ensure full URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = self.base_url + src
                
                if src not in images:
                    images.append(src)
            
            # If we found images with this selector, stop
            if images:
                break
        
        return images

    def get_image_headers(self, image_url: str) -> dict:
        """Get headers for image download."""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Referer': self.base_url + '/',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        }
