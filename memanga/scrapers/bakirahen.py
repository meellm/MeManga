"""
BakiRahen Scraper

Dedicated Baki Rahen manga reader.
WordPress ifenzi-v2 theme + cdn.readkakegurui.com CDN.
"""

import re
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class BakiRahenScraper(BaseScraper):
    """Scraper for bakirahen.com - Baki Rahen dedicated manga site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://bakirahen.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - returns single result for Baki Rahen if query matches."""
        query_lower = query.lower()
        if any(term in query_lower for term in ["baki", "rahen", "baki rahen"]):
            return [Manga(
                title="Baki Rahen",
                url=self.base_url,
                cover_url="https://bakirahen.com/wp-content/uploads/2024/04/Baki-Rahen-Manga.webp"
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for Baki Rahen."""
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            chapters = []
            
            # Find chapter list items
            chapter_items = soup.select('li.item[data-number] a')
            
            for item in chapter_items:
                href = item.get('href', '')
                if not href:
                    continue
                
                # Extract chapter info
                span = item.select_one('span')
                if span:
                    title = span.get_text(strip=True).replace('🔥', '').strip()
                else:
                    title = item.get_text(strip=True)
                
                # Extract chapter number
                parent = item.find_parent('li')
                if parent and parent.get('data-number'):
                    chapter_num = float(parent.get('data-number'))
                else:
                    # Fallback: extract from URL
                    match = re.search(r'chapter[_-]?(\d+(?:\.\d+)?)', href, re.IGNORECASE)
                    chapter_num = float(match.group(1)) if match else 0
                
                chapters.append(Chapter(
                    number=str(chapter_num),
                    title=title,
                    url=href
                ))
            
            # Sort by chapter number (descending - newest first)
            chapters.sort(key=lambda c: c.numeric, reverse=True)
            
            logger.info(f"Found {len(chapters)} chapters for Baki Rahen")
            return chapters
            
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
            
            # Find all manga page images (in div.separator or with class aligncenter)
            # Images from cdn.readkakegurui.com
            img_tags = soup.select('img.aligncenter[src*="cdn.readkakegurui.com"]')
            
            if not img_tags:
                # Fallback: any img with cdn.readkakegurui.com
                img_tags = soup.find_all('img', src=re.compile(r'cdn\.readkakegurui\.com'))
            
            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and 'cdn.readkakegurui.com' in src:
                    images.append(src.strip())
            
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
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": self.base_url,
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
            logger.error(f"Failed to download {url}: {e}")
            return False
