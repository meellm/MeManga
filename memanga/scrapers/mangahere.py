"""
MangaHere scraper
Website: https://www.mangahere.cc
Simple HTTP scraper - no Cloudflare
"""

import re
from typing import List, Optional
from urllib.parse import urljoin, quote

from .base import BaseScraper, Manga, Chapter


class MangaHereScraper(BaseScraper):
    """Scraper for mangahere.cc"""
    
    name = "mangahere"
    base_url = "https://www.mangahere.cc"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga on MangaHere"""
        from bs4 import BeautifulSoup
        
        search_url = f"{self.base_url}/search?title={quote(query)}"
        
        try:
            html = self._get_html(search_url)
        except Exception as e:
            print(f"[MangaHere] Search request failed: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        # Find manga entries in the list
        for item in soup.select('.manga-list-4-list li'):
            link = item.select_one('.manga-list-4-item-title a')
            if not link:
                continue
            
            href = link.get('href', '')
            title = link.get('title', '') or link.get_text(strip=True)
            
            if not href or href in seen:
                continue
            seen.add(href)
            
            # Get cover image
            cover_url = None
            img = item.select_one('.manga-list-4-cover')
            if img:
                cover_url = img.get('src')
            
            manga_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga"""
        from bs4 import BeautifulSoup
        
        try:
            html = self._get_html(manga_url)
        except Exception as e:
            print(f"[MangaHere] Failed to get manga page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen = set()
        
        # Find chapter links
        for link in soup.select('.detail-main-list li a, a[href*="/manga/"][href*="/c"]'):
            href = link.get('href', '')
            if not href or href in seen or '/c' not in href:
                continue
            seen.add(href)
            
            # Extract chapter number from URL (e.g., /manga/solo_leveling/c202/1.html)
            match = re.search(r'/c(\d+\.?\d*)', href)
            if not match:
                continue
            
            chapter_num = match.group(1)
            
            # Get title from text
            text = link.get('title', '') or link.get_text(strip=True)
            
            chapter_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text if text else f"Chapter {chapter_num}",
                url=chapter_url,
            ))
        
        return sorted(chapters, reverse=True)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter"""
        from bs4 import BeautifulSoup
        
        # MangaHere uses JavaScript for loading pages
        # We need to try to get the image URLs from the page
        try:
            html = self._get_html(chapter_url)
        except Exception as e:
            print(f"[MangaHere] Failed to get chapter page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        pages = []
        
        # Try to find image from reader
        reader_img = soup.select_one('#image, .reader-main-img img')
        if reader_img:
            src = reader_img.get('src') or reader_img.get('data-src')
            if src:
                pages.append(src)
        
        # Try to extract from JavaScript
        # MangaHere stores images in JS variables
        for script in soup.find_all('script'):
            if not script.string:
                continue
            
            # Look for chapterImages array
            match = re.search(r'chapterImages\s*=\s*\[([^\]]+)\]', script.string)
            if match:
                array_content = match.group(1)
                urls = re.findall(r'["\']([^"\']+(?:\.jpg|\.jpeg|\.png|\.webp)[^"\']*)["\']', array_content, re.I)
                for url in urls:
                    if url.startswith('//'):
                        url = 'https:' + url
                    elif not url.startswith('http'):
                        url = urljoin(self.base_url, url)
                    if url not in pages:
                        pages.append(url)
        
        # Try to find page count and construct URLs
        if not pages:
            total_pages = 0
            for script in soup.find_all('script'):
                if script.string and 'imagecount' in script.string.lower():
                    match = re.search(r'imagecount\s*=\s*(\d+)', script.string, re.I)
                    if match:
                        total_pages = int(match.group(1))
                        break
            
            if total_pages > 0:
                # Try to construct page URLs
                base = chapter_url.rsplit('/', 1)[0]
                for i in range(1, total_pages + 1):
                    pages.append(f"{base}/{i}.html")
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': f'{self.base_url}/',
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            from pathlib import Path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"[MangaHere] Failed to download {url}: {e}")
            return False
