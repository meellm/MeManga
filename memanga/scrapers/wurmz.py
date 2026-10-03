"""
Wurmz scraper - Indonesian manga/manhwa/manhua reader
Site: wurmz.net

Wurmz is a Next.js site whose pages are server-rendered, so plain requests
are enough:

* search   -> /semua-komik?q=<query> renders the filtered catalogue as
              ``article.comic-card`` tiles. The /api/comics endpoint ignores
              the query, so it is not used.
* chapters -> /detail/<type>/<slug> renders every chapter as an
              ``a.chap-cell`` link to /detail/<type>/<slug>/chapter/<n>,
              where <n> may be a decimal (50.5) or 0.
* pages    -> the reader page renders every page as an ``<img>`` inside a
              ``div.reader-page`` block.

<type> is one of manga/manhwa/manhua and is part of every URL, so it is
carried alongside the slug.

Page images are hotlinked from blogger.googleusercontent.com and the reader
marks them ``referrerpolicy="no-referrer"``; no Referer is set on the
session, and the base-class ``download_image`` handles the downloads.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga


class WurmzScraper(BaseScraper):
    """Scraper for Wurmz (wurmz.net)."""

    name = "wurmz"
    base_url = "https://wurmz.net"
    search_url = "https://wurmz.net/semua-komik"

    # Series pages are /detail/<type>/<slug>; reader pages append
    # /chapter/<n>.
    _SERIES_RE = re.compile(
        r"/detail/([a-z0-9-]+)/([a-z0-9][a-z0-9-]*)(?:[/?#]|$)", re.I
    )
    _CHAPTER_RE = re.compile(
        r"/detail/([a-z0-9-]+)/([a-z0-9][a-z0-9-]*)/chapter/(\d+(?:\.\d+)?)(?:[/?#]|$)",
        re.I,
    )

    # URL helpers

    @classmethod
    def _parse_series_url(cls, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (type, slug) from a series or reader URL."""
        match = cls._SERIES_RE.search(url or "")
        if not match:
            return None, None
        return match.group(1).lower(), match.group(2).lower()

    @classmethod
    def _parse_chapter_url(cls, url: str):
        """Return (type, slug, chapter_number) from a reader URL."""
        match = cls._CHAPTER_RE.search(url or "")
        if match:
            return match.group(1).lower(), match.group(2).lower(), match.group(3)
        return None, None, None

    def _series_url(self, kind: str, slug: str) -> str:
        return f"{self.base_url}/detail/{kind}/{slug}"

    def _chapter_url(self, kind: str, slug: str, number: str) -> str:
        return f"{self.base_url}/detail/{kind}/{slug}/chapter/{number}"

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search via the server-rendered /semua-komik catalogue filter."""
        query = (query or "").strip()
        if not query:
            return []
        html = self._request(self.search_url, params=dict(q=query)).text
        return self._parse_search(html)

    def _parse_search(self, html: str) -> List[Manga]:
        """Parse ``article.comic-card`` tiles into Manga objects.

        Each tile links the series three times (cover, title, latest
        chapter); the latest-chapter link is a reader URL and only the
        series path is kept.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        results = []
        seen = set()
        for card in soup.select("article.comic-card"):
            kind = slug = None
            for link in card.select("a[href]"):
                kind, slug = self._parse_series_url(link["href"])
                if slug:
                    break
            if not slug or (kind, slug) in seen:
                continue

            title_el = card.select_one(".comic-title")
            title = title_el.get_text(" ", strip=True) if title_el is not None else ""
            if not title:
                labelled = card.select_one("a[aria-label]")
                title = (labelled.get("aria-label") or "").strip() if labelled is not None else ""
            if not title:
                continue
            seen.add((kind, slug))

            img = card.select_one("img")
            cover = ""
            if img is not None:
                cover = (img.get("src") or img.get("data-src") or "").strip()
            if cover:
                cover = urljoin(self.base_url + "/", cover)
            results.append(Manga(
                title=title,
                url=self._series_url(kind, slug),
                cover_url=cover if cover.startswith("http") else None,
            ))

        return results

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the series page."""
        kind, slug = self._parse_series_url(manga_url)
        if not slug:
            return []
        html = self._request(self._series_url(kind, slug)).text
        return self._parse_chapters(html, kind, slug)

    def _parse_chapters(self, html: str, kind: str, slug: str) -> List[Chapter]:
        """Parse ``a.chap-cell`` links into Chapter objects, sorted ascending.

        The series page also has "latest updates" rows linking other
        series' chapters, so links are matched against this series' path.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        # Fall back to every link if the chapter grid class is renamed.
        links = soup.select("a.chap-cell[href]") or soup.select("a[href]")

        chapters = []
        seen = set()
        for link in links:
            link_kind, link_slug, url_number = self._parse_chapter_url(link["href"])
            if (link_kind, link_slug) != (kind, slug) or url_number is None:
                continue
            number = self._chapter_number(url_number)
            if number in seen:
                continue
            seen.add(number)
            chapters.append(Chapter(
                number=number,
                title=f"Chapter {number}",
                # Keep the number exactly as the site links it in the URL.
                url=self._chapter_url(kind, slug, url_number),
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _chapter_number(raw) -> str:
        """Normalise "20", "50.5" or "12.0" to a chapter number string."""
        match = re.search(r"\d+(?:\.\d+)?", str(raw if raw is not None else ""))
        if not match:
            return ""
        value = match.group(0)
        if "." in value and float(value).is_integer():
            return str(int(float(value)))
        return value

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get ordered page image URLs for a chapter."""
        kind, slug, number = self._parse_chapter_url(chapter_url)
        if not slug:
            return []
        html = self._request(self._chapter_url(kind, slug, number)).text
        return self._parse_pages(html)

    def _parse_pages(self, html: str) -> List[str]:
        """Extract the reader's page images in order.

        Covers and avatars elsewhere on the page sit outside the
        ``div.reader-page`` blocks, so they are never picked up.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        images = soup.select("div.reader-page img") or soup.select("img.reader-image")
        if not images:
            canvas = soup.select_one(".reader-canvas")
            images = canvas.find_all("img") if canvas is not None else []

        pages = []
        seen = set()
        for img in images:
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src:
                continue
            src = urljoin(self.base_url + "/", src)
            if not src.startswith("http") or src in seen:
                continue
            seen.add(src)
            pages.append(src)
        return pages

    # Cover

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Read og:image from the series page on the canonical host."""
        kind, slug = self._parse_series_url(manga_url)
        if slug:
            manga_url = self._series_url(kind, slug)
        return super().get_cover_url(manga_url)
