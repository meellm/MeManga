"""
Thunder Scans EN scraper - English manhwa/manhua scanlation group
Site: en-thunderscans.com

Thunder Scans runs the WordPress "MangaReader" (MangaThemesia) theme, not
Madara, so the ``wp-manga`` search/REST routes do not exist. Everything is
plain server-rendered HTML:

* search   -> GET /?s=<query> lists ``.bsx`` cards linking to
              /comics/<slug>/; results paginate as /page/<n>/?s=<query>.
* chapters -> the series page renders the full ``#chapterlist`` as
              ``<li data-num="...">`` rows. Coin-locked chapters render
              without an ``href`` (they open an unlock modal) and are skipped.
* pages    -> the reader page embeds ``ts_reader.run({...})`` whose
              ``sources[].images`` holds the ordered page URLs, served from
              the site's own /wp-content/uploads/ without a token.

Some series and chapter slugs carry a numeric prefix
(``/comics/0086250808-<slug>/``) that the site can rotate. The unprefixed
slug 301-redirects to the current prefixed one, so a saved URL whose prefix
has gone stale (404) is retried without it.
"""

import json
import re
from typing import List, Optional
from urllib.parse import quote_plus

import requests

from .base import BaseScraper, Chapter, Manga


class ThunderScansScraper(BaseScraper):
    """Scraper for Thunder Scans EN (en-thunderscans.com)."""

    name = "thunderscans"
    base_url = "https://en-thunderscans.com"

    # Search results are 10 per page; follow "Next" a few pages at most.
    _MAX_SEARCH_PAGES = 3

    # Rotating numeric slug prefix, e.g. "/comics/0086250808-some-title/".
    _SLUG_PREFIX_RE = re.compile(r"(/(?:comics/)?)\d{6,}-([^/]+/?)$")

    def __init__(self):
        super().__init__()
        self.session.headers.update({"Referer": self.base_url + "/"})

    # URL helpers

    def _absolute(self, url: str) -> str:
        url = (url or "").strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.base_url + url
        return url

    @classmethod
    def _strip_slug_prefix(cls, url: str) -> Optional[str]:
        """Return ``url`` without the numeric slug prefix, or None if it has none."""
        match = cls._SLUG_PREFIX_RE.search(url or "")
        if not match:
            return None
        return url[:match.start()] + match.group(1) + match.group(2)

    def _get_page_html(self, url: str) -> str:
        """Fetch a series/reader page, retrying a stale prefixed slug unprefixed."""
        try:
            return self._get_html(url)
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            fallback = self._strip_slug_prefix(url)
            if status != 404 or not fallback:
                raise
            return self._get_html(fallback)

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search via the WordPress ``?s=`` page, following pagination."""
        query = (query or "").strip()
        if not query:
            return []

        results: List[Manga] = []
        seen = set()
        url = f"{self.base_url}/?s={quote_plus(query)}"
        for _ in range(self._MAX_SEARCH_PAGES):
            html = self._get_html(url)
            for manga in self._parse_search(html):
                if manga.url not in seen:
                    seen.add(manga.url)
                    results.append(manga)
            url = self._next_page_url(html)
            if not url:
                break
        return results

    def _parse_search(self, html: str) -> List[Manga]:
        """Parse ``.bsx`` result cards into Manga objects."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        results = []
        for card in soup.select(".listupd .bsx"):
            link = card.find("a", href=True)
            if not link:
                continue
            manga_url = self._absolute(link["href"])
            if "/comics/" not in manga_url:
                continue

            title_el = card.select_one(".tt")
            title = (link.get("title") or "").strip()
            if not title and title_el:
                title = title_el.get_text(strip=True)
            if not title:
                continue

            cover_url = None
            img = card.find("img")
            if img:
                cover = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                cover_url = self._absolute(cover) if cover else None

            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
        return results

    def _next_page_url(self, html: str) -> Optional[str]:
        """Return the absolute "Next" pagination URL, if any."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        link = soup.select_one(".pagination a.next[href], .hpage a.r[href]")
        return self._absolute(link["href"]) if link else None

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all readable chapters from the series page."""
        return self._parse_chapters(self._get_page_html(manga_url))

    def _parse_chapters(self, html: str) -> List[Chapter]:
        """Parse ``#chapterlist`` rows, skipping coin-locked chapters, ascending."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        chapters = []
        seen = set()
        for row in soup.select("#chapterlist li"):
            # Locked chapters have no href; they open the unlock modal instead.
            link = row.find("a", href=True)
            if not link:
                continue
            href = link["href"].strip()
            if not href or href.startswith("#"):
                continue
            chapter_url = self._absolute(href)
            if chapter_url in seen:
                continue
            seen.add(chapter_url)

            num_el = row.select_one(".chapternum")
            label = re.sub(r"\s+", " ", num_el.get_text(" ", strip=True)) if num_el else ""
            number = self._chapter_number(row.get("data-num"), label, chapter_url)

            date_el = row.select_one(".chapterdate")
            date = date_el.get_text(strip=True) if date_el else None

            chapters.append(Chapter(
                number=number,
                title=label or f"Chapter {number}",
                url=chapter_url,
                date=date or None,
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _chapter_number(data_num, label: str, url: str) -> str:
        """Pick the chapter number from data-num, then the label, then the URL."""
        for text in (data_num, label):
            match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
            if match:
                return match.group(0)
        match = re.search(r"chapter-(\d+)(?:-(\d+))?/?$", url or "")
        if match:
            return match.group(1) + (f".{match.group(2)}" if match.group(2) else "")
        return "0"

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get ordered page image URLs from the reader's ``ts_reader`` payload."""
        html = self._get_page_html(chapter_url)
        pages = self._parse_reader_payload(html)
        if pages:
            return pages
        return self._parse_reader_images(html)

    def _parse_reader_payload(self, html: str) -> List[str]:
        """Extract images from ``ts_reader.run({...})``, preferring the default source."""
        marker = re.search(r"ts_reader\.run\(\s*", html or "")
        if not marker:
            return []
        try:
            data, _ = json.JSONDecoder().raw_decode(html, marker.end())
        except ValueError:
            return []
        if not isinstance(data, dict):
            return []

        sources = [s for s in data.get("sources") or [] if isinstance(s, dict)]
        default = data.get("defaultSource")
        sources.sort(key=lambda s: s.get("source") != default)
        for source in sources:
            pages = []
            for url in source.get("images") or []:
                if isinstance(url, str) and url.strip():
                    pages.append(self._absolute(url))
            if pages:
                return pages
        return []

    def _parse_reader_images(self, html: str) -> List[str]:
        """Fallback: ``<img>`` tags rendered inside ``#readerarea``."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        pages = []
        seen = set()
        for img in soup.select("#readerarea img"):
            src = (img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "").strip()
            src = self._absolute(src)
            if not src.startswith("http") or src.endswith(".svg") or src in seen:
                continue
            seen.add(src)
            pages.append(src)
        return pages
