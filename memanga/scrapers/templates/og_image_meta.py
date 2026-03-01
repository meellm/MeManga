"""
Template for WordPress Comic Easel sites using og:image meta tags.

Covers Blogger CDN, img.spoilerhat.com, cdn.mangaclash.com, and other CDN patterns.
Most are single-manga dedicated sites.

Subclass config attributes:
    base_url: str              - Site URL
    manga_title: str           - Display title
    chapter_link_pattern: str  - Regex for chapter URLs (e.g., r'chapter-\\d+')
    image_cdn_filters: list    - CDN hostname substrings to accept (e.g., ["blogger.googleusercontent.com"])
    cover_url: str             - Optional cover image URL
    uses_cloudscraper: bool    - Use cloudscraper for Cloudflare bypass
    normalize_blogger: bool    - Normalize Blogger URLs to /s1600/ resolution
"""

import re
from typing import List
from pathlib import Path
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class OGImageMetaScraper(BaseScraper):
    """Template for sites using og:image/twitter:image meta tags for page images."""

    base_url: str = ""
    manga_title: str = ""
    chapter_link_pattern: str = r'chapter-?\d+'
    image_cdn_filters: list = []
    cover_url: str = ""
    uses_cloudscraper: bool = False
    normalize_blogger: bool = True

    def __init__(self):
        super().__init__()
        if self.uses_cloudscraper:
            try:
                import cloudscraper
                self.session = cloudscraper.create_scraper(
                    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
                )
            except ImportError:
                pass
        self.session.headers.update({
            "Referer": self.base_url,
        })

    def search(self, query: str) -> List[Manga]:
        """Single manga site — return the manga if query matches."""
        return [Manga(
            title=self.manga_title,
            url=self.base_url + "/",
            cover_url=self.cover_url or None,
        )]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters from homepage links."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href in seen:
                continue
            if not re.search(self.chapter_link_pattern, href, re.IGNORECASE):
                continue
            seen.add(href)

            text = link.get_text(strip=True)
            if not text:
                continue

            # Make absolute
            if not href.startswith("http"):
                href = self.base_url.rstrip("/") + "/" + href.lstrip("/")

            # Extract chapter number
            match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
            number = match.group(1) if match else "0"

            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))

        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images from og:image meta tags and img tags."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()

        # 1. Extract from og:image and twitter:image meta tags
        for prop in ("og:image", "twitter:image"):
            for meta in soup.select(f'meta[property="{prop}"], meta[name="{prop}"]'):
                url = meta.get("content", "")
                if url and self._is_cdn_image(url) and url not in seen:
                    seen.add(url)
                    pages.append(self._normalize_url(url))

        # 2. Fallback: scan img tags in content area
        if not pages:
            for img in soup.find_all("img"):
                url = (img.get("data-lazy-src") or img.get("data-src")
                       or img.get("src") or "")
                if url and self._is_cdn_image(url) and url not in seen:
                    seen.add(url)
                    pages.append(self._normalize_url(url))

        return pages

    def _is_cdn_image(self, url: str) -> bool:
        """Check if URL matches any configured CDN filter."""
        if not url or url.startswith("data:"):
            return False
        url_lower = url.lower()
        for f in self.image_cdn_filters:
            if f.lower() in url_lower:
                return True
        return False

    def _normalize_url(self, url: str) -> str:
        """Normalize image URLs (e.g., Blogger resolution)."""
        if self.normalize_blogger and ("blogger.googleusercontent.com" in url or "bp.blogspot.com" in url):
            # Upgrade to max resolution
            url = re.sub(r'/s\d+/', '/s1600/', url)
            url = re.sub(r'/w\d+-h\d+/', '/s1600/', url)
        return url

    def download_image(self, url: str, path: Path) -> bool:
        """Download image with Referer header."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            if len(response.content) < 1000:
                return False

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
