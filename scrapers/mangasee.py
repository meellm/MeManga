"""
MangaSee123 scraper
https://mangasee123.com

High quality manga scans.
"""

import re
import json
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaSeeScraper(BaseScraper):
    """Scraper for MangaSee123.com"""
    
    name = "mangasee"
    base_url = "https://mangasee123.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        # MangaSee uses a JavaScript-based search, try the directory
        url = f"{self.base_url}/search/?name={query.replace(' ', '+')}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        for item in soup.select(".SeriesName, .top-15 a, a[href*='/manga/']"):
            href = item.get("href", "")
            if not href or "/manga/" not in href:
                continue
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            title = item.get_text(strip=True)
            
            if not title:
                title = href.split("/")[-1].replace("-", " ").title()
            
            if title:
                results.append(Manga(title=title, url=manga_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # Try to find chapter data in JavaScript
        for script in soup.find_all("script"):
            text = script.string or ""
            if "vm.Chapters" in text:
                match = re.search(r'vm\.Chapters\s*=\s*(\[.*?\]);', text, re.DOTALL)
                if match:
                    try:
                        chapter_data = json.loads(match.group(1))
                        manga_slug = manga_url.rstrip("/").split("/")[-1]
                        
                        for ch in chapter_data:
                            ch_num = ch.get("Chapter", "0")
                            # Decode MangaSee chapter number format
                            if len(ch_num) > 1:
                                # Format: SCCCCD where S=series type, CCCC=chapter, D=decimal
                                ch_num = str(int(ch_num[1:-1])) + ("." + ch_num[-1] if ch_num[-1] != "0" else "")
                            
                            chapter_url = f"{self.base_url}/read-online/{manga_slug}-chapter-{ch_num}.html"
                            
                            chapters.append(Chapter(
                                number=ch_num,
                                url=chapter_url,
                            ))
                    except:
                        pass
        
        # Fallback: scrape links directly
        if not chapters:
            for link in soup.select("a[href*='-chapter-']"):
                href = link.get("href", "")
                chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                match = re.search(r'chapter-(\d+\.?\d*)', href, re.I)
                chapter_num = match.group(1) if match else "0"
                
                chapters.append(Chapter(number=chapter_num, url=chapter_url))
        
        return sorted(set(chapters), key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # MangaSee stores page info in JavaScript
        for script in soup.find_all("script"):
            text = script.string or ""
            if "vm.CurChapter" in text:
                # Extract chapter info
                chapter_match = re.search(r'vm\.CurChapter\s*=\s*({.*?});', text, re.DOTALL)
                path_match = re.search(r'vm\.CurPathName\s*=\s*"([^"]+)"', text)
                
                if chapter_match and path_match:
                    try:
                        chapter_info = json.loads(chapter_match.group(1))
                        path_name = path_match.group(1)
                        
                        page_count = int(chapter_info.get("Page", 0))
                        chapter_num = chapter_info.get("Chapter", "0")
                        
                        # Decode chapter number
                        if len(chapter_num) > 1:
                            ch_formatted = str(int(chapter_num[1:-1])).zfill(4)
                            if chapter_num[-1] != "0":
                                ch_formatted += "." + chapter_num[-1]
                        else:
                            ch_formatted = chapter_num.zfill(4)
                        
                        for i in range(1, page_count + 1):
                            page_num = str(i).zfill(3)
                            img_url = f"https://{path_name}/manga/{chapter_url.split('/')[-1].split('-chapter-')[0]}/{ch_formatted}-{page_num}.png"
                            pages.append(img_url)
                    except:
                        pass
        
        # Fallback: look for images directly
        if not pages:
            for img in soup.select("img.img-fluid, .reading-content img"):
                src = img.get("data-src") or img.get("src")
                if src and (".png" in src or ".jpg" in src):
                    pages.append(src)
        
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
