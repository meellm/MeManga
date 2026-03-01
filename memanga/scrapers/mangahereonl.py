"""
MangaHere.onl scraper - requires Playwright.
Site: https://mangahere.onl
Images from: imgx.mghcdn.com
"""

import re
from typing import List
from .playwright_base import PlaywrightScraper
from .base import Manga, Chapter
from bs4 import BeautifulSoup


class MangaHereOnlScraper(PlaywrightScraper):
    name = "MangaHereOnl"
    domains = ["mangahere.onl"]
    base_url = "https://mangahere.onl"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/?s={query.replace(' ', '+')}"
        html = self._get_page_content(url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        seen = set()

        for link in soup.select('a[href*="/manga/"]'):
            href = link.get("href", "")
            # Skip if not from this domain
            if "mangahere.onl" not in href and not href.startswith("/"):
                continue

            match = re.search(r"/manga/([^/]+)", href)
            if not match:
                continue

            slug = match.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            title = link.get_text(strip=True) or slug.replace("-", " ").title()

            results.append(Manga(
                title=title[:100],
                url=f"{self.base_url}/manga/{slug}",
            ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()

        for link in soup.select('a[href*="/chapter/"]'):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            match = re.search(r"/chapter/[^/]+/chapter-?([\d.]+)", href)
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

        # Images from imgx.mghcdn.com
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "mghcdn.com" in src:
                if src not in images:
                    images.append(src)

        return images
