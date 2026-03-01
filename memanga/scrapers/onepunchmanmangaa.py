"""
OnePunchManMangaa scraper for onepunchmanmangaa.com
WordPress + Kadence theme with WP Rocket lazy loading
One Punch Man dedicated manga reader
"""

import re
import logging
from pathlib import Path
from typing import List, Optional
from bs4 import BeautifulSoup
import requests

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class OnePunchManMangaaScraper(BaseScraper):
    """Scraper for onepunchmanmangaa.com - One Punch Man dedicated reader."""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://onepunchmanmangaa.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - this is a single-manga site."""
        results = []
        
        # Always return the main manga for One Punch Man searches
        if any(term in query.lower() for term in ["one punch", "onepunch", "opm", "saitama"]):
            manga = Manga(
                title="One Punch Man",
                url=self.base_url
            )
            results.append(manga)
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the homepage."""
        chapters = []
        
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find chapter links - they use simple anchor tags
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                # Match chapter patterns
                if "chapter" in href.lower() and "one-punch-man" in href.lower():
                    # Extract chapter number from URL or text
                    match = re.search(r"chapter[s]?[-_]?(\d+(?:\.\d+)?)", href, re.I)
                    if not match:
                        match = re.search(r"(\d+(?:\.\d+)?)\s*$", text)
                    
                    if match:
                        num = match.group(1)
                        chapter = Chapter(
                            number=num,
                            title=text or f"Chapter {num}",
                            url=href if href.startswith("http") else f"{self.base_url}{href}" if href.startswith("/") else href
                        )
                        chapters.append(chapter)
            
            # Remove duplicates by URL
            seen_urls = set()
            unique_chapters = []
            for ch in chapters:
                if ch.url not in seen_urls:
                    seen_urls.add(ch.url)
                    unique_chapters.append(ch)
            
            # Sort by chapter number descending
            unique_chapters.sort(key=lambda x: float(x.number) if x.number.replace(".", "").isdigit() else 0, reverse=True)
            
            logger.info(f"Found {len(unique_chapters)} chapters on onepunchmanmangaa.com")
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
            
            # Find images in wp-block-image figures
            # They use lazy loading with data-lazy-src or data-lazy-srcset
            for figure in soup.find_all("figure", class_=lambda c: c and "wp-block-image" in c):
                img = figure.find("img")
                if img:
                    # Try different image source attributes
                    img_url = None
                    
                    # Check data-lazy-src first (lazy loaded full-size)
                    if img.get("data-lazy-src"):
                        img_url = img.get("data-lazy-src")
                    # Then check data-lazy-srcset for the highest resolution
                    elif img.get("data-lazy-srcset"):
                        srcset = img.get("data-lazy-srcset")
                        # Parse srcset and get the original (non-sized) version
                        urls = [u.strip().split()[0] for u in srcset.split(",")]
                        if urls:
                            # Get the last one (usually highest res) or original
                            for url in urls:
                                if ".webp" in url and "-" not in url.split("/")[-1].split(".")[0][-4:]:
                                    img_url = url
                                    break
                            if not img_url:
                                img_url = urls[-1]
                    # Fall back to regular src (in noscript)
                    elif img.get("src") and not img.get("src").startswith("data:"):
                        img_url = img.get("src")
                    
                    if img_url:
                        # Get original image without WordPress size suffix
                        img_url = re.sub(r"-\d+x\d+\.(webp|jpg|jpeg|png)", r".\1", img_url)
                        
                        # Make absolute URL
                        if img_url.startswith("//"):
                            img_url = "https:" + img_url
                        elif img_url.startswith("/"):
                            img_url = self.base_url + img_url
                        elif not img_url.startswith("http"):
                            img_url = self.base_url + "/" + img_url
                        
                        # Only add manga pages (not site assets like logos)
                        if "/wp-content/uploads/" in img_url:
                            # Exclude site assets (logos, icons, small images)
                            if "cropped-" not in img_url and "logo" not in img_url.lower():
                                pages.append(img_url)
            
            # Also try noscript fallback images
            if not pages:
                for noscript in soup.find_all("noscript"):
                    noscript_soup = BeautifulSoup(str(noscript), "html.parser")
                    for img in noscript_soup.find_all("img"):
                        src = img.get("src", "")
                        if "/wp-content/uploads/" in src and ("chapter" in src.lower() or "manga" in src.lower()):
                            # Get original size
                            src = re.sub(r"-\d+x\d+\.(webp|jpg|jpeg|png)", r".\1", src)
                            if src not in pages:
                                pages.append(src)
            
            # Fallback: find any wp-content/uploads images related to the chapter
            if not pages:
                for img in soup.find_all("img"):
                    for attr in ["src", "data-src", "data-lazy-src"]:
                        src = img.get(attr, "")
                        if src and "/wp-content/uploads/" in src:
                            if not src.startswith("data:"):
                                src = re.sub(r"-\d+x\d+\.(webp|jpg|jpeg|png)", r".\1", src)
                                if src.startswith("//"):
                                    src = "https:" + src
                                elif src.startswith("/"):
                                    src = self.base_url + src
                                
                                # Filter to manga pages
                                if "punch" in src.lower() or "manga" in src.lower() or "chapter" in src.lower():
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
