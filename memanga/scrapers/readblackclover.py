"""
ReadBlackClover scraper (readblackclover.com / ww7.readblackclover.com) - Black Clover dedicated site.

The site now serves from the bare domain. Its series page no longer lists
chapters, so the main series is read from the chapter selector that every
chapter page carries. Reader pages are relative same-origin image URLs.
"""

import logging
import re
from typing import List
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .base import Chapter, Manga
from .readmanga_base import ReadMangaBaseScraper

logger = logging.getLogger(__name__)

_CANONICAL_HOST = "readblackclover.com"
# The registered legacy alias; its old URLs resolve on the bare domain.
_LEGACY_HOSTS = {"ww7.readblackclover.com"}
_MAIN_SERIES_PATHS = {"", "/", "/manga/black-clover", "/manga/black-clover/"}
_MAIN_CHAPTER_PATH = re.compile(r"^/chapter/black-clover-chapter-[^/]+/?$")
_READER_PATH_MARKER = "/file/mangap/"
_SEARCH_KEYWORDS = ("black clover", "blackclover")
# Recent chapters tried for the selector before falling back to home-page links.
_MAX_SELECTOR_PAGES = 2


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class ReadBlackCloverScraper(ReadMangaBaseScraper):
    """Scraper for readblackclover.com - Black Clover manga."""

    name = "readblackclover"
    base_url = "https://readblackclover.com"
    cdn_pattern = r"cdn\.readblackclover\.com"

    def _canonical_url(self, url: str) -> str:
        """Move URLs on the registered legacy host to the bare domain."""
        parsed = urlparse(url)
        if _host(url) in _LEGACY_HOSTS:
            return urlunparse(parsed._replace(netloc=_CANONICAL_HOST))
        return url

    def search(self, query: str) -> List[Manga]:
        """Single-series site: return Black Clover when the query matches."""
        q = " ".join(query.lower().split())
        if q and any(kw in q or q in kw for kw in _SEARCH_KEYWORDS):
            return [Manga(
                title="Black Clover",
                url=f"{self.base_url}/manga/black-clover/",
            )]
        return []

    # ── Chapters ──────────────────────────────────────────────────────

    @staticmethod
    def _chapter_number(href: str, text: str) -> str:
        """Same numbering as ReadMangaBaseScraper.get_chapters."""
        match = re.search(r'chapter[/-](\d+(?:\.\d+)?)', href.lower())
        if match:
            return match.group(1)
        match = re.search(r'chapter\s*(\d+(?:\.\d+)?)', text.lower())
        if match:
            return match.group(1)
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        return match.group(1) if match else "0"

    def _main_chapter_url(self, href: str, page_url: str):
        """Absolute bare-domain Black Clover chapter URL, or None."""
        url = urljoin(page_url, href.strip())
        if _host(url) != _CANONICAL_HOST:
            return None
        if not _MAIN_CHAPTER_PATH.match(urlparse(url).path):
            return None
        return url

    def _collect(self, pairs, page_url: str) -> List[Chapter]:
        chapters = []
        seen = set()
        for href, text in pairs:
            url = self._main_chapter_url(href, page_url)
            if url is None:
                continue
            key = url.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            chapters.append(Chapter(
                number=self._chapter_number(url, text),
                title=text,
                url=url,
            ))
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def _main_series_chapters(self) -> List[Chapter]:
        root_url = f"{self.base_url}/"
        soup = BeautifulSoup(self._get_html(root_url), "html.parser")
        recent = self._collect(
            ((a.get("href", ""), a.get_text(strip=True))
             for a in soup.find_all("a", href=True)),
            root_url,
        )
        # Document order puts the newest chapter first; the selector lives
        # on every chapter page.
        candidates = []
        for a in soup.find_all("a", href=True):
            url = self._main_chapter_url(a["href"], root_url)
            if url and url not in candidates:
                candidates.append(url)

        for chapter_url in candidates[:_MAX_SELECTOR_PAGES]:
            try:
                page = BeautifulSoup(self._get_html(chapter_url), "html.parser")
            except Exception as e:
                logger.debug("Failed to read chapter selector from %s: %s", chapter_url, e)
                continue
            options = [
                (opt.get("value", ""), opt.get_text(strip=True))
                for select in page.find_all("select")
                for opt in select.find_all("option")
            ]
            chapters = self._collect(options, chapter_url)
            if chapters:
                return chapters

        if recent:
            logger.warning(
                "Black Clover chapter selector not found; only %d recent "
                "chapters from the home page are listed", len(recent))
        return recent

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Main series from the chapter selector; other series as before."""
        url = self._canonical_url(manga_url)
        if urlparse(url).path in _MAIN_SERIES_PATHS:
            # The series page no longer lists chapters, and saved URLs may
            # carry any former host: read the known bare-domain pages.
            return self._main_series_chapters()
        chapters = super().get_chapters(url)
        return [c for c in chapters
                if _host(c.url) == _CANONICAL_HOST
                or _host(c.url).endswith("." + _CANONICAL_HOST)]

    # ── Pages ─────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Reader images, resolved against the chapter URL on the bare domain."""
        url = self._canonical_url(chapter_url)
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        container = soup.select_one("div.js-pages-container")
        images = (container or soup).select("img.js-page")
        if not images:
            # No reader markup: accept only the site's reader image path,
            # never arbitrary page images.
            images = soup.find_all("img")

        pages = []
        seen = set()
        for img in images:
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            page_url = urljoin(url, src)
            if _host(page_url) != _CANONICAL_HOST:
                continue
            if _READER_PATH_MARKER not in urlparse(page_url).path:
                continue
            if page_url not in seen:
                seen.add(page_url)
                pages.append(page_url)
        return pages
