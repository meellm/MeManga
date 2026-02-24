"""
KenganAshura Scraper

Website: kenganashura.com
Manga: Kengan Ashura / Kengan Omega by Sandrovich Yabako and Daromeon
Architecture: WordPress + wp-content/uploads CDN
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga


class KenganAshuraMangaScraper(BaseScraper):
    """Scraper for kenganashura.com - Kengan Ashura/Omega dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://kenganashura.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://kenganashura.com/",
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (multi-manga site: Kengan Ashura and Kengan Omega)."""
        results = []
        query_lower = query.lower()
        
        if any(term in query_lower for term in ["kengan", "ashura", "omega"]):
            results.append(Manga(
                id="kengan-ashura",
                title="Kengan Ashura",
                url=f"{self.base_url}/manga/kengan-ashura-chapter-1/",
                cover_url="",
                source="kenganashura.com"
            ))
            results.append(Manga(
                id="kengan-omega",
                title="Kengan Omega",
                url=f"{self.base_url}/manga/kengan-omega-chapter-1/",
                cover_url="",
                source="kenganashura.com"
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from Kengan manga."""
        chapters = []
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Determine which series to get based on URL
            if 'omega' in manga_url.lower():
                pattern = r'/manga/kengan-omega-chapter-'
                series_prefix = "kengan-omega"
            else:
                pattern = r'/manga/kengan-ashura-chapter-'
                series_prefix = "kengan-ashura"
            
            # Find chapter links
            chapter_links = soup.find_all('a', href=re.compile(pattern))
            
            seen_urls = set()
            for link in chapter_links:
                href = link.get('href', '')
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number
                    match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
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
            
            # Find images - check src attributes
            # Images are in wp-content/uploads
            for img in soup.find_all('img'):
                src = img.get('data-lazy-src') or img.get('data-src') or img.get('src', '')
                
                if 'wp-content/uploads' in src and 'kenganashura.com' in src:
                    # Clean up the URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    
                    # Skip WordPress system images and small thumbnails
                    if '/theme/' not in src and '/plugin/' not in src:
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
