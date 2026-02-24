"""
DDDManga Scraper - Dandadan manga reader

URL: https://dddmanga.com
Architecture: Nuxt SSR (same network as furieren.com, punpunmanga.com, etc.)
Images: assets.dddmanga.com CDN
"""

import re
import requests
from typing import Optional, List, Dict, Any
from .base import BaseScraper, Manga, Chapter


class DDDMangaScraper(BaseScraper):
    """Scraper for dddmanga.com - Dandadan dedicated reader."""
    
    BASE_URL = "https://dddmanga.com"
    ASSETS_URL = "https://assets.dddmanga.com/dandadan"
    
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
        """Search for manga. This site is Dandadan-only."""
        if "danda" in query.lower() or "dan da dan" in query.lower():
            return [Manga(
                title="Dandadan",
                url=self.BASE_URL,
                cover_url=f"{self.BASE_URL}/volume-covers3/dandadan.webp",
                source="dddmanga.com"
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters. The site has 225+ chapters."""
        chapters = []
        
        # The site has sequential chapters from 1 to current
        # We can get the chapter count from the homepage or use a reasonable max
        try:
            resp = self.session.get(self.BASE_URL, timeout=30)
            resp.raise_for_status()
            
            # Extract chapter count from the HTML (look for "Latest Chapter" or chapter links)
            match = re.search(r'Read Latest Chapter \((\d+)\)', resp.text)
            if match:
                max_chapter = int(match.group(1))
            else:
                # Fallback: search for highest chapter number in links
                chapter_matches = re.findall(r'/chapter/(\d+)/', resp.text)
                if chapter_matches:
                    max_chapter = max(int(c) for c in chapter_matches)
                else:
                    max_chapter = 225  # Known current count
            
            for i in range(1, max_chapter + 1):
                chapters.append(Chapter(
                    title=f"Chapter {i}",
                    url=f"{self.BASE_URL}/chapter/{i}/",
                    chapter_number=float(i)
                ))
            
            return chapters
            
        except Exception as e:
            print(f"Error getting chapters: {e}")
            # Return a reasonable range as fallback
            return [Chapter(
                title=f"Chapter {i}",
                url=f"{self.BASE_URL}/chapter/{i}/",
                chapter_number=float(i)
            ) for i in range(1, 226)]
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all image URLs from a chapter page."""
        try:
            resp = self.session.get(chapter_url, timeout=30)
            resp.raise_for_status()
            
            images = []
            
            # Extract chapter number from URL
            match = re.search(r'/chapter/(\d+)/', chapter_url)
            if not match:
                return []
            
            chapter_num = match.group(1)
            
            # Find images from assets CDN
            # Pattern: https://assets.dddmanga.com/dandadan/chapter-N/X.jpeg
            img_matches = re.findall(
                rf'src="(https://assets\.dddmanga\.com/dandadan/chapter-{chapter_num}/\d+\.(?:jpeg|jpg|png|webp))"',
                resp.text
            )
            
            if img_matches:
                images = list(dict.fromkeys(img_matches))  # Remove duplicates, preserve order
            else:
                # Fallback: search for any assets.dddmanga.com images
                all_imgs = re.findall(
                    r'src="(https://assets\.dddmanga\.com/dandadan/[^"]+)"',
                    resp.text
                )
                images = list(dict.fromkeys(all_imgs))
            
            return images
            
        except Exception as e:
            print(f"Error getting chapter images: {e}")
            return []
    
    def download_image(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[bytes]:
        """Download an image with proper headers."""
        try:
            img_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": self.BASE_URL,
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
