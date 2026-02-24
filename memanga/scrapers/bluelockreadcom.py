"""
BlueLockReadCom scraper (bluelock-read.com) - Blue Lock dedicated site.

Custom site with chapters list on main page, images hosted on same domain via /attachment/comic/XXXX/ pattern.
"""

import re
from typing import List
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class BlueLockReadComScraper(BaseScraper):
    """Scraper for bluelock-read.com - Blue Lock manga."""
    
    name = "bluelockreadcom"
    base_url = "https://bluelock-read.com"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site - Blue Lock)."""
        return [Manga(
            title="Blue Lock",
            url=f"{self.base_url}/",
            cover_url=None,
        )]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the main page."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Find chapter links - pattern: /chapter/XXX
        for link in soup.find_all("a", href=re.compile(r'/chapter/\d+', re.I)):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            
            # Extract chapter number from URL
            match = re.search(r'/chapter/(\d+)', href)
            if not match:
                continue
            
            chapter_num = match.group(1)
            
            # Get title text
            title_elem = link.find(class_=re.compile(r'chapter-title', re.I))
            text = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
            if not text:
                text = f"Chapter {chapter_num}"
            
            # Make absolute URL
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
        
        # Find manga page containers with images
        for page_div in soup.find_all("div", class_=re.compile(r'manga-page', re.I)):
            img = page_div.find("img")
            if not img:
                continue
            
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not src or src in seen:
                continue
            
            # Only include attachment URLs
            if "/attachment/" not in src:
                continue
            
            seen.add(src)
            
            # Make absolute URL
            if src.startswith("/"):
                src = self.base_url + src
            elif not src.startswith("http"):
                src = self.base_url + "/" + src
            
            pages.append(src)
        
        # If no pages found with manga-page class, try finding all images in manga-pages container
        if not pages:
            manga_container = soup.find(id="mangaPages") or soup.find(class_=re.compile(r'manga-pages', re.I))
            if manga_container:
                for img in manga_container.find_all("img"):
                    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                    if not src or src in seen:
                        continue
                    
                    if "/attachment/" not in src:
                        continue
                    
                    seen.add(src)
                    
                    if src.startswith("/"):
                        src = self.base_url + src
                    elif not src.startswith("http"):
                        src = self.base_url + "/" + src
                    
                    pages.append(src)
        
        return pages
