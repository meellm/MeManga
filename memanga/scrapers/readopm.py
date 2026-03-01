"""
ReadOPM scraper for readopm.com
Multi-manga aggregator with cdn.readopm.com CDN
"""

import re
import logging
from pathlib import Path
from typing import List, Optional
from bs4 import BeautifulSoup
import requests

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class ReadOPMScraper(BaseScraper):
    """Scraper for readopm.com - Manga aggregator with One Punch Man focus."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://ww6.readopm.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        results = []
        
        try:
            # This site has a search/manga listing
            response = self.session.get(f"{self.base_url}/manga/", timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find manga links
            for card in soup.find_all("div", class_=lambda c: c and "card" in c):
                title_elem = card.find(["h5", "h4", "h3", "a"])
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if query.lower() in title.lower():
                        link = card.find("a", href=True)
                        if link:
                            manga = Manga(
                                title=title,
                                url=link["href"] if link["href"].startswith("http") else f"{self.base_url}{link['href']}"
                            )
                            results.append(manga)
            
            # If no results, try main page
            if not results and any(term in query.lower() for term in ["one punch", "onepunch", "opm"]):
                manga = Manga(
                    title="One Punch Man",
                    url=f"{self.base_url}/manga/onepunch-man-one/"
                )
                results.append(manga)
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            # Fallback
            if "one punch" in query.lower() or "opm" in query.lower():
                results.append(Manga(
                    title="One Punch Man",
                    url=f"{self.base_url}/manga/onepunch-man-one/"
                ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the manga page."""
        chapters = []
        
        try:
            response = self.session.get(manga_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find chapter links
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                # Match chapter URLs
                if "/chapter/" in href:
                    # Extract chapter number
                    match = re.search(r"chapter[s]?[-_]?(\d+(?:\.\d+)?)", href, re.I)
                    if not match:
                        match = re.search(r"(\d+(?:\.\d+)?)\s*$", text)
                    
                    if match:
                        num = match.group(1)
                        chapter = Chapter(
                            number=num,
                            title=text or f"Chapter {num}",
                            url=href if href.startswith("http") else f"{self.base_url}{href}"
                        )
                        chapters.append(chapter)
            
            # Remove duplicates
            seen_urls = set()
            unique_chapters = []
            for ch in chapters:
                if ch.url not in seen_urls:
                    seen_urls.add(ch.url)
                    unique_chapters.append(ch)
            
            # Sort by chapter number descending
            unique_chapters.sort(key=lambda x: float(x.number) if x.number.replace(".", "").isdigit() else 0, reverse=True)
            
            logger.info(f"Found {len(unique_chapters)} chapters")
            return unique_chapters
            
        except Exception as e:
            logger.error(f"Error getting chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs from a chapter."""
        pages = []
        
        try:
            response = self.session.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find images with class pages__img
            for img in soup.find_all("img", class_=lambda c: c and "pages__img" in c):
                # Check data-src first (lazy loaded)
                img_url = img.get("data-src") or img.get("src")
                
                if img_url and not img_url.startswith("data:"):
                    # Clean URL (remove whitespace/control chars)
                    img_url = img_url.strip()
                    
                    # Make absolute URL
                    if img_url.startswith("//"):
                        img_url = "https:" + img_url
                    elif img_url.startswith("/"):
                        img_url = self.base_url + img_url
                    
                    # Only CDN images
                    if "cdn.readopm.com" in img_url or "/file/mangap/" in img_url:
                        pages.append(img_url)
            
            # Fallback: find all cdn images
            if not pages:
                for img in soup.find_all("img"):
                    for attr in ["src", "data-src"]:
                        src = img.get(attr, "")
                        if src and "cdn.readopm.com" in src:
                            if src not in pages:
                                pages.append(src)
            
            logger.info(f"Found {len(pages)} pages in chapter")
            return pages
            
        except Exception as e:
            logger.error(f"Error getting pages from {chapter_url}: {e}")
            return []
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": self.base_url,
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            if len(response.content) < 1000:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(response.content)
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False
