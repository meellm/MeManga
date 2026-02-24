"""
Bakidou Scraper

Multi-Baki series manga reader (Hanma Baki, New Grappler Baki, etc.).
WordPress Comic Easel theme + wp-content/uploads CDN.
"""

import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class BakidouScraper(BaseScraper):
    """Scraper for bakidou.com - Multi-Baki series manga site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://bakidou.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns Baki series if query matches."""
        query_lower = query.lower()
        results = []
        
        baki_series = [
            ("baki", "Baki (Complete Series)", "baki"),
            ("hanma", "Hanma Baki / Son of Ogre", "hanma-baki"),
            ("grappler", "New Grappler Baki", "new-grappler-baki"),
            ("dou", "Baki-Dou", "baki-dou"),
        ]
        
        if any(term in query_lower for term in ["baki", "hanma", "grappler", "dou"]):
            # Return main series entry that includes all chapters
            results.append(Manga(
                id="baki-complete",
                title="Baki (All Series)",
                url=self.base_url,
                cover_url="https://bakidou.com/wp-content/uploads/2020/01/hiya.jpg"
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters across all Baki series."""
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            chapters = []
            
            # Find all chapter links in the chapter widget
            chapter_links = soup.select('ul li a[href*="/comic/"]')
            
            for link in chapter_links:
                href = link.get('href', '')
                if not href or '/comic/' not in href:
                    continue
                
                title = link.get_text(strip=True)
                if not title:
                    continue
                
                # Extract chapter number from title
                # Format: "Baki:Hanma Baki, Vol.37, Chapter 312 : The Conclusion"
                chapter_match = re.search(r'Chapter\s*(\d+(?:\.\d+)?)', title, re.IGNORECASE)
                chapter_num = float(chapter_match.group(1)) if chapter_match else 0
                
                # Determine series prefix for sorting
                series_order = 0
                if 'hanma' in title.lower() or 'son of ogre' in title.lower():
                    series_order = 3  # Third series
                elif 'new grappler' in title.lower():
                    series_order = 2  # Second series
                elif 'grappler' in title.lower():
                    series_order = 1  # First series
                elif 'dou' in title.lower():
                    series_order = 4  # Fourth series
                
                # Create sortable chapter ID
                sort_num = series_order * 1000 + chapter_num
                
                chapters.append(Chapter(
                    number=str(sort_num),
                    title=title,
                    url=href
                ))
            
            # Sort by sort number (descending - newest first)
            chapters.sort(key=lambda c: c.numeric, reverse=True)
            
            # Dedupe by URL
            seen_urls = set()
            unique_chapters = []
            for ch in chapters:
                if ch.url not in seen_urls:
                    seen_urls.add(ch.url)
                    unique_chapters.append(ch)
            
            logger.info(f"Found {len(unique_chapters)} chapters for Baki series")
            return unique_chapters
            
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all image URLs for a chapter."""
        try:
            response = self.session.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            images = []
            
            # Find all manga page images in wp-content/uploads
            # They have wp-image-XXXX class and src containing wp-content/uploads
            img_tags = soup.find_all('img', src=re.compile(r'wp-content/uploads/\d{3}'))
            
            for img in img_tags:
                src = img.get('src')
                if src and 'wp-content/uploads' in src:
                    # Get full-size image (not thumbnail)
                    # Skip thumbnails that end with -NNNxNNN.jpg
                    if not re.search(r'-\d+x\d+\.(jpg|png|webp)$', src):
                        images.append(src.strip())
                    else:
                        # Try to get full-size URL by removing dimension suffix
                        full_src = re.sub(r'-\d+x\d+\.', '.', src)
                        images.append(full_src.strip())
            
            # Dedupe while preserving order
            seen = set()
            unique_images = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            
            logger.info(f"Found {len(unique_images)} images in chapter")
            return unique_images
            
        except Exception as e:
            logger.error(f"Failed to get chapter images: {e}")
            return []
    
    def download_image(self, image_url: str, chapter_url: str = None) -> Optional[bytes]:
        """Download an image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": chapter_url or self.base_url,
            }
            
            response = requests.get(image_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if len(response.content) > 1000:  # Basic validation
                return response.content
            return None
            
        except Exception as e:
            logger.error(f"Failed to download image {image_url}: {e}")
            return None
