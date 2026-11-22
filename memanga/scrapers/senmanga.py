"""
Sen Manga raw scraper
https://raw.senmanga.com

A raw manga reader with a public JSON API. A series' chapter list and a
chapter's pages come from that API, anonymously.

Series are added by their direct URL (https://raw.senmanga.com/manga/<slug>).
Search is not supported: the site's search endpoint ignores the query, so
it could only return unrelated titles.

The API states no total for a series, so a chapter list is what the series
reply names, not a claim that the series is complete. A chapter's number
is the one the reply gives it: replies are not in chapter or date order,
so a chapter's position says nothing, and its URL id is not its number.

Nothing in a series reply states the language of its pages, so no language
is claimed for the catalogue. It is a general catalogue that may include
adult titles, which are not assessed one by one.
"""

import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "raw.senmanga.com"
_BASE_URL = f"https://{_HOST}"
# The one host the reader's page lists name. It carries another site's
# name, which says nothing about who runs it, so that site is not an alias.
_IMAGE_HOST = "cdn.rawkuma.com"

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SERIES_PATH = re.compile(r"/manga/([^/]+)/?")
_CHAPTER_PATH = re.compile(r"/manga/([^/]+)/chapter-([^/]+)/?")
_NUMBER = re.compile(r"\d{1,9}(?:\.\d{1,6})?")
_TITLE_NUMBER = re.compile(r"Chapter (\d{1,9}(?:\.\d{1,6})?)(?=$|[\s:：–—-])")
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_MAX_PAGE_BYTES = 64 * 1024 * 1024


class SenMangaSourceError(RuntimeError):
    """Sen Manga did not serve what was asked for, or served it in a shape
    this scraper does not know."""


def _failure(error: BaseException) -> str:
    """A short description of a failed request: its status or its kind."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _identifier(value: Any) -> str:
    """A slug or chapter id exactly as served, safe as one URL segment."""
    if not (isinstance(value, str) and _IDENTIFIER.fullmatch(value)):
        raise SenMangaSourceError("reply has an unusable identifier")
    return value


def _site_path(url: Any) -> str:
    try:
        parts = urlsplit(url)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Not a Sen Manga URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST or parts.query or parts.fragment:
        raise ValueError(f"Not a Sen Manga URL: {url}")
    return parts.path


def series_slug(url: str) -> str:
    """The slug of a series URL; anything else raises ValueError."""
    match = _SERIES_PATH.fullmatch(_site_path(url))
    if not match or not _IDENTIFIER.fullmatch(match.group(1)):
        raise ValueError(f"Not a Sen Manga series URL: {url}")
    return match.group(1)


def chapter_ids(url: str) -> Tuple[str, str]:
    """(slug, chapter id) of a chapter URL; anything else raises ValueError."""
    match = _CHAPTER_PATH.fullmatch(_site_path(url))
    if not (match and _IDENTIFIER.fullmatch(match.group(1))
            and _IDENTIFIER.fullmatch(match.group(2))):
        raise ValueError(f"Not a Sen Manga chapter URL: {url}")
    return match.group(1), match.group(2)


def _chapter_number(value: Any) -> Decimal:
    """A chapter's number as served: a whole or decimal numeric string."""
    if not (isinstance(value, str) and _NUMBER.fullmatch(value)):
        raise SenMangaSourceError("chapter has no usable number")
    return Decimal(value)


def _checked_date(value: Any) -> str:
    """A chapter's UTC datetime, kept as served."""
    if not (isinstance(value, str) and _DATETIME.fullmatch(value)):
        raise SenMangaSourceError("chapter has no usable datetime")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise SenMangaSourceError("chapter has no usable datetime") from None
    return value


def _title(value: Any) -> str:
    if not (isinstance(value, str) and value.strip()):
        raise SenMangaSourceError("reply has no usable title")
    return value.strip()


def _cover(item: dict) -> Optional[str]:
    cover = item.get("cover")
    return cover if isinstance(cover, str) and cover.startswith("https://") else None


def _chapter(row: Any, slug: str) -> Tuple[Chapter, str]:
    """One chapter row, checked field by field, and its served id."""
    if not isinstance(row, dict):
        raise SenMangaSourceError("chapter row is not an object")
    chapter_id = _identifier(row.get("url"))
    number = _chapter_number(row.get("number"))
    title = _title(row.get("title"))
    named = _TITLE_NUMBER.match(title)
    if named and Decimal(named.group(1)) != number:
        raise SenMangaSourceError("a chapter's title and number disagree")
    # A title that only repeats the number adds nothing to the label.
    only_number = named is not None and named.end() == len(title)
    return Chapter(
        number=format(number.normalize(), "f"),
        title=None if only_number else title,
        url=f"{_BASE_URL}/manga/{slug}/chapter-{chapter_id}/",
        date=_checked_date(row.get("datetime")),
    ), chapter_id


def _check_reader_identity(data: dict, slug: str, chapter_id: str) -> None:
    """A reader reply must be for this series and this chapter.

    The reply names its chapter by number and carries the series' chapter
    list, so the requested id must select exactly one row there, and that
    row's number and slug must both equal the chapter the reply names.
    """
    series = data.get("series")
    if not isinstance(series, dict) or series.get("slug") != slug:
        raise SenMangaSourceError("reader reply is not for this series")
    rows = series.get("chapterList")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SenMangaSourceError("reader reply has no usable chapter list")
    selected = [row for row in rows if row.get("url") == chapter_id]
    if len(selected) != 1:
        raise SenMangaSourceError("reader reply is not for this chapter")
    chapter = data.get("chapter")
    if not (isinstance(chapter, str) and _NUMBER.fullmatch(chapter)
            and chapter == selected[0].get("number") == selected[0].get("slug")):
        raise SenMangaSourceError("reader reply is not for this chapter")
    for key in ("previousChapter", "nextChapter"):
        if key not in data:
            raise SenMangaSourceError("reader reply has no neighbouring chapter field")
        neighbour = data[key]
        if neighbour is not None and not (isinstance(neighbour, str) and neighbour):
            raise SenMangaSourceError("reader reply has an unusable neighbouring chapter")


def _page_url(value: Any) -> str:
    """A page image URL on the reader's image host; anything else raises."""
    if (not isinstance(value, str) or "?" in value or "#" in value or "\\" in value
            or any(ch.isspace() or ord(ch) < 32 for ch in value)):
        raise SenMangaSourceError("page has an unusable image URL")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise SenMangaSourceError("page has an unusable image URL") from None
    segments = parts.path.split("/")
    if (parts.scheme != "https" or parts.netloc != _IMAGE_HOST
            or not parts.path.startswith("/") or not segments[-1]
            or "." in segments or ".." in segments):
        raise SenMangaSourceError("page image is on an unexpected host or path")
    return value


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Sen Manga: could not remove a failed page file")


class SenMangaScraper(BaseScraper):
    """Scraper for Sen Manga's raw catalogue (raw.senmanga.com).

    Series are added by direct URL; search is not supported. A chapter list
    is what the series reply names; the site states no total, so it is not
    a claim of completeness.
    """

    name = "senmanga"
    base_url = _BASE_URL
    engine = "api"
    # Replies do not state a series' language, so none is claimed.
    content_language = None
    # A general catalogue that may include adult titles.
    nsfw = True

    def _api(self, path: str) -> Any:
        """One API reply. Redirects are not followed."""
        try:
            response = self._request(f"{_BASE_URL}{path}", allow_redirects=False)
        except requests.RequestException as e:
            raise SenMangaSourceError(f"Sen Manga did not answer ({_failure(e)})") from None
        if response.status_code != 200:
            raise SenMangaSourceError(f"Sen Manga answered HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise SenMangaSourceError("Sen Manga's reply is not JSON") from None

    def _series(self, slug: str) -> dict:
        data = self._api(f"/api/manga/{slug}")
        if not isinstance(data, dict) or data.get("slug") != slug:
            raise SenMangaSourceError("reply is not for this series")
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Not supported, and sends nothing: the site's search endpoint
        ignores the query, so any result would be unrelated to it."""
        raise SenMangaSourceError(
            "Sen Manga's search ignores queries; add a series by its direct URL")

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter the series reply names, ordered by number."""
        slug = series_slug(manga_url)
        data = self._series(slug)
        _title(data.get("title"))
        rows = data.get("chapterList")
        if not isinstance(rows, list):
            raise SenMangaSourceError("series reply has no chapter list")
        if not rows:
            raise SenMangaSourceError("series reply lists no chapters")

        chapters, ids, numbers = [], set(), set()
        for row in rows:
            chapter, chapter_id = _chapter(row, slug)
            if chapter_id in ids:
                raise SenMangaSourceError("a chapter id is listed twice")
            if chapter.number in numbers:
                raise SenMangaSourceError("a chapter number is listed twice")
            ids.add(chapter_id)
            numbers.add(chapter.number)
            chapters.append(chapter)
        logger.info("Sen Manga: listing %d chapter(s) the series reply names "
                    "(the site states no total)", len(chapters))
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover the series reply names, if any."""
        try:
            return _cover(self._series(series_slug(manga_url)))
        except (SenMangaSourceError, ValueError):
            return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the order the reader serves."""
        slug, chapter_id = chapter_ids(chapter_url)
        data = self._api(f"/api/read/{slug}/{chapter_id}")
        if not isinstance(data, dict):
            raise SenMangaSourceError("reader reply is not an object")
        _check_reader_identity(data, slug, chapter_id)
        pages = data.get("pages")
        if not isinstance(pages, list):
            raise SenMangaSourceError("reader reply has no page list")
        if not pages:
            raise SenMangaSourceError("reader reply lists no pages")
        urls = [_page_url(page) for page in pages]
        if len(set(urls)) != len(urls):
            raise SenMangaSourceError("reader lists one page twice")
        return urls

    def _fetch_page(self, url: str) -> Optional[bytes]:
        """A page's bytes, or None when it was not served whole."""
        response = None
        try:
            response = self._request(url, stream=True, allow_redirects=False,
                                     headers={"Referer": f"{_BASE_URL}/"})
            if response.status_code != 200:
                logger.debug("Sen Manga page on %s: HTTP %d", _IMAGE_HOST, response.status_code)
                return None
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > _MAX_PAGE_BYTES:
                    logger.debug("Sen Manga page on %s is too large", _IMAGE_HOST)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            logger.debug("Sen Manga page on %s failed (%s)", _IMAGE_HOST, _failure(e))
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            return None
        finally:
            if response is not None:
                response.close()

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the image host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        try:
            _page_url(url)
        except SenMangaSourceError:
            logger.debug("Sen Manga page refused: not on %s", _IMAGE_HOST)
            _discard(path)
            return False
        content = self._fetch_page(url)
        if content is None or not _identifies_as_image(content):
            _discard(path)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            logger.debug("Sen Manga page could not be saved")
            _discard(path)
            return False
        return True
