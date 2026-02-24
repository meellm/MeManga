"""
MangaForFree scraper
https://mangaforfree.net

WordPress Madara theme manga site.
Uses AJAX POST to /wp-admin/admin-ajax.php for chapter loading.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaForFreeScraper(BaseScraper):
    """Scraper for MangaForFree.net"""
    
    name = "mangaforfree"
    base_url = "https://mangaforfree.net"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".c-tabs-item__content"):
            title_el = item.select_one(".post-title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            manga_url = title_el.get("href", "")
            
            cover_el = item.select_one("img")
            cover_url = None
            if cover_el:
                cover_url = cover_el.get("data-src") or cover_el.get("src")
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga using AJAX."""
        from bs4 import BeautifulSoup
        
        # First, get the manga page to find the manga ID
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Find manga ID from data-id attribute
        manga_id = None
        el = soup.select_one('[data-id]')
        if el:
            manga_id = el.get('data-id')
        
        chapters = []
        seen = set()
        
        if manga_id:
            # Use AJAX to load chapters
            ajax_url = f"{self.base_url}/wp-admin/admin-ajax.php"
            data = {
                'action': 'manga_get_chapters',
                'manga': manga_id
            }
            
            try:
                response = self.session.post(ajax_url, data=data, timeout=20)
                ajax_soup = BeautifulSoup(response.text, "html.parser")
                
                for link in ajax_soup.select('a'):
                    href = link.get("href", "")
                    if not href or href == "#" or href in seen:
                        continue
                    seen.add(href)
                    
                    chapter_text = link.get_text(strip=True)
                    
                    # Extract chapter number
                    match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
                    if not match:
                        match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
                    
                    chapter_num = match.group(1) if match else chapter_text[:30]
                    
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=None,
                        url=href,
                        date=None,
                    ))
            except Exception as e:
                print(f"AJAX chapter load failed: {e}")
        
        # Fallback: try direct HTML parsing
        if not chapters:
            for link in soup.select('.wp-manga-chapter a, .chapter-item a'):
                href = link.get("href", "")
                if not href or href in seen:
                    continue
                seen.add(href)
                
                chapter_text = link.get_text(strip=True)
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
                chapter_num = match.group(1) if match else chapter_text[:30]
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=None,
                    url=href,
                    date=None,
                ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        for img in soup.select(".reading-content img"):
            src = img.get("data-src") or img.get("src") or img.get("data-lazy-src")
            if not src:
                continue
            
            src = src.strip()
            if src in seen:
                continue
            
            # Skip loading placeholders
            if any(x in src.lower() for x in ["loading", "lazy", "placeholder", ".gif"]):
                continue
            
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                seen.add(src)
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
