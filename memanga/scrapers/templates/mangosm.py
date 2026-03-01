"""
Template for WordPress Mangosm theme sites.

Single-manga sites using mangafreak.me, mangarchive.com, planeptune.us,
cdn.mangaclash.com, or saidvps.xyz CDNs.

Subclass config attributes:
    base_url: str         - Site URL
    manga_title: str      - Display title
    manga_slug: str       - URL slug (e.g., "hunter-x-hunter")
    cdn_domains: list     - CDN hostname substrings to accept
    cdn_referer: str      - Referer override for CDN requests (if different from base_url)
    chapter_link_pattern: str - Regex for chapter URLs
"""

import re
from typing import List
from pathlib import Path
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class MangosmScraper(BaseScraper):
    """Template for WordPress Mangosm theme single-manga sites."""

    base_url: str = ""
    manga_title: str = ""
    manga_slug: str = ""
    cdn_domains: list = []
    cdn_referer: str = ""
    chapter_link_pattern: str = ""

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })
        if not self.chapter_link_pattern and self.manga_slug:
            self.chapter_link_pattern = rf'{self.manga_slug}-chapter'

    def search(self, query: str) -> List[Manga]:
        """Single manga site — return the manga."""
        return [Manga(
            title=self.manga_title,
            url=self.base_url + "/",
        )]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters from dropdown or links."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()

        # Method 1: Mangosm dropdown
        dropdown = soup.select_one("select.mangosm-manga-nav-select")
        if dropdown:
            for option in dropdown.find_all("option"):
                href = option.get("value", "")
                text = option.get_text(strip=True)
                if not href or href == "#":
                    continue
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")
                if href in seen:
                    continue
                seen.add(href)

                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
                number = match.group(1) if match else "0"
                chapters.append(Chapter(number=number, title=text, url=href))

        # Method 2: Link extraction
        if not chapters:
            pattern = self.chapter_link_pattern or r'chapter'
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if href in seen:
                    continue
                if not re.search(pattern, href, re.IGNORECASE):
                    continue
                seen.add(href)

                text = link.get_text(strip=True)
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")

                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
                number = match.group(1) if match else "0"
                chapters.append(Chapter(number=number, title=text, url=href))

        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images from entry-content or images-container."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()

        # Search in content containers
        container = (
            soup.select_one(".images-container")
            or soup.select_one(".entry-content")
            or soup
        )

        for img in container.find_all("img"):
            url = (img.get("data-src") or img.get("data-lazy-src")
                   or img.get("src") or "")

            if not url or url.startswith("data:"):
                continue

            # Filter by CDN domains
            url_lower = url.lower()
            is_cdn = any(d in url_lower for d in self.cdn_domains)

            # Fallback: accept wp-content/uploads (skip logos/icons/favicons)
            if not is_cdn and "wp-content/uploads" in url_lower:
                if any(skip in url_lower for skip in ["logo", "icon", "favicon"]):
                    continue
                is_cdn = True

            if not is_cdn:
                continue

            if url not in seen:
                seen.add(url)
                pages.append(url)

        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Download image with proper Referer."""
        try:
            referer = self.cdn_referer or self.base_url
            headers = {
                "Referer": referer,
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
