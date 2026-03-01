"""
Template for WordPress Zazm/Toivo sites using laiond.com or loinew.com CDN.

Single-manga sites with chapter links in /comic/ or /manga/ paths.

Subclass config attributes:
    base_url: str             - Site URL
    manga_title: str          - Display title
    chapter_link_pattern: str - Regex for chapter href matching
    cdn_domains: list         - CDN domain substrings for image filtering (default: ["laiond.com"])
    uses_cloudscraper: bool   - Use cloudscraper for Cloudflare bypass
    url_path_prefix: str      - URL path prefix ("comic" or "manga")
"""

import re
from typing import List
from pathlib import Path
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class LaiondCDNScraper(BaseScraper):
    """Template for WordPress sites using laiond.com/loinew.com CDN."""

    base_url: str = ""
    manga_title: str = ""
    chapter_link_pattern: str = r'chapter-?\d+'
    cdn_domains: list = ["laiond.com"]
    uses_cloudscraper: bool = False
    url_path_prefix: str = "comic"

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
        """Single manga site — return the manga."""
        return [Manga(
            title=self.manga_title,
            url=self.base_url + "/",
        )]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters from homepage links or dropdown."""
        html = self._get_html(self.base_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()

        # Method 1: Try dropdown selector (Detective Conan pattern)
        dropdown = soup.select_one("select.mangosm-manga-nav-select")
        if dropdown:
            for option in dropdown.find_all("option"):
                href = option.get("value", "")
                text = option.get_text(strip=True)
                if not href or href == "#" or "chapter" not in href.lower():
                    continue
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")
                if href in seen:
                    continue
                seen.add(href)

                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
                number = match.group(1) if match else "0"

                chapters.append(Chapter(number=number, title=text, url=href))
        else:
            # Method 2: Standard link extraction
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
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")

                match = re.search(r'chapter[- ]?(\d+(?:\.\d+)?)', href.lower())
                number = match.group(1) if match else "0"

                chapters.append(Chapter(number=number, title=text, url=href))

        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images by finding CDN-hosted img tags."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()

        for img in soup.find_all("img"):
            # Check multiple src attributes for lazy loading
            url = (img.get("data-lazy-src") or img.get("data-src")
                   or img.get("data-original") or img.get("lazyload")
                   or img.get("src") or "")

            if not url or url.startswith("data:"):
                continue

            # Filter by CDN domain
            url_lower = url.lower()
            is_cdn = any(d in url_lower for d in self.cdn_domains)
            if not is_cdn:
                continue

            # Skip thumbnails
            if any(x in url_lower for x in ["/32x32", "/192x192", "/180x180", "/270x270"]):
                continue

            if url not in seen:
                seen.add(url)
                pages.append(url)

        return pages

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
