"""
ReadBerserkManga Scraper - Berserk dedicated manga reader
Site: read-berserk-manga.com
Content: Berserk by Kentaro Miura (383+ chapters)
Architecture: WordPress + hot.planeptune.us CDN
"""

import re
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional


class ReadBerserkMangaScraper(BaseScraper):
    """Scraper for read-berserk-manga.com - Berserk dedicated site"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://read-berserk-manga.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://read-berserk-manga.com/',
        })

    def search(self, query: str) -> List[Manga]:
        """Search for manga - this is a single-manga site"""
        results = []
        
        # This site only has Berserk
        if 'berserk' in query.lower() or not query:
            manga = Manga(
                title="Berserk",
                url=self.base_url,
                cover_url="https://read-berserk-manga.com/wp-content/uploads/2024/07/berserk-manga.jpg"
            )
            results.append(manga)
        
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for Berserk"""
        chapters = []
        
        try:
            resp = self.session.get(self.base_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find all chapter links - pattern: /manga/berserk-chapter-X/
            chapter_links = soup.find_all('a', href=re.compile(r'/manga/berserk-chapter-\d+'))
            
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
            
            # Find images with planeptune.us CDN URLs
            img_tags = soup.find_all('img', src=re.compile(r'planeptune\.us'))
            
            for img in img_tags:
                src = img.get('src', '')
                if src and 'planeptune.us' in src:
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
        """Download image from planeptune.us CDN"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Referer': 'https://read-berserk-manga.com/',
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
