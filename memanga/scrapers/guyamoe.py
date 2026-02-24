"""
Guya.moe scraper - Kaguya-sama and Oshi no Ko focused scanlation site

Site uses a clean REST API:
- /api/get_all_series/ - list all available manga
- /api/series/{slug} - get manga details + chapters
- Images hosted on guya.cubari.moe CDN
"""

import cloudscraper
from typing import List, Optional
from .base import BaseScraper, Manga, Chapter


class GuyaMoeScraper(BaseScraper):
    """Scraper for guya.moe - Kaguya-sama focused scanlation site"""
    
    name = "guya.moe"
    base_url = "https://guya.moe"
    
    def __init__(self):
        super().__init__()
        self.cdn_base = "https://guya.cubari.moe/media/manga"
        self.session = cloudscraper.create_scraper()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.base_url,
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga - guya.moe has limited series, so we list all and filter"""
        results = []
        query_lower = query.lower()
        
        try:
            r = self.session.get(f"{self.base_url}/api/get_all_series/", timeout=15)
            data = r.json()
            
            for title, info in data.items():
                if query_lower in title.lower() or query_lower in info.get('slug', '').lower():
                    results.append(Manga(
                        title=title,
                        url=f"{self.base_url}/read/manga/{info['slug']}/",
                    ))
        except Exception as e:
            print(f"Search error: {e}")
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga"""
        chapters = []
        
        # Extract slug from URL
        # URL format: https://guya.moe/read/manga/{slug}/
        parts = manga_url.rstrip('/').split('/')
        slug = parts[-1] if parts else None
        
        if not slug:
            return chapters
        
        try:
            r = self.session.get(f"{self.base_url}/api/series/{slug}", timeout=15)
            data = r.json()
            
            chapters_data = data.get('chapters', {})
            slug = data.get('slug', slug)
            
            for ch_num, ch_info in chapters_data.items():
                folder = ch_info.get('folder', '')
                title = ch_info.get('title', '')
                
                # Build chapter URL
                ch_url = f"{self.base_url}/read/manga/{slug}/{ch_num}/1"
                
                # Store extra data for page retrieval
                display_title = f"Chapter {ch_num}"
                if title:
                    display_title = f"Chapter {ch_num}: {title}"
                
                chapters.append(Chapter(
                    number=ch_num,
                    title=display_title,
                    url=ch_url,
                ))
            
            # Sort by chapter number (descending - newest first)
            chapters.sort(key=lambda x: x.numeric, reverse=True)
            
        except Exception as e:
            print(f"Get chapters error: {e}")
        
        return chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page images for a chapter"""
        pages = []
        
        # Extract slug and chapter from URL
        # URL format: https://guya.moe/read/manga/{slug}/{chapter}/1
        parts = chapter_url.rstrip('/').split('/')
        # Find manga index and get slug + chapter
        try:
            manga_idx = parts.index('manga')
            slug = parts[manga_idx + 1]
            chapter_num = parts[manga_idx + 2]
        except (ValueError, IndexError):
            return pages
        
        try:
            r = self.session.get(f"{self.base_url}/api/series/{slug}", timeout=15)
            data = r.json()
            
            chapters_data = data.get('chapters', {})
            ch_info = chapters_data.get(chapter_num, {})
            
            if not ch_info:
                # Try with decimal format
                for ch_num, info in chapters_data.items():
                    if ch_num.startswith(chapter_num):
                        ch_info = info
                        break
            
            if ch_info:
                folder = ch_info.get('folder', '')
                groups = ch_info.get('groups', {})
                
                # Get pages from first available group
                for group_id, page_list in groups.items():
                    for page_name in page_list:
                        # Remove query params from page name if present
                        clean_name = page_name.split('?')[0]
                        # Build full CDN URL
                        page_url = f"{self.cdn_base}/{slug}/chapters/{folder}/{clean_name}"
                        pages.append(page_url)
                    break  # Use first group only
            
        except Exception as e:
            print(f"Get pages error: {e}")
        
        return pages
    
    def download_image(self, url: str, path: str) -> bool:
        """Download an image to the specified path"""
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(path, 'wb') as f:
                    f.write(r.content)
                return True
        except Exception as e:
            print(f"Download error: {e}")
        return False
