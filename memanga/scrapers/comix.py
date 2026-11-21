"""
Comix.to scraper.

Comix is a React SPA backed by protected JSON endpoints. The public pages
render the data after the frontend initializes, so this scraper follows the
existing Playwright pattern used by other protected aggregators.

Every list is read in full or reported as a failure: chapter lists are
paged until the site's own total is reached, and a chapter's pages are
the reader's page slots, each one scrolled into view inside the reader's
own scroller and waited on, so a lazily loaded page is never left out.
"""

import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from .base import Chapter, Manga, _identifies_as_image
from .playwright_base import PlaywrightScraper, step_timeout_ms

logger = logging.getLogger(__name__)


class ComixSourceError(RuntimeError):
    """comix.to did not deliver a complete chapter list or page list."""


_CHAPTER_ROW = 'a.mchap-row__primary, a[href*="/chapter-"]'
# "Showing 1 to 20 of 741 items" under the chapter list.
_REPORTED_TOTAL = re.compile(
    r"Showing\s+[\d,]+\s+to\s+[\d,]+\s+of\s+([\d,]+)\s+items", re.I)
_TITLE_HID = re.compile(r"/title/([a-z0-9]+)-", re.I)

# The title page itself loads, but its chapter rows come from an API the
# site can put behind its own Turnstile check. The API then answers 403
# and the page shows the check, from this path, in a frame. Passing it
# sets this cookie.
_SITE_CHECK_PATH = "/@waf/challenge"
_SITE_CHECK_COOKIE = "waf_pass"

# The page's server-rendered query data, as JSON text.
_INITIAL_DATA = """
() => {
    const el = document.getElementById('initial-data');
    return el ? el.textContent : null;
}
"""


def _find_flag(value, name: str, depth: int = 0) -> Optional[bool]:
    """The first boolean ``name`` in nested dicts and lists."""
    if depth > 6:
        return None
    if isinstance(value, dict):
        if isinstance(value.get(name), bool):
            return value[name]
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = _find_flag(child, name, depth + 1)
        if found is not None:
            return found
    return None


def _title_has_chapters(raw: Optional[str], hid: str) -> Optional[bool]:
    """Whether the title's own data says it has chapters.

    Read from ``hasChapters`` in the title's detail query in the page's
    initial data. None when that cannot be read, which is no evidence
    either way.
    """
    if not raw or not hid:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    queries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(queries, dict):
        return None
    for key, value in queries.items():
        key = str(key).lower()
        if "manga" in key and "detail" in key and hid.lower() in key:
            found = _find_flag(value, "hasChapters")
            if found is not None:
                return found
    return None


class _ChapterRequests:
    """HTTP errors the page's chapter-list API requests got."""

    def __init__(self):
        self.errors: List[int] = []

    def attach(self, page) -> None:
        page.on("response", self._seen)

    def _seen(self, response) -> None:
        try:
            if ("/api/" in response.url and "/chapters" in response.url
                    and response.status >= 400):
                self.errors.append(response.status)
        except Exception:
            pass

    def site_check_shown(self, page) -> bool:
        """True once the API refused the page (403) or the page shows
        the site's check."""
        if 403 in self.errors:
            return True
        try:
            return any(_SITE_CHECK_PATH in (frame.url or "")
                       for frame in page.frames)
        except Exception:
            return False

    def note(self) -> str:
        if not self.errors:
            return ""
        return f"; the chapter API answered HTTP {sorted(set(self.errors))}"


class _ListPacer:
    """Spaces chapter-list page loads by a random gap.

    Comix puts a client that pages its chapter list too fast, or at too
    regular a rhythm, behind its site check, and that check does not
    pass in a headless browser. Each list page load (one chapter-API
    request) therefore starts a random ``gap_ms`` after the previous one
    started.
    """

    def __init__(self, gap_ms, clock=time.monotonic):
        self.gap_ms = gap_ms
        self._clock = clock
        self._next: Optional[float] = None

    def wait(self, page) -> None:
        now = self._clock()
        start = now if self._next is None else max(now, self._next)
        if start > now:
            page.wait_for_timeout(step_timeout_ms((start - now) * 1000))
        low, high = self.gap_ms
        self._next = start + random.uniform(low, high) / 1000


# One slot per page in the long-strip reader; a slot gets its <img> only
# once it is scrolled near the viewport.
_PAGE_SLOT = ".rpage-page"
_PAGE_IMAGE = "img.rpage-page__img"

# Totals of the reader's "N / M" page labels.
_SHOWN_PAGE_TOTALS = """
() => {
    const totals = new Set();
    for (const el of document.body.querySelectorAll('*')) {
        if (el.firstElementChild) continue;
        const m = /^\\s*\\d+\\s*\\/\\s*(\\d+)\\s*$/.exec(el.textContent || '');
        if (m) totals.add(parseInt(m[1], 10));
    }
    return [...totals];
}
"""


def _scramble_reason(headers) -> Optional[str]:
    """Why an image response is not a plain page, from its headers.

    Comix's image hosts can XOR-encode the bytes (``x-enc-seed`` /
    ``x-enc-len``) or shuffle the picture in tiles (``x-scramble-grid``
    with a ``x-scramble-seed``). Neither is undone here, so such a page
    must not be saved as a good one.
    """
    enc_seed = str(headers.get("x-enc-seed") or "").strip()
    if enc_seed and enc_seed != "0" and headers.get("x-enc-len"):
        return "XOR-encoded (x-enc-seed)"
    grid = str(headers.get("x-scramble-grid") or "").strip()
    seed = str(headers.get("x-scramble-seed") or "").strip()
    if grid and seed and seed != "0":
        return f"tile-scrambled (x-scramble-grid={grid})"
    return None


class ComixScraper(PlaywrightScraper):
    """Scraper for Comix.to."""

    name = "comix"
    base_url = "https://comix.to"

    # Comix lists 20 chapter rows per page. Reading stops at the site's
    # reported total; this bound only guards against a list that never
    # ends.
    _ROWS_PER_PAGE = 20
    _MAX_CHAPTER_PAGES = 1000
    # A list page counts as loaded once it shows the rows it should hold
    # that were not on an earlier page. It is polled for that, and loaded
    # again if it never gets there; a navigation can come back with
    # rows of an earlier page, or none, before the requested page
    # renders.
    _LIST_POLLS = 48
    _LIST_POLL_MS = 250
    _LIST_ATTEMPTS = 3
    # How long the site's check may take to pass in the page.
    _SITE_CHECK_POLLS = 120
    _SITE_CHECK_POLL_MS = 500
    # Random gap between chapter-list page loads, in ms.
    _LIST_GAP_MS = (2500, 5000)
    # How long one reader page may take to load once scrolled to.
    _PAGE_LOAD_MS = 15000

    def _new_page(self):
        """A new page on the shared browser context, with stealth applied."""
        from playwright_stealth import Stealth

        _, context = self._get_browser_in_thread()
        page = context.new_page()
        try:
            Stealth().apply_stealth_sync(page)
        except Exception:
            page.close()
            raise
        return page

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
        page = self._new_page()
        try:
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

        for link in soup.select(_CHAPTER_ROW):
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

    @staticmethod
    def _reported_total(html: str) -> Optional[int]:
        """The chapter count the list itself reports, if it shows one."""
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        match = _REPORTED_TOTAL.search(text)
        return int(match.group(1).replace(",", "")) if match else None

    def _read_list_page(self, page, url: str, page_num: int, seen: set,
                        total: Optional[int], api: _ChapterRequests,
                        pacer: _ListPacer):
        """Load one page of the chapter list and wait until it holds its
        own rows. Returns ``(batch, new, total, loaded)``: every row
        parsed, the rows not seen on an earlier page, the list's reported
        total, and whether the page got there.

        With a total known, the page must show
        ``min(rows per page, chapters still missing)`` new rows. Without
        one, it must show the same number of new rows on two reads in a
        row. A page that does not get there is loaded again, up to
        ``_LIST_ATTEMPTS`` times. It stops at once when the site's check
        is in the way, since loading it again cannot help. Every load,
        reloads included, waits its turn on ``pacer``.
        """
        batch, new = [], []
        for _ in range(self._LIST_ATTEMPTS):
            pacer.wait(page)
            page.goto(url, wait_until="domcontentloaded",
                      timeout=step_timeout_ms(45000))
            previous = None
            for _ in range(self._LIST_POLLS):
                html = page.content()
                if total is None:
                    total = self._reported_total(html)
                batch = self._parse_chapters_html(html)
                new = [c for c in batch if c.url not in seen]
                if total is not None:
                    expected = min(self._ROWS_PER_PAGE, total - len(seen))
                    if len(new) >= expected:
                        return batch, new, total, True
                elif new and len(new) == previous:
                    return batch, new, total, True
                if api.site_check_shown(page):
                    return batch, new, total, False
                previous = len(new)
                # Raises once the caller's budget is used up, so a page
                # still loading is never taken for the list's end.
                page.wait_for_timeout(step_timeout_ms(self._LIST_POLL_MS))
            logger.debug("Comix chapter list page %d not loaded (%d rows, "
                         "%d new); loading it again", page_num, len(batch),
                         len(new))
        return batch, new, total, False

    @staticmethod
    def _site_pass(page) -> Optional[str]:
        """The site check's pass cookie in the page's context, if any."""
        for cookie in page.context.cookies():
            if cookie.get("name") == _SITE_CHECK_COOKIE:
                return cookie.get("value")
        return None

    def _pass_site_check(self, page, manga_url: str) -> None:
        """Open the site's check as a page and wait until it sets a new
        pass cookie. The check runs on its own in a browser; it is not
        solved here. Raises ``ComixSourceError`` if no pass arrives in
        time.
        """
        before = self._site_pass(page)
        logger.info("Opening comix.to's site check for the chapter list...")
        page.goto(f"{self.base_url}{_SITE_CHECK_PATH}",
                  wait_until="domcontentloaded", timeout=step_timeout_ms(45000))
        for _ in range(self._SITE_CHECK_POLLS):
            current = self._site_pass(page)
            if current and current != before:
                return
            page.wait_for_timeout(step_timeout_ms(self._SITE_CHECK_POLL_MS))
        seconds = self._SITE_CHECK_POLLS * self._SITE_CHECK_POLL_MS / 1000
        raise ComixSourceError(
            f"Comix chapter list for {manga_url} is behind the site's "
            f"Turnstile check ({_SITE_CHECK_PATH}), and it did not pass in "
            f"the browser within {seconds:g}s")

    def _no_rows_error(self, page, manga_url: str,
                       api: _ChapterRequests) -> Optional[ComixSourceError]:
        """Why the first list page showing no rows is not proof the title
        has none. Returns None only when the title's own data says it has
        no chapters."""
        try:
            raw = page.evaluate(_INITIAL_DATA)
        except Exception:
            raw = None
        match = _TITLE_HID.search(manga_url)
        has_chapters = _title_has_chapters(raw, match.group(1) if match else "")
        if has_chapters is False:
            return None
        why = ("the title's data says it has chapters" if has_chapters
               else "the page's data does not say whether it has any")
        return ComixSourceError(
            f"Comix showed no chapter rows for {manga_url}, but {why}"
            f"{api.note()}")

    def _get_chapters_in_thread(self, manga_url: str) -> List[Chapter]:
        """Collect every rendered chapter row across the list's pages.

        Reading stops at the total the list reports, or at its last
        (short) page. Fewer rows than the reported total is an error, never
        a shorter list. ``MEMANGA_COMIX_MAX_CHAPTER_PAGES`` caps the walk
        on request; a list cut short by it is logged as truncated.

        When the site's check keeps the rows from loading, it is opened
        once and the page read again. No rows at all is only an empty
        list when the title's own data says it has no chapters; otherwise
        it is an error saying what was seen.
        """
        cap_setting = os.environ.get("MEMANGA_COMIX_MAX_CHAPTER_PAGES", "").strip()
        cap = int(cap_setting) if cap_setting else None
        limit = cap if cap else self._MAX_CHAPTER_PAGES

        page = self._new_page()
        try:
            api = _ChapterRequests()
            api.attach(page)
            checked = False
            pacer = _ListPacer(self._LIST_GAP_MS)
            chapters = []
            seen = set()
            total = None
            base = manga_url.split("?", 1)[0]

            for page_num in range(1, limit + 1):
                url = f"{base}?page={page_num}"
                batch, new, total, loaded = self._read_list_page(
                    page, url, page_num, seen, total, api, pacer)
                if (not loaded and not checked
                        and api.site_check_shown(page)):
                    # Opened at most once per list: a check that passes
                    # and is shown again is reported, not looped on.
                    self._pass_site_check(page, manga_url)
                    checked = True
                    api.errors.clear()
                    batch, new, total, loaded = self._read_list_page(
                        page, url, page_num, seen, total, api, pacer)
                if not loaded:
                    if total is not None and len(seen) < total:
                        raise ComixSourceError(
                            f"Comix chapter list page {page_num} for "
                            f"{manga_url} did not load: it showed "
                            f"{len(batch)} rows, {len(new)} of them new, with "
                            f"{total - len(seen)} of the {total} reported "
                            f"chapters still missing{api.note()}")
                    if page_num == 1 and not new:
                        error = self._no_rows_error(page, manga_url, api)
                        if error is not None:
                            raise error
                        return []
                for chapter in new:
                    seen.add(chapter.url)
                    chapters.append(chapter)

                if total is not None and len(seen) >= total:
                    break
                if not new or len(batch) < self._ROWS_PER_PAGE:
                    # Without a reported total, an empty or short page
                    # is the end of the list. With one, the check
                    # below refuses a list that ended early.
                    break
            else:
                if not cap:
                    raise ComixSourceError(
                        f"Comix chapter list for {manga_url} still had more "
                        f"pages after {limit} pages; refusing an incomplete list")
                logger.warning(
                    "Comix chapter list for %s stopped after %d pages "
                    "(MEMANGA_COMIX_MAX_CHAPTER_PAGES); older chapters are "
                    "not listed", manga_url, cap)
                return sorted(chapters, key=lambda ch: ch.numeric)

            if total is not None and len(seen) < total:
                raise ComixSourceError(
                    f"Comix chapter list for {manga_url} has {len(seen)} of "
                    f"the {total} chapters it reports; refusing an "
                    f"incomplete list")
            return sorted(chapters, key=lambda ch: ch.numeric)
        finally:
            page.close()

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga."""
        return self._run_serialized(
            self._get_chapters_in_thread, manga_url, timeout=600,
        )

    def _get_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Read every page of the long-strip reader, in order.

        The reader scrolls inside its own container, not the window, and
        gives a page slot its image only once that slot is near the
        viewport. Each slot is therefore scrolled into view and waited
        on until its image has loaded. The URL is read after the load, so
        a host the reader switched to is the one recorded. A slot whose
        image never loads fails the whole chapter.
        """
        page = self._new_page()
        try:
            page.goto(chapter_url, wait_until="domcontentloaded",
                      timeout=step_timeout_ms(45000))
            page.wait_for_selector(_PAGE_IMAGE, timeout=step_timeout_ms(20000))

            slots = page.locator(_PAGE_SLOT)
            total = slots.count()
            if not total:
                raise ComixSourceError(f"Comix reader shows no pages for {chapter_url}")
            shown = page.evaluate(_SHOWN_PAGE_TOTALS) or []
            if shown and total not in shown:
                raise ComixSourceError(
                    f"Comix reader for {chapter_url} has {total} page slots "
                    f"but labels its pages out of {sorted(shown)}")

            urls = []
            for index in range(total):
                slot = slots.nth(index)
                slot.scroll_into_view_if_needed(timeout=step_timeout_ms(10000))
                image = slot.locator(_PAGE_IMAGE).first
                try:
                    handle = image.element_handle(
                        timeout=step_timeout_ms(self._PAGE_LOAD_MS))
                    page.wait_for_function(
                        "img => img.complete && img.naturalWidth > 0",
                        arg=handle, timeout=step_timeout_ms(self._PAGE_LOAD_MS))
                    src = handle.evaluate("img => img.currentSrc || img.src || ''")
                except Exception as e:
                    drawn = ""
                    try:
                        if slot.locator("canvas").count():
                            drawn = " (it is drawn on a canvas, which is not supported)"
                    except Exception:
                        pass
                    raise ComixSourceError(
                        f"Comix page {index + 1} of {total} did not load for "
                        f"{chapter_url}{drawn}") from e
                if not src.startswith(("http://", "https://")):
                    raise ComixSourceError(
                        f"Comix page {index + 1} of {total} for {chapter_url} "
                        f"has no image URL ({src[:40]!r})")
                urls.append(src)
            return urls
        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        return self._run_serialized(
            self._get_pages_in_thread, chapter_url, timeout=300,
        )

    def download_image(self, url: str, path) -> bool:
        """Download one page image.

        Comix's image hosts refuse a request that carries a Referer or
        Origin, so the page is fetched with the plain session headers,
        which send neither, through the shared request policy. An
        encoded or tile-scrambled response, or a body that is not an
        image, is a failed page, never a saved one.
        """
        path = Path(path)
        try:
            response = self._request(url)
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False

        reason = _scramble_reason(response.headers)
        if reason:
            path.unlink(missing_ok=True)
            logger.warning("Comix served %s %s; not saving an unreadable page",
                           url, reason)
            return False

        content = response.content
        if not _identifies_as_image(content):
            path.unlink(missing_ok=True)
            logger.debug("Failed to download %s: response body is not an image", url)
            return False

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return True
