"""
Comix.to scraper.

Comix is a React SPA backed by protected JSON endpoints. The public pages
render the data after the frontend initializes, so this scraper follows the
existing Playwright pattern used by other protected aggregators.
"""

import os
import re
from pathlib import Path
from typing import List
from urllib.parse import urljoin

from .base import Chapter, Manga
from .playwright_base import PlaywrightScraper


class ComixScraper(PlaywrightScraper):
    """Scraper for Comix.to."""

    name = "comix"
    base_url = "https://comix.to"

    def _parse_search_html(self, html: str) -> List[Manga]:
        """Parse rendered browse/search HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        by_url = {}

        for link in soup.select('a[href*="/title/"]'):
            href = link.get("href", "")
            if not href or "/chapter-" in href:
                continue

            url = href if href.startswith("http") else urljoin(self.base_url, href)
            entry = by_url.setdefault(url, {"title": "", "cover_url": None})

            text = link.get_text(" ", strip=True)
            if text and not entry["title"]:
                entry["title"] = text

            img = link.find("img")
            if img and not entry["cover_url"]:
                entry["cover_url"] = img.get("data-src") or img.get("src")
                if not entry["title"]:
                    entry["title"] = img.get("alt", "")

        results = []
        for url, data in by_url.items():
            title = data["title"]
            if not title:
                title = url.rstrip("/").rsplit("/", 1)[-1]
                title = re.sub(r"^[a-z0-9]+-", "", title).replace("-", " ").title()
            results.append(Manga(
                title=title,
                url=url,
                cover_url=data["cover_url"],
            ))

        return results[:20]

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Drive the rendered browse search box."""
        from playwright_stealth import Stealth

        browser, context = self._get_browser_in_thread()
        page = context.new_page()

        try:
            Stealth().apply_stealth_sync(page)
            page.goto(f"{self.base_url}/browse", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector('input[type="search"]', timeout=20000)
            page.fill('input[type="search"]', query)
            page.wait_for_timeout(5000)
            return self._parse_search_html(page.content())
        finally:
            page.close()

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        return self._run_serialized(self._search_in_thread, query, timeout=90)

    def _parse_chapters_html(self, html: str) -> List[Chapter]:
        """Parse rendered chapter-list HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        chapters = []
        seen = set()

        for link in soup.select('a.mchap-row__primary, a[href*="/chapter-"]'):
            href = link.get("href", "")
            if not href or "chapter-" not in href:
                continue

            url = href if href.startswith("http") else urljoin(self.base_url, href)
            if url in seen:
                continue
            seen.add(url)

            text = link.get_text(" ", strip=True)
            match = re.search(r"\bCh\.?\s*(\d+(?:\.\d+)?)", text, re.I)
            if not match:
                match = re.search(r"chapter-(\d+(?:\.\d+)?)", href, re.I)
            number = match.group(1) if match else "0"

            title = text
            title = re.sub(r"^Ch\.?\s*\d+(?:\.\d+)?\s*", "", title, flags=re.I)
            title = title.strip() or f"Chapter {number}"

            chapters.append(Chapter(number=number, title=title, url=url))

        return chapters

    def _get_chapters_in_thread(self, manga_url: str) -> List[Chapter]:
        """Collect rendered chapter rows across paginated chapter-list pages."""
        from playwright_stealth import Stealth

        # Comix exposes 20 chapter rows per rendered page. Five pages covers
        # the newest 100 rows, which is enough for normal update checks while
        # avoiding very slow first-time crawls on long-running series. Set
        # MEMANGA_COMIX_MAX_CHAPTER_PAGES for deeper backfills.
        max_pages = int(os.environ.get("MEMANGA_COMIX_MAX_CHAPTER_PAGES", "5"))
        browser, context = self._get_browser_in_thread()
        page = context.new_page()

        try:
            Stealth().apply_stealth_sync(page)

            chapters = []
            seen = set()
            base = manga_url.split("?", 1)[0]

            for page_num in range(1, max_pages + 1):
                url = f"{base}?page={page_num}"
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector(
                        'a.mchap-row__primary, a[href*="/chapter-"]',
                        timeout=12000 if page_num == 1 else 6000,
                    )
                except Exception:
                    break

                batch = self._parse_chapters_html(page.content())
                new_count = 0
                for chapter in batch:
                    if chapter.url in seen:
                        continue
                    seen.add(chapter.url)
                    chapters.append(chapter)
                    new_count += 1

                if new_count == 0 or len(batch) < 20:
                    break

            return sorted(chapters, key=lambda ch: ch.numeric)
        finally:
            page.close()

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga."""
        return self._run_serialized(
            self._get_chapters_in_thread, manga_url, timeout=180,
        )

    def _get_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Extract reader image URLs from the rendered chapter page."""
        from playwright_stealth import Stealth

        browser, context = self._get_browser_in_thread()
        page = context.new_page()

        try:
            Stealth().apply_stealth_sync(page)
            page.goto(chapter_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector(".rpage-page__img, img", timeout=20000)

            last_height = 0
            for _ in range(20):
                page.evaluate("window.scrollBy(0, 1200)")
                page.wait_for_timeout(350)
                height = page.evaluate("document.documentElement.scrollHeight")
                if height == last_height:
                    break
                last_height = height

            return page.evaluate("""
                () => {
                    const urls = [];
                    const seen = new Set();
                    document.querySelectorAll('.rpage-page__img, img').forEach(img => {
                        const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
                        if (!src || seen.has(src)) return;
                        if (src.includes('avatar') || src.includes('logo') || src.includes('icon')) return;
                        if (!img.classList.contains('rpage-page__img') && img.naturalHeight < 300) return;
                        seen.add(src);
                        urls.push(src);
                    });
                    return urls;
                }
            """)
        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        return self._run_serialized(
            self._get_pages_in_thread, chapter_url, timeout=120,
        )

    def download_image(self, url: str, path) -> bool:
        """Download image with Comix reader headers."""
        try:
            response = self.session.get(
                url,
                headers={
                    "User-Agent": self.session.headers.get("User-Agent", ""),
                    "Referer": f"{self.base_url}/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                timeout=30,
            )
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception:
            return False
