"""
MangaDex scraper - Uses official API (no HTML scraping needed)
https://api.mangadex.org/docs/
"""

from typing import List, Optional
from .base import BaseScraper, Chapter, Manga


class MangaDexScraper(BaseScraper):
    """Scraper for MangaDex using official API."""
    
    name = "mangadex"
    base_url = "https://api.mangadex.org"
    
    def __init__(self):
        super().__init__()
        self._rate_limit = 0.5  # MangaDex is generous with rate limits
    
    def _extract_manga_id(self, url: str) -> Optional[str]:
        """Extract manga ID from MangaDex URL."""
        # URL formats:
        # https://mangadex.org/title/abc123
        # https://mangadex.org/title/abc123/manga-name
        import re
        match = re.search(r'/title/([a-f0-9-]+)', url)
        return match.group(1) if match else None
    
    def _extract_chapter_id(self, url: str) -> Optional[str]:
        """Extract chapter ID from MangaDex URL."""
        import re
        match = re.search(r'/chapter/([a-f0-9-]+)', url)
        return match.group(1) if match else None
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/manga"
        params = {
            "title": query,
            "limit": 10,
            "includes[]": ["cover_art"],
            "order[relevance]": "desc",
        }
        
        data = self._get_json(url, params=params)
        results = []
        
        for item in data.get("data", []):
            manga_id = item["id"]
            attrs = item["attributes"]
            
            # Get title (prefer English)
            titles = attrs.get("title", {})
            title = titles.get("en") or titles.get("ja-ro") or list(titles.values())[0]
            
            # Get cover
            cover_url = None
            for rel in item.get("relationships", []):
                if rel["type"] == "cover_art":
                    cover_filename = rel.get("attributes", {}).get("fileName")
                    if cover_filename:
                        cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}.256.jpg"
            
            results.append(Manga(
                title=title,
                url=f"https://mangadex.org/title/{manga_id}",
                cover_url=cover_url,
                description=attrs.get("description", {}).get("en", ""),
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all English chapters for a manga."""
        manga_id = self._extract_manga_id(manga_url)
        if not manga_id:
            raise ValueError(f"Could not extract manga ID from: {manga_url}")
        
        chapters = []
        offset = 0
        limit = 100
        
        while True:
            url = f"{self.base_url}/manga/{manga_id}/feed"
            params = {
                "translatedLanguage[]": ["en"],
                "order[chapter]": "asc",
                "limit": limit,
                "offset": offset,
                "includes[]": ["scanlation_group"],
            }
            
            data = self._get_json(url, params=params)
            items = data.get("data", [])
            
            if not items:
                break
            
            for item in items:
                attrs = item["attributes"]
                chapter_num = attrs.get("chapter") or "0"
                
                # Skip external chapters (no pages hosted on MangaDex)
                if attrs.get("externalUrl") or attrs.get("pages", 0) == 0:
                    continue
                
                chapters.append(Chapter(
                    number=chapter_num,
                    title=attrs.get("title"),
                    url=f"https://mangadex.org/chapter/{item['id']}",
                    date=attrs.get("publishAt"),
                ))
            
            offset += limit
            if len(items) < limit:
                break
        
        # Sort and deduplicate (keep first occurrence of each chapter)
        seen = set()
        unique_chapters = []
        for ch in sorted(chapters):
            if ch.number not in seen:
                seen.add(ch.number)
                unique_chapters.append(ch)
        
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        chapter_id = self._extract_chapter_id(chapter_url)
        if not chapter_id:
            raise ValueError(f"Could not extract chapter ID from: {chapter_url}")
        
        url = f"{self.base_url}/at-home/server/{chapter_id}"
        data = self._get_json(url)
        
        base = data["baseUrl"]
        chapter_hash = data["chapter"]["hash"]
        pages = data["chapter"]["data"]  # High quality
        # data["chapter"]["dataSaver"]  # Lower quality option
        
        return [f"{base}/data/{chapter_hash}/{page}" for page in pages]
