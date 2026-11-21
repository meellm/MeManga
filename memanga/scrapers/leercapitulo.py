"""
LeerCapitulo scraper - Spanish manga, manhwa and manhua reader
Site: www.leercapitulo.co

The site is server-rendered HTML:

* search   -> GET /manga/?q=<query> lists ``article.lc-card`` results.
* chapters -> GET /manga/<id>/<slug>/ lists every chapter on one page as
              ``#chapterList a.lc-chapter-row`` with a "Capitulo N" label and
              a date. Chapter URLs are used as served, and numbers come from
              the label, never from the URL.
* pages    -> GET /leer/<id>/<slug>/<chapter>/ holds the pages as
              ``main#lcPages img[data-src]`` in reading order.

Requests to the site are spaced at least three seconds apart. Page images
live on a separate image host and are not held to that spacing.

The catalogue has adult sections and no sitewide flag, so the check is made on
each title's own genre and theme labels: a title labelled Adult, Hentai, Smut,
Lolicon, Shotacon, Loli or Shota is not listed for download. Other labels,
Ecchi and Mature among them, are left alone.
"""

import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "leercapitulo.co"
_IMAGE_HOSTS = frozenset({"es2s12-2127.t34798ndc.com", "es1s11-95168.t34798ndc.com"})

_SEGMENT = r"[^/?#\s]{1,200}"
_SERIES_PATH = re.compile(rf"^/manga/([A-Za-z0-9]{{1,40}})/({_SEGMENT})/?$")
_CHAPTER_PATH = re.compile(rf"^/leer/([A-Za-z0-9]{{1,40}})/({_SEGMENT})/({_SEGMENT})/?$")
_IMAGE_PATH = re.compile(r"^/(?:[^/?#\s]+/)+[^/?#\s]+\.(?:webp|jpe?g|png)$", re.I)
_CHAPTER_LABEL = re.compile(r"^Cap[ií]tulo\s+(\d+(?:\.\d+)?)$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHIP_SELECTOR = "a.badge[href^='/manga/?genre='], a.badge[href^='/manga/?theme=']"
_ADULT_LABELS = frozenset({"adult", "hentai", "smut", "lolicon", "shotacon", "loli", "shota"})

# The catalogue page the site serves for a search without results.
_CATALOGUE_TITLE = "Lista Completa de Manga - Leer Online | LeerCapitulo"
_CATALOGUE_HEADING = "Catalogo de manga"
_NO_RESULTS_COUNT = "0 series"
_NO_RESULTS_NOTICE = "No se encontraron series con esos filtros."
_NO_RESULTS_LINK = "Limpiar filtros"

# Bounds on what one page may hold.
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class LeerCapituloSourceError(RuntimeError):
    """leercapitulo.co answered with a page this scraper cannot use."""


def _split(url):
    """urlsplit() of a string URL with a valid port, or None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        parts.port
    except ValueError:
        return None
    return parts


def _safe_segments(*segments: str) -> bool:
    return all(segment not in (".", "..") for segment in segments)


def _chapter_number(label: str) -> Optional[str]:
    """The number of a "Capitulo N" label as a stable string, or None."""
    match = _CHAPTER_LABEL.match(label)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return format(value.normalize(), "f")


def _page_url(value) -> str:
    """``value`` if it is a page image URL on the image host, else raise."""
    parts = _split(value)
    if (parts is None or parts.scheme != "https" or parts.hostname not in _IMAGE_HOSTS
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment
            or not _IMAGE_PATH.match(parts.path)
            or any(part in (".", "..") for part in parts.path.split("/"))):
        raise LeerCapituloSourceError("Unexpected LeerCapitulo page image URL")
    return value


def _has_no_results_notice(soup: BeautifulSoup) -> bool:
    """True when the page carries the site's no-results notice text."""
    return any(_NO_RESULTS_NOTICE in " ".join(alert.get_text(" ").split())
               for alert in soup.select("div.alert"))


def _is_no_results_page(soup: BeautifulSoup) -> bool:
    """True only for the complete catalogue page of a search without results:
    its title and heading, a count of 0 series, the filter form, and the one
    notice with its reset link, with no result or pagination markup."""
    title = soup.title.get_text(strip=True) if soup.title else ""
    headings = soup.select("h1")
    if (title != _CATALOGUE_TITLE or len(headings) != 1
            or headings[0].get_text(strip=True) != _CATALOGUE_HEADING):
        return False
    section = headings[0].parent
    if section is None or "lc-section-title" not in (section.get("class") or []):
        return False
    counts = section.select("span.lc-more")
    if len(counts) != 1 or counts[0].get_text(strip=True) != _NO_RESULTS_COUNT:
        return False
    if (soup.select("article") or soup.select("ul.pagination")
            or not soup.select_one("form[data-filter-form]")):
        return False
    alerts = soup.select("div.alert")
    if len(alerts) != 1 or "alert-secondary" not in (alerts[0].get("class") or []):
        return False
    links = alerts[0].select("a")
    if (len(links) != 1 or "alert-link" not in (links[0].get("class") or [])
            or links[0].get("href") != "/manga/"
            or links[0].get_text(strip=True) != _NO_RESULTS_LINK):
        return False
    notice = " ".join(" ".join(alerts[0].find_all(string=True, recursive=False)).split())
    return notice == _NO_RESULTS_NOTICE


class LeerCapituloScraper(BaseScraper):
    """Scraper for LeerCapitulo (www.leercapitulo.co)."""

    name = "leercapitulo"
    base_url = "https://www.leercapitulo.co"
    content_language = "es"  # Spanish-language site
    engine = "http"
    nsfw = False  # titles with an adult label are refused

    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    def __init__(self):
        super().__init__()
        self._rate_limit = 3.0  # the site's request spacing, in seconds
        # Series whose own labels were checked; worker copies share this set.
        self._cleared: Set[Tuple[str, str]] = set()

    # URLs

    @staticmethod
    def _site_path(url: str) -> Optional[str]:
        parts = _split(url)
        if parts is None:
            return None
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if parts.scheme not in ("http", "https") or host != _HOST or parts.port is not None:
            return None
        return parts.path

    def _series_key(self, manga_url: str) -> Tuple[str, str]:
        path = self._site_path(manga_url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match or not _safe_segments(match.group(2)):
            raise LeerCapituloSourceError(f"Not a LeerCapitulo series URL: {manga_url}")
        return match.group(1), match.group(2)

    def _chapter_key(self, chapter_url: str) -> Tuple[str, str, str]:
        path = self._site_path(chapter_url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match or not _safe_segments(match.group(2), match.group(3)):
            raise LeerCapituloSourceError(f"Not a LeerCapitulo chapter URL: {chapter_url}")
        return match.group(1), match.group(2), match.group(3)

    def _series_url(self, series_id: str, slug: str) -> str:
        return f"{self.base_url}/manga/{series_id}/{slug}/"

    def _soup(self, url: str) -> BeautifulSoup:
        """One site page; a redirect is an error, not a different page."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise LeerCapituloSourceError(
                f"LeerCapitulo answered HTTP {response.status_code} for {url}")
        return BeautifulSoup(response.text, "html.parser")

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search titles through the site's catalogue page."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/manga/?{urlencode({'q': query})}"
        soup = self._soup(url)
        cards = soup.select("article.lc-card")
        if not cards:
            if _is_no_results_page(soup):
                return []
            raise LeerCapituloSourceError(
                f"LeerCapitulo search for {query!r} returned no result cards")
        if _has_no_results_notice(soup) or any(
                count.get_text(strip=True) == _NO_RESULTS_COUNT
                for count in soup.select("span.lc-more")):
            raise LeerCapituloSourceError(
                f"LeerCapitulo search for {query!r} returned results and a "
                f"no-results notice")

        results = []
        seen = set()
        for card in cards:
            link = card.select_one("a.lc-card-name")
            title = link.get_text(" ", strip=True) if link else ""
            href = link.get("href") if link else None
            path = self._site_path(urljoin(self.base_url + "/", href)) if href else None
            match = _SERIES_PATH.match(path) if path else None
            if not title or not match or not _safe_segments(match.group(2)):
                raise LeerCapituloSourceError(
                    f"LeerCapitulo search for {query!r} returned a malformed card")
            series_url = self._series_url(match.group(1), match.group(2))
            if series_url in seen:
                continue
            seen.add(series_url)
            image = card.select_one(".lc-card-cover img")
            src = image.get("src") if image else None
            results.append(Manga(
                title=title,
                url=series_url,
                cover_url=urljoin(self.base_url + "/", src) if src else None,
            ))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_id: str, slug: str) -> BeautifulSoup:
        """A series page, refused when its own labels mark it as adult."""
        soup = self._soup(self._series_url(series_id, slug))
        if len(soup.select("h1")) != 1 or not soup.select_one("#chapterList"):
            raise LeerCapituloSourceError(
                f"LeerCapitulo returned no series page for {slug!r}")
        for chip in soup.select(_CHIP_SELECTOR):
            label = chip.get_text(" ", strip=True).casefold()
            value = (chip.get("href") or "").rsplit("=", 1)[-1].casefold()
            if label in _ADULT_LABELS or value in _ADULT_LABELS:
                raise LeerCapituloSourceError(
                    f"LeerCapitulo labels {slug!r} as adult; adult titles are "
                    f"not supported")
        self._cleared.add((series_id, slug))
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get every chapter of a series, oldest first."""
        series_id, slug = self._series_key(manga_url)
        soup = self._series_page(series_id, slug)
        rows = soup.select("#chapterList a.lc-chapter-row")
        if not rows:
            raise LeerCapituloSourceError(f"LeerCapitulo lists no chapters for {manga_url}")
        if len(rows) > _MAX_CHAPTERS:
            raise LeerCapituloSourceError(
                f"LeerCapitulo lists {len(rows)} chapters for {manga_url}, more "
                f"than the {_MAX_CHAPTERS} this scraper accepts")

        chapters: Dict[str, Chapter] = {}
        urls = set()
        for row in rows:
            label = row.select_one(".n")
            date = row.select_one(".d")
            number = _chapter_number(label.get_text(" ", strip=True)) if label else None
            published = date.get_text(" ", strip=True) if date else ""
            if number is None or not _DATE.match(published):
                raise LeerCapituloSourceError(
                    f"LeerCapitulo chapter list for {manga_url} has a malformed row")
            href = row.get("href")
            path = self._site_path(urljoin(self.base_url + "/", href)) if href else None
            match = _CHAPTER_PATH.match(path) if path else None
            if (not match or (match.group(1), match.group(2)) != (series_id, slug)
                    or not _safe_segments(match.group(3))):
                raise LeerCapituloSourceError(
                    f"LeerCapitulo chapter {number} of {manga_url} links elsewhere")
            url = f"{self.base_url}/leer/{series_id}/{slug}/{match.group(3)}/"
            if number in chapters or url in urls:
                raise LeerCapituloSourceError(
                    f"LeerCapitulo lists chapter {number} of {manga_url} twice")
            urls.add(url)
            chapters[number] = Chapter(number=number, title=None, url=url, date=published)
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_id, slug = self._series_key(manga_url)
            image = self._series_page(series_id, slug).select_one(".lc-cover-lg img")
            src = image.get("src") if image else None
            return urljoin(self.base_url + "/", src) if src else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get the page images of a chapter in served order, all or nothing."""
        series_id, slug, part = self._chapter_key(chapter_url)
        url = f"{self.base_url}/leer/{series_id}/{slug}/{part}/"
        soup = self._soup(url)
        series_path = f"/manga/{series_id}/{slug}/"
        if not any(link.get("href") == series_path for link in soup.select("a[href]")):
            raise LeerCapituloSourceError(
                f"LeerCapitulo reader answered for another series than {chapter_url}")
        if (series_id, slug) not in self._cleared:
            self._series_page(series_id, slug)

        containers = soup.select("main#lcPages")
        if len(containers) != 1:
            raise LeerCapituloSourceError(f"LeerCapitulo returned no reader for {chapter_url}")
        images = containers[0].select("img")
        if not images:
            raise LeerCapituloSourceError(f"LeerCapitulo reader lists no pages for {chapter_url}")
        if len(images) > _MAX_PAGES:
            raise LeerCapituloSourceError(
                f"LeerCapitulo reader lists {len(images)} pages for {chapter_url}, "
                f"more than the {_MAX_PAGES} this scraper accepts")

        pages = []
        for position, image in enumerate(images):
            index = image.get("data-index")
            if index is not None and index != str(position):
                raise LeerCapituloSourceError(
                    f"LeerCapitulo reader pages for {chapter_url} are out of order")
            pages.append(_page_url(image.get("data-src")))
        if len(set(pages)) != len(pages):
            raise LeerCapituloSourceError(
                f"LeerCapitulo reader lists the same image twice for {chapter_url}")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _page_url(url)
            response = self.session.get(image_url, headers=self._IMAGE_HEADERS,
                                        timeout=30, allow_redirects=False)
            if response.status_code != 200:
                raise LeerCapituloSourceError(
                    f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise LeerCapituloSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise LeerCapituloSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a LeerCapitulo page: %s", e)
            return False
