"""
RawKuma scraper
https://rawkuma.net

Raw Japanese manga library using WordPress Manga theme.
Has both raw and English translated manga.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class RawKumaScraper(BaseScraper):
    """Scraper for RawKuma.net"""
    
    name = "rawkuma"
    base_url = "https://rawkuma.net"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        # RawKuma uses simple search parameter
        url = f"{self.base_url}/?s={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        # Find manga items in search results
        for item in soup.select(".bsx a, .bs a, .bixbox a"):
            href = item.get("href", "")
            
            if not href or href in seen_urls or "/manga/" not in href:
                continue
            if "genre" in href or "type" in href or "status" in href:
                continue
                
            seen_urls.add(href)
            
            # Get title
            title_elem = item.select_one(".bigor .tt, .tt, .title")
            title = title_elem.get_text(strip=True) if title_elem else item.get_text(strip=True)
            
            if not title or len(title) < 2:
                continue
            
            # Get cover image
            cover_url = None
            img = item.select_one("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=href, cover_url=cover_url))
        
        return results[:15]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen_urls = set()
        
        # Find chapter list (multiple selectors for compatibility)
        chapter_list = soup.select("#chapterlist li a, .eplister li a, .chapterlist a, .wp-manga-chapter a")
        
        for link in chapter_list:
            href = link.get("href", "")
            
            if not href or href in seen_urls:
                continue
            if "manga" not in href:
                continue
                
            # Extract chapter number from URL
            match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
            if not match:
                # Try numeric pattern
                match = re.search(r'/(\d+\.?\d*)/?$', href)
            
            if not match:
                continue
            
            seen_urls.add(href)
            chapter_num = match.group(1)
            chapter_text = link.get_text(strip=True) or f"Chapter {chapter_num}"
            
            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text,
                url=href,
            ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        import json
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Method 1: Find reader images with data-src (common for Madara theme)
        for img in soup.select("#readerarea img, .reading-content img, .page-break img"):
            src = img.get("data-src") or img.get("src")
            if src:
                src = src.strip()
                if src not in seen and any(ext in src.lower() for ext in ['.jpg', '.png', '.webp', '.jpeg']):
                    seen.add(src)
                    pages.append(src)
        
        # Method 2: Look for ts_reader JSON data (some sites use this)
        if not pages:
            for script in soup.find_all("script"):
                text = script.string or ""
                if "ts_reader.run" in text:
                    match = re.search(r'ts_reader\.run\((\{.*?\})\)', text, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group(1))
                            if "sources" in data and len(data["sources"]) > 0:
                                for source in data["sources"]:
                                    if "images" in source:
                                        pages = source["images"]
                                        break
                        except json.JSONDecodeError:
                            pass
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
