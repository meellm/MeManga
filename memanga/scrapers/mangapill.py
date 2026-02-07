"""
Mangapill scraper
https://mangapill.com

Simple requests-based scraper - no Cloudflare protection.
"""

import re
from typing import List, Optional
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangapillScraper(BaseScraper):
    """Scraper for Mangapill."""
    
    name = "mangapill"
    base_url = "https://mangapill.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        # Find all manga links in search results
        seen = set()
        for link in soup.select('a[href^="/manga/"]'):
            href = link.get("href", "")
            if href in seen or not href:
                continue
            seen.add(href)
            
            manga_url = f"{self.base_url}{href}"
            
            # Get title from the link or nearby text
            title = link.get_text(strip=True)
            if not title:
                # Try to get from image alt or title attribute
                img = link.find("img")
                if img:
                    title = img.get("alt", "") or img.get("title", "")
            
            if not title:
                # Extract from URL
                title = href.split("/")[-1].replace("-", " ").title()
            
            # Get cover image if available
            cover_url = None
            img = link.find("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
            
            if title and len(title) > 2:
                results.append(Manga(
                    title=title,
                    url=manga_url,
                    cover_url=cover_url,
                ))
        
        # Deduplicate by URL
        unique = {}
        for m in results:
            if m.url not in unique:
                unique[m.url] = m
        
        return list(unique.values())[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # Find chapters in the chapters container
        for link in soup.select('a[href*="/chapters/"]'):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number from text like "Chapter 57" or "Chapter 36.5"
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if match:
                chapter_num = match.group(1)
            else:
                # Try to extract from URL
                url_match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
                chapter_num = url_match.group(1) if url_match else chapter_text
            
            chapters.append(Chapter(
                number=chapter_num,
                title=None,
                url=chapter_url,
                date=None,
            ))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Find all page images with data-src attribute
        for img in soup.select('img.js-page'):
            src = img.get("data-src") or img.get("src")
            if src and not src.endswith("loading.gif"):
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://mangapill.com/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
