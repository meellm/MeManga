"""
TCB Scans scraper - Simple requests-based (no Cloudflare!)
https://tcbonepiecechapters.com
"""

import re
from typing import List
from .base import BaseScraper, Chapter, Manga


class TCBScansScraper(BaseScraper):
    """Scraper for TCB Scans - One Piece, Jujutsu Kaisen, My Hero Academia, etc."""
    
    name = "tcbscans"
    base_url = "https://tcbonepiecechapters.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - TCB has limited selection, so we list all projects."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(f"{self.base_url}/projects")
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        query_lower = query.lower()
        
        for link in soup.select("a[href*='/mangas/']"):
            title = link.get_text(strip=True)
            if not title:
                continue
            
            manga_url = link.get("href", "")
            if not manga_url.startswith("http"):
                manga_url = self.base_url + manga_url
            
            # Filter by query
            if query_lower in title.lower():
                results.append(Manga(
                    title=title,
                    url=manga_url,
                ))
        
        # Dedupe
        seen = set()
        unique = []
        for m in results:
            if m.title not in seen:
                seen.add(m.title)
                unique.append(m)
        
        return unique[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # TCB selector: div.col-span-2 > a.block.border
        for link in soup.select("div.col-span-2 a.block.border, a[href*='/chapters/']"):
            chapter_url = link.get("href", "")
            if not chapter_url.startswith("http"):
                chapter_url = self.base_url + chapter_url
            
            # Get title parts
            title_div = link.select_one("div.text-lg")
            subtitle_div = link.select_one("div.text-gray-500")
            
            title_text = title_div.get_text(strip=True) if title_div else ""
            subtitle_text = subtitle_div.get_text(strip=True) if subtitle_div else ""
            
            full_title = f"{title_text}: {subtitle_text}" if subtitle_text else title_text
            
            # Extract chapter number
            match = re.search(r'chapter[.\s-]*(\d+\.?\d*)', title_text, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', title_text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=full_title,
                    url=chapter_url,
                ))
        
        # Deduplicate
        seen = set()
        unique = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique.append(ch)
        
        return sorted(unique)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # TCB selector: picture > img
        for img in soup.select("picture img, .chapter-content img"):
            src = img.get("src") or img.get("data-src")
            if src and "logo" not in src.lower():
                if not src.startswith("http"):
                    src = self.base_url + src
                pages.append(src)
        
        return pages
