"""
Base scraper for read[manga].com style sites.

These sites share a common WordPress manga theme structure with CDN-hosted images.
Sites: readsnk.com, readberserk.com, readhaikyuu.com, readjujutsukaisen.com, readchainsawman.com
"""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class ReadMangaBaseScraper(BaseScraper):
    """
    Base scraper for read[manga].com style sites.
    
    These sites use WordPress with a manga theme and host images on CDN.
    Images require Referer header to download.
    """
    
    name: str = "readmanga_base"
    base_url: str = ""
    cdn_pattern: str = ""  # Pattern to match CDN URLs in images
    
    def __init__(self):
        super().__init__()
        # These sites need Referer header for images
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def _make_absolute(self, url: str) -> str:
        """Convert relative URL to absolute."""
        if not url:
            return url
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return self.base_url + url
        return self.base_url + "/" + url
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/?s={query.replace(' ', '+')}"
        html = self._get_html(search_url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        # These sites typically have manga links in search results
        for item in soup.select("a[href*='/manga/']"):
            href = item.get("href", "")
            if not href or "/manga/" not in href:
                continue
            
            # Make URL absolute
            href = self._make_absolute(href)
            
            # Extract title from link text or nested elements
            title = item.get_text(strip=True)
            if not title:
                img = item.find("img")
                if img:
                    title = img.get("alt", "")
            
            if title and href:
                # Avoid duplicates
                if not any(m.url == href for m in results):
                    cover = None
                    img = item.find("img")
                    if img:
                        cover = img.get("data-src") or img.get("src")
                        cover = self._make_absolute(cover)
                    
                    results.append(Manga(
                        title=title,
                        url=href,
                        cover_url=cover,
                    ))
        
        return results[:20]  # Limit results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        # Look for chapter links
        for link in soup.select("a[href*='/chapter/']"):
            href = link.get("href", "")
            if not href:
                continue
            
            # Make URL absolute
            href = self._make_absolute(href)
            
            # Extract chapter number from URL or text
            text = link.get_text(strip=True)
            
            # Try to extract number from URL first
            # Pattern: chapter-name-chapter-123 or chapter-name-123
            match = re.search(r'chapter[/-](\d+(?:\.\d+)?)', href.lower())
            if match:
                number = match.group(1)
            else:
                # Try from text
                match = re.search(r'chapter\s*(\d+(?:\.\d+)?)', text.lower())
                if match:
                    number = match.group(1)
                else:
                    # Extract any number
                    match = re.search(r'(\d+(?:\.\d+)?)', text)
                    number = match.group(1) if match else "0"
            
            # Avoid duplicates
            if not any(c.url == href for c in chapters):
                chapters.append(Chapter(
                    number=number,
                    title=text,
                    url=href,
                ))
        
        # Sort by chapter number (descending is typical for these sites)
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        seen_urls = set()
        
        # Find manga images by looking for CDN URLs
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            
            # Check if it's a manga page image (CDN URL pattern)
            if self._is_manga_image(src):
                if src not in seen_urls:
                    seen_urls.add(src)
                    pages.append(src)
        
        return pages
    
    def _is_manga_image(self, url: str) -> bool:
        """Check if URL is a manga page image."""
        if not url:
            return False
        
        # Check for CDN patterns
        patterns = [
            r"cdn\.(read|manga)",
            r"mangap/",
            r"/file/",
            r"AnimeRleases",
        ]
        
        if self.cdn_pattern:
            patterns.append(self.cdn_pattern)
        
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        
        return False
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper Referer header."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
