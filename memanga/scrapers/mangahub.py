"""
MangaHub scraper
https://mangahub.io

Large manga library with clean interface.
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

# Chapter pages are served from this host only.
_PAGE_HOST = "imgx.mghcdn.com"
_PAGE_FILE = re.compile(r"\d+\.(?:jpe?g|png|webp|gif)", re.I)

# The served reader page already shows its first pages with counters
# that look complete ("1/6" .. "6/6"); the site's own script then loads
# the chapter's page list, unpacks it with JSON.parse into a path prefix
# "p" and the page files "i", and renders the rest. This script, run
# before the site's own, keeps a copy of every such list as it is parsed,
# so the rendered reader can be checked against the list it was given.
_PAGE_LISTS = """
(() => {
    if (window.__memangaPageLists) return;
    const lists = [];
    Object.defineProperty(window, '__memangaPageLists', {value: lists});
    const parse = JSON.parse;
    JSON.parse = function () {
        const value = parse.apply(this, arguments);
        try {
            if (value && typeof value === 'object' && Array.isArray(value.i)
                    && value.i.length
                    && value.i.every((name) => typeof name === 'string')
                    && (value.p === undefined || typeof value.p === 'string')) {
                lists.push({p: value.p || '', i: value.i.slice()});
            }
        } catch (e) {}
        return value;
    };
})();
"""

# The reader's page slots and its "k/N" page counters, in DOM order, and
# the page lists parsed so far. A slot's `src` attribute is read, not
# `currentSrc`: pages further down are loaded lazily, and until then only
# the attribute holds their URL.
_READER_STATE = """
(host) => {
    const onHost = (value) => {
        if (!value) return false;
        try { return new URL(value, location.href).hostname === host; }
        catch (e) { return false; }
    };
    const slots = [];
    for (const img of document.querySelectorAll('img')) {
        const src = img.getAttribute('src') || '';
        if (onHost(src) || onHost(img.getAttribute('data-src'))) slots.push(src);
    }
    const counters = [];
    for (const el of document.body.querySelectorAll('*')) {
        if (el.firstElementChild) continue;
        const text = (el.textContent || '').trim();
        if (/^\\d+\\s*\\/\\s*\\d+$/.test(text)) counters.push(text);
    }
    const lists = (window.__memangaPageLists || []).map((l) => ({p: l.p, i: l.i}));
    return {slots: slots, counters: counters, lists: lists};
}
"""

_CHAPTER_NUMBER = re.compile(r"/chapter-(\d+(?:\.\d+)?)/?$")


class MangaHubReaderIncomplete(TimeoutError):
    """MangaHub's reader did not show every page of a chapter in time."""


def _carries_page_list(response, number: Optional[float]) -> bool:
    """Whether a response is the site's own answer with this chapter's
    page list: a MangaHub GraphQL reply whose ``data.chapter`` carries
    ``pages`` (it is not unpacked here) for the chapter being read."""
    try:
        parts = urlsplit(response.url)
        if (parts.hostname != urlsplit(MangaHubScraper.base_url).hostname
                or not parts.path.endswith("/graphql") or response.status != 200):
            return False
        body = response.json()
    except Exception:
        return False
    data = body.get("data") if isinstance(body, dict) else None
    chapter = data.get("chapter") if isinstance(data, dict) else None
    if not isinstance(chapter, dict) or not isinstance(chapter.get("pages"), str):
        return False
    if not chapter["pages"]:
        return False
    if number is None or chapter.get("number") is None:
        return True
    try:
        return float(chapter["number"]) == number
    except (TypeError, ValueError):
        return False


def _page_list_paths(page_list: dict) -> List[Tuple[Optional[str], str]]:
    """(host, path) of each page in a parsed page list, resolved the way
    the reader resolves them: on the page host unless already a URL."""
    prefix = page_list.get("p") or ""
    paths = []
    for name in page_list.get("i") or []:
        path = f"{prefix}{name}"
        if not path.startswith(("http://", "https://")):
            path = f"https://{_PAGE_HOST}/{path.lstrip('/')}"
        parts = urlsplit(path)
        paths.append((parts.hostname, parts.path))
    return paths


def _reader_pages(state: dict, page_url: str,
                  list_received: bool) -> Tuple[Optional[str], List[str]]:
    """The chapter's page URLs once the reader shows all of them.

    Returns ``(None, urls)`` only after the site's chapter page list has
    arrived, when the reader's counters run 1..N with a single total N,
    it holds N distinct page images, in the reader's own (DOM) order, and
    those are exactly the pages of a page list the site's script parsed.
    A chapter of as few pages as the served page shows is then accepted
    too, while the served page on its own never is. Otherwise returns
    ``(why not, [])``.
    """
    if not list_received:
        return "never received its chapter's page list", []
    counters = []
    for text in state.get("counters") or []:
        shown, _, total = text.partition("/")
        counters.append((int(shown), int(total)))
    totals = sorted({total for _, total in counters})
    if not totals or totals == [0]:
        return "shows no page total", []
    if len(totals) > 1:
        return f"shows page totals that disagree ({totals})", []
    total = totals[0]
    slots = state.get("slots") or []
    if len(slots) != total:
        return f"showed {len(slots)} of {total} pages", []
    if sorted(shown for shown, _ in counters) != list(range(1, total + 1)):
        return f"does not count its pages 1 to {total}", []

    urls: List[str] = []
    for src in slots:
        if not src:
            return "has a page slot without an image URL", []
        url = urljoin(page_url, src)
        parts = urlsplit(url)
        if parts.scheme != "https":
            return f"has a page that is not an https URL ({url})", []
        if parts.hostname != _PAGE_HOST:
            return f"has a page image on another host ({parts.hostname})", []
        if not _PAGE_FILE.fullmatch(parts.path.rsplit("/", 1)[-1]):
            return f"has a page that is not a numbered image ({url})", []
        if url in urls:
            return f"shows page {url} twice", []
        urls.append(url)

    lists = state.get("lists") or []
    if not lists:
        return "has not unpacked its page list", []
    shown = sorted((urlsplit(url).hostname, urlsplit(url).path) for url in urls)
    if not any(sorted(_page_list_paths(page_list)) == shown for page_list in lists):
        sizes = sorted({len(page_list.get("i") or []) for page_list in lists})
        return (f"shows {len(urls)} pages that are not its page list "
                f"(of {', '.join(map(str, sizes))} pages)"), []
    return None, urls


class _MangaHubReader(PlaywrightScraper):
    """MangaHub's chapter reader in the shared headless browser.

    Not a source of its own: `MangaHubScraper.get_pages` runs it on this
    class's browser worker. The served reader page holds only the first
    few pages; the site's own script adds the rest once it has loaded the
    chapter's page list, so the pages are read from the rendered reader,
    and only once it shows that list.
    """

    name = "mangahub"
    base_url = "https://mangahub.io"

    # Poll the rendered reader for up to 40 s for every page.
    _POLLS = 160
    _POLL_MS = 250

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

    def _read_pages_in_thread(self, chapter_url: str) -> List[str]:
        match = _CHAPTER_NUMBER.search(urlsplit(chapter_url).path)
        number = float(match.group(1)) if match else None
        received = []

        def on_response(response):
            if not received and _carries_page_list(response, number):
                received.append(True)

        page = self._new_page()
        try:
            page.add_init_script(_PAGE_LISTS)
            page.on("response", on_response)
            page.goto(chapter_url, wait_until="domcontentloaded",
                      timeout=step_timeout_ms(45000))
            problem = "never received its chapter's page list"
            for poll in range(self._POLLS):
                if poll:
                    page.wait_for_timeout(step_timeout_ms(self._POLL_MS))
                state = page.evaluate(_READER_STATE, _PAGE_HOST) or {}
                problem, urls = _reader_pages(state, page.url or chapter_url,
                                              bool(received))
                if problem is None:
                    return urls
            seconds = self._POLLS * self._POLL_MS / 1000
            raise MangaHubReaderIncomplete(
                f"MangaHub reader for {chapter_url} {problem} after {seconds:g}s")
        finally:
            page.close()


class MangaHubScraper(BaseScraper):
    """Scraper for MangaHub.io"""

    name = "mangahub"
    base_url = "https://mangahub.io"
    # Search, chapter lists and page images are plain HTTP, but a
    # chapter's page list is read from the rendered reader in a browser.
    engine = "browser"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        url = f"{self.base_url}/search?q={quote_plus(query)}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get("href", "")
            
            # Skip chapter links and duplicates
            if not href or "chapter" in href or href in seen_urls:
                continue
            
            # Must be a manga page link
            if not re.match(r'.*/manga/[^/]+$', href):
                continue
                
            seen_urls.add(href)
            
            # Get title from link or parent
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                # Try to find title in parent element
                parent = link.find_parent(class_="media")
                if parent:
                    title_elem = parent.select_one("h4, .media-heading")
                    title = title_elem.get_text(strip=True) if title_elem else ""
            
            if not title:
                # Extract from URL
                title = href.split("/")[-1].replace("-", " ").replace("_", " ").title()
            
            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            
            # Get cover image
            cover_url = None
            parent = link.find_parent(class_="media")
            if parent:
                img = parent.select_one("img")
                if img:
                    cover_url = img.get("data-src") or img.get("src")
            
            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga.

        Only this series' own reader links count: the page also links
        other series' chapters (the "Popular Manga Updates" slider), and
        each chapter row hides extra ``title="Chapter"`` links addressed
        by chapter ID (``chapter-2757061`` for chapter 1195), which would
        list as bogus newest chapters. A chapter is listed once per
        number, named from its row in the chapter list when it has one
        rather than from buttons such as "Start Reading".
        """
        from bs4 import BeautifulSoup

        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")

        slug_match = _MANGA_SLUG.search(urlsplit(manga_url).path)
        slug = re.escape(slug_match.group(1)) if slug_match else r"[^/]+"
        reader_path = re.compile(rf"/chapter/{slug}/chapter-(\d+(?:\.\d+)?)/?")
        host = urlsplit(self.base_url).hostname

        # number -> (chapter, found in a chapter-list row)
        by_number: Dict[str, Tuple[Chapter, bool]] = {}

        for link in soup.select('a[href*="chapter"]'):
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
            in_row = link.find_parent("li") is not None
            known = by_number.get(chapter_num)
            if known and (known[1] or not in_row):
                continue

            chapter_text = link.get_text(strip=True)
            if not in_row or chapter_text.lower() in ("start reading", "read first", "read last"):
                chapter_text = ""
            by_number[chapter_num] = (Chapter(
                number=chapter_num,
                title=chapter_text or f"Chapter {chapter_num}",
                url=full_url,
            ), in_row)

        return sorted((chapter for chapter, _ in by_number.values()),
                      key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter, in reading order.

        The served reader page lists only its first few pages, with
        counters that already look complete, so the reader is rendered in
        the browser and read once the site has loaded the chapter's page
        list and the reader shows exactly that list. A reader that never
        gets there raises MangaHubReaderIncomplete rather than returning a
        shorter chapter.
        """
        reader = _MangaHubReader()
        return _MangaHubReader._run_serialized(
            reader._read_pages_in_thread, chapter_url, timeout=120)
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers.

        A body that is not an image (a block page, an empty reply) is a
        failed page, and an older file at ``path`` is removed rather than
        left behind.
        """
        try:
            headers = {
                "User-Agent": BROWSER_USER_AGENT_SHORT,
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content = response.content
            if not _identifies_as_image(content):
                Path(path).unlink(missing_ok=True)
                logger.debug("Failed to download %s: response body is not an image", url)
                return False
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False
