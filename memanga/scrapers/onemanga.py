"""
1Manga.co Scraper

Large manga library with simple HTTP access.
Uses MangaHub CDN for images.
"""

import re
import logging
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

from .base import (BaseScraper, Chapter, Manga, BROWSER_USER_AGENT_SHORT,
                   _identifies_as_image)
from .playwright_base import PlaywrightScraper, step_timeout_ms

logger = logging.getLogger(__name__)

_SERIES_SLUG = re.compile(r"/manga/([^/?#]+)")
# A chapter page: /chapter/<series>/chapter-<number>, the number as the
# site writes it ("87", "76.5").
_CHAPTER_IN_URL = re.compile(r"/chapter/[^/]+/chapter-(\d+(?:\.\d+)?)/?$")

# Chapter page images are served from this host, under a
# "<series folder>/<chapter>/" folder. The series folder is the CDN's own
# name for the series ("moriarty-the-patriot" for /manga/yukoku-no-moriarty),
# so it is taken from the chapter page's own served images, not the URL.
_PAGE_HOST = "imgx.mghcdn.com"
_NUMBERED_IMAGE = re.compile(r"\d+\.(?:jpe?g|png|webp|gif)", re.I)
_SERVED_PAGE_IMAGE = re.compile(
    r"https://imgx\.mghcdn\.com/([^/\"'\s?#]+)/([^/\"'\s?#]+)/\d+\.(?:jpe?g|png|webp|gif)",
    re.I)

# Runs before the site's own scripts. The reader unpacks the chapter's
# page list with JSON.parse into an object holding a path prefix "p" and
# the page files "i"; a copy of each such list is kept, with the time it
# was unpacked (epoch ms), for the checks below. The value the site gets
# back is unchanged.
_PAGE_LIST_RECORDER = """
(() => {
    if (window.__onemangaPageLists) return;
    const seen = [];
    Object.defineProperty(window, '__onemangaPageLists', {value: seen});
    const originalParse = JSON.parse;
    JSON.parse = function () {
        const parsed = originalParse.apply(this, arguments);
        try {
            if (parsed && typeof parsed === 'object' && Array.isArray(parsed.i)
                    && parsed.i.length > 0
                    && parsed.i.every((file) => typeof file === 'string')
                    && (parsed.p === undefined || typeof parsed.p === 'string')) {
                seen.push({p: parsed.p || '', i: parsed.i.slice(),
                           t: performance.timeOrigin + performance.now()});
            }
        } catch (e) {}
        return parsed;
    };
})();
"""

# What the rendered reader shows: its page slots in DOM order (the raw
# `src` attribute, which lazily loaded pages already carry before their
# image loads), its "k/N" page counters, the page lists unpacked so far,
# and whether the recorder above is running at all.
_READER_SNAPSHOT = """
(host) => {
    const onPageHost = (value) => {
        if (!value) return false;
        try { return new URL(value, location.href).hostname === host; }
        catch (e) { return false; }
    };
    const slots = [];
    for (const img of document.querySelectorAll('img')) {
        const src = img.getAttribute('src') || '';
        if (onPageHost(src) || onPageHost(img.getAttribute('data-src'))) slots.push(src);
    }
    const counters = [];
    for (const el of document.body.querySelectorAll('*')) {
        if (el.firstElementChild) continue;
        const text = (el.textContent || '').trim();
        if (/^\\d+\\s*\\/\\s*\\d+$/.test(text)) counters.push(text);
    }
    const recorded = window.__onemangaPageLists;
    const lists = Array.isArray(recorded)
        ? recorded.map((l) => ({p: l.p, i: l.i, t: l.t})) : [];
    return {slots: slots, counters: counters, lists: lists,
            recorder: Array.isArray(recorded)};
}
"""


class OneMangaReaderError(TimeoutError):
    """The 1Manga reader did not deliver a chapter's page list.

    A TimeoutError, so a probe reports it as the source failing."""


class OneMangaReaderIncomplete(OneMangaReaderError):
    """The 1Manga reader did not show a chapter's whole page list in time."""


def _chapter_in_url(chapter_url: str) -> Optional[str]:
    """The chapter number as the chapter URL writes it ("87", "76.5")."""
    match = _CHAPTER_IN_URL.search(urlsplit(chapter_url).path)
    return match.group(1) if match else None


def _served_page_folder(html: str, chapter: str) -> Optional[str]:
    """The "<series folder>/<chapter>" folder of the page images the
    chapter page itself serves, when they all share one; else None."""
    folders = {f"{series}/{folder}"
               for series, folder in _SERVED_PAGE_IMAGE.findall(html or "")
               if folder == chapter}
    return folders.pop() if len(folders) == 1 else None


def _is_own_reply(response, chapter: str) -> bool:
    """Whether a response is this chapter's own page-list reply: the
    site's GraphQL POST to https://1manga.co/graphql, answered 200, whose
    ``data.chapter`` carries a non-empty ``pages`` (left packed) and the
    number of this chapter."""
    try:
        parts = urlsplit(response.url)
        if (parts.scheme != "https"
                or parts.hostname != urlsplit(OneMangaScraper.base_url).hostname
                or parts.path != "/graphql"
                or response.status != 200
                or response.request.method != "POST"):
            return False
        body = response.json()
    except Exception:
        return False
    data = body.get("data") if isinstance(body, dict) else None
    reply = data.get("chapter") if isinstance(data, dict) else None
    if not isinstance(reply, dict):
        return False
    pages = reply.get("pages")
    if not isinstance(pages, str) or not pages:
        return False
    try:
        return float(reply["number"]) == float(chapter)
    except (KeyError, TypeError, ValueError):
        return False


def _reply_end(request) -> Optional[float]:
    """When a reply's last byte was received (epoch ms), from its
    request's timing as it stands now; None while that is not known.

    The browser fills in ``responseEnd`` (-1 until then) once the request
    has finished, so it is read afresh on each look rather than waited
    for. A failed request has no usable end.
    """
    try:
        if request.failure:
            return None
        timing = request.timing
        start = timing.get("startTime")
        received = timing.get("responseEnd")
    except Exception:
        return None
    if (not _is_number(start) or not _is_number(received)
            or start <= 0 or received < 0):
        return None
    return float(start) + float(received)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolved_list(page_list: dict) -> List[Tuple[Optional[str], str]]:
    """(host, path) of each entry of a parsed page list, in list order:
    "p" + file on the page host, unless the entry is already a URL."""
    prefix = page_list.get("p") or ""
    resolved = []
    for name in page_list.get("i") or []:
        target = f"{prefix}{name}"
        if not target.startswith(("http://", "https://")):
            target = f"https://{_PAGE_HOST}/{target.lstrip('/')}"
        parts = urlsplit(target)
        resolved.append((parts.hostname, parts.path))
    return resolved


def _own_page_image(src: str, folder: str) -> bool:
    """Whether a raw slot ``src`` is, exactly, a numbered page image
    ``https://imgx.mghcdn.com/<folder>/<n>.<ext>`` of this chapter's own
    folder: absolute, no port, login, query or fragment."""
    if not src.startswith("https://"):
        return False
    parts = urlsplit(src)
    directory, _, name = parts.path.rpartition("/")
    return (parts.netloc == _PAGE_HOST
            and not parts.query and not parts.fragment
            and directory == f"/{folder}"
            and bool(_NUMBERED_IMAGE.fullmatch(name)))


def _complete_pages(snapshot: dict, folder: str,
                    reply_ends: List[Optional[float]]
                    ) -> Tuple[Optional[str], List[str], Optional[float]]:
    """``(None, urls, margin)`` once the reader shows exactly the page
    list the site gave it for this chapter, else ``(why not, [], None)``;
    ``margin`` is how long (ms) after the reply that list was unpacked.

    Complete means: this chapter's own page-list reply has arrived, with
    its timing; the counters run 1..N with one total N; there are N
    distinct slots, each exactly a numbered image in this chapter's own
    folder on the page host; and those slots, in order, are exactly one
    page list the site's script unpacked no earlier than that reply
    ended. The served page's first pages and counters ("1/6" .. "6/6")
    look complete on their own, so neither the counters nor the slots
    alone are ever enough, and neither is a list unpacked before the
    reply or one whose unpacking time is unknown.
    """
    def refused(why: str):
        return why, [], None

    if not reply_ends:
        return refused("never received its chapter's page list")
    timed = [end for end in reply_ends if end is not None]
    if not timed:
        return refused("has no timing for its chapter's page-list reply")
    reply_end = min(timed)
    if snapshot.get("recorder") is not True:
        return refused("has no page-list recorder running")
    counters = []
    for text in snapshot.get("counters") or []:
        shown, _, total = text.partition("/")
        counters.append((int(shown), int(total)))
    totals = sorted({total for _, total in counters})
    if not totals or totals == [0]:
        return refused("shows no page total")
    if len(totals) > 1:
        return refused(f"shows page totals that disagree ({totals})")
    total = totals[0]
    slots = snapshot.get("slots") or []
    if len(slots) != total:
        return refused(f"showed {len(slots)} of {total} pages")
    if sorted(shown for shown, _ in counters) != list(range(1, total + 1)):
        return refused(f"does not count its pages 1 to {total}")

    urls: List[str] = []
    for src in slots:
        if not src:
            return refused("has a page slot without an image URL")
        if not isinstance(src, str) or not _own_page_image(src, folder):
            return refused(f"has a page that is not an image of its folder {folder} ({src})")
        if src in urls:
            return refused(f"shows page {src} twice")
        urls.append(src)

    lists = snapshot.get("lists") or []
    if not lists:
        return refused("has not unpacked its page list")
    fresh = [page_list for page_list in lists
             if _is_number(page_list.get("t")) and page_list["t"] >= reply_end]
    if not fresh:
        return refused("has not unpacked a page list since its chapter's reply")
    shown = [(urlsplit(url).hostname, urlsplit(url).path) for url in urls]
    for page_list in fresh:
        if _resolved_list(page_list) == shown:
            return None, urls, page_list["t"] - reply_end
    sizes = sorted({len(page_list.get("i") or []) for page_list in fresh})
    return refused(f"shows {len(urls)} pages that are not its page list "
                   f"(of {', '.join(map(str, sizes))} pages)")


class _OneMangaReader(PlaywrightScraper):
    """The 1Manga chapter reader in the shared headless browser.

    Not a source of its own: ``OneMangaScraper.get_pages`` runs it on
    this class's browser worker. The served chapter page holds only its
    first few pages; the site's script adds the rest from the chapter's
    page list, so the pages are read from the rendered reader once it
    shows that whole list.
    """

    name = "1manga.co"
    base_url = "https://1manga.co"

    # Up to 60 s for the whole list: a 41-page chapter took about 20 s
    # to render every slot. A complete state must hold on two polls in
    # a row before it is returned.
    _POLLS = 120
    _POLL_MS = 500

    # Titles of a browser check page served in place of the chapter.
    _CHALLENGE_TITLES = ("just a moment", "attention required")

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

    def _chapter_page_folder(self, page, response, chapter_url: str,
                             chapter: str) -> str:
        """This chapter's own image folder, from the chapter page the
        site served; raises at once when that page is not the chapter."""
        if response is None:
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} gave no response")
        if not 200 <= response.status < 300:
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} answered HTTP {response.status}")
        title = (page.title() or "").strip().lower()
        if title.startswith(self._CHALLENGE_TITLES):
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} is a browser check page")
        served = urlsplit(response.url or "")
        if (served.hostname != urlsplit(self.base_url).hostname
                or _chapter_in_url(response.url) != chapter):
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} was served as {response.url}")
        try:
            html = response.text()
        except Exception as e:
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} could not be read: {e}") from e
        folder = _served_page_folder(html, chapter)
        if folder is None:
            raise OneMangaReaderError(
                f"1Manga chapter page {chapter_url} serves no page images "
                f"of one chapter {chapter} folder")
        return folder

    def _read_pages_in_thread(self, chapter_url: str) -> List[str]:
        parts = urlsplit(chapter_url)
        chapter = _chapter_in_url(chapter_url)
        if (parts.scheme != "https" or chapter is None
                or parts.hostname != urlsplit(self.base_url).hostname):
            raise ValueError(f"Not a 1Manga chapter URL: {chapter_url}")
        # The requests of this chapter's own page-list replies; when each
        # ended is read from its timing on every look.
        own_requests = []

        def on_response(response):
            try:
                if _is_own_reply(response, chapter):
                    own_requests.append(response.request)
            except Exception:
                return

        page = self._new_page()
        try:
            page.add_init_script(_PAGE_LIST_RECORDER)
            page.on("response", on_response)
            response = page.goto(chapter_url, wait_until="domcontentloaded",
                                 timeout=step_timeout_ms(45000))
            folder = self._chapter_page_folder(page, response, chapter_url, chapter)
            problem = "never received its chapter's page list"
            previous = None
            for poll in range(self._POLLS):
                if poll:
                    page.wait_for_timeout(step_timeout_ms(self._POLL_MS))
                snapshot = page.evaluate(_READER_SNAPSHOT, _PAGE_HOST) or {}
                if snapshot.get("recorder") is not True:
                    # The recorder runs before any of the page's scripts,
                    # so it is either there from the start or not at all.
                    raise OneMangaReaderError(
                        f"1Manga reader for {chapter_url} has no page-list "
                        f"recorder running")
                reply_ends = [_reply_end(request) for request in own_requests]
                problem, urls, margin = _complete_pages(snapshot, folder, reply_ends)
                if problem is None:
                    if urls == previous:
                        logger.debug("1Manga: %d-page list unpacked %.0f ms after its reply",
                                     len(urls), margin)
                        return urls
                    problem = "had not yet shown the same pages twice"
                previous = urls or None
            seconds = self._POLLS * self._POLL_MS / 1000
            raise OneMangaReaderIncomplete(
                f"1Manga reader for {chapter_url} {problem} after {seconds:g}s")
        finally:
            page.close()


class OneMangaScraper(BaseScraper):
    """Scraper for 1manga.co"""
    
    name = "1manga.co"
    base_url = "https://1manga.co"
    # Search, chapter lists and page images are plain HTTP, but a
    # chapter's page list is read from the rendered reader in a browser.
    engine = "browser"

    def __init__(self):
        super().__init__()
        self._use_cloudscraper()
        self.session.headers.update({
            "User-Agent": BROWSER_USER_AGENT_SHORT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": self.base_url
        })
        self._rate_limit = 0.5  # Faster rate limit for this site
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/search?keyword={quote_plus(query)}"

        # A failed request raises: an empty result would read as "no
        # matches" when the site was never searched.
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        
        # Find manga links in search results (prefer links with text from media-heading)
        seen_urls = set()
        manga_data = {}  # url -> (title, cover)
        
        manga_links = soup.find_all("a", href=lambda x: x and "/manga/" in x)
        
        for link in manga_links:
            href = link.get("href", "")
            if not href:
                continue
            
            # Skip navigation links
            if href.endswith("/manga/") or "/manga-" in href or href.count("/") < 3:
                continue
            
            manga_url = href if href.startswith("http") else urljoin(self.base_url, href)
            
            # Get title from link text
            title = link.get_text(strip=True)
            
            # Get cover image from link or nearby
            cover = None
            img = link.find("img")
            if img:
                cover = img.get("src") or img.get("data-src")
            
            # Only add if we have a title, or update if this one has a better title
            if manga_url in manga_data:
                existing_title, existing_cover = manga_data[manga_url]
                if title and len(title) > len(existing_title):
                    manga_data[manga_url] = (title, cover or existing_cover)
                elif cover and not existing_cover:
                    manga_data[manga_url] = (existing_title, cover)
            else:
                manga_data[manga_url] = (title, cover)
        
        # Convert to Manga objects (only those with titles)
        results = []
        for url, (title, cover) in manga_data.items():
            if title and len(title) >= 2:
                results.append(Manga(
                    title=title,
                    url=url,
                    cover_url=cover
                ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga, newest first.

        Only this series' own visible chapter links count, numbered from
        their URL. The series page also links other series' chapters
        (an updates slider) and, in each chapter row, hidden
        ``title="Chapter"`` links addressed by chapter ID
        (``chapter-2680037``) whose text repeats the row's label; those
        are skipped. Each number is listed once, from its chapter-list
        row when it has one. A failed request raises.
        """
        response = self.session.get(manga_url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        slug_match = _SERIES_SLUG.search(urlsplit(manga_url).path)
        if not slug_match:
            raise ValueError(f"Not a 1Manga series URL: {manga_url}")
        slug = slug_match.group(1)
        series_prefix = f"/chapter/{slug}/"
        own_chapter = re.compile(
            rf"/chapter/{re.escape(slug)}/chapter-(\d+(?:\.\d+)?)/?")
        host = urlsplit(self.base_url).hostname

        # number -> (chapter, from a chapter-list row)
        by_number: Dict[float, Tuple[Chapter, bool]] = {}
        unmatched = 0
        for link in soup.find_all("a", href=True):
            if (link.get("title") or "").strip() == "Chapter":
                continue
            url = urljoin(f"{self.base_url}/", link["href"])
            parts = urlsplit(url)
            if parts.hostname != host or parts.query or parts.fragment:
                continue
            if not parts.path.startswith(series_prefix):
                continue
            match = own_chapter.fullmatch(parts.path)
            if not match:
                unmatched += 1
                continue

            # Labels keep the form this source has always used ("87.0").
            chapter_num = float(match.group(1))
            in_row = link.find_parent("li") is not None
            known = by_number.get(chapter_num)
            if known and (known[1] or not in_row):
                continue

            text = link.get_text(strip=True) if in_row else ""
            title = text
            label = f"#{match.group(1)}-"
            if title.startswith(label):
                title = title[len(label):].strip()
            by_number[chapter_num] = (Chapter(
                number=str(chapter_num),
                title=title or f"Chapter {chapter_num}",
                url=url,
            ), in_row)

        if unmatched:
            logger.warning("1Manga: %d chapter link(s) of %s have an "
                           "unrecognised chapter path and were not listed",
                           unmatched, manga_url)
        return sorted((chapter for chapter, _ in by_number.values()),
                      key=lambda c: c.numeric, reverse=True)

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get image URLs for a chapter, in reading order.

        The served chapter page holds only its first pages, with
        counters that already look complete. The reader is therefore
        rendered in the browser and read once the site has loaded this
        chapter's page list and shows exactly that list.
        OneMangaReaderError is raised at once when the chapter page is
        not served (no response, an HTTP error, a browser check page,
        no page images of its own), and OneMangaReaderIncomplete when
        the whole list is not shown in time, rather than returning a
        shorter chapter.
        """
        reader = _OneMangaReader()
        return _OneMangaReader._run_serialized(
            reader._read_pages_in_thread, chapter_url, timeout=150)
    
    def download_image(self, url: str, path: Path) -> bool:
        """Download an image with proper headers."""
        headers = {
            "User-Agent": BROWSER_USER_AGENT_SHORT,
            "Referer": self.base_url,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # A body that is not an image (a block page, an empty reply)
            # is a failed page, and no older file is left behind.
            content = response.content
            if not _identifies_as_image(content):
                Path(path).unlink(missing_ok=True)
                logger.warning("Not an image (%d bytes): %s", len(content), url)
                return False

            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return False
