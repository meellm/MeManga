"""
MangaPanda scraper
https://mangapanda.onl and https://mangafox.fun

React-based manga site of the MangaHub network (same as mangafox.fun,
mangahub.us). Search, chapter lists and page images are plain HTTP
through cloudscraper; a chapter's page list is read from the rendered
reader in the browser (see `_MangaPandaReader`).
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlsplit
from pathlib import Path
from .base import (BaseScraper, Chapter, Manga, BROWSER_USER_AGENT_SHORT,
                   _identifies_as_image)
from .playwright_base import PlaywrightScraper, step_timeout_ms

logger = logging.getLogger(__name__)

_MANGA_SLUG = re.compile(r"/manga/([^/?#]+)")
# Reader buttons that link a chapter without naming it.
_BUTTON_LABELS = ("start reading", "read first", "read last")

# Chapter pages are served from this host only.
_PAGE_HOST = "imgx.mghcdn.com"
_READER_PATH = re.compile(r"/chapter/([^/?#]+)/chapter-(\d+(?:\.\d+)?)/?$")
_PAGE_PATH = re.compile(
    r"/([^/]+)/([^/]+)/[^/]+\.(?:jpe?g|png|webp|gif|avif)", re.IGNORECASE)

# The served reader page shows only the chapter's first pages, with
# counters that already look complete ("1/6" .. "6/6" on a 20-page
# chapter). The site's own script then fetches the chapter from /graphql,
# decrypts its page list in the browser, unpacks it with JSON.parse into
# a path prefix "p" and page files "i", and renders the rest. This script
# runs before the site's own and keeps a copy of each such list, with the
# time it was unpacked, so the rendered reader can be held against the
# list the site itself was given. It decrypts and sends nothing.
_PAGE_LIST_OBSERVER = """
(() => {
    if (window.__mangaPandaPageLists) return;
    const lists = [];
    Object.defineProperty(window, '__mangaPandaPageLists', {value: lists});
    const nativeParse = JSON.parse;
    JSON.parse = function (text, reviver) {
        const value = nativeParse.call(this, text, reviver);
        try {
            if (value !== null && typeof value === 'object'
                    && Array.isArray(value.i) && value.i.length > 0
                    && value.i.every((name) => typeof name === 'string')
                    && (value.p === undefined || value.p === null
                        || typeof value.p === 'string')
                    && lists.length < 50) {
                lists.push({p: value.p || '', i: value.i.slice(0, 5000),
                            t: performance.now()});
            }
        } catch (e) {}
        return value;
    };
})();
"""

# One look at the reader: its "k/N" counters, every image's raw `src` in
# document order (pages further down load lazily, and until then only the
# attribute holds their URL), the page lists unpacked so far, and when
# the page's own /graphql requests finished, on the page's clock.
_READER_STATE = """
() => {
    const counters = [];
    for (const el of (document.body ? document.body.querySelectorAll('*') : [])) {
        if (el.firstElementChild) continue;
        const m = /^\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*$/.exec(el.textContent || '');
        if (m) counters.push([parseInt(m[1], 10), parseInt(m[2], 10)]);
    }
    const images = [];
    for (const img of document.images) images.push(img.getAttribute('src') || '');
    const kept = window.__mangaPandaPageLists;
    const lists = kept ? kept.map((l) => ({p: l.p, i: l.i.slice(), t: l.t})) : null;
    const graphqlEnds = performance.getEntriesByType('resource').filter((e) => {
        try {
            const u = new URL(e.name);
            return u.origin === location.origin && u.pathname === '/graphql';
        } catch (x) { return false; }
    }).map((e) => e.responseEnd).filter((t) => t > 0);
    return {counters, images, lists, graphqlEnds};
}
"""


class MangaPandaReaderIncomplete(TimeoutError):
    """The reader did not show a chapter's whole page list in time."""


def _chapter_of(chapter_url: str) -> Tuple[Optional[str], Optional[str]]:
    """`(series slug, chapter number)` of a reader URL."""
    match = _READER_PATH.search(urlsplit(chapter_url or "").path)
    return (match.group(1), match.group(2)) if match else (None, None)


def _same_number(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def chapter_reply_matches(payload, number) -> bool:
    """True for a GraphQL reply carrying chapter `number`'s page list.
    The list itself stays encrypted; only its presence is checked."""
    data = payload.get("data") if isinstance(payload, dict) else None
    chapter = data.get("chapter") if isinstance(data, dict) else None
    if not isinstance(chapter, dict):
        return False
    pages = chapter.get("pages")
    if not (isinstance(pages, str) and pages.strip()):
        return False
    return number is not None and _same_number(chapter.get("number"), number)


def reader_page_urls(images: List[str], chapter_url: str) -> List[str]:
    """The reader's page images of this chapter, in document order:
    https on the page host, in this series' and this chapter's folder.
    Covers, ads and other chapters' pages are left out."""
    series, number = _chapter_of(chapter_url)
    urls = []
    for src in images or []:
        parts = urlsplit(src or "")
        if parts.scheme != "https" or parts.hostname != _PAGE_HOST:
            continue
        match = _PAGE_PATH.fullmatch(parts.path)
        if (not match or series is None or match.group(1) != series
                or not _same_number(match.group(2), number)):
            continue
        urls.append(src)
    return urls


def _list_entries(page_list: dict) -> List[Tuple[Optional[str], str]]:
    """`(host, path)` of each page of an unpacked list. The host is None
    for a bare entry (the site's lists hold file names under a prefix)."""
    prefix = page_list.get("p") or ""
    entries = []
    for name in page_list.get("i") or []:
        entry = f"{prefix}{name}"
        parts = urlsplit(entry)
        if parts.netloc:
            entries.append(((parts.hostname or "").lower(), parts.path))
        else:
            entries.append((None, "/" + entry.lstrip("/")))
    return entries


def list_matches(page_list: dict, urls: List[str]) -> bool:
    """True when `urls` are exactly the pages of `page_list`: one each,
    a bare entry matching the end of a page's path at a segment boundary,
    an absolute one its host and path."""
    remaining = _list_entries(page_list)
    if len(remaining) != len(urls):
        return False
    for url in urls:
        parts = urlsplit(url)
        for k, (host, path) in enumerate(remaining):
            if (host is None or host == parts.hostname) and (
                    parts.path == path or parts.path.endswith(path)):
                del remaining[k]
                break
        else:
            return False
    return not remaining


def _unpacked_after_reply(page_list: dict, graphql_ends: List[float]) -> bool:
    """True for a list unpacked after the page's first /graphql request
    had finished. A list unpacked with the served page itself is not."""
    unpacked = page_list.get("t")
    return (isinstance(unpacked, (int, float)) and bool(graphql_ends)
            and unpacked >= min(graphql_ends))


def reader_progress(state, chapter_url: str,
                    reply_received: bool) -> Tuple[Optional[List[str]], str]:
    """`(urls, problem)` for one look at the rendered reader.

    `urls` is the chapter's whole page list, in the reader's own order,
    once the site's reply for this chapter has arrived and the reader
    shows exactly a list the site unpacked after its /graphql answer,
    with one image and one counter 1..N per page. The served first pages
    never pass on their own, however complete their counters look: no
    list was unpacked for them. Otherwise `urls` is None.
    """
    state = state if isinstance(state, dict) else {}
    if not reply_received:
        return None, "never received its page list"
    counters = []
    for pair in state.get("counters") or []:
        try:
            counters.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
    totals = sorted({total for _, total in counters})
    if not totals:
        return None, "shows no page total"
    if len(totals) > 1:
        return None, f"shows page totals that disagree ({totals})"
    total = totals[0]

    urls = reader_page_urls(state.get("images") or [], chapter_url)
    if len(set(urls)) != len(urls):
        return None, "shows the same page image twice"
    lists = state.get("lists")
    if not isinstance(lists, list):
        return None, "could not watch its page list being unpacked"
    ends = [t for t in state.get("graphqlEnds") or [] if isinstance(t, (int, float))]
    if lists and not ends:
        return None, "could not time its page list against the site's reply"
    unpacked = [l for l in lists
                if isinstance(l, dict) and _unpacked_after_reply(l, ends)]
    if len(urls) != total:
        return None, f"showed {len(urls)} of {total} pages"
    if sorted(shown for shown, _ in counters) != list(range(1, total + 1)):
        return None, f"does not count its pages 1 to {total}"
    if not unpacked:
        return None, "has not unpacked its page list"
    if not any(list_matches(l, urls) for l in unpacked):
        sizes = sorted({len(l.get("i") or []) for l in unpacked})
        return None, (f"shows {total} pages that are not its page list "
                      f"(unpacked lists of {', '.join(map(str, sizes))} pages)")
    return urls, ""


class _MangaPandaReader(PlaywrightScraper):
    """The MangaHub-network chapter reader in the shared headless browser.

    Not a source of its own: `MangaPandaScraper.get_pages` runs it on this
    class's browser worker, for mangapanda.onl and mangafox.fun alike.
    """

    name = "mangapanda"
    base_url = "https://mangapanda.onl"

    # Look at the reader every 500 ms for up to 40 s. The complete list
    # must then be the same on _STABLE_LOOKS looks in a row.
    _LOOKS = 80
    _LOOK_MS = 500
    _STABLE_LOOKS = 4

    def search(self, query: str) -> List[Manga]:
        raise NotImplementedError

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        raise NotImplementedError

    def get_pages(self, chapter_url: str) -> List[str]:
        raise NotImplementedError

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

    @staticmethod
    def _is_chapter_reply(response, site_host: str, number) -> bool:
        """True for the site's own GraphQL reply with this chapter."""
        try:
            parts = urlsplit(response.url)
            if (response.request.method != "POST" or not response.ok
                    or parts.hostname != site_host or parts.path != "/graphql"):
                return False
            return chapter_reply_matches(response.json(), number)
        except Exception:
            return False

    def _read_pages_in_thread(self, chapter_url: str, site_host: str) -> List[str]:
        _, number = _chapter_of(chapter_url)
        replies = []

        # A plain function: Playwright tags each handler it is given with
        # an attribute, which a built-in such as `replies.append` refuses.
        def keep_reply(response):
            replies.append(response)

        page = self._new_page()
        try:
            page.add_init_script(_PAGE_LIST_OBSERVER)
            page.on("response", keep_reply)
            response = page.goto(chapter_url, wait_until="domcontentloaded",
                                 timeout=step_timeout_ms(45000))
            if response is None or response.status >= 400:
                status = "no response" if response is None else f"HTTP {response.status}"
                raise MangaPandaReaderIncomplete(
                    f"Reader for {chapter_url} did not load ({status})")

            received = False
            checked = 0
            steady, last = 0, None
            problem = "did not load"
            state = {}
            for look in range(1, self._LOOKS + 1):
                state = page.evaluate(_READER_STATE) or {}
                for reply in replies[checked:]:
                    received = received or self._is_chapter_reply(reply, site_host, number)
                checked = len(replies)

                urls, problem = reader_progress(state, chapter_url, received)
                if urls is None:
                    steady, last = 0, None
                else:
                    steady = steady + 1 if urls == last else 1
                    last = urls
                    if steady >= self._STABLE_LOOKS:
                        lists = state.get("lists") or []
                        logger.debug(f"[MangaPanda] reader: {len(urls)} pages after "
                                     f"{look} looks; {len(lists)} page list(s) unpacked")
                        return urls
                    problem = "page list kept changing"
                page.wait_for_timeout(step_timeout_ms(self._LOOK_MS))

            lists = state.get("lists") if isinstance(state, dict) else None
            logger.debug(f"[MangaPanda] reader incomplete: reply received {received}; "
                         f"{len(lists) if isinstance(lists, list) else 0} page list(s) unpacked")
            seconds = self._LOOKS * self._LOOK_MS / 1000
            raise MangaPandaReaderIncomplete(
                f"Reader for {chapter_url} {problem} after {seconds:g}s")
        finally:
            page.close()


class MangaPandaScraper(BaseScraper):
    """Scraper for MangaPanda.onl"""

    name = "mangapanda"
    base_url = "https://mangapanda.onl"
    # Search, chapter lists and page images are plain HTTP, but a
    # chapter's page list is read from the rendered reader in a browser.
    engine = "browser"

    def __init__(self):
        super().__init__()
        self._use_cloudscraper()
        self.session.headers.update({
            "User-Agent": BROWSER_USER_AGENT_SHORT
        })
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={quote_plus(query)}"
        resp = self.session.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        results = []
        seen_urls = set()
        
        # Find all links containing /manga/
        for link in soup.select('a'):
            href = link.get("href", "")
            if not href:
                continue
            if "/manga/" not in href:
                continue
            if "/chapter/" in href:
                continue
            
            title = link.get("title") or link.get_text(strip=True)
            # Skip links without titles (they're usually image-only)
            if not title:
                continue
            
            # Normalize URL for deduplication
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            if full_url in seen_urls:
                continue
            
            # Skip navigation elements
            if title.lower() in ["directory", "popular", "updates", "new", "home", "search"]:
                continue
            
            seen_urls.add(full_url)
            
            # Get cover image
            img = link.find("img")
            cover_url = None
            if img:
                cover_url = img.get("src") or img.get("data-src")
            
            results.append(Manga(
                title=title,
                url=full_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga.

        Only this series' own reader links on this site count: the page
        also links other series' chapters (the "Popular Manga Updates"
        slider), and each chapter row hides extra ``title="Chapter"``
        links addressed by chapter ID rather than number, which would
        list as bogus newest chapters. The number is read from the link's
        path, and each chapter is listed once, named from its row in the
        chapter list when it has one rather than from a reader button.
        """
        from bs4 import BeautifulSoup

        resp = self.session.get(manga_url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        slug_match = _MANGA_SLUG.search(urlsplit(manga_url).path)
        slug = re.escape(slug_match.group(1)) if slug_match else r"[^/]+"
        reader_path = re.compile(rf"/chapter/{slug}/chapter-(\d+(?:\.\d+)?)/?")
        host = urlsplit(self.base_url).hostname

        # number -> (chapter, found in a chapter-list row)
        by_number: Dict[float, Tuple[Chapter, bool]] = {}

        for link in soup.select('a[href*="/chapter/"]'):
            if (link.get("title") or "").strip() == "Chapter":
                continue
            full_url = urljoin(f"{self.base_url}/", link.get("href", ""))
            parts = urlsplit(full_url)
            if parts.hostname != host or parts.query or parts.fragment:
                continue
            match = reader_path.fullmatch(parts.path)
            if not match:
                continue

            chapter_num = match.group(1)
            key = float(chapter_num)
            in_row = link.find_parent("li") is not None
            known = by_number.get(key)
            if known and (known[1] or not in_row):
                continue

            chapter_text = link.get_text(" ", strip=True)
            if not in_row or chapter_text.lower() in _BUTTON_LABELS:
                chapter_text = ""
            by_number[key] = (Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=full_url,
            ), in_row)

        return sorted(chapter for chapter, _ in by_number.values())
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter, in reading order.

        The served reader page lists only its first few pages, with
        counters that already look complete, so the reader is rendered in
        the browser and read once the site's reply for this chapter has
        arrived and the reader shows exactly the page list the site
        unpacked. A reader that never gets there raises
        MangaPandaReaderIncomplete rather than returning a shorter chapter.
        """
        reader = _MangaPandaReader()
        return _MangaPandaReader._run_serialized(
            reader._read_pages_in_thread, chapter_url,
            urlsplit(self.base_url).hostname, timeout=120)
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header.

        A body that is not an image (a block page, an empty reply) is a
        failed page, and an older file at ``path`` is removed rather than
        left behind.
        """
        path = Path(path)
        try:
            headers = {
                "User-Agent": BROWSER_USER_AGENT_SHORT,
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content = response.content
            if not _identifies_as_image(content):
                path.unlink(missing_ok=True)
                logger.debug("Failed to download %s: response body is not an image", url)
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False


class MangaFoxFunScraper(MangaPandaScraper):
    """Scraper for MangaFox.fun (same MangaHub network site as MangaPanda)."""

    name = "mangafoxfun"
    base_url = "https://mangafox.fun"
