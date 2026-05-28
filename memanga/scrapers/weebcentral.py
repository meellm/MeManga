"""WeebCentral scraper — full Playwright (the site is fully JS-rendered).

Hardened against the common runtime failure modes:
  * Cloudflare interstitial on first contact — pre-warm the homepage
    to seed cookies, retry once on empty result.
  * "show all chapters" button gated behind a slow HTMX swap — wait
    for the link list to actually appear instead of a blind fixed sleep.
  * Lazy-loaded chapter images hidden below 12 000 px — scroll until
    page height stops growing instead of a fixed iteration count.
  * Browser wedged after a prior failure — the internal helpers expose
    a one-shot retry path.
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote_plus

from .playwright_base import PlaywrightScraper, cleanup_browsers, _thread_local
from .base import Chapter, Manga


# Phrases that show up in the title / body of a Cloudflare challenge
# page. If any of these are present in the rendered HTML we assume the
# real content didn't load.
_CF_HINTS = (
    "just a moment",
    "checking your browser",
    "cloudflare",
    "ddos protection",
)


def _looks_like_cloudflare(html: str, title: str = "") -> bool:
    """Cheap heuristic — only the first 4 KB is sampled."""
    sample = (title + " " + html[:4096]).lower()
    return any(h in sample for h in _CF_HINTS)


class WeebCentralScraper(PlaywrightScraper):
    """Scraper for WeebCentral - full Playwright (JS rendering required)."""

    name = "weebcentral"
    base_url = "https://weebcentral.com"

    # WeebCentral's advanced search is an HTMX form whose visible URL is
    # /search but whose actual filtered data endpoint is /search/data.
    # Hitting /search/data with the full filter param set is the same
    # request the page itself makes and returns the filtered grid in
    # ~400 ms. Typing into the quick-search sidebar only refreshes a
    # side-panel and never updates the main grid.
    _SEARCH_URL_FMT = (
        "{base}/search/data?text={q}"
        "&sort=Best+Match&order=Descending"
        "&official=Any&anime=Any&adult=Any"
        "&display_mode=Full+Display"
    )

    # ------------------------------------------------------------------
    # Internal: browser hygiene
    # ------------------------------------------------------------------

    def _restart_browser_in_thread(self):
        """Tear down the thread-local Firefox so the next call starts
        fresh. Used after a hard failure (CF wall, navigation hang) to
        drop any session the site may have fingerprinted.
        """
        try:
            cleanup_browsers()
        except Exception:
            pass

    def _new_page(self):
        """Open a new page on the persistent Firefox context.

        Returns ``(browser, context, page)``. Caller is responsible for
        ``page.close()``.
        """
        browser, context = self._get_browser_in_thread()
        page = context.new_page()
        return browser, context, page

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _do_search_once(self, query: str) -> List[Manga]:
        from bs4 import BeautifulSoup

        results: List[Manga] = []
        _, _, page = self._new_page()
        try:
            search_url = self._SEARCH_URL_FMT.format(
                base=self.base_url, q=quote_plus(query),
            )
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            # Wait for at least one real series link OR the empty-state
            # render, then snapshot. wait_for_selector returns instantly
            # when the link already exists in the static HTML the
            # /search/data endpoint returns.
            try:
                page.wait_for_selector(
                    'a[href*="/series/"]:not([href*="/series/random"])',
                    timeout=10000,
                )
            except Exception:
                pass

            content = page.content()
            if _looks_like_cloudflare(content, page.title() or ""):
                # Signal the caller to retry after a warm-up.
                raise RuntimeError("cloudflare interstitial")

            soup = BeautifulSoup(content, "html.parser")
            for link in soup.select('a[href*="/series/"]'):
                href = link.get("href", "")
                if "/series/random" in href:
                    continue
                # /search/data wraps titles in nested spans alongside an
                # "Official" / "Unofficial" badge. Prefer the <abbr
                # title="..."> when present, else strip the prefix off
                # the collapsed text.
                title = ""
                abbr = link.select_one("abbr[title]")
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
                if not href.startswith("http"):
                    href = self.base_url + href
                results.append(Manga(title=title, url=href))
        finally:
            page.close()
        return results

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Search with one Cloudflare-retry fallback.

        First attempt hits ``/search/data`` directly. If the response
        looks like a CF challenge we visit the homepage (which the
        thread-local browser can solve interactively, since it has a
        full JS engine) and retry once.
        """
        try:
            return self._do_search_once(query)
        except RuntimeError:
            # Pre-warm the homepage and retry. A single page.goto on the
            # root domain is enough to seed CF cookies into the context.
            print("[WeebCentral] CF interstitial — warming up homepage…")
            try:
                _, _, p = self._new_page()
                try:
                    p.goto(self.base_url, wait_until="domcontentloaded",
                            timeout=30000)
                    p.wait_for_timeout(2000)
                finally:
                    p.close()
            except Exception as e:
                print(f"[WeebCentral] homepage warm-up failed: {e}")
            try:
                return self._do_search_once(query)
            except Exception as e:
                print(f"[WeebCentral] retry search failed: {e}")
                return []
        except Exception as e:
            print(f"[WeebCentral] search error: {e}")
            return []

    def search(self, query: str) -> List[Manga]:
        """Search via the persistent Firefox under the class lock."""
        results = self._run_serialized(
            self._search_in_thread, query, timeout=120,
        )
        # Deduplicate by URL — WeebCentral occasionally renders the same
        # series link twice (cover + title hyperlinks both within one
        # card).
        seen: set = set()
        unique: List[Manga] = []
        for m in results:
            if m.url in seen:
                continue
            seen.add(m.url)
            unique.append(m)
        return unique[:10]

    # ------------------------------------------------------------------
    # get_chapters
    # ------------------------------------------------------------------

    # Button labels WeebCentral has used for "expand the chapter list".
    # Match case-insensitively because the site has shipped both
    # "show all chapters" and "Show All Chapters" at different times.
    _SHOW_ALL_SELECTORS = (
        'button:has-text("show all chapters")',
        'button:has-text("Show All Chapters")',
        'button:has-text("Show all chapters")',
        'a:has-text("show all chapters")',
        '[hx-get*="full-chapter-list"]',
        '[hx-get*="chapters"]',
    )

    def _expand_all_chapters(self, page) -> bool:
        """Click the "show all chapters" affordance if present.

        Returns True if a click was performed. Some pages don't have
        this button when the series only has a handful of chapters —
        those pages already show every link in the initial render.
        """
        for selector in self._SHOW_ALL_SELECTORS:
            try:
                loc = page.locator(selector)
                if loc.count() > 0:
                    print("[WeebCentral] Clicking 'show all chapters'…")
                    loc.first.click()
                    self._wait_for_chapter_list_stable(page)
                    return True
            except Exception as e:
                # Try the next selector — WeebCentral has shipped a
                # couple of label variants over time and one stale
                # match shouldn't crash the whole flow.
                print(f"[WeebCentral] selector {selector!r} failed: {e}")
                continue
        return False

    def _wait_for_chapter_list_stable(self, page,
                                          max_passes: int = 20,
                                          interval_ms: int = 400) -> int:
        """Block until the chapter-link count stops growing.

        The "show all chapters" button triggers an HTMX swap that
        streams links in batches. Bailing as soon as the count crosses
        "more than the initial 5" can leave only the first frame of
        a 300-chapter series rendered. Poll until two consecutive
        passes report the same number, then return.
        """
        last = -1
        stable = 0
        count = 0
        for _ in range(max_passes):
            try:
                count = page.evaluate(
                    "document.querySelectorAll('a[href*=\"/chapters/\"]').length"
                )
            except Exception:
                count = last
            if count == last and count > 0:
                stable += 1
                if stable >= 2:
                    return count
            else:
                stable = 0
                last = count
            page.wait_for_timeout(interval_ms)
        return count

    def _looks_like_404(self, page) -> bool:
        try:
            title = (page.title() or "").lower()
        except Exception:
            title = ""
        if "404" in title or "not found" in title:
            return True
        try:
            url = page.url or ""
        except Exception:
            url = ""
        return "/404" in url

    def _collect_chapters(self, page) -> List[Chapter]:
        """Pull every `<a href="/chapters/…">` from the rendered DOM."""
        out: List[Chapter] = []
        for link in page.query_selector_all('a[href*="/chapters/"]'):
            try:
                chapter_url = link.get_attribute("href")
                if not chapter_url:
                    continue
                if not chapter_url.startswith("http"):
                    chapter_url = self.base_url + chapter_url

                chapter_text = (link.inner_text() or "").strip()
                # Drop trailing date that follows on its own line.
                chapter_text = re.sub(r"\n.*$", "", chapter_text).strip()

                match = re.search(r"chapter[.\s-]*(\d+\.?\d*)",
                                   chapter_text, re.I)
                if not match:
                    match = re.search(r"(\d+\.?\d*)", chapter_text)
                chapter_num = match.group(1) if match else "0"

                if chapter_num != "0":
                    out.append(Chapter(
                        number=chapter_num,
                        title=chapter_text or f"Chapter {chapter_num}",
                        url=chapter_url,
                    ))
            except Exception as e:
                print(f"[WeebCentral] chapter parse skipped: {e}")
                continue
        return out

    def _resolve_series_url(self, page) -> Optional[str]:
        """Find the parent /series/<id>/<slug> link on the current
        page, ignoring the /series/random "Random series" affordance.

        Used to self-heal library entries whose stored URL is a
        chapter URL (``/chapters/<id>``) instead of a series URL.
        Older builds of the scraper occasionally saved the chapter URL
        as the manga's source URL; on those entries, calling
        ``get_chapters`` on the raw value loads the chapter reader,
        which has zero series-chapter-list links.
        """
        try:
            links = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href*=\"/series/\"]'))"
                "  .map(a => a.getAttribute('href'))"
                "  .filter(v => v && !v.includes('/series/random'))"
            )
        except Exception:
            return None
        if not links:
            return None
        # Defensive Python-side filter: the JS expression already drops
        # /series/random but we re-check here so the helper stays
        # correct even when a test or future caller hands it a raw
        # link list.
        for href in links:
            if not href or "/series/random" in href:
                continue
            if not href.startswith("http"):
                href = self.base_url + href
            return href
        return None

    def _do_chapters_once(self, manga_url: str) -> List[Chapter]:
        chapters: List[Chapter] = []
        _, _, page = self._new_page()
        try:
            print(f"[WeebCentral] Loading: {manga_url}")
            page.goto(manga_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            if self._looks_like_404(page):
                print(f"[WeebCentral] 404 for {manga_url}")
                return []

            if _looks_like_cloudflare(page.content(), page.title() or ""):
                raise RuntimeError("cloudflare interstitial")

            # Self-heal: if the stored URL is a chapter URL instead of
            # a series URL (legacy library entries from before the
            # search-results URL shape was nailed down), find the link
            # back to the series and re-navigate. Without this
            # fallback such entries return 0 chapters forever, making
            # check-updates indistinguishable from a genuinely empty
            # upstream series.
            if "/chapters/" in manga_url and "/series/" not in manga_url:
                series_url = self._resolve_series_url(page)
                if series_url and series_url != manga_url:
                    print(f"[WeebCentral] resolved chapter URL → series URL: {series_url}")
                    page.goto(series_url, wait_until="domcontentloaded",
                              timeout=60000)
                    page.wait_for_timeout(1500)
                else:
                    print(f"[WeebCentral] could not resolve series URL from chapter page {manga_url}")

            self._expand_all_chapters(page)
            chapters = self._collect_chapters(page)
            print(f"[WeebCentral] Found {len(chapters)} chapter links")
        finally:
            page.close()

        # Deduplicate by chapter number, keeping the first occurrence.
        seen: set = set()
        unique: List[Chapter] = []
        for ch in chapters:
            if ch.number in seen:
                continue
            seen.add(ch.number)
            unique.append(ch)
        return sorted(unique)

    def _get_chapters_in_thread(self, manga_url: str) -> List[Chapter]:
        """Two-attempt chapter fetch.

        First attempt is the normal flow. If it returns zero chapters
        OR raises a CF interstitial, the browser is restarted and we
        try once more.
        """
        try:
            ch = self._do_chapters_once(manga_url)
            if ch:
                return ch
            print("[WeebCentral] empty chapter list — restarting browser and retrying")
        except RuntimeError:
            print("[WeebCentral] CF interstitial on chapter page — retrying")
        except Exception as e:
            print(f"[WeebCentral] chapter load error: {e} — retrying")

        # One restart + retry. _restart_browser_in_thread closes the
        # thread-local Firefox so the next call rebuilds it from
        # scratch. That clears any wedged state from a half-loaded CF
        # challenge or a navigation that timed out mid-flight.
        self._restart_browser_in_thread()
        try:
            return self._do_chapters_once(manga_url)
        except Exception as e:
            print(f"[WeebCentral] chapter retry failed: {e}")
            return []

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters under the class lock so concurrent callers
        don't burn their timeout queued behind another browser task.
        """
        return self._run_serialized(
            self._get_chapters_in_thread, manga_url, timeout=180,
        )

    # ------------------------------------------------------------------
    # get_pages
    # ------------------------------------------------------------------

    def _scroll_until_settled(self, page, max_passes: int = 60,
                                  step_px: int = 1200) -> None:
        """Scroll the chapter reader until the document height stops
        growing.

        WeebCentral lazy-loads chapter images on scroll. A fixed
        15 × 800 px sweep caps coverage at 12 000 px — chapters above
        ~40 pages get truncated. Instead, scroll until two
        consecutive measurements report the same body scrollHeight,
        or until ``max_passes`` is hit.
        """
        last_height = 0
        stable = 0
        for _ in range(max_passes):
            page.evaluate(f"window.scrollBy(0, {step_px})")
            page.wait_for_timeout(350)
            try:
                h = page.evaluate(
                    "document.body.scrollHeight || document.documentElement.scrollHeight"
                )
            except Exception:
                h = last_height
            if h == last_height:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                last_height = h
        # Scroll back to the top so any image lazy-loading triggered by
        # visibility (rare, but some chapters use it) settles before
        # we snapshot the DOM.
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(800)
        except Exception:
            pass

    def _collect_page_images(self, page) -> List[str]:
        """Pull every chapter image URL from the rendered DOM."""
        images = page.query_selector_all(
            "img[alt*='Page'], "
            "main section img[src*='.png'], "
            "main section img[src*='.jpg'], "
            "main section img[src*='.jpeg'], "
            "main section img[src*='.webp']"
        )
        out: List[str] = []
        seen: set = set()
        for img in images:
            try:
                src = img.get_attribute("src") or ""
            except Exception:
                src = ""
            if not src or "brand" in src or "logo" in src or "avatar" in src:
                continue
            if src in seen:
                continue
            seen.add(src)
            out.append(src)
        return out

    def _do_pages_once(self, chapter_url: str) -> List[str]:
        _, _, page = self._new_page()
        try:
            # Seed cookies via the homepage. Some chapter loads need a
            # warm session to avoid an inline auth check; one extra
            # navigation is cheaper than a retry round trip.
            try:
                page.goto(self.base_url, timeout=30000)
                page.wait_for_timeout(1500)
            except Exception:
                pass

            page.goto(chapter_url, timeout=45000)
            page.wait_for_timeout(2500)

            if _looks_like_cloudflare(page.content(), page.title() or ""):
                raise RuntimeError("cloudflare interstitial")

            self._scroll_until_settled(page)
            pages = self._collect_page_images(page)
            print(f"[WeebCentral] Found {len(pages)} pages")
            return pages
        finally:
            page.close()

    def _get_pages_in_thread(self, chapter_url: str) -> List[str]:
        try:
            pages = self._do_pages_once(chapter_url)
            if pages:
                return pages
            print("[WeebCentral] empty page list — restarting browser and retrying")
        except RuntimeError:
            print("[WeebCentral] CF interstitial on reader — retrying")
        except Exception as e:
            print(f"[WeebCentral] page load error: {e} — retrying")

        self._restart_browser_in_thread()
        try:
            return self._do_pages_once(chapter_url)
        except Exception as e:
            print(f"[WeebCentral] page retry failed: {e}")
            return []

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get pages under the class lock."""
        return self._run_serialized(
            self._get_pages_in_thread, chapter_url, timeout=180,
        )
