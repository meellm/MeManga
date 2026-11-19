"""
Olympus Scanlation scraper - Spanish manhwa/manga scanlation group
Site: olympusxyz.com

Olympus is a Nuxt SSR app. Everything the downloader needs is reachable
over plain HTTP JSON without a browser:

* search   -> GET /api/series/list returns the whole catalogue as
              ``{id, name, slug, cover, type}`` rows. The site's own search
              modal fetches this list once and filters it client-side, so
              search does the same.
* chapters -> GET /api/series/<slug>/chapters?page=N&direction=desc&type=comic
              is a paginated chapter list whose ``meta.total`` gives the
              number of rows. It used to live on a panel subdomain that no
              longer resolves.
* pages    -> GET /api/capitulo/<slug>/<chapter_id> returns ``chapter.pages``,
              an ordered list of absolute media.imagesolymp.xyz image URLs.
              The reader page SSR-renders the pages as
              ``main.strip div.panel > img``, which is the fallback when the
              JSON is unavailable or its shape changes.

The catalogue mixes comics and text-only novels (``type == "novel"``).
MeManga downloads page images, so novels are left out of search results
and novel URLs resolve to no chapters.

Page images are served directly (no Referer/token needed), so the base-class
``download_image`` handles the actual downloads.
"""

import logging
import re
import unicodedata
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests

from .base import BaseScraper, Chapter, Manga, CLOUDSCRAPER_CHROME_DESKTOP

logger = logging.getLogger(__name__)


class OlympusSourceError(RuntimeError):
    """olympusxyz.com did not deliver a complete, well-formed chapter list."""


def _cloudflare_refusal(response) -> bool:
    """True for an HTTP 403 that Cloudflare's edge sent or passed on."""
    if response is None or response.status_code != 403:
        return False
    headers = response.headers or {}
    return (str(headers.get("server") or "").lower() == "cloudflare"
            or "cf-ray" in headers or "cf-mitigated" in headers)


class OlympusScraper(BaseScraper):
    """Scraper for Olympus Scanlation (olympusxyz.com)."""

    name = "olympus"
    base_url = "https://olympusxyz.com"
    content_language = "es"  # Spanish-language site

    # Series pages are /series/comic-<slug> (or novela-<slug>); reader pages
    # are /capitulo/<chapter_id>/comic-<slug>.
    _SERIES_RE = re.compile(r"/series/(comic|novela)-([a-z0-9-]+)")
    _CHAPTER_RE = re.compile(r"/capitulo/(\d+)/(comic|novela)-([a-z0-9-]+)")

    # Safety cap on chapter-list pagination; reaching it while the list
    # still reports more rows is an error, not a shorter list.
    _MAX_CHAPTER_PAGES = 100

    _HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Referer": base_url + "/",
    }

    def __init__(self):
        super().__init__()
        self.session.headers.update(self._HEADERS)
        self._catalogue: Optional[list] = None
        # Set once the plain session was refused and cloudscraper's took over.
        self._cloudflare_session = False

    # Transport

    def _switch_to_cloudflare_session(self) -> None:
        """Send this scraper's requests through cloudscraper from now on.

        Cloudflare refuses the plain ``requests`` client outright on some
        networks (HTTP 403 even on the catalogue) while it lets a
        browser-like client through. cloudscraper keeps its own
        User-Agent, which matches its TLS profile; only the site's Accept
        and Referer are put back.
        """
        self._use_cloudscraper(CLOUDSCRAPER_CHROME_DESKTOP)
        self.session.headers.update(self._HEADERS)
        self._cloudflare_session = True

    def _request(self, url: str, **kwargs) -> requests.Response:
        """The shared request policy, falling back to cloudscraper once.

        A request refused with Cloudflare's 403 is sent again through a
        cloudscraper session, which this scraper then keeps. Any other
        error, and a refusal of the cloudscraper session as well, is
        raised as before.
        """
        try:
            return super()._request(url, **kwargs)
        except requests.HTTPError as error:
            if self._cloudflare_session or not _cloudflare_refusal(error.response):
                raise
        logger.info("olympusxyz.com refused the plain HTTP client (Cloudflare "
                    "403); retrying through cloudscraper")
        self._switch_to_cloudflare_session()
        return super()._request(url, **kwargs)

    def worker_copy(self) -> "OlympusScraper":
        """A copy for another thread; it keeps the cloudscraper session if
        this scraper had to switch to it (the base copy rebuilds a plain
        one)."""
        clone = super().worker_copy()
        if self._cloudflare_session:
            clone._switch_to_cloudflare_session()
            clone.session.cookies.update(self.session.cookies)
        return clone

    # URL helpers

    @classmethod
    def _parse_series_url(cls, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (kind, slug) from a series URL, e.g. ("comic", "solo-swordmaster")."""
        match = cls._SERIES_RE.search(url or "")
        if match:
            return match.group(1), match.group(2)
        return None, None

    @classmethod
    def _parse_chapter_url(cls, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (chapter_id, slug) from a reader URL."""
        match = cls._CHAPTER_RE.search(url or "")
        if match:
            return match.group(1), match.group(3)
        return None, None

    def _series_url(self, slug: str, kind: str = "comic") -> str:
        return f"{self.base_url}/series/{kind}-{slug}"

    def _chapter_url(self, slug: str, chapter_id) -> str:
        return f"{self.base_url}/capitulo/{chapter_id}/comic-{slug}"

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search the catalogue by title/slug (client-side, like the site)."""
        if self._catalogue is None:
            data = self._get_json(f"{self.base_url}/api/series/list")
            self._catalogue = (data or {}).get("data") or []
        return self._parse_search(self._catalogue, query)

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip accents, and collapse non-alphanumerics to spaces.

        Titles are Spanish ("Acción", "Regresión"), so accent folding lets an
        unaccented query still match.
        """
        text = unicodedata.normalize("NFKD", text or "")
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def _parse_search(self, entries, query: str) -> List[Manga]:
        """Filter catalogue rows to comics matching every query word.

        Exact title matches rank first, then titles starting with the query,
        then the rest in catalogue order.
        """
        needle = self._normalize(query)
        if not needle or not isinstance(entries, list):
            return []
        words = needle.split()

        ranked = []
        seen = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            # Novels are text-only; there are no page images to download.
            if entry.get("type") != "comic":
                continue
            title = (entry.get("name") or "").strip()
            slug = (entry.get("slug") or "").strip()
            if not title or not slug or slug in seen:
                continue

            name_norm = self._normalize(title)
            haystack = name_norm + " " + self._normalize(slug)
            if not all(word in haystack for word in words):
                continue
            seen.add(slug)

            if name_norm == needle:
                rank = 0
            elif name_norm.startswith(needle):
                rank = 1
            else:
                rank = 2
            ranked.append((rank, index, Manga(
                title=title,
                url=self._series_url(slug),
                cover_url=entry.get("cover") or None,
            )))

        ranked.sort(key=lambda item: (item[0], item[1]))
        return [manga for _, _, manga in ranked][:20]

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a comic via the paginated chapter API.

        The list is read until it holds the ``meta.total`` rows it
        reports (or, without a total, up to ``meta.last_page``). A list
        that ends early, or a payload of the wrong shape, raises
        ``OlympusSourceError`` instead of passing as a shorter list.
        """
        kind, slug = self._parse_series_url(manga_url)
        if not slug or kind != "comic":
            # Novels have no image pages, so there is nothing to download.
            return []

        entries = []
        total = None
        for page in range(1, self._MAX_CHAPTER_PAGES + 1):
            url = (f"{self.base_url}/api/series/{slug}/chapters"
                   f"?page={page}&direction=desc&type=comic")
            data = self._get_json(url)
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise OlympusSourceError(
                    f"Olympus returned an invalid chapter list for {url}")
            entries.extend(rows)

            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            if isinstance(meta.get("total"), int) and not isinstance(
                    meta.get("total"), bool):
                total = meta["total"]
            if total is not None:
                if len(entries) >= total:
                    break
                if not rows:
                    raise OlympusSourceError(
                        f"Olympus chapter list for {manga_url} has "
                        f"{len(entries)} of the {total} chapters it reports; "
                        f"refusing an incomplete list")
                continue
            last_page = meta.get("last_page")
            if not rows or (isinstance(last_page, int) and page >= last_page):
                break
        else:
            raise OlympusSourceError(
                f"Olympus chapter list for {manga_url} still had more pages "
                f"after {self._MAX_CHAPTER_PAGES} pages; refusing an "
                f"incomplete list")

        # Rows come newest first; parse them oldest first so a number
        # released by several teams keeps its earliest listed release.
        return self._parse_chapters(list(reversed(entries)), slug)

    def _parse_chapters(self, entries, slug: str) -> List[Chapter]:
        """Parse chapter-list rows into Chapter objects, sorted ascending.

        A number can be released by more than one team; keep the first
        release listed so the downloader gets one row per chapter.
        """
        chapters = []
        seen = set()
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            chapter_id = entry.get("id")
            if chapter_id is None:
                continue
            number = self._chapter_number(entry.get("name"))
            if number in seen:
                continue
            seen.add(number)

            published = entry.get("published_at")
            chapters.append(Chapter(
                number=number,
                title=f"Chapter {number}",
                url=self._chapter_url(slug, chapter_id),
                date=str(published)[:10] if published else None,
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _chapter_number(raw) -> str:
        """Normalise a chapter name like "12", "22.05" or "12.0" to a number string."""
        text = str(raw if raw is not None else "").strip()
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return text or "0"
        value = match.group(0)
        if "." in value and float(value).is_integer():
            return str(int(float(value)))
        return value

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get ordered page image URLs for a chapter."""
        chapter_id, slug = self._parse_chapter_url(chapter_url)
        if not chapter_id or not slug:
            return []

        try:
            data = self._get_json(
                f"{self.base_url}/api/capitulo/{slug}/{chapter_id}"
            )
            pages = self._parse_pages(data)
        except Exception:
            pages = []
        if pages:
            return pages

        # Fallback: the SSR reader page renders the same images as <img>
        # tags. A failure to load it is a failure, not a chapter without
        # pages.
        html = self._get_html(self._chapter_url(slug, chapter_id))
        return self._parse_pages_html(html, chapter_id)

    @staticmethod
    def _parse_pages(data) -> List[str]:
        """Extract ordered page URLs from an /api/capitulo payload."""
        if not isinstance(data, dict):
            return []
        chapter = data.get("chapter") or {}
        pages = []
        for url in chapter.get("pages") or []:
            if isinstance(url, str) and url.strip().startswith("http"):
                pages.append(url.strip())
        return pages

    @classmethod
    def _parse_pages_html(cls, html: str, chapter_id) -> List[str]:
        """Extract this chapter's page images from the SSR reader HTML.

        The reader strip holds one ``div.panel`` per page
        (``main.strip div.panel > img``), in page order. Without it, only
        images whose path carries the chapter id are kept, which skips
        covers, avatars and site chrome.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        pages = []
        seen = set()
        for img in soup.select("main.strip div.panel > img"):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src:
                continue
            src = urljoin(cls.base_url + "/", src)
            if src.startswith("http") and src not in seen:
                seen.add(src)
                pages.append(src)
        if pages:
            return pages

        marker = f"/{chapter_id}/"
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src.startswith("http") or marker not in src or src in seen:
                continue
            seen.add(src)
            pages.append(src)
        return pages

    # Cover

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get the cover from the series API instead of scraping og:image."""
        _, slug = self._parse_series_url(manga_url)
        if not slug:
            return super().get_cover_url(manga_url)
        try:
            data = self._get_json(f"{self.base_url}/api/series/{slug}")
            return ((data or {}).get("data") or {}).get("cover") or None
        except Exception:
            return None
