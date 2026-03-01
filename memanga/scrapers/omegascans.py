"""
Omega Scans scraper - requires Playwright for JS rendering.
Site: https://omegascans.org
"""

import re
from typing import List
from .playwright_base import PlaywrightScraper
from .base import Manga, Chapter
from bs4 import BeautifulSoup


class OmegaScansScraper(PlaywrightScraper):
    name = "OmegaScans"
    domains = ["omegascans.org"]
    base_url = "https://omegascans.org"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        # OmegaScans doesn't have a search API, scrape the homepage
        # and filter by query
        url = self.base_url
        html = self._get_page_content(url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        query_lower = query.lower()
        seen = set()

        # Find series links with their titles
        for link in soup.select('a[href*="/series/"]'):
            href = link.get("href", "")
            if "/series/" in href and "/chapter" not in href:
                # Extract slug from href
                match = re.search(r"/series/([^/]+)", href)
                if not match:
                    continue

                slug = match.group(1)
                if slug in seen:
                    continue

                # Get title - either from link text or convert slug
                text = link.get_text(strip=True)
                if text:
                    # Title might be concatenated with description, try to split
                    # Usually title is followed by description without space
                    title = text.split('\n')[0][:100]
                else:
                    # Convert slug to title: "solo-leveling" -> "Solo Leveling"
                    title = slug.replace("-", " ").title()

                # Check if query matches title or slug
                if query_lower in title.lower() or query_lower in slug.lower():
                    seen.add(slug)
                    results.append(Manga(
                        title=title,
                        url=f"{self.base_url}/series/{slug}",
                    ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")

        # Extract slug from manga_url for filtering chapter links
        slug_match = re.search(r"/series/([^/]+)", manga_url)
        slug = slug_match.group(1) if slug_match else ""

        chapters = []
        seen = set()

        # Find chapter links - pattern: /series/{slug}/chapter-{num}
        selector = f'a[href*="/series/{slug}/chapter"]' if slug else 'a[href*="/chapter"]'
        for link in soup.select(selector):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # Extract chapter number from URL
            match = re.search(r"/chapter-?([\d.]+)", href)
            if not match:
                continue

            chapter_num = match.group(1)
            if chapter_num in seen:
                continue
            seen.add(chapter_num)

            # Build chapter URL
            if href.startswith("http"):
                chapter_url = href
            elif href.startswith("/"):
                chapter_url = f"{self.base_url}{href}"
            else:
                chapter_url = f"{self.base_url}/{href}"

            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=chapter_url,
            ))

        # Sort by chapter number (descending - newest first)
        def parse_chapter(ch):
            try:
                return float(ch.number)
            except (ValueError, TypeError):
                return 0

        chapters.sort(key=parse_chapter, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")

        images = []

        # Find images from media.omegascans.org
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "media.omegascans.org" in src and "/uploads/" in src:
                if src not in images:
                    images.append(src)

        return images
