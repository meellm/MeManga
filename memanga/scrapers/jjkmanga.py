"""
JJKManga scraper - jjkmanga.net

Jujutsu Kaisen dedicated manga reader site.
WordPress + pic.readkakegurui.com CDN.
"""

import cloudscraper
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga


class JJKMangaScraper(BaseScraper):
    """Scraper for jjkmanga.net"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://jjkmanga.net"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "Referer": f"{self.base_url}/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga - this is a single-manga site"""
        query_lower = query.lower()
        if any(x in query_lower for x in ['jujutsu', 'kaisen', 'jjk', 'gojo', 'itadori', 'sukuna']):
            return [Manga(
                title="Jujutsu Kaisen",
                url=f"{self.base_url}/",
                cover_url=""
            )]
        return []
    
    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get all chapters for the manga"""
        resp = self.session.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        chapters = []
        seen_urls = set()
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'chapter' in href.lower() and href not in seen_urls:
                seen_urls.add(href)
                
                # Extract chapter number
                text = link.get_text(strip=True)
                import re
                match = re.search(r'chapter[- _]?(\d+(?:\.\d+)?)', href.lower())
                if match:
                    chapter_num = match.group(1)
                else:
                    chapter_num = text
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=f"Chapter {chapter_num}",
                    url=href if href.startswith('http') else f"{self.base_url}{href}"
                ))
        
        # Sort by chapter number (numeric)
        def sort_key(ch):
            try:
                return float(ch.chapter_num)
            except:
                return 0
        
        chapters.sort(key=sort_key)
        return chapters
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all page image URLs for a chapter"""
        resp = self.session.get(chapter_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        pages = []
        
        # Find reading-content div if exists
        reading_div = soup.find('div', class_='reading-content')
        container = reading_div if reading_div else soup
        
        for img in container.find_all('img'):
            # Try multiple src attributes
            src = None
            for attr in ['src', 'data-src', 'data-lazy-src']:
                val = img.get(attr)
                if val and 'pic.readkakegurui.com' in val:
                    src = val.strip()
                    break
            
            if src and src not in pages:
                pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path: str) -> bool:
        """Download an image with proper headers"""
        try:
            headers = {
                "Referer": f"{self.base_url}/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
            }
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            if len(resp.content) < 1000:
                return False
            
            with open(path, 'wb') as f:
                f.write(resp.content)
            return True
        except Exception as e:
            print(f"Download error: {e}")
            return False
