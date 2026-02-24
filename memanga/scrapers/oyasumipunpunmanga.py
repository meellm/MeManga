"""
OyasumiPunpun Scraper

Website: oyasumipunpun.com
Manga: Oyasumi Punpun (Goodnight Punpun) by Inio Asano
Architecture: WordPress + cdn.readkakegurui.com CDN
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga


class OyasumiPunpunMangaScraper(BaseScraper):
    """Scraper for oyasumipunpun.com - Goodnight Punpun dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://oyasumipunpun.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://oyasumipunpun.com/",
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (this is a single-manga site)."""
        query_lower = query.lower()
        if any(term in query_lower for term in ["punpun", "oyasumi", "goodnight", "inio", "asano"]):
            return [Manga(
                id="oyasumi-punpun",
                title="Oyasumi Punpun (Goodnight Punpun)",
                url=self.base_url,
                cover_url="",
                source="oyasumipunpun.com"
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from Oyasumi Punpun manga."""
        chapters = []
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find chapter links - format: /manga/68715-oyasumi-chapter-1-XXX/
            # (where XXX is the actual chapter number at the end)
            chapter_links = soup.find_all('a', href=re.compile(r'/manga/68715-oyasumi-chapter-\d+-\d+'))
            
            seen_urls = set()
            for link in chapter_links:
                href = link.get('href', '')
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number from various formats
                    # Format 1: 68715-oyasumi-chapter-1-147 (last number is chapter)
                    # Format 2: oyasumi-punpun-manga-vol-1-chapter-1
                    # Get the last number in the URL (actual chapter number)
                    match = re.search(r'-(\d+)/?$', href)
                    if match:
                        chapter_num = match.group(1)
                        title = link.get_text(strip=True) or f"Chapter {chapter_num}"
                        
                        chapters.append(Chapter(
                            number=chapter_num,
                            title=title,
                            url=href if href.startswith('http') else urljoin(self.base_url, href),
                        ))
            
            # Sort by chapter number
            chapters.sort(key=lambda x: x.numeric, reverse=True)
            
        except Exception as e:
            print(f"Error getting chapters: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images from a chapter."""
        pages = []
        
        try:
            response = self.session.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find images - check src and data-src attributes
            # Images are on cdn.readkakegurui.com
            for img in soup.find_all('img'):
                src = img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                
                if 'cdn.readkakegurui.com' in src:
                    # Clean up the URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    
                    if src not in pages:
                        pages.append(src)
            
        except Exception as e:
            print(f"Error getting pages from {chapter_url}: {e}")
        
        return pages
    
    def download_image(self, url: str, path: str) -> bool:
        """Download an image from the given URL."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": self.base_url,
            }
            
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if len(response.content) > 1000:  # Basic validation
                with open(path, 'wb') as f:
                    f.write(response.content)
                return True
            
        except Exception as e:
            print(f"Error downloading image {url}: {e}")
        
        return False
