"""
Lector Manga scraper - Spanish manga/manhwa/comics reader
Site: lector-mangas.lat (lectormangass.net 301-redirects here)

Lector Manga is a static Astro site. Everything the downloader needs is
server-rendered HTML, so plain requests are enough:

* search   -> GET cdn.zerocomics.net/comics?search=<q>&page=1 is the HTML
              fragment the site's own live search fetches. The
              ``/comics?q=`` URL advertised in the page metadata ignores
              the query and just lists the directory, so it is not used.
* chapters -> /comics/<slug> renders the full chapter list in
              ``#chapters-list``; each row carries ``data-chapter-num``.
              Sidebar and SEO blocks also link a "first chapter" alias
              (/comics/<slug>/chapter-1), which is skipped.
* pages    -> /comics/<slug>/capitulo-<n> renders every page as an
              ``img.reader-page-img`` tag.

Saved URLs on the old lectormangass.net host are rebuilt on the current
host from their path, so they keep resolving without a redirect hop.

Page images are served directly (no Referer/token needed), so the base-class
``download_image`` handles the actual downloads.
"""

import re
from typing import List, Optional
from urllib.parse import urljoin

from .base import BaseScraper, Chapter, Manga


class LectorMangaScraper(BaseScraper):
    """Scraper for Lector Manga (lector-mangas.lat)."""

    name = "lectormanga"
    base_url = "https://lector-mangas.lat"
    search_url = "https://cdn.zerocomics.net/comics"

    # Series pages are /comics/<slug>; reader pages are
    # /comics/<slug>/capitulo-<n> where <n> may be a decimal (90.5).
    _SERIES_RE = re.compile(r"/comics/([a-z0-9][a-z0-9-]*)(?:[/?#]|$)", re.I)
    _CHAPTER_RE = re.compile(
        r"/comics/([a-z0-9][a-z0-9-]*)/capitulo-(\d+(?:\.\d+)?)(?:[/?#]|$)", re.I
    )

    # Directory routes that share the /comics/ prefix but are not series.
    _RESERVED_SLUGS = {"genre", "genres", "type", "types", "status", "statuses"}

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            "Referer": self.base_url + "/",
        })

    def _get_page(self, url: str, **kwargs) -> str:
        """Fetch HTML as UTF-8.

        The search host answers ``text/html`` without a charset, so
        ``response.text`` would fall back to Latin-1 and mangle Spanish
        titles ("Selección" -> "SelecciÃ³n").
        """
        return self._request(url, **kwargs).content.decode("utf-8", "replace")

    # URL helpers

    @classmethod
    def _parse_series_url(cls, url: str) -> Optional[str]:
        """Return the series slug from a series or reader URL."""
        match = cls._SERIES_RE.search(url or "")
        if not match:
            return None
        slug = match.group(1).lower()
        if slug in cls._RESERVED_SLUGS:
            return None
        return slug

    @classmethod
    def _parse_chapter_url(cls, url: str):
        """Return (slug, chapter_number) from a reader URL."""
        match = cls._CHAPTER_RE.search(url or "")
        if match:
            return match.group(1).lower(), match.group(2)
        return None, None

    def _series_url(self, slug: str) -> str:
        return f"{self.base_url}/comics/{slug}"

    def _chapter_url(self, slug: str, number: str) -> str:
        return f"{self.base_url}/comics/{slug}/capitulo-{number}"

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search via the same HTML fragment the site's live search uses."""
        query = (query or "").strip()
        # The site's own search ignores queries shorter than two characters.
        if len(query) < 2:
            return []
        html = self._get_page(
            self.search_url,
            params={"search": query, "page": 1},
            headers={"Accept": "text/html", "X-Requested-With": "fetch"},
        )
        return self._parse_search(html)

    def _parse_search(self, html: str) -> List[Manga]:
        """Parse result cards from the ``.manga-grid`` search fragment.

        Only the grid is read - the fragment also carries ranking and
        recommendation sliders that link unrelated series.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        grid = soup.select_one(".manga-grid")
        if grid is None:
            return []

        results = []
        seen = set()
        for card in grid.find_all(recursive=False):
            link = card.select_one("a.card-cover-link[href]") or card.select_one(
                ".card-info a[href]"
            )
            if link is None:
                continue
            slug = self._parse_series_url(link["href"])
            if not slug or slug in seen:
                continue

            title = (link.get("title") or "").strip()
            if not title:
                info = card.select_one(".card-info a[href]")
                title = info.get_text(" ", strip=True) if info is not None else ""
            if not title:
                continue
            seen.add(slug)

            img = card.select_one("img.card-cover-img") or card.select_one("img")
            cover = ""
            if img is not None:
                cover = (img.get("src") or img.get("data-src") or "").strip()
            results.append(Manga(
                title=title,
                url=self._series_url(slug),
                cover_url=cover if cover.startswith("http") else None,
            ))

        return results[:20]

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the series page."""
        slug = self._parse_series_url(manga_url)
        if not slug:
            return []
        html = self._get_page(self._series_url(slug))
        return self._parse_chapters(html, slug)

    def _parse_chapters(self, html: str, slug: str) -> List[Chapter]:
        """Parse ``#chapters-list`` rows into Chapter objects, sorted ascending."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        # Scope to the chapter list so the sidebar "first chapter" button and
        # the SEO block's /chapter-1 alias don't add duplicates. Fall back to
        # the whole page if the container is renamed.
        container = soup.select_one("#chapters-list") or soup

        chapters = []
        seen = set()
        for link in container.select("a[href]"):
            link_slug, url_number = self._parse_chapter_url(link["href"])
            if link_slug != slug or not url_number:
                continue
            row = link.find_parent(attrs={"data-chapter-num": True})
            number = self._chapter_number(row.get("data-chapter-num")) if row is not None else ""
            number = number or self._chapter_number(url_number)
            if number in seen:
                continue
            seen.add(number)
            chapters.append(Chapter(
                number=number,
                title=f"Chapter {number}",
                # Keep the number exactly as the site links it in the URL.
                url=self._chapter_url(slug, url_number),
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _chapter_number(raw) -> str:
        """Normalise "100", "90.5" or "12.0" to a chapter number string."""
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
        slug, number = self._parse_chapter_url(chapter_url)
        if not slug:
            return []
        html = self._get_page(self._chapter_url(slug, number))
        return self._parse_pages(html)

    def _parse_pages(self, html: str) -> List[str]:
        """Extract the reader's page images in order.

        Covers and avatars elsewhere on the page are outside
        ``.reader-pages``, so they are never picked up.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        images = soup.select("img.reader-page-img")
        if not images:
            reader = soup.select_one(".reader-pages")
            images = reader.find_all("img") if reader is not None else []

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
        """Read og:image from the series page on the current host."""
        slug = self._parse_series_url(manga_url)
        if slug:
            manga_url = self._series_url(slug)
        return super().get_cover_url(manga_url)
