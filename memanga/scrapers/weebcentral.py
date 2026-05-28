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

    # WeebCentral's advanced search is an HTMX form whose visible URL is
    # /search but whose actual filtered data endpoint is /search/data.
    # The old implementation typed into the quick-search bar and pressed
    # Enter — but the quick-search input only POSTs to a side-panel,
    # NOT the main result grid, so Enter never filtered anything and
    # we got the full unfiltered series list back (64+ rows, none
    # matching the query → relevance filter dropped them all → user
    # saw zero WeebCentral results). Hitting /search/data with the
    # full filter param set is the same request the page itself makes
    # and returns Blue Lock in ~400 ms.
    _SEARCH_URL_FMT = (
        "{base}/search/data?text={q}"
        "&sort=Best+Match&order=Descending"
        "&official=Any&anime=Any&adult=Any"
        "&display_mode=Full+Display"
    )

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Search using Playwright - runs in executor thread."""
        from bs4 import BeautifulSoup
        from urllib.parse import quote_plus

        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        results = []

        try:
            search_url = self._SEARCH_URL_FMT.format(
                base=self.base_url, q=quote_plus(query),
            )
            page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            # Wait for at least one real series link OR the empty-state
            # render, then snapshot. wait_for_selector returns instantly
            # when the link already exists in the static HTML the
            # /search/data endpoint returns.
            try:
                page.wait_for_selector(
                    'a[href*="/series/"]:not([href*="/series/random"])',
                    timeout=8000,
                )
            except Exception:
                pass

            soup = BeautifulSoup(page.content(), 'html.parser')

            for link in soup.select('a[href*="/series/"]'):
                href = link.get('href', '')
                if '/series/random' in href:
                    continue
                # /search/data wraps the title in nested spans alongside
                # an "Official" badge. Grab the deepest title node by
                # preferring an <abbr title="..."> when present, else
                # strip the leading "Official" / "Unofficial" prefix
                # from the collapsed text.
                title = ""
                abbr = link.select_one('abbr[title]')
                if abbr and abbr.get("title"):
                    title = abbr.get("title").strip()
                if not title:
                    title = link.get_text(separator=" ", strip=True)
                    for prefix in ("Official ", "Unofficial ",
                                    "Official", "Unofficial"):
                        if title.startswith(prefix):
                            title = title[len(prefix):].lstrip()
                            break
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
        """Search for manga using Quick Search dropdown."""
        # Keep PySide6's _run_serialized — wraps submit+wait in the
        # class-level lock so queued futures don't burn their timeout
        # while waiting for an earlier task to finish.
        results = self._run_serialized(self._search_in_thread, query, timeout=120)

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
        # Use _run_serialized (same as search/pages) so concurrent
        # callers don't burn their timeout queued behind the prior task.
        return self._run_serialized(self._get_chapters_in_thread, manga_url,
                                     timeout=120)

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
        return self._run_serialized(self._get_pages_in_thread, chapter_url, timeout=120)
