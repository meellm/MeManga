"""
Manytoon scraper - WordPress Madara theme, requires Playwright.
Site: https://manytoon.com (NSFW - hentai manhwa)
"""

import re
from typing import List
from .playwright_base import PlaywrightScraper
from .base import Manga, Chapter
from bs4 import BeautifulSoup


class ManyToonScraper(PlaywrightScraper):
    name = "Manytoon"
    domains = ["manytoon.com"]
    base_url = "https://manytoon.com"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/?s={query.replace(' ', '+')}"
        html = self._get_page_content(url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        seen = set()

        for link in soup.select('a[href*="/comic/"]'):
            href = link.get("href", "")
            if "/comic/" not in href or "/chapter" in href:
                continue

            # Extract slug from URL
            match = re.search(r"/comic/([^/]+)/?", href)
            if not match:
                continue

            slug = match.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            title = link.get_text(strip=True) or slug.replace("-", " ").title()

            results.append(Manga(
                title=title[:100],
                url=f"{self.base_url}/comic/{slug}/",
            ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")

        # Extract slug from manga_url for filtering chapter links
        slug_match = re.search(r"/comic/([^/]+)", manga_url)
        slug = slug_match.group(1) if slug_match else ""

        chapters = []
        seen = set()

        selector = f'a[href*="/comic/{slug}/chapter"]' if slug else 'a[href*="/chapter"]'
        for link in soup.select(selector):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # Extract chapter number
            match = re.search(r"/chapter-?([\d.]+)", href)
            if not match:
                continue

            chapter_num = match.group(1)
            if chapter_num in seen:
                continue
            seen.add(chapter_num)

            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"

            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=chapter_url,
            ))

        # Sort by chapter number (descending)
        def parse_num(ch):
            try:
                return float(ch.number)
            except (ValueError, TypeError):
                return 0

        chapters.sort(key=parse_num, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")

        images = []

        # WordPress Madara stores images in /wp-content/uploads/WP-manga/
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            # Filter for manga page images
            if "WP-manga" in src or "manga" in src.lower():
                # Skip logos and icons
                if "logo" in src.lower() or "icon" in src.lower():
                    continue
                if src not in images:
                    images.append(src)

        return images
