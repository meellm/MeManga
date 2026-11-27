"""
Inventario Oculto scraper - manga scans
Site: inventariooculto.com

The site runs the WordPress "Madara" theme with series under /manga/:

* search   -> POST /wp-admin/admin-ajax.php with ``action=madara_load_more``
              returns ``div.page-item-detail`` cards. No results is an empty
              body. Cards carrying an adult badge ("18+") are left out.
* chapters -> POST <series>/ajax/chapters/ returns ``li.wp-manga-chapter``
              rows, grouped under volume headers. A numbered row reads
              "Capítulo N" or "Capítulo N - <title>"; its link may sit under a
              volume path (/manga/<slug>/volumen-2/capitulo-9/).
* pages    -> a chapter page lists ``div.page-break img`` in reader order.

Rows that carry no chapter number ("Capítulo final", "VOLUMEN 2 - Extras",
"EPÍLOGO") are left out with one warning that counts and names them, since
the app would read the volume number in "VOLUMEN 2 - Extras" as a chapter
number. A number served twice with different links lists neither row. Any
other label raises. Soft hyphens inside labels are dropped before reading.

The catalogue includes adult titles, so the source is marked NSFW; titles
whose own badges or genres mark them as adult are refused. No content
language is claimed for the catalogue.
"""

import logging
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import (
    BaseScraper,
    Chapter,
    Manga,
    _identifies_as_image,
    _retry,
    is_retryable_request_error,
)

logger = logging.getLogger(__name__)

_HOST = "inventariooculto.com"
_SLUG = r"[a-z0-9]+(?:[-_][a-z0-9]+)*_?"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/manga/({_SLUG})/(?:(volumen-\d+)/)?({_SLUG})/?$")
_RESERVED_SLUGS = frozenset({"page", "feed"})
_IMAGE_PATH = re.compile(
    r"^/wp-content/uploads/WP-manga/data/manga_[0-9a-f]+/[0-9a-f]{32}/"
    r"[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_COVER_PATH = re.compile(r"^/wp-content/uploads/\d{4}/\d{2}/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)

_LABEL_NUMBERED = re.compile(r"^Capítulo (\d+)(?: - (.+))?$")
_LABEL_SPECIAL = re.compile(r"^(?:Capítulo final(?: - .+)?|VOLUMEN \d+ - Extras|EPÍLOGO)$")
_ROW_DATE = re.compile(r"^(\d{1,2}) ([a-z]+), (\d{4})$")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_SOFT_HYPHEN = "\u00ad"
_INLINE_SERIES = re.compile(r'"manga_id":"(\d+)"')
_INLINE_CHAPTER = re.compile(r'"chapter_slug":"([^"]*)"')
_POST_ID = re.compile(r"^postid-(\d+)$")
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_WORDS = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NOVEL_WORDS = frozenset({"novel", "novela"})

# The search form the site's own archive sends; only the query is added.
_SEARCH_FORM: Tuple[Tuple[str, str], ...] = (
    ("action", "madara_load_more"),
    ("page", "0"),
    ("template", "madara-core/content/content-archive"),
    ("vars[paged]", "1"),
    ("vars[template]", "archive"),
    ("vars[posts_per_page]", "25"),
    ("vars[post_type]", "wp-manga"),
    ("vars[post_status]", "publish"),
    ("vars[manga_archives_item_layout]", "big_thumbnail"),
    ("vars[meta_query][0][key]", "_wp_manga_chapter_type"),
    ("vars[meta_query][0][value]", "manga"),
)

_MAX_SEARCH_RESULTS = 25
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class InventarioOcultoSourceError(RuntimeError):
    """inventariooculto.com answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).replace(_SOFT_HYPHEN, "").split())


def _split(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        parts.port
    except ValueError:
        return None
    return parts


def _site_path(url) -> Optional[str]:
    parts = _split(url)
    if (parts is None or parts.scheme not in ("http", "https")
            or (parts.hostname or "").lower() not in (_HOST, f"www.{_HOST}")
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment):
        return None
    return parts.path


def _own_url(url, pattern) -> Optional[str]:
    """``url`` as an https URL of this site whose path matches ``pattern``."""
    parts = _split(url)
    if (parts is None or parts.scheme != "https" or parts.hostname != _HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment or not pattern.match(parts.path)
            or ".." in parts.path.split("/")):
        return None
    return url.strip()


def _row_date(text: str) -> Optional[str]:
    """A served Spanish date ("6 septiembre, 2025") as YYYY-MM-DD, or None."""
    match = _ROW_DATE.match(text)
    month = _MONTHS.get(match.group(2)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def _has_paid_class(element) -> bool:
    return any(_PAID_CLASS.search(name)
               for node in [element, *element.find_all(True)]
               for name in node.get("class") or [])


def _badges(element) -> Set[str]:
    """Words a title's badges show: their text and their class names."""
    words = set()
    for badge in element.select(".manga-title-badges"):
        words.add(_text(badge).casefold())
        words.update(name.casefold() for name in badge.get("class") or [])
    return words


def _post_id(soup: BeautifulSoup) -> Optional[str]:
    body = soup.find("body")
    ids = [match.group(1) for match in
           (_POST_ID.match(name) for name in (body.get("class") or [] if body else []))
           if match]
    return ids[0] if len(ids) == 1 else None


class InventarioOcultoScraper(BaseScraper):
    """Scraper for Inventario Oculto (inventariooculto.com)."""

    name = "inventariooculto"
    base_url = f"https://{_HOST}"
    content_language = None  # not stated for the catalogue
    nsfw = True  # the catalogue holds adult titles; those are refused here

    _AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: each checked series' post id, and the
        # series URL of each listed chapter.
        self._series_ids: Dict[str, str] = {}
        self._listed: Dict[str, str] = {}

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match or match.group(1) in _RESERVED_SLUGS:
            raise InventarioOcultoSourceError(f"Not an Inventario Oculto series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}/", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, str, str]:
        """A chapter page's canonical URL, series slug and chapter slug."""
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match or match.group(1) in _RESERVED_SLUGS:
            raise InventarioOcultoSourceError(f"Not an Inventario Oculto chapter URL: {url}")
        series, volume, chapter = match.groups()
        middle = f"{volume}/" if volume else ""
        return f"{self.base_url}/manga/{series}/{middle}{chapter}/", series, chapter

    # Requests

    def _post(self, url: str, data=None, headers=None):
        """POST with the source's request spacing and retry rules, without
        following redirects."""
        def send():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            response = self.session.post(url, data=data, headers=headers, timeout=30,
                                         allow_redirects=False)
            response.raise_for_status()
            return response

        return _retry(send, max_attempts=3, base_delay=1.0,
                      exceptions=(requests.RequestException,),
                      retry_if=is_retryable_request_error)

    def _checked(self, response, what: str, url: str):
        if response.status_code != 200:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto answered HTTP {response.status_code} for {what} {url}")
        return response

    def _page(self, url: str, what: str) -> BeautifulSoup:
        response = self._checked(self._request(url, allow_redirects=False), what, url)
        return BeautifulSoup(response.text, "html.parser")

    # Search

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's archive search, without adult titles."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/wp-admin/admin-ajax.php"
        headers = dict(self._AJAX_HEADERS, Referer=f"{self.base_url}/")
        response = self._checked(
            self._post(url, data=[*_SEARCH_FORM, ("vars[s]", query)], headers=headers),
            "search", url)
        if response.content == b"":
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("div.page-item-detail")
        if not rows:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto search for {query!r} did not serve a result list")
        if any(row.select_one("div.page-item-detail") for row in rows):
            raise InventarioOcultoSourceError(
                f"Inventario Oculto search for {query!r} nests result rows")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            link = row.select_one(".post-title a[href]")
            title = _text(link) if link else ""
            if not title:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto search for {query!r} lists a result without a title")
            try:
                series_url, _ = self._series_parts(link["href"])
            except InventarioOcultoSourceError:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto search for {query!r} lists a result that is "
                    f"not a series") from None
            if series_url in seen:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto search for {query!r} lists {series_url} twice")
            seen.add(series_url)
            if _badges(row) & (_ADULT_WORDS | _NOVEL_WORDS):
                continue
            image = row.select_one("img[src]")
            cover = _own_url(image["src"], _COVER_PATH) if image else None
            results.append(Manga(title=title, url=series_url, cover_url=cover))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for novels and adult titles."""
        soup = self._page(series_url, "series page")
        canonical = soup.select('link[rel="canonical"]')
        post_id = _post_id(soup)
        holders = soup.select("#manga-chapters-holder")
        if (len(canonical) != 1 or canonical[0].get("href") != series_url
                or len(soup.select("div.post-title h1")) != 1 or post_id is None
                or len(holders) != 1 or holders[0].get("data-id") != post_id):
            raise InventarioOcultoSourceError(
                f"Inventario Oculto page {series_url} is not a series page")
        # The title's own badges only, around its heading, not those of other
        # titles the page may list.
        badges = _badges(soup.select("div.post-title h1")[0].parent)
        genres = {_text(link).casefold() for link in soup.select("div.genres-content a")}
        if (genres | badges) & _ADULT_WORDS:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto lists {series_url} as adult; adult titles are not supported")
        types = {_text(item.select_one(".summary-content")).casefold()
                 for item in soup.select(".post-content_item")
                 if item.select_one(".summary-heading") is not None
                 and item.select_one(".summary-content") is not None
                 and _text(item.select_one(".summary-heading")) == "Type"}
        if (types | badges) & _NOVEL_WORDS:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto lists {series_url} as a novel; only comics are supported")
        self._series_ids[series_url] = post_id
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The numbered chapters a series serves, oldest first."""
        series_url, slug = self._series_parts(manga_url)
        self._series_page(series_url)
        ajax_url = f"{series_url.rstrip('/')}/ajax/chapters/"
        headers = dict(self._AJAX_HEADERS, Referer=series_url)
        response = self._checked(self._post(ajax_url, headers=headers), "chapter list", ajax_url)
        rows = BeautifulSoup(response.text, "html.parser").select("li.wp-manga-chapter")
        if not rows:
            raise InventarioOcultoSourceError(f"Inventario Oculto lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto lists too many chapters for {slug}")

        by_number: Dict[str, List[Tuple[str, Optional[str], str, Optional[str]]]] = {}
        specials: List[str] = []
        urls: Set[str] = set()
        for row in rows:
            links = row.select("a[href]")
            if len(links) != 1 or _has_paid_class(row):
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto has a locked or paid chapter of {slug}; "
                    f"this source reads free chapters only")
            label = _text(links[0])
            try:
                url, row_series, _ = self._chapter_parts(links[0]["href"])
            except InventarioOcultoSourceError:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto links {label!r} of {slug} elsewhere") from None
            if row_series != slug:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto links {label!r} of {slug} to another series")
            if url in urls:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto links {url} twice for {slug}")
            urls.add(url)

            match = _LABEL_NUMBERED.match(label)
            if match:
                served_date = row.select_one("span.chapter-release-date")
                number = format(Decimal(match.group(1)).normalize(), "f")
                by_number.setdefault(number, []).append((
                    label, match.group(2), url,
                    _row_date(_text(served_date)) if served_date else None))
            elif _LABEL_SPECIAL.match(label):
                specials.append(label)
            else:
                raise InventarioOcultoSourceError(
                    f"Inventario Oculto has a chapter row of {slug} in an unknown form: {label!r}")

        chapters: List[Chapter] = []
        for number, entries in by_number.items():
            if len(entries) > 1:
                logger.warning(
                    "%s: chapter %s of %s is served %d times with different links (%s); "
                    "none of them is listed", self.name, number, series_url, len(entries),
                    ", ".join(url for _, _, url, _ in entries))
                continue
            _, title, url, published = entries[0]
            chapters.append(Chapter(number=number, title=title, url=url, date=published))
            self._listed[url] = series_url
        if specials:
            logger.warning(
                "%s: %d chapter row(s) of %s have no chapter number and were not listed: %s",
                self.name, len(specials), series_url, ", ".join(specials))
        if not chapters:
            raise InventarioOcultoSourceError(
                f"Inventario Oculto lists no numbered chapters for {slug}")
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_url, _ = self._series_parts(manga_url)
            image = self._series_page(series_url).select_one("div.summary_image img[src]")
            return _own_url(image["src"], _COVER_PATH) if image else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in reader order, all or nothing."""
        url, series_slug, chapter_slug = self._chapter_parts(chapter_url)
        series_url = f"{self.base_url}/manga/{series_slug}/"

        def refused(why: str):
            return InventarioOcultoSourceError(f"Inventario Oculto chapter {url} {why}")

        response = self._checked(self._request(url, allow_redirects=False), "chapter", url)
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if len(canonical) != 1 or canonical[0].get("href") != url:
            raise refused("answered for another page")
        crumbs = set()
        for link in soup.select("ol.breadcrumb a[href]"):
            path = _site_path(link.get("href"))
            if path is not None and _SERIES_PATH.match(path):
                crumbs.add(link["href"].strip())
        current = soup.select("#wp-manga-current-chap")
        inline_series = _INLINE_SERIES.findall(html)
        inline_chapter = _INLINE_CHAPTER.findall(html)
        if (crumbs != {series_url} or len(current) != 1
                or current[0].get("value") != chapter_slug
                or inline_chapter != [chapter_slug] or len(inline_series) != 1
                or _post_id(soup) != inline_series[0]):
            raise refused("does not name this chapter and its series")
        if series_url not in self._series_ids:
            self._series_page(series_url)
        if self._series_ids[series_url] != inline_series[0]:
            raise refused("names another series")
        if self._listed.get(url, series_url) != series_url:
            raise refused("is not the chapter the series lists")

        readers = soup.select(".reading-content")
        if len(readers) != 1:
            raise refused("lists no pages")
        if _has_paid_class(readers[0]):
            raise refused("is locked or paid; this source reads free chapters only")
        # Descendants, not children: the page's markup leaves the page blocks
        # inside an unclosed element.
        breaks = readers[0].select("div.page-break")
        if not breaks:
            raise refused("lists no pages")
        if len(breaks) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        pages: List[str] = []
        for index, block in enumerate(breaks):
            images = block.find_all("img")
            image = images[0] if len(images) == 1 else None
            source = (image.get("src") or "").strip() if image is not None else ""
            lazy = [(image.get(name) or "").strip() for name in ("data-src", "data-lazy-src")
                    if image is not None and image.get(name)]
            if (image is None or image.get("id") != f"image-{index}"
                    or any(value != source for value in lazy)):
                raise refused(f"has a malformed page {index + 1}")
            page = _own_url(source, _IMAGE_PATH)
            if page is None:
                raise refused(f"has an unexpected image for page {index + 1}")
            pages.append(page)
        if len(set(pages)) != len(pages):
            raise refused("lists the same image twice")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _own_url(url, _IMAGE_PATH)
            if image_url is None:
                raise InventarioOcultoSourceError(f"refused a page URL: {url}")
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise InventarioOcultoSourceError(
                    f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise InventarioOcultoSourceError(
                    f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise InventarioOcultoSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download an Inventario Oculto page: %s", e)
            return False
