"""Witch Hat Atelier scraper for witch-hat-atelier.online"""

import re
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga
from typing import List, Optional


class WitchHatAtelierScraper(BaseScraper):
    """Scraper for witch-hat-atelier.online - WordPress Zazm theme + laiond.com CDN"""
    
    name = "WitchHatAtelier"
    base_url = "https://witch-hat-atelier.online"
    
    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - single manga site, returns if query matches"""
        query_lower = query.lower()
        keywords = ["witch hat atelier", "tongari", "boushi", "atelier", "coco", "qifrey"]
        
        if any(kw in query_lower for kw in keywords):
            return [Manga(
                title="Witch Hat Atelier (Tongari Boushi no Atelier)",
                url=self.base_url,
                cover_url="https://witch-hat-atelier.online/wp-content/uploads/2025/06/witch-hat-atelier-manga.webp",
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
            
            # Find chapter links - format: /comic/witch-hat-atelier-chapter-N/
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "/comic/witch-hat-atelier-chapter-" in href:
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    
                    # Extract chapter number
                    match = re.search(r"-chapter-(\d+(?:\.\d+)?)", href, re.I)
                    if match:
                        num = float(match.group(1))
                        title = link.get_text(strip=True) or f"Chapter {num}"
                        
                        full_url = href if href.startswith("http") else self.base_url + href
                        
                        chapters.append(Chapter(
                            title=title,
                            url=full_url,
                            number=str(num),
                        ))
            
            # Sort by chapter number
            chapters.sort(key=lambda x: x.number)
            
        except Exception as e:
            print(f"[WitchHatAtelier] Error fetching chapters: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all image URLs from a chapter"""
        images = []
        
        try:
            resp = self._request(chapter_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find images in .images-container or .entry-content
            container = soup.select_one(".images-container") or soup.select_one(".entry-content")
            
            if container:
                for img in container.find_all("img"):
                    # Check various src attributes - lazyload is custom attribute
                    src = None
                    for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
                        val = img.get(attr, "")
                        if val and ("laiond.com" in val or "loinew.com" in val or val.endswith((".jpg", ".png", ".webp"))):
                            src = val
                            break
                    
                    if src:
                        if not src.startswith("http"):
                            src = "https:" + src if src.startswith("//") else self.base_url + src
                        images.append(src)
            
        except Exception as e:
            print(f"[WitchHatAtelier] Error fetching pages: {e}")
        
        return images
