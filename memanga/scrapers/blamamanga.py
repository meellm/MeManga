"""
BlameManga Scraper - BLAME! dedicated manga reader
Site: blame-manga.com (w9.blame-manga.com)
Content: BLAME! by Tsutomu Nihei (65 chapters)
Architecture: WordPress + Blogger CDN (blogger.googleusercontent.com)
"""

import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional


class BlameMangaScraper(BaseScraper):
    """Scraper for blame-manga.com - BLAME! dedicated site"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://w9.blame-manga.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://w9.blame-manga.com/',
        })

    def search(self, query: str) -> List[Manga]:
        """Search for manga - this is a single-manga site"""
        results = []
        
        # This site only has BLAME!
        if 'blame' in query.lower() or not query:
            manga = Manga(
                title="BLAME!",
                url=self.base_url,
                cover_url="https://w9.blame-manga.com/wp-content/uploads/2022/03/Blame-Volume-1.webp"
            )
            results.append(manga)
        
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for BLAME!"""
        chapters = []
        
        try:
            resp = self.session.get(self.base_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find all chapter links - pattern: /manga/blame-chapter-X/
            chapter_links = soup.find_all('a', href=re.compile(r'/manga/blame-chapter-\d+'))
            
            seen_urls = set()
            for link in chapter_links:
                href = link.get('href', '')
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                # Extract chapter number
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    chapter_num = match.group(1)
                    chapter = Chapter(
                        number=chapter_num,
                        title=f"Chapter {chapter_num}",
                        url=href if href.startswith('http') else f"{self.base_url}{href}"
                    )
                    chapters.append(chapter)
            
            # Sort chapters by number (descending - latest first)
            chapters.sort(key=lambda x: float(x.number), reverse=True)
            
        except Exception as e:
            print(f"Error fetching chapters: {e}")
        
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get image URLs for a chapter"""
        images = []
        
        try:
            resp = self.session.get(chapter_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find images with Blogger CDN URLs (blogger.googleusercontent.com)
            img_tags = soup.find_all('img', src=re.compile(r'blogger\.googleusercontent\.com'))
            
            for img in img_tags:
                src = img.get('src', '')
                if src and 'blogger.googleusercontent.com' in src:
                    # Skip small images (thumbnails)
                    if '/s320/' in src or '/s200/' in src or '/s100/' in src:
                        continue
                    images.append(src)
            
            # Deduplicate while preserving order
            seen = set()
            unique_images = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            
            return unique_images
            
        except Exception as e:
            print(f"Error fetching pages: {e}")
        
        return images

    def download_image(self, url: str, headers: Optional[dict] = None) -> bytes:
        """Download image from Blogger CDN"""
        if headers is None:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Referer': 'https://w9.blame-manga.com/',
            }
        
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content
