"""
Uzay Manga scraper - Turkish manga, manhwa and manhua reader
Site: uzaymanga.com

The site is a SvelteKit app. Its ``__data.json`` routes return each page's data
as one flat array whose values refer to each other by index, read here as plain
data:

* search   -> /manga/__data.json?page=1&search=<query> holds ``series`` rows,
              ``totalCount`` and the ``filters`` the answer was made for.
* chapters -> /manga/<slug>/__data.json holds ``series`` with every chapter in
              ``SeriesEpisode``.
* pages    -> /manga/<slug>/<episode>/__data.json holds ``episode.images``,
              relative paths on the image host, in reading order.

Page order is the served order. Files named ``6.2.avif`` are parts of a page,
so the list is never sorted. Saved bytes are the served bytes: images are
judged by their content, because the site labels JPEG files as AVIF.

Titles the site puts in its adult category are refused, and so is anything
carrying a lock, price or premium field.
"""

import logging
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "uzaymanga.com"
_IMAGE_HOST = "cdn-u.efsaneler2.can.re"
_DATA_QUERY = "x-sveltekit-invalidated=001"

_SLUG = r"[A-Za-z0-9][A-Za-z0-9._~-]{0,199}"
_SLUG_RE = re.compile(rf"^{_SLUG}$")
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/manga/({_SLUG})/({_SLUG})/?$")
_PAGE_PATH = re.compile(r"^/_manga/(\d+)/[^/?#\s]+/[^/?#\s]+$")
_COVER_PATH = re.compile(r"^/thumbnails/[^?#\s]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_PAID_FIELD = re.compile(r"lock|premium|paid|price|coin|vip|purchase", re.I)
_ADULT_CATEGORIES = frozenset({"yetiskin", "yetişkin"})

# Bounds on what one answer may hold.
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 2000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class UzayMangaSourceError(RuntimeError):
    """uzaymanga.com answered with data this scraper cannot use."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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


def _chapter_number(raw) -> Optional[str]:
    """A served ``order`` as a stable string ("27", "12.5"), or None."""
    if _is_int(raw):
        text = str(raw)
    elif isinstance(raw, float) and math.isfinite(raw):
        text = repr(raw)
    else:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    return format(value.normalize(), "f")


def _page_url(value) -> str:
    """``value`` if it is a page image URL on the image host, else raise."""
    parts = _split(value)
    if (parts is None or parts.scheme != "https" or parts.hostname != _IMAGE_HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment
            or not _PAGE_PATH.match(parts.path)
            or any(part in (".", "..") for part in parts.path.split("/"))):
        raise UzayMangaSourceError("Unexpected Uzay Manga page image URL")
    return value


class _Flat:
    """One flat SvelteKit data array, read by index and never executed."""

    def __init__(self, values: list):
        self.values = values

    def value(self, ref):
        """The value at ``ref``; -1 is the format's "undefined"."""
        if ref == -1 and _is_int(ref):
            return None
        if not _is_int(ref) or not 0 <= ref < len(self.values):
            raise UzayMangaSourceError("Uzay Manga data has a broken reference")
        return self.values[ref]

    def field(self, holder: Dict, key: str):
        return self.value(holder[key]) if key in holder else None

    def object_field(self, holder: Dict, key: str) -> Dict:
        value = self.field(holder, key)
        if not isinstance(value, dict):
            raise UzayMangaSourceError(f"Uzay Manga data has no {key!r} object")
        return value

    def list_field(self, holder: Dict, key: str) -> List:
        """The referenced items of a plain list field."""
        value = self.field(holder, key)
        if not isinstance(value, list) or (value and isinstance(value[0], str)):
            raise UzayMangaSourceError(f"Uzay Manga data has no {key!r} list")
        return [self.value(ref) for ref in value]

    def date_field(self, holder: Dict, key: str) -> Optional[str]:
        """The YYYY-MM-DD of a served Date value, or None."""
        value = self.field(holder, key)
        if (isinstance(value, list) and len(value) == 2 and value[0] == "Date"
                and isinstance(value[1], str) and _DATE.match(value[1])):
            return value[1][:10]
        return None

    def refuse_paid(self, holder: Dict, where: str) -> None:
        """Raise when a lock, price or premium field is set."""
        for key in holder:
            if _PAID_FIELD.search(key) and self.value(holder[key]):
                raise UzayMangaSourceError(
                    f"Uzay Manga marks {where} as paid or locked ({key})")


class UzayMangaScraper(BaseScraper):
    """Scraper for Uzay Manga (uzaymanga.com)."""

    name = "uzaymanga"
    base_url = "https://uzaymanga.com"
    content_language = "tr"  # Turkish-language site
    engine = "api"
    nsfw = False  # titles in the site's adult category are refused

    _IMAGE_BASE = f"https://{_IMAGE_HOST}"
    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    def __init__(self):
        super().__init__()
        # Series slug -> id of series whose categories were checked; worker
        # copies share this mapping.
        self._cleared: Dict[str, int] = {}

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

    def _series_slug(self, manga_url: str) -> str:
        path = self._site_path(manga_url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise UzayMangaSourceError(f"Not an Uzay Manga series URL: {manga_url}")
        return match.group(1)

    def _chapter_slugs(self, chapter_url: str) -> Tuple[str, str]:
        path = self._site_path(chapter_url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise UzayMangaSourceError(f"Not an Uzay Manga chapter URL: {chapter_url}")
        return match.group(1), match.group(2)

    def _data(self, path_and_query: str) -> Tuple[_Flat, Dict]:
        """The flat data and root object of one ``__data.json`` answer."""
        url = f"{self.base_url}{path_and_query}"
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise UzayMangaSourceError(
                f"Uzay Manga answered HTTP {response.status_code} for {url}")
        try:
            payload = response.json()
        except ValueError:
            raise UzayMangaSourceError(f"Uzay Manga returned no JSON for {url}") from None
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("type") != "data" \
                or not isinstance(nodes, list) or not nodes:
            raise UzayMangaSourceError(f"Uzay Manga returned no page data for {url}")
        node = nodes[-1]
        values = node.get("data") if isinstance(node, dict) and node.get("type") == "data" else None
        if not isinstance(values, list) or not values or not isinstance(values[0], dict):
            raise UzayMangaSourceError(f"Uzay Manga returned no page data for {url}")
        return _Flat(values), values[0]

    def _cover(self, flat: _Flat, series: Dict) -> Optional[str]:
        image = flat.field(series, "image")
        if isinstance(image, str) and _COVER_PATH.match(image):
            return f"{self._IMAGE_BASE}{image}"
        return None

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search titles; this reads the first page the site serves."""
        query = (query or "").strip()
        if not query:
            return []
        params = urlencode({"page": 1, "search": query})
        flat, root = self._data(f"/manga/__data.json?{params}&{_DATA_QUERY}")

        filters = flat.object_field(root, "filters")
        served = flat.field(filters, "search")
        if not isinstance(served, str) or served.casefold().split() != query.casefold().split():
            raise UzayMangaSourceError(
                f"Uzay Manga answered for another search than {query!r}")
        rows = flat.list_field(root, "series")
        total = flat.field(root, "totalCount")
        if not _is_int(total) or total < 0:
            raise UzayMangaSourceError(
                f"Uzay Manga search for {query!r} has no usable total")
        if not rows:
            if total != 0:
                raise UzayMangaSourceError(
                    f"Uzay Manga search for {query!r} reports {total} titles but "
                    f"serves none")
            return []

        results = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise UzayMangaSourceError(
                    f"Uzay Manga search for {query!r} returned a malformed row")
            title, slug = flat.field(row, "name"), flat.field(row, "slug")
            if (not isinstance(title, str) or not title.strip()
                    or not isinstance(slug, str) or not _SLUG_RE.match(slug)):
                raise UzayMangaSourceError(
                    f"Uzay Manga search for {query!r} returned a row without a "
                    f"usable title and slug")
            if slug in seen:
                raise UzayMangaSourceError(
                    f"Uzay Manga search for {query!r} lists {slug!r} twice")
            seen.add(slug)
            results.append(Manga(
                title=title.strip(),
                url=f"{self.base_url}/manga/{slug}",
                cover_url=self._cover(flat, row),
            ))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series(self, slug: str) -> Tuple[_Flat, Dict]:
        """A series that is not in the adult category and carries no paid field."""
        flat, root = self._data(f"/manga/{slug}/__data.json?{_DATA_QUERY}")
        series = flat.object_field(root, "series")
        series_id = flat.field(series, "id")
        if flat.field(series, "slug") != slug or not _is_int(series_id):
            raise UzayMangaSourceError(f"Uzay Manga answered for another series than {slug!r}")
        flat.refuse_paid(series, repr(slug))
        for category in flat.list_field(series, "resolvedCategories"):
            if not isinstance(category, dict):
                raise UzayMangaSourceError(f"Uzay Manga has a malformed category on {slug!r}")
            labels = (flat.field(category, "slug"), flat.field(category, "title"))
            if any(isinstance(label, str) and label.casefold() in _ADULT_CATEGORIES
                   for label in labels):
                raise UzayMangaSourceError(
                    f"Uzay Manga lists {slug!r} as adult; adult titles are not supported")
        self._cleared[slug] = series_id
        return flat, series

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get every chapter of a series, oldest first."""
        slug = self._series_slug(manga_url)
        flat, series = self._series(slug)
        rows = flat.list_field(series, "SeriesEpisode")
        if not rows:
            raise UzayMangaSourceError(f"Uzay Manga lists no chapters for {manga_url}")
        if len(rows) > _MAX_CHAPTERS:
            raise UzayMangaSourceError(
                f"Uzay Manga lists {len(rows)} chapters for {manga_url}, more than "
                f"the {_MAX_CHAPTERS} this scraper accepts")
        total = flat.field(series, "totalEpisode")
        if not _is_int(total) or total != len(rows):
            raise UzayMangaSourceError(
                f"Uzay Manga lists {len(rows)} chapters for {manga_url} but the "
                f"series says {total!r}")

        chapters: Dict[str, Chapter] = {}
        episode_slugs = set()
        for row in rows:
            if not isinstance(row, dict):
                raise UzayMangaSourceError(
                    f"Uzay Manga chapter list for {manga_url} has a malformed row")
            flat.refuse_paid(row, f"a chapter of {slug!r}")
            number = _chapter_number(flat.field(row, "order"))
            episode_slug = flat.field(row, "slug")
            date = flat.date_field(row, "createdDate")
            name = flat.field(row, "name")
            if (number is None or date is None
                    or not isinstance(episode_slug, str) or not _SLUG_RE.match(episode_slug)
                    or not (name is None or isinstance(name, str))):
                raise UzayMangaSourceError(
                    f"Uzay Manga chapter list for {manga_url} has a malformed row")
            if number in chapters or episode_slug in episode_slugs:
                raise UzayMangaSourceError(
                    f"Uzay Manga lists chapter {number} of {manga_url} twice")
            episode_slugs.add(episode_slug)
            chapters[number] = Chapter(
                number=number,
                title=name.strip() if name and name.strip() else None,
                url=f"{self.base_url}/manga/{slug}/{episode_slug}",
                date=date,
            )
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series data."""
        try:
            flat, series = self._series(self._series_slug(manga_url))
            return self._cover(flat, series)
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get a chapter's page images in served order, all or nothing."""
        slug, episode_slug = self._chapter_slugs(chapter_url)
        flat, root = self._data(f"/manga/{slug}/{episode_slug}/__data.json?{_DATA_QUERY}")
        series = flat.object_field(root, "series")
        episode = flat.object_field(root, "episode")
        series_id = flat.field(series, "id")
        if (flat.field(series, "slug") != slug or flat.field(episode, "slug") != episode_slug
                or not _is_int(series_id) or flat.field(episode, "seriesId") != series_id):
            raise UzayMangaSourceError(
                f"Uzay Manga reader answered for another chapter than {chapter_url}")
        flat.refuse_paid(episode, chapter_url)
        if slug not in self._cleared:
            self._series(slug)
        if self._cleared[slug] != series_id:
            raise UzayMangaSourceError(
                f"Uzay Manga reader answered for another series than {chapter_url}")

        images = flat.list_field(episode, "images")
        if not images:
            raise UzayMangaSourceError(f"Uzay Manga reader lists no pages for {chapter_url}")
        if len(images) > _MAX_PAGES:
            raise UzayMangaSourceError(
                f"Uzay Manga reader lists {len(images)} pages for {chapter_url}, "
                f"more than the {_MAX_PAGES} this scraper accepts")

        pages = []
        for image in images:
            match = _PAGE_PATH.match(image) if isinstance(image, str) else None
            if not match or match.group(1) != str(series_id):
                raise UzayMangaSourceError(
                    f"Uzay Manga reader has an unexpected page path for {chapter_url}")
            pages.append(_page_url(f"{self._IMAGE_BASE}{image}"))
        if len(set(pages)) != len(pages):
            raise UzayMangaSourceError(
                f"Uzay Manga reader lists the same image twice for {chapter_url}")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Save one page's served bytes; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _page_url(url)
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise UzayMangaSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise UzayMangaSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise UzayMangaSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download an Uzay Manga page: %s", e)
            return False
