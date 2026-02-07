"""
Mangago scraper
https://www.mangago.me

Large yaoi/shoujo collection, general manga too.
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangagoScraper(BaseScraper):
    """Scraper for Mangago.me"""
    
    name = "mangago"
    base_url = "https://www.mangago.me"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/r/l_search/?name={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".pic_list li, .manga-list li, .searchlist li"):
            link = item.find("a")
            if not link:
                continue
            
            href = link.get("href", "")
            if not href or "/read-manga/" not in href:
                continue
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            # Get title
            title_elem = item.select_one(".title, h3, a")
            title = title_elem.get("title", "") or title_elem.get_text(strip=True) if title_elem else ""
            
            if not title:
                img = item.find("img")
                title = img.get("alt", "") if img else href.split("/")[-2].replace("_", " ").title()
            
            # Get cover
            cover_url = None
            img = item.find("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")
            
            if title:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        for link in soup.select("#chapter_table a, .chapter_list a, a[href*='/chapter/']"):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            chapter_text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'ch(?:apter)?[_\s.-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'ch(?:apter)?[_\s.-]*(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'/(\d+\.?\d*)/?$', href)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_url not in [c.url for c in chapters]:
                chapters.append(Chapter(
                    number=chapter_num,
                    title=chapter_text,
                    url=chapter_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Mangago often uses an image server
        for img in soup.select("#page img, .page-img, .image-content img"):
            src = img.get("data-src") or img.get("src")
            if src and (".jpg" in src.lower() or ".png" in src.lower() or ".webp" in src.lower()):
                if not src.startswith("http"):
                    src = f"https:{src}" if src.startswith("//") else f"{self.base_url}{src}"
                if src not in pages:
                    pages.append(src)
        
        # Also check for images in script (some use JS loading)
        for script in soup.find_all("script"):
            text = script.string or ""
            if "imgsrcs" in text or "images" in text:
                urls = re.findall(r'https?://[^\s"\'<>]+\.(?:jpg|png|webp)', text)
                for url in urls:
                    if url not in pages:
                        pages.append(url)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
