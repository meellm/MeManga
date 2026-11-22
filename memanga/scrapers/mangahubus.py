"""
MangaHub.us scraper
https://mangahub.us

Part of the MangaHub network (same as mangapanda.onl, mangafox.fun).
Search and chapter lists are read from the served HTML through
cloudscraper. A chapter's pages are read from the rendered reader: the
served chapter page shows only its first pages, with counters that look
complete ("1/6" .. "6/6"), and the site's own script fetches the
chapter's page list from its /graphql, decrypts it in the browser and
renders the rest.
"""

import logging
import re
from typing import Dict, List, Tuple
from urllib.parse import quote_plus, urljoin, urlsplit
from pathlib import Path

import requests

from .base import (BaseScraper, Chapter, Manga, BROWSER_USER_AGENT_SHORT,
                   _identifies_as_image)
from .playwright_base import PlaywrightScraper, step_timeout_ms

logger = logging.getLogger(__name__)

_HOST = "mangahub.us"
_GRAPHQL_PATH = "/graphql"
# Chapter page images are served from this host only.
_PAGE_HOST = "imgx.mghcdn.com"
_PAGE_FILE = re.compile(r"\d+\.(?:jpe?g|png|webp|gif|avif)", re.I)
_MANGA_SLUG = re.compile(r"/manga/([^/?#]+)")
_CHAPTER_NUMBER = re.compile(r"/chapter-(\d+(?:\.\d+)?)/?$")
_NAV_TITLES = ("directory", "popular", "updates", "new", "home", "search")


class MangaHubUsSourceError(RuntimeError):
    """mangahub.us did not serve what was asked for: an HTTP error, no
    response, a Cloudflare challenge, or a reader that never showed a
    chapter's complete page list."""


def _failure(error: BaseException) -> str:
    """A short description of a failed request, without its body."""
    response = getattr(error, "response", None)
    if response is not None:
        mitigated = response.headers.get("cf-mitigated")
        return f"HTTP {response.status_code}" + (
            f", cf-mitigated: {mitigated}" if mitigated else "")
    return type(error).__name__


def _is_challenge(response) -> bool:
    """True for a Cloudflare challenge served with a success status."""
    if (response.headers.get("cf-mitigated") or "").lower() == "challenge":
        return True
    return "<title>just a moment" in (response.text or "")[:4000].lower()


# The reader. This script runs before the site's own and keeps a copy of
# each page list as the site unpacks it with JSON.parse (a path prefix
# "p" and page files "i"), stamped with the wall-clock time it was
# unpacked, so it can be held against the moment this chapter's own
# GraphQL reply finished arriving. It decrypts nothing and sends nothing.
_PAGE_LIST_OBSERVER = """
(() => {
    if (window.__mangahubUsReader) return;
    const seen = {lists: []};
    Object.defineProperty(window, '__mangahubUsReader', {value: seen});
    const nativeParse = JSON.parse;
    const isPageList = (v) => v !== null && typeof v === 'object'
        && Array.isArray(v.i) && v.i.length > 0
        && v.i.every((name) => typeof name === 'string')
        && (v.p === undefined || v.p === null || typeof v.p === 'string');
    JSON.parse = function (text, reviver) {
        const value = nativeParse.call(this, text, reviver);
        try {
            if (isPageList(value) && seen.lists.length < 50) {
                seen.lists.push({p: value.p || '', i: value.i.slice(0, 5000),
                                 te: performance.timeOrigin + performance.now()});
            }
        } catch (e) {}
        return value;
    };
})();
"""

# One look at the reader: the "k/N" counters, every image's raw `src`
# attribute in document order (an image without one reads as ""), and
# the page lists unpacked so far.
_READER_STATE = """
() => {
    const counters = [];
    for (const el of (document.body ? document.body.querySelectorAll('*') : [])) {
        if (el.firstElementChild) continue;
        const m = /^\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*$/.exec(el.textContent || '');
        if (m) counters.push([parseInt(m[1], 10), parseInt(m[2], 10)]);
    }
    const images = [];
    for (const img of document.images) {
        images.push(img.getAttribute('src') || '');
    }
    const seen = window.__mangahubUsReader;
    const lists = seen ? seen.lists.map((l) => ({p: l.p, i: l.i.slice(), te: l.te})) : null;
    return {counters, images, lists};
}
"""


def _same_number(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def page_list_reply(payload, number) -> bool:
    """True when a GraphQL reply carries the page list of chapter `number`."""
    data = payload.get("data") if isinstance(payload, dict) else None
    chapter = data.get("chapter") if isinstance(data, dict) else None
    if not isinstance(chapter, dict):
        return False
    pages = chapter.get("pages")
    if not (isinstance(pages, str) and pages.strip()):
        return False
    return _same_number(chapter.get("number"), number)


def page_list_paths(page_list: dict) -> List[Tuple[str, str]]:
    """`(host, path)` of each page of an unpacked page list, resolved the
    way the reader resolves them: on the page host unless already a URL."""
    prefix = page_list.get("p") or ""
    paths = []
    for name in page_list.get("i") or []:
        url = f"{prefix}{name}"
        if not url.startswith(("http://", "https://")):
            url = f"https://{_PAGE_HOST}/{url.lstrip('/')}"
        parts = urlsplit(url)
        paths.append(((parts.hostname or "").lower(), parts.path))
    return paths


def page_folder(src: str):
    """The folder of a chapter page image URL, or None.

    A page is a raw ``https://imgx.mghcdn.com/<folder>/<n>.<ext>`` URL:
    exactly that host (no port or login), no query or fragment, and a
    numbered image file.
    """
    parts = urlsplit(src or "")
    if parts.scheme != "https" or parts.netloc != _PAGE_HOST:
        return None
    if parts.query or parts.fragment:
        return None
    folder, _, name = parts.path.rpartition("/")
    if not folder or not _PAGE_FILE.fullmatch(name):
        return None
    return folder


def served_folder(html: str):
    """The one page folder of the chapter's served reader page, or None
    when it shows no page image or pages from more than one folder."""
    from bs4 import BeautifulSoup

    folders = set()
    for img in BeautifulSoup(html or "", "html.parser").find_all("img"):
        folder = page_folder(img.get("src") or "")
        if folder:
            folders.add(folder)
    return folders.pop() if len(folders) == 1 else None


def reply_end(response):
    """Wall-clock time (ms) the reply to `response`'s request finished
    arriving, or None while the browser has not timed it."""
    try:
        timing = response.request.timing
        start, end = timing.get("startTime"), timing.get("responseEnd")
    except Exception:
        return None
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    if start <= 0 or end < 0:
        return None
    return start + end


def reader_progress(state, received: bool, reply_ends: List[float], folder: str):
    """`(urls, problem)` for one look at the rendered reader.

    `urls` is the whole chapter in the reader's own order, and `problem`
    None, once this chapter's own GraphQL reply has arrived (`received`)
    and been timed (`reply_ends`), and the reader shows exactly, and in
    order, the pages of a list the site unpacked after that reply
    finished arriving: one raw page image URL per page (see
    `page_folder`), all in `folder`, the served page's own page folder,
    and one counter each, running 1..N under a single total N. The served
    first pages never pass on their own: no list was unpacked for them
    after the reply. Otherwise `urls` is None and `problem` says what is
    missing.
    """
    state = state if isinstance(state, dict) else {}
    if not received:
        return None, "never received its chapter's page list"
    if not reply_ends:
        return None, "has no timing for its chapter's page list reply"
    counters = []
    for pair in state.get("counters") or []:
        try:
            counters.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
    totals = sorted({total for _, total in counters})
    if not totals or totals == [0]:
        return None, "shows no page total"
    if len(totals) > 1:
        return None, f"shows page totals that disagree ({totals})"
    total = totals[0]

    # Every image on the page host is a page slot; one that is not a raw
    # page URL then fails below rather than being left out.
    slots = []
    for src in state.get("images") or []:
        if (urlsplit(src or "").hostname or "").lower() == _PAGE_HOST:
            slots.append(src)
    if len(slots) != total:
        return None, f"showed {len(slots)} of {total} pages"
    if sorted(shown for shown, _ in counters) != list(range(1, total + 1)):
        return None, f"does not count its pages 1 to {total}"

    urls: List[str] = []
    for src in slots:
        page = page_folder(src)
        if page is None:
            return None, "has a page that is not a plain https page image URL"
        if page != folder:
            return None, "shows a page outside its served page folder"
        if src in urls:
            return None, "shows a page twice"
        urls.append(src)

    lists = state.get("lists")
    if not isinstance(lists, list):
        return None, "could not watch its page list being unpacked"
    replied = min(reply_ends)
    unpacked = [l for l in lists if isinstance(l, dict)
                and isinstance(l.get("te"), (int, float)) and l["te"] >= replied]
    if not unpacked:
        return None, "has not unpacked its page list since its reply"
    shown = [(_PAGE_HOST, urlsplit(src).path) for src in urls]
    if not any(page_list_paths(l) == shown for l in unpacked):
        sizes = sorted({len(l.get("i") or []) for l in unpacked})
        return None, (f"shows {total} pages that are not, in order, its page list "
                      f"(unpacked lists of {', '.join(map(str, sizes))} pages)")
    return urls, None


class _MangaHubUsReader(PlaywrightScraper):
    """MangaHub.us's chapter reader in the shared headless browser.

    Not a source of its own: `MangaHubUsScraper.get_pages` runs it on
    this class's browser worker.
    """

    name = "mangahubus"
    base_url = f"https://{_HOST}"

    # The reader is watched for up to _POLLS looks, _POLL_MS apart (30 s);
    # a 12-page chapter showed every page about 7 s after the page loaded.
    # The complete list must then be the same on _STABLE_POLLS looks in a
    # row (1.5 s apart at the ends).
    _POLL_MS = 500
    _POLLS = 60
    _STABLE_POLLS = 4

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
    def _is_page_list_reply(response, number) -> bool:
        """True for the site's own GraphQL reply carrying the page list
        of chapter `number`."""
        try:
            parts = urlsplit(response.url)
            if (response.request.method != "POST" or not response.ok
                    or (parts.hostname or "").lower() != _HOST
                    or parts.path != _GRAPHQL_PATH):
                return False
            return page_list_reply(response.json(), number)
        except Exception:
            return False

    def _read_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Every page image URL of a chapter, from the rendered reader.

        The page is loaded once, with the page-list observer in place. The
        served page must show this chapter's first pages in one folder;
        the reader is then read until it shows a complete list in that
        folder, unpacked after this chapter's own GraphQL reply finished
        arriving (as the browser timed that reply's request), and that
        list stays the same for a few looks (see `reader_progress`).
        Anything short of that raises MangaHubUsSourceError; a partial
        list is never returned.
        """
        match = _CHAPTER_NUMBER.search(urlsplit(chapter_url).path)
        if not match:
            raise ValueError(f"Not a MangaHub.us chapter URL: {chapter_url}")
        number = match.group(1)
        page = self._new_page()
        replies = []

        # A plain function: Playwright tags each handler it is given with
        # an attribute, which a built-in such as `replies.append` refuses.
        def keep_reply(response):
            replies.append(response)

        try:
            page.add_init_script(_PAGE_LIST_OBSERVER)
            page.on("response", keep_reply)
            served = page.goto(chapter_url, wait_until="domcontentloaded",
                               timeout=step_timeout_ms(45000))
            if served is None or served.status >= 400:
                status = "no response" if served is None else f"HTTP {served.status}"
                raise MangaHubUsSourceError(
                    f"MangaHub.us reader for {chapter_url} did not load ({status})")
            try:
                folder = served_folder(served.text())
            except Exception as e:
                raise MangaHubUsSourceError(
                    f"MangaHub.us reader for {chapter_url} served no readable page "
                    f"({type(e).__name__})") from None
            if folder is None:
                raise MangaHubUsSourceError(
                    f"MangaHub.us reader for {chapter_url} served no single page folder")

            own_replies = []
            checked = 0
            steady, last = 0, None
            problem = "did not load"
            state = {}
            for _look in range(self._POLLS):
                landed = urlsplit(page.url or "")
                if ((landed.hostname or "").lower() != _HOST
                        or landed.path.rstrip("/") != urlsplit(chapter_url).path.rstrip("/")):
                    raise MangaHubUsSourceError(
                        f"MangaHub.us reader for {chapter_url} left the chapter page")
                state = page.evaluate(_READER_STATE)
                for reply in replies[checked:]:
                    if self._is_page_list_reply(reply, number):
                        own_replies.append(reply)
                checked = len(replies)
                # Read afresh on every look: the browser times a reply
                # only once its last byte has arrived.
                ends = [end for end in map(reply_end, own_replies) if end is not None]

                urls, problem = reader_progress(state, bool(own_replies), ends, folder)
                if urls is None:
                    steady, last = 0, None
                else:
                    steady = steady + 1 if urls == last else 1
                    last = urls
                    if steady >= self._STABLE_POLLS:
                        lists = state.get("lists") if isinstance(state, dict) else None
                        logger.debug(
                            "[MangaHubUs] reader: %d pages; %d page list(s) unpacked",
                            len(urls), len(lists) if isinstance(lists, list) else 0)
                        return urls
                    problem = "page list kept changing"
                page.wait_for_timeout(step_timeout_ms(self._POLL_MS))

            waited = self._POLLS * self._POLL_MS / 1000
            raise MangaHubUsSourceError(
                f"MangaHub.us reader for {chapter_url} {problem} (waited {waited:g}s)")
        finally:
            page.close()


class MangaHubUsScraper(BaseScraper):
    """Scraper for MangaHub.us"""

    name = "mangahubus"
    base_url = f"https://{_HOST}"
    # Search and chapter lists are plain HTTP, but a chapter's page list
    # is read from the rendered reader in a browser.
    engine = "browser"

    def __init__(self):
        super().__init__()
        self._use_cloudscraper()
        self.session.headers.update({
            "User-Agent": BROWSER_USER_AGENT_SHORT
        })

    def _get_html(self, url: str) -> str:
        """The served page at `url`; a page the site did not serve raises
        MangaHubUsSourceError rather than reading as an empty one."""
        try:
            response = self._request(url)
        except requests.RequestException as e:
            raise MangaHubUsSourceError(
                f"MangaHub.us did not serve {url} ({_failure(e)})") from e
        if _is_challenge(response):
            raise MangaHubUsSourceError(
                f"MangaHub.us answered {url} with a Cloudflare challenge")
        return response.text

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title.

        A card links its series twice, cover first; a link is only
        counted once it gives a title, so a cover link without one does
        not hide the titled link that follows it.
        """
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/search?q={quote_plus(query)}"
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        results = []
        seen = set()
        covers: Dict[str, str] = {}

        for link in soup.select('a'):
            href = link.get("href", "")
            if not href or "/manga/" not in href or "/chapter/" in href:
                continue
            if href in seen:
                continue

            img = link.find("img")
            cover_url = (img.get("src") or img.get("data-src")) if img else None

            title = link.get("title") or link.get_text(strip=True)
            if not title or title.lower() in _NAV_TITLES:
                if cover_url and href not in covers:
                    covers[href] = cover_url
                continue
            seen.add(href)

            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            results.append(Manga(
                title=title,
                url=full_url,
                cover_url=cover_url or covers.get(href),
            ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga.

        Only this series' own reader links count: the page also links
        other series' chapters (the "Popular Manga Updates" slider), and
        each chapter row carries an extra ``title="Chapter"`` link
        addressed by chapter ID rather than number, which would list as
        bogus chapters. A chapter is listed once per number, read from
        its URL; rows the page keeps collapsed are listed too.
        """
        from bs4 import BeautifulSoup

        slug_match = _MANGA_SLUG.search(urlsplit(manga_url).path)
        if not slug_match:
            raise ValueError(f"Not a MangaHub.us manga URL: {manga_url}")
        reader_path = re.compile(
            rf"/chapter/{re.escape(slug_match.group(1))}/chapter-(\d+(?:\.\d+)?)/?")

        soup = BeautifulSoup(self._get_html(manga_url), "html.parser")

        # number -> (chapter, found in a chapter-list row)
        by_number: Dict[str, Tuple[Chapter, bool]] = {}

        for link in soup.select('a[href*="/chapter/"]'):
            if (link.get("title") or "").strip() == "Chapter":
                continue
            full_url = urljoin(f"{self.base_url}/", link.get("href", ""))
            parts = urlsplit(full_url)
            if (parts.hostname or "").lower() != _HOST or parts.query or parts.fragment:
                continue
            match = reader_path.fullmatch(parts.path)
            if not match:
                continue

            number = match.group(1)
            in_row = link.find_parent("li") is not None
            known = by_number.get(number)
            if known and (known[1] or not in_row):
                continue

            text = link.get_text(strip=True) if in_row else ""
            if text.lower() in ("start reading", "read first", "read last"):
                text = ""
            by_number[number] = (Chapter(
                number=number,
                title=text or f"Chapter {number}",
                url=full_url,
            ), in_row)

        return sorted((chapter for chapter, _ in by_number.values()),
                      key=lambda c: c.numeric)

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter, in reading order.

        Read from the rendered reader once it shows the chapter's whole
        page list; a reader that never gets there raises
        MangaHubUsSourceError rather than returning a shorter chapter.
        """
        reader = _MangaHubUsReader()
        return _MangaHubUsReader._run_serialized(
            reader._read_pages_in_thread, chapter_url, timeout=120)

    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header.

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
