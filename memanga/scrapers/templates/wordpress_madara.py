"""
Template for WordPress Madara theme manga sites.

Covers both multi-manga aggregators and single-manga dedicated sites.
Some use AJAX POST for chapter loading, others parse HTML directly.

Subclass config attributes:
    base_url: str             - Site URL
    manga_title: str          - Display title (for single-manga sites)
    manga_slug: str           - URL slug for the manga
    is_single_manga: bool     - True for dedicated single-manga sites
    image_cdn_filters: list   - CDN substrings to accept (e.g., ["img.spoilerhat.com"])
    uses_cloudscraper: bool   - Use cloudscraper for Cloudflare bypass
    uses_ajax: bool           - Use AJAX POST for chapter loading
"""

import re
from typing import List
from pathlib import Path
from urllib.parse import quote
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class WordPressMadaraScraper(BaseScraper):
    """Template for WordPress Madara theme sites."""

    base_url: str = ""
    manga_title: str = ""
    manga_slug: str = ""
    is_single_manga: bool = False
    image_cdn_filters: list = []
    uses_cloudscraper: bool = False
    uses_ajax: bool = False

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
        """Search for manga."""
        if self.is_single_manga:
            return [Manga(
                title=self.manga_title,
                url=f"{self.base_url}/manga/{self.manga_slug}/",
            )]

        search_url = f"{self.base_url}/?s={quote(query)}&post_type=wp-manga"
        html = self._get_html(search_url)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        for item in soup.select(".post-title a, h3 a, h4 a"):
            href = item.get("href", "")
            title = item.get_text(strip=True)
            if href and title and "/manga/" in href:
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")
                if not any(m.url == href for m in results):
                    results.append(Manga(title=title, url=href))

        return results[:10]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters via AJAX or HTML parsing."""
        chapters = []

        if self.uses_ajax:
            chapters = self._get_chapters_ajax(manga_url)

        if not chapters:
            chapters = self._get_chapters_html(manga_url)

        return chapters

    def _get_chapters_ajax(self, manga_url: str) -> List[Chapter]:
        """Get chapters via Madara AJAX POST."""
        try:
            ajax_url = manga_url.rstrip("/") + "/ajax/chapters/"
            # Use rate-limited _request pattern but with POST
            import time
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            resp = self.session.post(
                ajax_url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=30,
            )
            if resp.status_code != 200:
                return []
            return self._parse_chapter_links(resp.text)
        except Exception:
            return []

    def _get_chapters_html(self, manga_url: str) -> List[Chapter]:
        """Get chapters by parsing HTML directly."""
        try:
            html = self._get_html(manga_url)
            return self._parse_chapter_links(html)
        except Exception:
            return []

    def _parse_chapter_links(self, html: str) -> List[Chapter]:
        """Parse chapter links from HTML content."""
        soup = BeautifulSoup(html, "html.parser")
        chapters = []
        seen = set()

        selectors = [
            ".wp-manga-chapter a",
            "li.wp-manga-chapter a",
            "a[href*='chapter']",
        ]
        if self.manga_slug:
            selectors.append(f"a[href*='{self.manga_slug}']")

        for selector in selectors:
            for link in soup.select(selector):
                href = link.get("href", "")
                if href in seen or not href:
                    continue
                seen.add(href)

                text = link.get_text(strip=True)
                if not href.startswith("http"):
                    href = self.base_url.rstrip("/") + "/" + href.lstrip("/")

                match = re.search(r'chapter[_\s-]*(\d+(?:\.\d+)?)', href.lower())
                if not match:
                    match = re.search(r'chapter[_\s-]*(\d+(?:\.\d+)?)', text.lower())
                number = match.group(1) if match else "0"

                chapters.append(Chapter(number=number, title=text, url=href))

        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images from reading-content area."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()

        # Search in Madara reading containers
        container = soup.select_one(".reading-content") or soup

        for img in container.find_all("img"):
            url = (img.get("data-src") or img.get("data-lazy-src")
                   or img.get("src") or "")
            url = url.strip()

            if not url or url.startswith("data:"):
                continue

            # Fix protocol-relative URLs
            if url.startswith("//"):
                url = "https:" + url

            # Filter by CDN if configured, otherwise accept image-like URLs
            if self.image_cdn_filters:
                url_lower = url.lower()
                is_valid = any(f in url_lower for f in self.image_cdn_filters)
                if not is_valid:
                    continue
            else:
                # Accept any image URL that looks like manga content
                url_lower = url.lower()
                if any(skip in url_lower for skip in ["logo", "icon", "avatar", "favicon"]):
                    continue
                if not any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
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
