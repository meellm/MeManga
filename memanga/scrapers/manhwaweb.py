"""
ManhwaWeb scraper - Spanish manhwa, manga and manhua community library
Site: manhwaweb.com

The site is a React app over a public JSON API on api.manhwaweb.com:

* search   -> GET /manhwa/library?buscar=<query>&erotico=no&page=0 returns
              ``data`` rows with ``real_id``, ``the_real_name``, ``_imagen``
              and ``_erotico``.
* chapters -> GET /manhwa/see/<real_id> returns the series with ``chapters``.
              Each row has a ``chapter`` number and ``versions``, the uploads
              of that chapter, each with a reader ``link`` and a ``create``
              time in milliseconds. A version without a time is not released.
* pages    -> GET /chapters/see/<id> returns ``chapter.img``, the page images.

The reader id comes from the served version link, with the series ``_id``
replaced by its ``real_id`` the way the site's own links are built. It is never
derived from the chapter number.

The library also holds erotic titles and untranslated raws. This scraper lists
and downloads only titles whose own ``_erotico`` is exactly ``"no"``, and only
chapters up to ``numero_cap_esp``, the last chapter the site tracks in Spanish.
A series the site marks with ``copyright`` has its chapters withheld on the
site, so it is reported as unavailable here too.

When a chapter has several dated versions, the earliest one is used (the lowest
reader id on a tie), so a later upload never changes an existing chapter's URL.
"""

import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "manhwaweb.com"
_API_URL = "https://api.manhwaweb.com"
_IMAGE_HOST = "img2mw.xyz"

# One URL path segment as the API serves it for titles and chapters.
_ID = r"[A-Za-z0-9][A-Za-z0-9_.~-]{0,199}"
_ID_RE = re.compile(rf"^{_ID}$")
_SERIES_PATH = re.compile(rf"^/(?:manhwa|manga)/({_ID})/?$")
_CHAPTER_PATH = re.compile(rf"^/leer/({_ID})/?$")
_IMAGE_PATH = re.compile(r"^/(?:[^/?#\s]+/)+[^/?#\s]+\.(?:webp|jpe?g|png)$", re.I)
_PLAIN_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
# Reader ids of untranslated uploads end in "raw" ("<id>-10raw").
_RAW_ID = re.compile(r"raw$", re.I)

# Release times are milliseconds since the epoch (13 digits).
_MIN_RELEASE_MS = 10 ** 12
_MAX_RELEASE_MS = 10 ** 13

# Bounds on what one answer may hold.
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class ManhwaWebSourceError(RuntimeError):
    """manhwaweb.com answered with data this scraper cannot use."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _chapter_number(raw) -> Optional[str]:
    """A served chapter number as a stable string ("12", "68.05"), or None."""
    if _is_int(raw):
        text = str(raw)
    elif isinstance(raw, float):
        if not math.isfinite(raw):
            return None
        text = repr(raw)
    elif isinstance(raw, str) and _PLAIN_NUMBER.match(raw.strip()):
        text = raw.strip()
    else:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    return format(value.normalize(), "f")


def _release_ms(value) -> Optional[int]:
    """A version's release time in milliseconds; None when it has none."""
    if value is None:
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if not _is_int(value) or not _MIN_RELEASE_MS <= value < _MAX_RELEASE_MS:
        raise ValueError("not a release time")
    return value


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


def _page_url(value) -> str:
    """``value`` if it is a page image URL on the image host, else raise."""
    parts = _split(value)
    if (parts is None or parts.scheme != "https" or parts.hostname != _IMAGE_HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment
            or not _IMAGE_PATH.match(parts.path)
            or any(part in (".", "..") for part in parts.path.split("/"))):
        raise ManhwaWebSourceError("Unexpected ManhwaWeb page image URL")
    return value


class ManhwaWebScraper(BaseScraper):
    """Scraper for ManhwaWeb (manhwaweb.com)."""

    name = "manhwaweb"
    base_url = "https://manhwaweb.com"
    content_language = "es"  # only chapters tracked in Spanish are listed
    engine = "api"
    nsfw = False  # erotic titles are left out

    _API_HEADERS = {
        "Accept": "application/json",
        "Referer": base_url + "/",
    }
    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    # URLs

    @staticmethod
    def _site_path(url: str) -> Optional[str]:
        parts = _split(url)
        if parts is None:
            return None
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if parts.scheme not in ("http", "https") or host != _HOST:
            return None
        return parts.path

    def _series_id(self, manga_url: str) -> str:
        path = self._site_path(manga_url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise ManhwaWebSourceError(f"Not a ManhwaWeb series URL: {manga_url}")
        return match.group(1)

    def _reader_id(self, chapter_url: str) -> str:
        path = self._site_path(chapter_url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise ManhwaWebSourceError(f"Not a ManhwaWeb chapter URL: {chapter_url}")
        return match.group(1)

    def _api(self, path: str) -> Dict:
        """One API answer as a JSON object; redirects are not followed."""
        url = f"{_API_URL}{path}"
        response = self._request(url, headers=self._API_HEADERS, allow_redirects=False)
        if response.status_code != 200:
            raise ManhwaWebSourceError(
                f"ManhwaWeb answered HTTP {response.status_code} for {url}")
        try:
            data = response.json()
        except ValueError:
            raise ManhwaWebSourceError(f"ManhwaWeb returned no JSON for {url}") from None
        if not isinstance(data, dict):
            raise ManhwaWebSourceError(f"ManhwaWeb returned no JSON object for {url}")
        return data

    @staticmethod
    def _cover(row: Dict) -> Optional[str]:
        value = row.get("_imagen")
        return value if isinstance(value, str) and value.startswith("https://") else None

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search titles; only those marked exactly as not erotic are listed."""
        query = (query or "").strip()
        if not query:
            return []
        params = urlencode({"buscar": query, "erotico": "no", "page": 0})
        data = self._api(f"/manhwa/library?{params}")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ManhwaWebSourceError(
                f"ManhwaWeb search for {query!r} returned no result list")

        results = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ManhwaWebSourceError(
                    f"ManhwaWeb search for {query!r} returned a malformed row")
            title, real_id = row.get("the_real_name"), row.get("real_id")
            if (not isinstance(title, str) or not title.strip()
                    or not isinstance(real_id, str) or not _ID_RE.match(real_id)):
                raise ManhwaWebSourceError(
                    f"ManhwaWeb search for {query!r} returned a row without a "
                    f"usable title and id")
            if row.get("_erotico") != "no" or row.get("copyright") or real_id in seen:
                continue
            seen.add(real_id)
            results.append(Manga(
                title=title.strip(),
                url=f"{self.base_url}/manhwa/{real_id}",
                cover_url=self._cover(row),
            ))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series(self, series_id: str) -> Dict:
        """A series that is marked as not erotic and is not withheld."""
        data = self._api(f"/manhwa/see/{series_id}")
        real_id, own_id = data.get("real_id"), data.get("_id")
        if (not isinstance(real_id, str) or not _ID_RE.match(real_id)
                or not isinstance(own_id, str) or not _ID_RE.match(own_id)
                or series_id not in (real_id, own_id)):
            raise ManhwaWebSourceError(
                f"ManhwaWeb answered for another series than {series_id!r}")
        if data.get("_erotico") != "no":
            raise ManhwaWebSourceError(
                f"ManhwaWeb does not mark {series_id!r} as not erotic; only "
                f"non-erotic titles are supported")
        if data.get("copyright"):
            raise ManhwaWebSourceError(
                f"ManhwaWeb withholds the chapters of {series_id!r} for copyright")
        return data

    @staticmethod
    def _version_reader_id(link, own_id: str, real_id: str, series_id: str) -> str:
        """The reader id of a served version link, checked against its series."""
        parts = _split(link)
        host = (parts.hostname or "").lower() if parts is not None else ""
        if host.startswith("www."):
            host = host[4:]
        match = _CHAPTER_PATH.match(parts.path) if parts is not None else None
        if (parts is None or parts.scheme != "https" or host != _HOST
                or parts.port is not None or parts.query or parts.fragment or not match):
            raise ManhwaWebSourceError(
                f"ManhwaWeb lists an unexpected chapter link for {series_id!r}")
        reader_id = match.group(1).replace(own_id, real_id, 1)
        if not _ID_RE.match(reader_id) or not reader_id.startswith(f"{real_id}-"):
            raise ManhwaWebSourceError(
                f"ManhwaWeb lists a chapter link of another series for {series_id!r}")
        return reader_id

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get the released Spanish chapters of a series, oldest first."""
        series_id = self._series_id(manga_url)
        series = self._series(series_id)
        real_id, own_id = series["real_id"], series["_id"]

        spanish_up_to = _chapter_number(series.get("numero_cap_esp"))
        if spanish_up_to is None:
            raise ManhwaWebSourceError(
                f"ManhwaWeb does not state the Spanish chapters of {series_id!r}")
        rows = series.get("chapters")
        if not isinstance(rows, list) or not rows:
            raise ManhwaWebSourceError(f"ManhwaWeb lists no chapters for {series_id!r}")
        if len(rows) > _MAX_CHAPTERS:
            raise ManhwaWebSourceError(
                f"ManhwaWeb lists {len(rows)} chapters for {series_id!r}, more "
                f"than the {_MAX_CHAPTERS} this scraper accepts")

        # number -> (release time, reader id) of its earliest dated version
        chosen: Dict[str, Tuple[int, str]] = {}
        owners: Dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ManhwaWebSourceError(
                    f"ManhwaWeb chapter list for {series_id!r} has a malformed row")
            number = _chapter_number(row.get("chapter"))
            versions = row.get("versions")
            if number is None or not isinstance(versions, list):
                raise ManhwaWebSourceError(
                    f"ManhwaWeb chapter list for {series_id!r} has a row without a "
                    f"usable number and versions")
            if Decimal(number) > Decimal(spanish_up_to):
                continue
            for version in versions:
                if not isinstance(version, dict):
                    raise ManhwaWebSourceError(
                        f"ManhwaWeb chapter {number} of {series_id!r} has a "
                        f"malformed version")
                try:
                    released = _release_ms(version.get("create"))
                except ValueError:
                    raise ManhwaWebSourceError(
                        f"ManhwaWeb chapter {number} of {series_id!r} has an "
                        f"unusable release time") from None
                if released is None:
                    continue
                reader_id = self._version_reader_id(
                    version.get("link"), own_id, real_id, series_id)
                if _RAW_ID.search(reader_id):
                    continue
                if owners.setdefault(reader_id, number) != number:
                    raise ManhwaWebSourceError(
                        f"ManhwaWeb lists one reader link under two chapters of "
                        f"{series_id!r}")
                candidate = (released, reader_id)
                if number not in chosen or candidate < chosen[number]:
                    chosen[number] = candidate

        if not chosen:
            raise ManhwaWebSourceError(
                f"ManhwaWeb lists no released Spanish chapters for {series_id!r}")
        chapters = [
            Chapter(
                number=number,
                title=None,
                url=f"{self.base_url}/leer/{reader_id}",
                date=datetime.fromtimestamp(released / 1000, timezone.utc).strftime("%Y-%m-%d"),
            )
            for number, (released, reader_id) in chosen.items()
        ]
        return sorted(chapters)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series API."""
        try:
            return self._cover(self._series(self._series_id(manga_url)))
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get the ordered page images of a chapter, all or nothing."""
        reader_id = self._reader_id(chapter_url)
        data = self._api(f"/chapters/see/{reader_id}")

        if data.get("erotico") != "no":
            raise ManhwaWebSourceError(
                f"ManhwaWeb does not mark {chapter_url} as not erotic; only "
                f"non-erotic titles are supported")
        real_id = data.get("real_id")
        if not isinstance(real_id, str) or not real_id or not reader_id.startswith(f"{real_id}-"):
            raise ManhwaWebSourceError(
                f"ManhwaWeb reader answered for another series than {chapter_url}")
        chapter = data.get("chapter")
        images = chapter.get("img") if isinstance(chapter, dict) else None
        if not isinstance(images, list) or not images:
            raise ManhwaWebSourceError(f"ManhwaWeb reader lists no pages for {chapter_url}")
        if len(images) > _MAX_PAGES:
            raise ManhwaWebSourceError(
                f"ManhwaWeb reader lists {len(images)} pages for {chapter_url}, "
                f"more than the {_MAX_PAGES} this scraper accepts")

        pages = [_page_url(image) for image in images]
        if len(set(pages)) != len(pages):
            raise ManhwaWebSourceError(
                f"ManhwaWeb reader lists the same image twice for {chapter_url}")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _page_url(url)
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise ManhwaWebSourceError(
                    f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise ManhwaWebSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise ManhwaWebSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a ManhwaWeb page: %s", e)
            return False
