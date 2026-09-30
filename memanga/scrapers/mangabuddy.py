"""
MangaBuddy scraper
https://mangabuddy.com

Popular manga aggregator. Uses Playwright for chapter pages (JS-loaded images)
and HTTP for search/chapter listing.
"""

import json
import re
from typing import List
from pathlib import Path
from urllib.parse import quote_plus
from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class MangaBuddyScraper(PlaywrightScraper):
    """Scraper for MangaBuddy.com"""

    name = "mangabuddy"
    base_url = "https://mangabuddy.com"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title.

        mangabuddy.com now redirects to comizy.io, a Next.js site that
        ships search results in ``#__NEXT_DATA__`` (``pageProps.ssrItems``).
        The legacy ``.book-item`` card markup is kept as a fallback.
        """
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/search?q={quote_plus(query)}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")

        results = self._parse_next_search(soup)
        if results:
            return results[:10]

        for item in soup.select(".book-item, .manga-item, .list-item"):
            link = item.find("a")
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue

            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"

            # Get title
            title_elem = item.select_one(".title, h3, h2, .name")
            title = title_elem.get_text(strip=True) if title_elem else ""

            if not title:
                img = item.find("img")
                title = img.get("alt", "") if img else href.split("/")[-1].replace("-", " ").title()

            # Get cover
            cover_url = None
            img = item.find("img")
            if img:
                cover_url = img.get("data-src") or img.get("src")

            if title:
                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))

        return results[:10]

    @staticmethod
    def _next_page_props(soup) -> dict:
        """Return ``props.pageProps`` from the Next.js data blob, or {}."""
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return {}
        try:
            data = json.loads(script.string)
        except ValueError:
            return {}
        props = data.get("props") if isinstance(data, dict) else None
        page_props = props.get("pageProps") if isinstance(props, dict) else None
        return page_props if isinstance(page_props, dict) else {}

    def _parse_next_search(self, soup) -> List[Manga]:
        """Parse Comizy search results from ``pageProps.ssrItems``."""
        items = self._next_page_props(soup).get("ssrItems")
        if not isinstance(items, list):
            return []

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("name") or "").strip()
            href = item.get("url") or (f"/{item['slug']}" if item.get("slug") else "")
            if not title or not href:
                continue
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=item.get("cover") or None,
                description=item.get("summary") or None,
            ))
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup

        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        for link in soup.select(".chapter-list a, .chapters a, a[href*='/chapter']"):
            href = link.get("href", "")
            if not href or "chapter" not in href.lower():
                continue

            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            chapter_text = link.get_text(strip=True)

            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)

            chapter_num = match.group(1) if match else "0"

            chapters.append(Chapter(
                number=chapter_num,
                title=chapter_text,
                url=chapter_url,
            ))

        # Deduplicate
        seen = set()
        unique = []
        for ch in chapters:
            if ch.url not in seen:
                seen.add(ch.url)
                unique.append(ch)

        return sorted(unique, key=lambda x: x.numeric)

    def _parse_next_pages(self, html: str) -> List[str]:
        """Parse Comizy chapter images from ``pageProps.initialChapter``.

        Reads ``initialChapter.images`` (list of URLs) and falls back to
        ``initialChapter.pages[*].url``. Returns [] when neither is present.
        """
        from bs4 import BeautifulSoup

        chapter = self._next_page_props(BeautifulSoup(html, "html.parser")).get("initialChapter")
        if not isinstance(chapter, dict):
            return []

        for key in ("images", "pages"):
            entries = chapter.get(key)
            if not isinstance(entries, list):
                continue
            urls = []
            for entry in entries:
                src = entry.get("url") if isinstance(entry, dict) else entry
                if not isinstance(src, str) or not src.strip():
                    continue
                src = src.strip()
                if src.startswith("//"):
                    src = f"https:{src}"
                if src.startswith("http") and src not in urls:
                    urls.append(src)
            if urls:
                return urls
        return []

    def _get_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Fetch page images using Playwright - runs in executor thread.

        MangaBuddy loads images dynamically via JavaScript, so we need
        a real browser to render the page and extract image URLs.
        """
        from playwright_stealth import Stealth

        browser, context = self._get_browser_in_thread()
        page = context.new_page()

        try:
            Stealth().apply_stealth_sync(page)

            page.goto(chapter_url, wait_until='domcontentloaded', timeout=45000)

            # mangabuddy.com redirects to comizy.io, which embeds the page
            # image URLs in #__NEXT_DATA__ -- no scrolling needed.
            next_pages = self._parse_next_pages(page.content())
            if next_pages:
                return next_pages

            page.wait_for_timeout(3000)

            # Scroll down to trigger lazy loading of all images
            prev_height = 0
            for _ in range(20):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(500)
                curr_height = page.evaluate("document.documentElement.scrollHeight")
                if curr_height == prev_height:
                    break
                prev_height = curr_height

            # Scroll back to top and wait for any final loads
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)

            # Extract image URLs from the rendered DOM
            pages = page.evaluate("""
                () => {
                    const urls = [];
                    const seen = new Set();

                    // Strategy 1: common reader container selectors
                    document.querySelectorAll('.reading-content img, .chapter-content img, .page-img, #chapter-images img, .container-reader-chapter img, .chapter-img img').forEach(img => {
                        const src = img.getAttribute('data-src') || img.getAttribute('src') || '';
                        if (src && !seen.has(src) && !src.includes('logo') && !src.includes('icon') && !src.includes('avatar')) {
                            if (src.match(/\\.(jpg|jpeg|png|webp|gif)/i) || src.includes('/manga/') || src.includes('/chapter/')) {
                                seen.add(src);
                                urls.push(src);
                            }
                        }
                    });

                    // Strategy 2: broader search for manga page images
                    if (urls.length === 0) {
                        document.querySelectorAll('img').forEach(img => {
                            const src = img.getAttribute('data-src') || img.getAttribute('src') || '';
                            if (src && !seen.has(src) && src.match(/\\d+\\.(jpg|jpeg|png|webp)/i)) {
                                if (!src.includes('logo') && !src.includes('icon') && !src.includes('avatar') && !src.includes('thumb')) {
                                    seen.add(src);
                                    urls.push(src);
                                }
                            }
                        });
                    }

                    return urls;
                }
            """)

            return pages

        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter.

        Uses Playwright to render JS-loaded images.
        """
        return self._run_serialized(self._get_pages_in_thread, chapter_url, timeout=120)

    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers.

        Tries the MangaBuddy referer first, then the Comizy one (the
        site now redirects there and serves images from its CDN).
        """
        error = None
        for referer in (f"{self.base_url}/", "https://comizy.io/"):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": referer,
                }
                response = self.session.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(response.content)
                return True
            except Exception as e:
                error = e
        print(f"Failed to download {url}: {error}")
        return False
