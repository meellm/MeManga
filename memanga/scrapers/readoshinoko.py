"""
ReadOshiNoKo Scraper - Oshi no Ko dedicated manga reader
Site: readoshinoko.com (redirects to w13.readoshinoko.com)
Content: Oshi no Ko by Aka Akasaka and Mengo Yokoyari (167+ chapters)
Architecture: WordPress + mangaread.org CDN
"""

import re
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional


class ReadOshiNoKoScraper(BaseScraper):
    """Scraper for readoshinoko.com - Oshi no Ko dedicated site"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://w13.readoshinoko.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://w13.readoshinoko.com/',
        })

    def search(self, query: str) -> List[Manga]:
        """Search for manga - this is a single-manga site"""
        results = []
        
        # This site only has Oshi no Ko
        query_lower = query.lower()
        if 'oshi' in query_lower or 'oshinoko' in query_lower or '[推しの子]' in query or not query:
            manga = Manga(
                title="Oshi no Ko",
                url=self.base_url
            )
            results.append(manga)
        
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for Oshi no Ko"""
        chapters = []
        
        try:
            resp = self.session.get(self.base_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find all chapter links - pattern: /manga/oshi-no-ko-chapter-X/
            chapter_links = soup.find_all('a', href=re.compile(r'/manga/oshi-no-ko-chapter-'))
            
            seen_urls = set()
            for link in chapter_links:
                href = link.get('href', '')
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                # Extract chapter number - handles decimals like 166.5
                match = re.search(r'chapter-(\d+(?:[.-]\d+)?)', href)
                if match:
                    chapter_num = match.group(1).replace('-', '.')
                    chapter = Chapter(
                        number=chapter_num,
                        title=f"Chapter {chapter_num}",
                        url=href if href.startswith('http') else f"{self.base_url}{href}"
                    )
                    chapters.append(chapter)
            
            # Sort chapters by number (descending - latest first)
            def sort_key(ch):
                try:
                    return float(ch.number)
                except:
                    return 0
            chapters.sort(key=sort_key, reverse=True)
            
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
            
            # Find images - prioritize data-src, fallback to src
            # Images are from mangaread.org CDN
            img_tags = soup.find_all('img')
            
            for img in img_tags:
                # Try data-src first (lazy-loaded images)
                src = img.get('data-src', '').strip()
                if not src:
                    src = img.get('src', '').strip()
                
                # Filter for manga page images from mangaread.org or wp-content
                if src and ('mangaread.org' in src or 'wp-content/uploads' in src):
                    # Skip small thumbnails
                    if any(x in src for x in ['/thumbnail', '/avatar', '-150x', '-100x']):
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

    def download_image(self, url: str, path: Path) -> bool:
        """Download image from mangaread.org CDN"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Referer': 'https://w13.readoshinoko.com/',
            }
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            if len(resp.content) < 1000:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(resp.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
