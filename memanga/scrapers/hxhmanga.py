"""
HxHManga Scraper - Hunter x Hunter dedicated reader

URL: https://hxhmanga.com
Architecture: WordPress Mangosm theme
Images: images.mangafreak.me CDN
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
from .base import BaseScraper, Manga, Chapter


class HxHMangaScraper(BaseScraper):
    """Scraper for hxhmanga.com - Hunter x Hunter dedicated reader."""
    
    BASE_URL = "https://hxhmanga.com"
    
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.BASE_URL,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga. This site is HxH-only, so search returns the main manga."""
        if "hunter" in query.lower() or "hxh" in query.lower():
            return [Manga(
                title="Hunter x Hunter",
                url=self.BASE_URL,
                cover_url=None,
                source="hxhmanga.com"
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the homepage."""
        try:
            resp = self.session.get(self.BASE_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            chapters = []
            
            # Find chapter links - they follow pattern /comic/hunter-x-hunter-chapter-N/
            chapter_links = soup.find_all('a', href=re.compile(r'/comic/hunter-x-hunter-chapter-\d+/?'))
            
            seen_chapters = set()
            for link in chapter_links:
                href = link.get('href', '')
                match = re.search(r'chapter-(\d+)', href)
                if match:
                    chapter_num = match.group(1)
                    if chapter_num not in seen_chapters:
                        seen_chapters.add(chapter_num)
                        chapters.append(Chapter(
                            title=f"Chapter {chapter_num}",
                            url=f"{self.BASE_URL}/comic/hunter-x-hunter-chapter-{chapter_num}/",
                            chapter_number=float(chapter_num)
                        ))
            
            # Sort by chapter number
            chapters.sort(key=lambda c: c.chapter_number)
            return chapters
            
        except Exception as e:
            print(f"Error getting chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all image URLs from a chapter page."""
        try:
            resp = self.session.get(chapter_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            images = []
            
            # Find entry-content div which contains the chapter images
            entry_content = soup.find('div', class_='entry-content')
            if entry_content:
                # Find all img tags with mangafreak CDN
                for img in entry_content.find_all('img'):
                    src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                    if src and 'mangafreak' in src:
                        images.append(src.strip())
            
            # Fallback: search entire page for mangafreak images
            if not images:
                for img in soup.find_all('img', src=re.compile(r'mangafreak')):
                    src = img.get('src', '').strip()
                    if src and src not in images:
                        images.append(src)
            
            return images
            
        except Exception as e:
            print(f"Error getting chapter images: {e}")
            return []
    
    def download_image(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[bytes]:
        """Download an image with proper headers."""
        try:
            # mangafreak CDN requires proper referer
            if 'mangafreak' in url:
                referer = "https://mangafreak.me/"
            else:
                referer = self.BASE_URL
            
            img_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": referer,
            }
            if headers:
                img_headers.update(headers)
            
            resp = self.session.get(url, headers=img_headers, timeout=30)
            resp.raise_for_status()
            
            # Verify it's actually an image
            content_type = resp.headers.get('content-type', '')
            if 'image' in content_type or len(resp.content) > 1000:
                return resp.content
            return None
            
        except Exception as e:
            print(f"Error downloading image {url}: {e}")
            return None
