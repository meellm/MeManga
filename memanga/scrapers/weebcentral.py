"""
WeebCentral scraper - Hybrid approach
- cloudscraper for chapters (bypass Cloudflare)
- Playwright for search and pages (JavaScript rendering needed)
https://weebcentral.com
"""

import re
from typing import List, Optional
from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class WeebCentralScraper(PlaywrightScraper):
    """Scraper for WeebCentral - hybrid cloudscraper + Playwright."""

    name = "weebcentral"
    base_url = "https://weebcentral.com"

    def __init__(self):
        super().__init__()
        # Use cloudscraper for chapter listing
        import cloudscraper
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'firefox', 'platform': 'windows', 'mobile': False}
        )

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Search using Playwright - runs in executor thread."""
        from bs4 import BeautifulSoup

        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        results = []

        try:
            page.goto(self.base_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2000)

            search_input = page.locator('input[placeholder*="Quick Search"], input[type="search"]').first
            search_input.fill(query)
            page.wait_for_timeout(2000)

            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')

            for link in soup.select('a[href*="/series/"]'):
                href = link.get('href', '')
                if '/series/random' in href:
                    continue
                title = link.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                if not href.startswith('http'):
                    href = self.base_url + href
                if query.lower() in title.lower() or title.lower() in query.lower():
                    results.append(Manga(title=title, url=href))
        except Exception as e:
            print(f"[WeebCentral] Search error: {e}")
        finally:
            page.close()

        return results

    def search(self, query: str) -> List[Manga]:
        """Search for manga using Quick Search dropdown."""
        results = self._run_serialized(self._search_in_thread, query, timeout=120)

        # Deduplicate
        seen = set()
        unique = []
        for m in results:
            if m.url not in seen:
                seen.add(m.url)
                unique.append(m)
        return unique[:10]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters using cloudscraper (no JS needed)."""
        from bs4 import BeautifulSoup

        match = re.search(r'(/series/[^/]+)', manga_url)
        if match:
            chapter_list_url = self.base_url + match.group(1) + "/full-chapter-list"
        else:
            chapter_list_url = manga_url

        html = self._get_html(chapter_list_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []

        for link in soup.select("a[href*='/chapters/']"):
            chapter_url = link.get("href", "")
            if not chapter_url.startswith("http"):
                chapter_url = self.base_url + chapter_url

            span = link.select_one("span.grow span")
            chapter_text = span.get_text(strip=True) if span else link.get_text(strip=True)
            chapter_text = re.sub(r'Last Read.*$', '', chapter_text).strip()

            match = re.search(r'chapter[.\s-]*(\d+\.?\d*)', chapter_text, re.I)
            if not match:
                match = re.search(r'(\d+\.?\d*)', chapter_text)

            chapter_num = match.group(1) if match else "0"

            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=chapter_text,
                    url=chapter_url,
                ))

        seen = set()
        unique = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique.append(ch)

        return sorted(unique)

    def _get_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Get pages using Playwright - runs in executor thread."""
        browser, context = self._get_browser_in_thread()
        page = context.new_page()

        try:
            # Load homepage first to get cookies
            page.goto(self.base_url, timeout=30000)
            page.wait_for_timeout(2000)

            # Navigate to chapter
            page.goto(chapter_url, timeout=45000)
            page.wait_for_timeout(3000)

            # Scroll to trigger lazy loading
            for _ in range(10):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(500)

            # Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)

            # Get all page images
            images = page.query_selector_all("img[alt*='Page'], main section img[src*='.png'], main section img[src*='.jpg']")

            pages = []
            for img in images:
                src = img.get_attribute("src")
                if src and "brand" not in src and "logo" not in src:
                    pages.append(src)

            return pages
        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get pages using Playwright (JavaScript rendering required)."""
        return self._run_serialized(self._get_pages_in_thread, chapter_url, timeout=120)
