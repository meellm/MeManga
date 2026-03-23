"""
Kagane.org scraper - Custom REST API manga platform.
https://kagane.org

API Architecture:
    API server: https://yuzuki.kagane.org/api/v2
    Image/cache server: https://akari.kagane.org
    Web frontend: https://kagane.org

Search and chapter metadata use the REST API directly (with cloudscraper
for Cloudflare bypass). Chapter images require a DRM challenge, so we use
Playwright (Chromium) to load the reader page and intercept authenticated
image URLs from network requests.

Based on keiyoushi/extensions-source Tachiyomi extension
and Yui007/kagane-downloader.
"""

import re
import time
import logging
import requests
from typing import List, Optional
from pathlib import Path

from .base import BaseScraper, Chapter, Manga, _retry
from .playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)


class KaganeScraper(PlaywrightScraper):
    """Scraper for kagane.org using REST API + Playwright for images."""

    name = "kagane"
    base_url = "https://kagane.org"

    API_BASE = "https://yuzuki.kagane.org"
    IMAGE_BASE = "https://akari.kagane.org"

    def __init__(self):
        super().__init__()
        self._rate_limit = 1.0

        # Use cloudscraper for API calls (Cloudflare-protected)
        try:
            import cloudscraper
            self.session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "desktop": True}
            )
        except ImportError:
            pass

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://kagane.org",
            "Referer": "https://kagane.org/",
            "Accept": "application/json",
        })

    # ── Helpers ──

    def _post_json(self, url: str, json_body: dict = None,
                   extra_headers: dict = None, **kwargs) -> dict:
        """Rate-limited POST returning JSON, with retry."""
        def _do_post():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            headers = dict(extra_headers) if extra_headers else {}
            resp = self.session.post(
                url, json=json_body, headers=headers, timeout=30, **kwargs
            )
            resp.raise_for_status()
            return resp.json()

        return _retry(
            _do_post,
            max_attempts=3,
            base_delay=1.0,
            exceptions=(requests.RequestException,),
        )

    @staticmethod
    def _extract_series_id(url: str) -> Optional[str]:
        """Extract series ID/slug from kagane.org URL."""
        match = re.search(r'/series/([^/?#]+)', url)
        return match.group(1) if match else None

    @staticmethod
    def _extract_chapter_id(url: str) -> Optional[str]:
        """Extract chapter ID from kagane.org URL."""
        match = re.search(r'/read/([^/?#]+)', url)
        return match.group(1) if match else None

    # ── Public API ──

    def search(self, query: str) -> List[Manga]:
        """Search for manga on kagane.org."""
        url = f"{self.API_BASE}/api/v2/search/series"
        data = self._post_json(
            url,
            json_body={"title": query},
            params={"page": 1, "size": 35, "sort": "relevance"},
        )

        results = []
        for item in data.get("content", []):
            series_id = item.get("series_id", "")
            title = item.get("title", "")
            if not title or not series_id:
                continue

            cover_url = None
            cover_id = item.get("cover_image_id")
            if cover_id:
                cover_url = f"{self.API_BASE}/api/v2/image/{cover_id}"

            results.append(Manga(
                title=title,
                url=f"{self.base_url}/series/{series_id}",
                cover_url=cover_url,
            ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        series_id = self._extract_series_id(manga_url)
        if not series_id:
            raise ValueError(f"Could not extract series ID from: {manga_url}")

        url = f"{self.API_BASE}/api/v2/series/{series_id}"
        data = self._get_json(url)

        chapters = []
        books = data.get("series_books", [])

        for book in books:
            book_id = book.get("book_id", "")
            if not book_id:
                continue

            chapter_no = book.get("chapter_no") or "0"
            title = book.get("title", "")
            date = book.get("created_at")

            chapter_url = f"{self.base_url}/read/{book_id}"
            chapters.append(Chapter(
                number=str(chapter_no),
                title=title or None,
                url=chapter_url,
                date=date,
            ))

        return sorted(chapters)

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs by loading the reader in Playwright.

        The kagane.org reader requires a DRM challenge to obtain image
        tokens. Instead of generating the challenge programmatically,
        we load the chapter in Chromium (which handles DRM natively)
        and intercept the authenticated image URLs from network requests.
        """
        chapter_id = self._extract_chapter_id(chapter_url)
        if not chapter_id:
            raise ValueError(f"Could not extract chapter ID from: {chapter_url}")

        reader_url = f"{self.base_url}/read/{chapter_id}"

        # Use Playwright to capture image URLs from network requests
        image_urls = self._capture_image_urls(reader_url)

        if not image_urls:
            logger.warning(f"No images found for chapter {chapter_id}")

        return image_urls

    def _capture_image_urls_in_thread(self, url: str) -> List[str]:
        """Load reader page and capture image network requests.

        Tries browsers in order: system Chrome (best DRM support),
        then Playwright Firefox (installed by default in MeManga).
        """
        from playwright.sync_api import sync_playwright

        captured_urls = []

        pw = sync_playwright().start()
        try:
            browser = self._launch_browser(pw)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            # Intercept responses matching the image endpoint
            def handle_response(response):
                req_url = response.url
                if "/api/v2/books/file/" in req_url:
                    captured_urls.append(req_url)

            page.on("response", handle_response)

            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Wait for reader to initialize and images to start loading
            page.wait_for_timeout(8000)

            # Scroll through the reader to trigger lazy-loaded images
            prev_count = 0
            for _ in range(60):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(800)
                if len(captured_urls) > prev_count:
                    prev_count = len(captured_urls)
                elif prev_count > 0:
                    # No new images after scrolling, wait a bit more
                    page.wait_for_timeout(3000)
                    if len(captured_urls) == prev_count:
                        break

            page.close()
            context.close()
            browser.close()
        finally:
            pw.stop()

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for u in captured_urls:
            base = u.split("?")[0]
            if base not in seen:
                seen.add(base)
                unique.append(u)

        return unique

    @staticmethod
    def _launch_browser(pw):
        """Launch the best available browser for DRM support.

        Tries system Chrome first (has Widevine CDM), then
        Playwright's bundled Firefox as fallback.
        """
        # System Chrome has Widevine DRM support
        for channel in ("chrome", "msedge"):
            try:
                return pw.chromium.launch(headless=True, channel=channel)
            except Exception:
                continue

        # Bundled Chromium (no DRM but may work for non-DRM chapters)
        try:
            return pw.chromium.launch(headless=True)
        except Exception:
            pass

        # Firefox fallback (installed by default in MeManga)
        return pw.firefox.launch(headless=True)

    def _capture_image_urls(self, url: str) -> List[str]:
        """Run image capture in thread pool (avoids asyncio conflicts)."""
        future = self._executor.submit(self._capture_image_urls_in_thread, url)
        return future.result(timeout=180)

    def download_image(self, url: str, path: Path) -> bool:
        """Download image with kagane-specific headers."""
        try:
            headers = {
                "Origin": "https://kagane.org",
                "Referer": "https://kagane.org/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*",
            }

            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            if len(response.content) < 1000:
                return False

            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get cover image URL via API."""
        series_id = self._extract_series_id(manga_url)
        if not series_id:
            return None

        try:
            url = f"{self.API_BASE}/api/v2/series/{series_id}"
            data = self._get_json(url)
            # Cover is in series_covers array
            covers = data.get("series_covers", [])
            if covers:
                cover_id = covers[0].get("image_id")
                if cover_id:
                    return f"{self.API_BASE}/api/v2/image/{cover_id}"
            # Fallback to cover_image_id
            cover_id = data.get("cover_image_id")
            if cover_id:
                return f"{self.API_BASE}/api/v2/image/{cover_id}"
        except Exception:
            pass
        return None
