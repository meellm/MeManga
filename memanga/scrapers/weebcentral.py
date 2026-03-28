"""
WeebCentral scraper - Full Playwright approach
Site requires JavaScript rendering for all pages.
https://weebcentral.com
"""

import re
from typing import List, Optional
from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class WeebCentralScraper(PlaywrightScraper):
    """Scraper for WeebCentral - full Playwright (JS rendering required)."""

    name = "weebcentral"
    base_url = "https://weebcentral.com"

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Search using Playwright - runs in executor thread."""
        from bs4 import BeautifulSoup

        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        results = []

        try:
            # Use advanced search page
            page.goto(f"{self.base_url}/search", wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2000)

            # Fill search input
            search_input = page.locator('input[type="text"], input[type="search"]').first
            search_input.fill(query)
            search_input.press('Enter')
            page.wait_for_timeout(3000)

            # Get results
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
                results.append(Manga(title=title, url=href))
        except Exception as e:
            print(f"[WeebCentral] Search error: {e}")
        finally:
            page.close()

        return results

    def search(self, query: str) -> List[Manga]:
        """Search for manga using advanced search."""
        future = self._executor.submit(self._search_in_thread, query)
        results = future.result(timeout=120)

        # Deduplicate
        seen = set()
        unique = []
        for m in results:
            if m.url not in seen:
                seen.add(m.url)
                unique.append(m)
        return unique[:10]

    def _get_chapters_in_thread(self, manga_url: str) -> List[Chapter]:
        """Get chapters using Playwright - runs in executor thread."""
        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        chapters = []

        try:
            print(f"[WeebCentral] Loading: {manga_url}")
            page.goto(manga_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2000)

            # Check if page loaded correctly
            title = page.title()
            if '404' in title:
                print(f"[WeebCentral] 404 error for {manga_url}")
                return []

            # Click "show all chapters" button if present
            try:
                show_all_btn = page.locator('button:has-text("show all chapters"), button:has-text("Show All Chapters")')
                if show_all_btn.count() > 0:
                    print("[WeebCentral] Clicking 'show all chapters'...")
                    show_all_btn.first.click()
                    page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[WeebCentral] No 'show all' button or click failed: {e}")

            # Get all chapter links
            chapter_links = page.query_selector_all('a[href*="/chapters/"]')
            print(f"[WeebCentral] Found {len(chapter_links)} chapter links")

            for link in chapter_links:
                try:
                    chapter_url = link.get_attribute("href")
                    if not chapter_url:
                        continue
                    if not chapter_url.startswith("http"):
                        chapter_url = self.base_url + chapter_url

                    chapter_text = link.inner_text().strip()
                    # Clean up the text (remove date)
                    chapter_text = re.sub(r'\n.*$', '', chapter_text).strip()

                    # Extract chapter number
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
                except Exception as e:
                    print(f"[WeebCentral] Error parsing chapter link: {e}")
                    continue

        except Exception as e:
            print(f"[WeebCentral] get_chapters error: {e}")
        finally:
            page.close()

        # Deduplicate and sort
        seen = set()
        unique = []
        for ch in chapters:
            if ch.number not in seen:
                seen.add(ch.number)
                unique.append(ch)

        return sorted(unique)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters using Playwright (JavaScript rendering required)."""
        future = self._executor.submit(self._get_chapters_in_thread, manga_url)
        return future.result(timeout=120)

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
            for _ in range(15):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(400)

            # Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)

            # Get all page images
            images = page.query_selector_all("img[alt*='Page'], main section img[src*='.png'], main section img[src*='.jpg'], main section img[src*='.webp']")

            pages = []
            for img in images:
                src = img.get_attribute("src")
                if src and "brand" not in src and "logo" not in src and "avatar" not in src:
                    pages.append(src)

            print(f"[WeebCentral] Found {len(pages)} pages")
            return pages
        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get pages using Playwright (JavaScript rendering required)."""
        future = self._executor.submit(self._get_pages_in_thread, chapter_url)
        return future.result(timeout=120)
