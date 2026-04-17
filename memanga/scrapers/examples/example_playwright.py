"""
Example: JavaScript-heavy site requiring a real browser (Playwright + Firefox).

Use this pattern for sites that:
- Load manga pages via JavaScript (React, Vue, Next.js)
- Use anti-bot measures that defeat even cloudscraper
- Scramble/encrypt image URLs that only decode client-side

Real examples: mangafire.to (VRF bypass), fanfox.net, comick.io, toonily.me

How it works:
- PlaywrightScraper runs a headless Firefox in a ThreadPoolExecutor to avoid
  conflicts with asyncio (used by rich and other CLI libs).
- Stealth mode patches navigator properties to reduce bot fingerprint.
- Use _run_in_thread() to submit any sync Playwright code.
"""

import re
from typing import List
from ..base import Chapter, Manga
from ..playwright_base import PlaywrightScraper


class ExamplePlaywrightScraper(PlaywrightScraper):
    """Scraper for a JS-heavy manga site using Playwright/Firefox."""

    name = "example_pw"
    base_url = "https://example-js-site.com"

    def search(self, query: str) -> List[Manga]:
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"

        def _search_in_thread():
            page = self._get_page_in_thread(url)
            results = []
            for card in page.query_selector_all(".manga-item"):
                a = card.query_selector("a")
                img = card.query_selector("img")
                if not a:
                    continue
                results.append(Manga(
                    title=a.inner_text().strip(),
                    url=a.get_attribute("href"),
                    cover_url=img.get_attribute("src") if img else None,
                ))
            return results

        return self._run_in_thread(_search_in_thread)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        def _chapters_in_thread():
            page = self._get_page_in_thread(manga_url)
            # Wait for chapter list to render
            page.wait_for_selector(".chapter-list", timeout=10000)

            chapters = []
            for li in page.query_selector_all(".chapter-list li"):
                a = li.query_selector("a")
                if not a:
                    continue
                href = a.get_attribute("href") or ""
                match = re.search(r'chapter[/-](\d+(?:\.\d+)?)', href, re.IGNORECASE)
                number = match.group(1) if match else a.inner_text().strip()
                chapters.append(Chapter(
                    number=number,
                    title=a.inner_text().strip(),
                    url=href if href.startswith("http") else self.base_url + href,
                ))
            return sorted(chapters, reverse=True)

        return self._run_in_thread(_chapters_in_thread)

    def get_pages(self, chapter_url: str) -> List[str]:
        def _pages_in_thread():
            page = self._get_page_in_thread(chapter_url)
            page.wait_for_selector(".reader-images img", timeout=15000)

            pages = []
            for img in page.query_selector_all(".reader-images img"):
                src = img.get_attribute("data-src") or img.get_attribute("src") or ""
                if src and not src.startswith("data:"):
                    pages.append(src.strip())
            return pages

        return self._run_in_thread(_pages_in_thread)
