"""
KimetsuYaibaOnline scraper (kimetsu-yaiba.online) - Demon Slayer dedicated site.
WordPress Comic Easel theme + wp-content CDN (images in og:image meta tags).
"""

import re
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

from .base import BaseScraper, Manga, Chapter


class KimetsuYaibaOnlineScraper(BaseScraper):
    """Scraper for kimetsu-yaiba.online - Demon Slayer / Kimetsu no Yaiba manga."""
    
    name = "kimetsuyaibaonline"
    base_url = "https://kimetsu-yaiba.online"
    
    def __init__(self):
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.base_url
        })
    
    def search(self, query: str) -> list[Manga]:
        """Search for manga - this is a single-manga site."""
        query_lower = query.lower()
        
        keywords = ['demon slayer', 'kimetsu', 'yaiba', 'tanjiro', 'nezuko']
        if any(kw in query_lower for kw in keywords):
            return [Manga(
                id="kimetsu-no-yaiba",
                title="Demon Slayer: Kimetsu no Yaiba",
                url=f"{self.base_url}/",
                cover=f"{self.base_url}/wp-content/uploads/2025/08/Demon-Slayer_-Kimetsu-no-Yaiba.webp"
            )]
        
        return []
    
    def get_chapters(self, manga_id: str) -> list[Chapter]:
        """Get list of chapters for a manga."""
        url = f"{self.base_url}/"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        chapters = []
        seen_urls = set()
        
        # Find chapter links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/comic/kimetsu-no-yaiba-chapter-' in href and href not in seen_urls:
                seen_urls.add(href)
                
                # Extract chapter number from URL
                match = re.search(r'chapter-(\d+(?:\.\d+)?)', href)
                if match:
                    chapter_num = match.group(1)
                    title = link.get_text(strip=True) or f"Chapter {chapter_num}"
                    
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=title,
                        url=href
                    ))
        
        # Sort by chapter number
        chapters.sort(key=lambda c: c.number)
        return chapters
    
    def get_pages(self, manga_id: str, chapter_number: str) -> list[str]:
        """Get list of page image URLs for a chapter."""
        url = f"{self.base_url}/comic/kimetsu-no-yaiba-chapter-{chapter_number}/"
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        pages = []
        seen_urls = set()
        
        # Find images in og:image meta tags (Comic Easel pattern)
        for meta in soup.find_all('meta', property='og:image'):
            content = meta.get('content', '')
            if content and content not in seen_urls:
                # Skip cover/logo images
                if 'Demon-Slayer_-Kimetsu-no-Yaiba.webp' in content:
                    continue
                if '/wp-content/uploads/' in content:
                    seen_urls.add(content)
                    pages.append(content)
        
        return pages
    
    def download_image(self, url: str, chapter_url: str = None) -> bytes:
        """Download an image with proper headers."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': self.base_url
        }
        
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.content
