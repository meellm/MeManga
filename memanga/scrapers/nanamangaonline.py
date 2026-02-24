"""
Nana Manga Online Scraper (nanamanga.online)

Site: nanamanga.online
Type: Nana by Ai Yazawa dedicated
Theme: WordPress Comic Easel
CDN: Blogger CDN (blogger.googleusercontent.com)
Chapters: 84 (series on indefinite hiatus)
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import BaseScraper, Chapter, Manga


class NanaMangaOnlineScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.base_url = "https://w2.nanamanga.online"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://nanamanga.online/"
        })

    def search(self, query: str) -> list[Manga]:
        """Search for manga - single series site."""
        if "nana" in query.lower():
            return [Manga(
                title="Nana",
                url=self.base_url + "/",
                cover="https://nanamanga.online/wp-content/uploads/2025/04/nana-manga-677x1024.webp"
            )]
        return []

    def get_chapters(self, manga_url: str) -> list[Chapter]:
        """Get all chapters from homepage."""
        response = self.session.get(self.base_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        chapters = []
        # Find chapter links in the widget
        chapter_links = soup.select('ul li a[href*="/manga/nana-chapter"]')
        
        seen_urls = set()
        for link in chapter_links:
            url = link.get("href", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            
            title = link.get_text(strip=True)
            if not title:
                continue
                
            # Extract chapter number (handles decimals like 78.1, 78.2)
            match = re.search(r"chapter[- ]?(\d+(?:\.\d+)?)", title.lower())
            if match:
                chapter_num = float(match.group(1))
            else:
                match = re.search(r"(\d+(?:\.\d+)?)", title)
                chapter_num = float(match.group(1)) if match else 0
            
            chapters.append(Chapter(
                number=str(chapter_num),
                title=title,
                url=url
            ))
        
        # Sort by chapter number descending
        chapters.sort(key=lambda c: float(c.number), reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all page image URLs from a chapter via og:image meta tags."""
        response = self.session.get(chapter_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        pages = []
        
        # Images are in og:image meta tags (Blogger CDN URLs)
        for meta in soup.select('meta[property="og:image"]'):
            content = meta.get("content", "")
            if content and "blogger.googleusercontent.com" in content:
                pages.append(content)
        
        # Fallback: look for images in the content
        if not pages:
            for img in soup.select("img"):
                src = img.get("src", "") or img.get("data-src", "")
                if src and "blogger.googleusercontent.com" in src:
                    pages.append(src)
        
        return pages

    def download_image(self, url: str, headers: dict = None) -> bytes:
        """Download an image with proper headers."""
        img_headers = {
            "User-Agent": self.session.headers["User-Agent"],
            "Referer": "https://nanamanga.online/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }
        if headers:
            img_headers.update(headers)
        
        response = self.session.get(url, headers=img_headers)
        response.raise_for_status()
        return response.content
