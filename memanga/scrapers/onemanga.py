"""
1Manga.co Scraper

Large manga library with simple HTTP access.
Uses MangaHub CDN for images.
"""

import re
import logging
import cloudscraper
from bs4 import BeautifulSoup
from typing import List, Optional
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class OneMangaScraper(BaseScraper):
    """Scraper for 1manga.co"""
    
    name = "1manga.co"
    base_url = "https://1manga.co"
    
    def __init__(self):
        super().__init__()
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": self.base_url
        })
        self._rate_limit = 0.5  # Faster rate limit for this site
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/search?keyword={quote_plus(query)}"
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Search request failed: {e}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        
        # Find manga links in search results (prefer links with text from media-heading)
        seen_urls = set()
        manga_data = {}  # url -> (title, cover)
        
        manga_links = soup.find_all("a", href=lambda x: x and "/manga/" in x)
        
        for link in manga_links:
            href = link.get("href", "")
            if not href:
                continue
            
            # Skip navigation links
            if href.endswith("/manga/") or "/manga-" in href or href.count("/") < 3:
                continue
            
            manga_url = href if href.startswith("http") else urljoin(self.base_url, href)
            
            # Get title from link text
            title = link.get_text(strip=True)
            
            # Get cover image from link or nearby
            cover = None
            img = link.find("img")
            if img:
                cover = img.get("src") or img.get("data-src")
            
            # Only add if we have a title, or update if this one has a better title
            if manga_url in manga_data:
                existing_title, existing_cover = manga_data[manga_url]
                if title and len(title) > len(existing_title):
                    manga_data[manga_url] = (title, cover or existing_cover)
                elif cover and not existing_cover:
                    manga_data[manga_url] = (existing_title, cover)
            else:
                manga_data[manga_url] = (title, cover)
        
        # Convert to Manga objects (only those with titles)
        results = []
        for url, (title, cover) in manga_data.items():
            if title and len(title) >= 2:
                results.append(Manga(
                    title=title,
                    url=url,
                    cover_url=cover
                ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        try:
            response = self.session.get(manga_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        chapters = []
        
        # Find chapter links
        chapter_links = soup.find_all("a", href=lambda x: x and "/chapter/" in x)
        seen_nums = set()
        
        for link in chapter_links:
            href = link.get("href", "")
            if not href:
                continue
            
            # Extract chapter number from text first (more reliable)
            # Pattern: #XXX-Title or Chapter XXX
            text = link.get_text(strip=True)
            chapter_num = None
            
            # Try text pattern #123- first (1manga specific)
            match = re.search(r"#(\d+(?:\.\d+)?)-", text)
            if match:
                chapter_num = float(match.group(1))
            
            # Try "Chapter 123" pattern
            if chapter_num is None:
                match = re.search(r"chapter\s*(\d+(?:\.\d+)?)", text, re.I)
                if match:
                    chapter_num = float(match.group(1))
            
            # Last resort: try URL pattern (but only short numbers to avoid weird IDs)
            if chapter_num is None:
                match = re.search(r"chapter-(\d{1,4}(?:\.\d+)?)\b", href, re.I)
                if match:
                    chapter_num = float(match.group(1))
            
            if chapter_num is None or chapter_num in seen_nums:
                continue
            
            seen_nums.add(chapter_num)
            
            chapter_url = href if href.startswith("http") else urljoin(self.base_url, href)
            
            # Clean up title
            title = text.strip()
            if title.startswith(f"#{int(chapter_num)}-"):
                title = title.split("-", 1)[1].strip() if "-" in title else title
            
            chapters.append(Chapter(
                number=str(chapter_num),
                title=title or f"Chapter {chapter_num}",
                url=chapter_url
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        
        # Remove duplicates
        unique_chapters = []
        seen_nums = set()
        for chapter in chapters:
            if chapter.numeric not in seen_nums:
                seen_nums.add(chapter.numeric)
                unique_chapters.append(chapter)
        
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get image URLs for a chapter."""
        try:
            response = self.session.get(chapter_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to get chapter pages: {e}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        page_urls = []
        
        # Find manga images - look for MangaHub CDN images specifically
        images = soup.find_all("img")
        for img in images:
            src = img.get("src") or img.get("data-src") or ""
            
            # Look for MangaHub CDN pattern: imgx.mghcdn.com
            # Format: https://imgx.mghcdn.com/{manga}/{chapter}/{page}.jpg
            if "mghcdn.com" in src:
                if src not in page_urls:
                    page_urls.append(src)
        
        return page_urls
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.base_url,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            content = response.content
            if len(content) < 1000:
                logger.warning(f"Image too small ({len(content)} bytes): {url}")
                return False
            
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return False
