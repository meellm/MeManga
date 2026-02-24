"""Call of the Night scraper for call-of-the-night.online"""

import re
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional


class CallOfTheNightScraper(BaseScraper):
    """Scraper for call-of-the-night.online - WordPress Zazm theme + laiond.com CDN"""
    
    name = "CallOfTheNight"
    base_url = "https://w2.call-of-the-night.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - single manga site, returns if query matches"""
        query_lower = query.lower()
        keywords = ["call of the night", "yofukashi", "uta", "nazuna", "kou", "vampire"]
        
        if any(kw in query_lower for kw in keywords):
            return [Manga(
                title="Call of the Night (Yofukashi no Uta)",
                url=self.base_url,
                cover="https://w2.call-of-the-night.online/wp-content/uploads/2025/07/cropped-ezgif-787022e03b6957-192x192.jpg",
                source=self.name
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga"""
        chapters = []
        seen_urls = set()
        
        try:
            resp = self._request(self.base_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find chapter links - format: /comic/call-of-the-night-chapter-N/
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "/comic/call-of-the-night-chapter-" in href:
                    # Handle special chapter numbers like "200-8"
                    match = re.search(r"chapter-(\d+(?:-\d+)?(?:\.\d+)?)", href)
                    if match:
                        chapter_str = match.group(1)
                        url = href if href.startswith("http") else self.base_url + href
                        
                        # Avoid duplicates
                        if url not in seen_urls:
                            seen_urls.add(url)
                            chapters.append(Chapter(
                                number=chapter_str,
                                title=f"Chapter {chapter_str}",
                                url=url,
                            ))
            
            # Sort by chapter number (handle 200-8 format)
            def parse_chapter_num(ch):
                try:
                    if "-" in ch.number:
                        parts = ch.number.split("-")
                        return float(parts[0]) + float(parts[1]) * 0.1
                    return float(ch.number)
                except:
                    return 0
            
            chapters.sort(key=parse_chapter_num)
            
        except Exception as e:
            print(f"Error getting chapters: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images for a chapter"""
        pages = []
        
        try:
            resp = self._request(chapter_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find images in .images-container (laiond.com CDN)
            container = soup.find(class_="images-container")
            if container:
                for img in container.find_all("img"):
                    # Handle lazyload attribute (used as src in this theme)
                    src = img.get("lazyload") or img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                    if src and ("laiond.com" in src or ".jpg" in src or ".png" in src or ".webp" in src):
                        if src not in pages:
                            pages.append(src)
            
            # Fallback: find all images with laiond.com domain
            if not pages:
                for img in soup.find_all("img"):
                    src = img.get("src", "") or img.get("lazyload", "")
                    if "laiond.com" in src:
                        if src not in pages:
                            pages.append(src)
            
        except Exception as e:
            print(f"Error getting chapter pages: {e}")
        
        return pages
    
    def download_image(self, url: str, path: str) -> bool:
        """Download an image to the specified path"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": self.base_url,
                "Accept": "image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
            }
            
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            if len(resp.content) < 1000:
                print(f"Image too small ({len(resp.content)} bytes): {url}")
                return False
            
            with open(path, "wb") as f:
                f.write(resp.content)
            
            return True
            
        except Exception as e:
            print(f"Error downloading image: {e}")
            return False
