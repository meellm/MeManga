"""
OnePieceRead scraper (onepieceread.com) - One Piece dedicated site.

Next.js SSR site with images rendered inline in HTML.
Images hosted on cdn.onepiecechapters.com.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class OnePieceReadScraper(BaseScraper):
    """Scraper for onepieceread.com - One Piece manga."""
    
    name = "onepieceread"
    base_url = "https://onepieceread.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site - One Piece)."""
        return [Manga(
            title="One Piece",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the chapters page."""
        # Main page has limited chapters, use chapters page for full list
        chapters_url = f"{self.base_url}/chapters"
        html = self._get_html(chapters_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - pattern: /reader/XXX
        for link in soup.find_all("a", href=re.compile(r'/reader/\d+', re.I)):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            # Extract chapter number from URL
            match = re.search(r'/reader/(\d+)', href)
            if not match:
                continue
            
            chapter_num = match.group(1)
            
            # Get title text - look for title span or use link text
            text = link.get_text(strip=True)
            if not text or text == "Read Now":
                text = f"Chapter {chapter_num}"
            
            # Make absolute URL
            if not href.startswith("http"):
                href = self.base_url + href
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text,
                url=href,
            ))
        
        # If chapters page didn't work, try main page
        if not chapters:
            html = self._get_html(self.base_url)
            soup = BeautifulSoup(html, "html.parser")
            
            for link in soup.find_all("a", href=re.compile(r'/reader/\d+', re.I)):
                href = link.get("href", "")
                if not href or href in seen:
                    continue
                seen.add(href)
                
                match = re.search(r'/reader/(\d+)', href)
                if not match:
                    continue
                
                chapter_num = match.group(1)
                text = link.get_text(strip=True)
                if not text or text == "Read Now":
                    text = f"Chapter {chapter_num}"
                
                if not href.startswith("http"):
                    href = self.base_url + href
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text,
                    url=href,
                ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen = set()
        
        # Find all img tags with cdn.onepiecechapters.com URLs
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src or src in seen:
                continue
            
            # Only include CDN images (actual manga pages)
            if "cdn.onepiecechapters.com" not in src:
                continue
            
            seen.add(src)
            pages.append(src)
        
        return pages
