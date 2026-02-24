"""
BeckManga Scraper

Website: beckmanga.com
Manga: Beck by Harold Sakuishi
Architecture: WordPress + Blogger CDN (bp.blogspot.com)
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga


class BeckMangaScraper(BaseScraper):
    """Scraper for beckmanga.com - Beck: Mongolian Chop Squad dedicated site."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://beckmanga.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://beckmanga.com/",
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (this is a single-manga site)."""
        query_lower = query.lower()
        if any(term in query_lower for term in ["beck", "mongolian", "chop", "koyuki", "tanaka"]):
            return [Manga(
                title="Beck: Mongolian Chop Squad",
                url=self.base_url,
                cover_url=f"{self.base_url}/wp-content/uploads/2024/10/Beck-Manga-Volume-1-685x1024.webp",
                description="Beck: Mongolian Chop Squad manga by Harold Sakuishi. Follow Koyuki Tanaka as he discovers his passion for music and joins a rock band."
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from Beck manga."""
        chapters = []
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find chapter links - they're in menu-item links or page content
            chapter_links = soup.find_all('a', href=re.compile(r'/manga/beck-chapter-'))
            
            seen_urls = set()
            for link in chapter_links:
                href = link.get('href', '')
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    
                    # Extract chapter number (handle formats like chapter-101-5 for 101.5)
                    match = re.search(r'chapter-(\d+)(?:-(\d+))?', href)
                    if match:
                        # Handle decimal chapters like chapter-101-5 -> 101.5
                        chapter_num = match.group(1)
                        if match.group(2):
                            chapter_num = f"{chapter_num}.{match.group(2)}"
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
            
            # Find images - check data-lazy-src, src attributes
            # Images are on Blogger CDN (blogger.googleusercontent.com)
            for img in soup.find_all('img'):
                src = img.get('data-lazy-src') or img.get('data-src') or img.get('src', '')
                
                if 'blogger.googleusercontent.com' in src or 'bp.blogspot.com' in src:
                    # Clean up the URL
                    if src.startswith('//'):
                        src = 'https:' + src
                    
                    if src not in pages:
                        pages.append(src)
            
            # Also check for og:image meta tags as backup
            if not pages:
                for meta in soup.find_all('meta', property='og:image'):
                    content = meta.get('content', '')
                    if 'blogger.googleusercontent.com' in content or 'bp.blogspot.com' in content:
                        pages.append(content)
            
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
