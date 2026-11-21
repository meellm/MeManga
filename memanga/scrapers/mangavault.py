"""
MangaVault scraper - Spanish manhwa, manga and manhua library
Site: mangavault.lat

* search   -> GET /api/mangas/search?q=<query>&nsfwMode=exclude&page=1 returns
              ``{results, hasMore}``. No results is exactly an empty list with
              ``hasMore`` false.
* chapters -> a series page holds an Astro island whose props carry
              ``chapters``, ``mangaSlug`` and ``mangaId``, and which renders one
              link per chapter.
* pages    -> a reader page holds one Astro island whose props carry
              ``imageUrls`` with the series and chapter they belong to.

Islands are found by the data they hold, not by component name, and their props
are read as data. A chapter or reader answer with a field this scraper does not
know fails, so a new access rule is never read past.

The site has a +18 section, and series and reader pages do not say whether a
title belongs to it. Search asks for safe titles only, but a direct URL is not
checked, so the source is marked NSFW.
"""

import json
import logging
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"mangavault.lat", "www.mangavault.lat"})
_MEDIA_HOST = "media.mangavault.lat"

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}"
_NUMBER_TEXT = r"\d+(?:\.\d+)?"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/manga/({_SLUG})/({_NUMBER_TEXT})/?$")
_HEX_ID = re.compile(r"^[0-9a-f]{32}$")
_CREATED_AT = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}$")
_PAGE_PATH = re.compile(
    rf"^/manga/([0-9a-f]{{32}})/ch-({_NUMBER_TEXT})/(\d{{4}})-[0-9a-f]{{8}}\.webp$")
_COVER_PATH = re.compile(r"^/covers/[A-Za-z0-9._-]+\.(?:jpe?g|png|webp)$", re.I)

_COMIC_TYPES = frozenset({"manga", "manhwa", "manhua", "comic"})
_SERIES_KEYS = frozenset({"chapters", "mangaSlug", "mangaId", "isAuthenticated",
                          "readChapterNumbers"})
_ROW_KEYS = frozenset({"id", "chapter_number", "title", "created_at"})
_READER_KEYS = frozenset({"manga", "chapter", "imageUrls", "prevChapter", "nextChapter",
                          "isAdminOrMod", "currentUserId"})
_READER_MANGA_KEYS = frozenset({"id", "slug", "title"})
_READER_CHAPTER_KEYS = frozenset({"id", "chapter_number", "title"})

_MAX_QUERY = 100
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class MangaVaultSourceError(RuntimeError):
    """mangavault.lat answered with data this scraper cannot use."""


def _decode(value):
    """One Astro prop: ``[0, value]`` or ``[1, array]``, as plain data."""
    if not (isinstance(value, list) and len(value) == 2 and type(value[0]) is int):
        raise ValueError("not an Astro value")
    tag, payload = value
    if tag == 1 and isinstance(payload, list):
        return [_decode(item) for item in payload]
    if tag == 0 and isinstance(payload, dict):
        return {key: _decode(item) for key, item in payload.items()}
    if tag == 0 and not isinstance(payload, list):
        return payload
    raise ValueError("unknown Astro value")


def _island(soup: BeautifulSoup, key: str, keys: frozenset, where: str):
    """The one island whose props hold ``key``, with exactly ``keys``."""
    found = []
    for island in soup.select("astro-island[props]"):
        try:
            raw = json.loads(island["props"])
            if not isinstance(raw, dict):
                continue
            props = {name: _decode(value) for name, value in raw.items()}
        except (ValueError, RecursionError):
            continue
        if key in props:
            found.append((island, props))
    if len(found) != 1:
        raise MangaVaultSourceError(f"MangaVault page {where} has no single {key} data")
    if set(found[0][1]) != keys:
        raise MangaVaultSourceError(f"MangaVault page {where} has unexpected {key} data")
    return found[0]


def _number_text(raw) -> Optional[str]:
    """A served chapter number as a stable string ("56", "12.5"), or None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        text = str(raw)
    elif isinstance(raw, float) and math.isfinite(raw):
        text = repr(raw)
    else:
        return None
    value = Decimal(text)
    return format(value.normalize(), "f") if value >= 0 else None


def _split(url):
    """urlsplit() of a string URL with a valid port, or None."""
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
            or (parts.hostname or "").lower() not in _SITE_HOSTS
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment):
        return None
    return parts.path


def _media_path(url) -> Optional[str]:
    parts = _split(url)
    if (parts is None or parts.scheme != "https" or parts.hostname != _MEDIA_HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment):
        return None
    return parts.path


def _cover(url) -> Optional[str]:
    path = _media_path(url)
    return url.strip() if path is not None and _COVER_PATH.match(path) else None


def _page_match(url):
    path = _media_path(url)
    match = _PAGE_PATH.match(path) if path is not None else None
    if match is None:
        raise MangaVaultSourceError("Unexpected MangaVault page image URL")
    return match


class MangaVaultScraper(BaseScraper):
    """Scraper for MangaVault (mangavault.lat)."""

    name = "mangavault"
    base_url = "https://mangavault.lat"
    content_language = "es"  # Spanish-language site
    nsfw = True  # the site has a +18 section; only search filters it

    _API_HEADERS = {"Accept": "application/json", "Referer": base_url + "/explore"}
    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    def __init__(self):
        super().__init__()
        # Worker copies share this: each listed chapter's (chapter id, series id).
        self._listed: Dict[str, Tuple[str, str]] = {}

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise MangaVaultSourceError(f"Not a MangaVault series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, str, str]:
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise MangaVaultSourceError(f"Not a MangaVault chapter URL: {url}")
        slug = match.group(1)
        number = format(Decimal(match.group(2)).normalize(), "f")
        return f"{self.base_url}/manga/{slug}/{number}", slug, number

    def _page(self, url: str, what: str) -> BeautifulSoup:
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise MangaVaultSourceError(
                f"MangaVault answered HTTP {response.status_code} for {what} {url}")
        return BeautifulSoup(response.text, "html.parser")

    @staticmethod
    def _owns(manga_id, slug: str) -> bool:
        """Whether a series id is the one the slug ends with."""
        return (isinstance(manga_id, str) and bool(_HEX_ID.match(manga_id))
                and manga_id.startswith(slug[-6:]))

    # Search

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's safe search, without novels."""
        query = (query or "").strip()[:_MAX_QUERY].strip()
        if not query:
            return []
        params = urlencode({"q": query, "nsfwMode": "exclude", "page": 1})
        url = f"{self.base_url}/api/mangas/search?{params}"
        response = self._request(url, headers=self._API_HEADERS, allow_redirects=False)
        if response.status_code != 200:
            raise MangaVaultSourceError(
                f"MangaVault answered HTTP {response.status_code} for search {url}")
        try:
            data = response.json()
        except ValueError:
            raise MangaVaultSourceError(f"MangaVault search {url} returned no JSON") from None
        rows = data.get("results") if isinstance(data, dict) else None
        more = data.get("hasMore") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not isinstance(more, bool):
            raise MangaVaultSourceError(f"MangaVault search {url} did not serve a result list")
        if not rows and more:
            raise MangaVaultSourceError(f"MangaVault search {url} has no rows but more pages")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise MangaVaultSourceError(f"MangaVault search {url} has a malformed row")
            slug, title, kind, adult = (row.get("slug"), row.get("title"),
                                        row.get("content_type"), row.get("is_nsfw"))
            if (not isinstance(slug, str) or not re.fullmatch(_SLUG, slug)
                    or not self._owns(row.get("id"), slug)
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(adult, bool)
                    or kind not in _COMIC_TYPES | {"novel"}):
                raise MangaVaultSourceError(f"MangaVault search {url} has a malformed row")
            if slug in seen:
                raise MangaVaultSourceError(f"MangaVault search {url} lists {slug} twice")
            seen.add(slug)
            if adult or kind == "novel":
                continue
            results.append(Manga(title=title.strip(), url=f"{self.base_url}/manga/{slug}",
                                 cover_url=_cover(row.get("cover_url"))))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter a series page serves, oldest first."""
        series_url, slug = self._series_parts(manga_url)
        island, props = _island(self._page(series_url, "series page"), "chapters",
                                _SERIES_KEYS, series_url)
        manga_id = props["mangaId"]
        if props["mangaSlug"] != slug or not self._owns(manga_id, slug):
            raise MangaVaultSourceError(f"MangaVault answered for another series than {slug}")
        if props["isAuthenticated"] is not False or props["readChapterNumbers"] != []:
            raise MangaVaultSourceError(f"MangaVault series page {series_url} is not anonymous")
        rows = props["chapters"]
        if not isinstance(rows, list) or not rows:
            raise MangaVaultSourceError(f"MangaVault lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaVaultSourceError(f"MangaVault lists too many chapters for {slug}")

        served_links: Set[str] = {link["href"] for link in island.select("a[href]")}
        chapters: Dict[str, Chapter] = {}
        listed: Dict[str, Tuple[str, str]] = {}
        chapter_ids = set()
        expected_links = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != _ROW_KEYS:
                raise MangaVaultSourceError(f"MangaVault has an unexpected chapter row for {slug}")
            number = _number_text(row["chapter_number"])
            chapter_id, title, created = row["id"], row["title"], row["created_at"]
            date = _CREATED_AT.match(created) if isinstance(created, str) else None
            if (number is None or date is None
                    or not isinstance(chapter_id, str) or not _HEX_ID.match(chapter_id)
                    or not (title is None or isinstance(title, str))):
                raise MangaVaultSourceError(f"MangaVault has a malformed chapter row for {slug}")
            link = f"/manga/{slug}/{number}"
            if link not in served_links:
                raise MangaVaultSourceError(f"MangaVault does not link chapter {number} of {slug}")
            if number in chapters or chapter_id in chapter_ids:
                raise MangaVaultSourceError(f"MangaVault lists chapter {number} of {slug} twice")
            chapter_ids.add(chapter_id)
            expected_links.add(link)
            url = f"{self.base_url}{link}"
            listed[url] = (chapter_id, manga_id)
            chapters[number] = Chapter(number=number, title=(title or "").strip() or None,
                                       url=url, date=date.group(1))
        if served_links != expected_links:
            raise MangaVaultSourceError(f"MangaVault links other chapters than it lists for {slug}")
        self._listed.update(listed)
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_url, _ = self._series_parts(manga_url)
            meta = self._page(series_url, "series page").select_one(
                'meta[property="og:image"][content]')
            return _cover(meta["content"]) if meta else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in served order, all or nothing."""
        url, slug, number = self._chapter_parts(chapter_url)

        def refused(why: str):
            return MangaVaultSourceError(f"MangaVault chapter {url} {why}")

        _, props = _island(self._page(url, "chapter"), "imageUrls", _READER_KEYS, url)
        manga, chapter = props["manga"], props["chapter"]
        if (not isinstance(manga, dict) or set(manga) != _READER_MANGA_KEYS
                or not isinstance(chapter, dict) or set(chapter) != _READER_CHAPTER_KEYS):
            raise refused("has unexpected reader data")
        if props["isAdminOrMod"] is not False or props["currentUserId"] is not None:
            raise refused("is not an anonymous reader")
        if manga["slug"] != slug or not self._owns(manga["id"], slug):
            raise refused("answered for another series")
        if _number_text(chapter["chapter_number"]) != number:
            raise refused("answered for another chapter")
        chapter_id = chapter["id"]
        if not isinstance(chapter_id, str) or not _HEX_ID.match(chapter_id):
            raise refused("has no chapter id")
        if self._listed.get(url, (chapter_id, manga["id"])) != (chapter_id, manga["id"]):
            raise refused("is not the chapter the series lists")

        images = props["imageUrls"]
        if not isinstance(images, list) or not images:
            raise refused("lists no pages")
        if len(images) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        pages: List[str] = []
        for index, image in enumerate(images):
            try:
                match = _page_match(image)
            except MangaVaultSourceError:
                raise refused(f"has an unexpected image for page {index + 1}") from None
            if (match.group(1) != manga["id"] or match.group(2) != number
                    or int(match.group(3)) != index):
                raise refused(f"has a misplaced image for page {index + 1}")
            pages.append(image.strip())
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            _page_match(url)
            image_url = url.strip()
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise MangaVaultSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise MangaVaultSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise MangaVaultSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a MangaVault page: %s", e)
            return False
