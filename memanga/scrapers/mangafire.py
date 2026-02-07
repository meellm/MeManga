"""
MangaFire.to scraper
https://mangafire.to

⚠️ NOTE: MangaFire uses heavy DRM protection:
  - Image URLs are generated via obfuscated JavaScript
  - Images are scrambled and require descrambling
  - Cloudflare Turnstile challenges
  
Search and chapters work, but page extraction does NOT work.
This scraper is kept for reference but should not be used in production.

For similar content, use: mangapill.com, mangadex.org, or mangakatana.com
"""

import re
from typing import List
from pathlib import Path
import cloudscraper
from .base import BaseScraper, Chapter, Manga


class MangaFireScraper(BaseScraper):
    """Scraper for MangaFire.to using cloudscraper"""
    
    name = "mangafire"
    base_url = "https://mangafire.to"
    
    def __init__(self):
        super().__init__()
        # Use cloudscraper instead of regular requests
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by scraping home/az-list pages."""
        from bs4 import BeautifulSoup
        
        query_lower = query.lower()
        results = []
        seen_urls = set()
        
        # Search in home page first (has popular/trending manga)
        pages_to_check = [
            f"{self.base_url}/home",
            f"{self.base_url}/updated",
            f"{self.base_url}/az-list?page=1",
        ]
        
        for page_url in pages_to_check:
            try:
                response = self.session.get(page_url, timeout=30)
                if response.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(response.text, "html.parser")
                
                for item in soup.select('.unit, .inner'):
                    link = item.find('a', href=re.compile(r'/manga/'))
                    if not link:
                        continue
                    
                    href = link.get('href', '')
                    if not href or href in seen_urls:
                        continue
                    
                    manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    seen_urls.add(href)
                    
                    # Get title
                    title_elem = item.select_one('.info .name, .title, h3')
                    title = title_elem.get_text(strip=True) if title_elem else ""
                    
                    if not title:
                        title = link.get("title", "") or link.get_text(strip=True)
                    
                    # Clean title (remove leading numbers)
                    title = re.sub(r'^\d+', '', title).strip()
                    
                    if not title:
                        img = item.find("img")
                        title = img.get("alt", "") if img else ""
                    
                    # Get cover
                    cover_url = None
                    img = item.find("img")
                    if img:
                        cover_url = img.get("data-src") or img.get("src")
                    
                    # Check if matches query
                    if title and query_lower in title.lower():
                        results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
                
                if len(results) >= 10:
                    break
                    
            except Exception as e:
                continue
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga using AJAX API."""
        from bs4 import BeautifulSoup
        
        response = self.session.get(manga_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        chapters = []
        
        # Try to find manga ID from URL (format: /manga/title.ID)
        manga_id = manga_url.rstrip("/").split(".")[-1]
        
        # Use AJAX endpoint to get chapters (English only for now)
        for chapter_type in ['chapter']:
            ajax_url = f"{self.base_url}/ajax/manga/{manga_id}/{chapter_type}/en"
            try:
                ajax_response = self.session.get(ajax_url, timeout=30)
                if ajax_response.status_code == 200:
                    data = ajax_response.json()
                    if data.get('status') == 200 and 'result' in data:
                        result_soup = BeautifulSoup(data['result'], 'html.parser')
                        for link in result_soup.select('a[href*="/read/"]'):
                            href = link.get("href", "")
                            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                            
                            # Get chapter number from span or text
                            span = link.select_one('span')
                            chapter_text = span.get_text(strip=True) if span else link.get_text(strip=True)
                            
                            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
                            if not match:
                                match = re.search(r'(\d+\.?\d*)', chapter_text)
                            
                            chapter_num = match.group(1) if match else "0"
                            
                            if chapter_url not in [c.url for c in chapters]:
                                chapters.append(Chapter(
                                    number=chapter_num,
                                    title=chapter_text,
                                    url=chapter_url,
                                ))
            except Exception:
                pass
        
        # Fallback: scrape from page directly
        if not chapters:
            for link in soup.select('a[href*="/read/"], .chapter-list a'):
                href = link.get("href", "")
                if not href:
                    continue
                
                chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                chapter_text = link.get_text(strip=True)
                
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
                if not match:
                    match = re.search(r'(\d+\.?\d*)', href)
                
                chapter_num = match.group(1) if match else "0"
                
                if chapter_url not in [c.url for c in chapters]:
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=chapter_text,
                        url=chapter_url,
                    ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter.
        
        ⚠️ WARNING: MangaFire uses DRM protection that prevents direct image extraction.
        This method will likely return an empty list or raise an error.
        """
        raise NotImplementedError(
            "MangaFire uses DRM protection (obfuscated JavaScript + image scrambling). "
            "Page extraction is not supported. "
            "Please use an alternative source like mangapill.com or mangadex.org instead."
        )
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
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
