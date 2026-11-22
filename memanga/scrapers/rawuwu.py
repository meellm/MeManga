"""
Raw UwU raw manga scraper
https://rawuwu.net

A series is https://rawuwu.net/raw/<id>. Search, series details, chapter
lists and page lists come from the site's public JSON routes under /spa.

A chapter list is every row the series reply names. Numbers the reply does
not name are not filled in, and the list says nothing about chapters the
site does not carry. A chapter's address carries its id in a fragment,
which is never sent, so a page list can be checked against the row it came
from.

Search reads one page. A reply that says more results follow fails instead
of being cut short, because the site's paging is not known here.

The reader reply has a boolean ``hidden`` whose meaning is not known. It
neither blocks nor unlocks a chapter: the reply must still name the chapter
and serve its pages, and any field outside the known shape fails.

Replies do not state a series' language or rating, so no language is
claimed and the catalogue is treated as one that may include adult series.
"""

import http.cookiejar
import json
import logging
import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import quote, urlsplit

import requests
from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "rawuwu.net"
_BASE_URL = f"https://{_HOST}"
_API_URL = f"{_BASE_URL}/spa"
_IMAGE_SERVER = "https://s3.rawuwu.net/"
_REFERER = f"{_BASE_URL}/"

_ID = r"[1-9][0-9]{0,11}"
_NUMBER_TEXT = r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?"
_PAGE_FILE = r"[0-9]{3,4}-[1-9][0-9]{0,4}x[1-9][0-9]{0,4}\.webp"

_SERIES_PATH = re.compile(rf"/raw/({_ID})/?")
_CHAPTER_PATH = re.compile(rf"/read/({_ID})/chapter-({_NUMBER_TEXT})")
_CHAPTER_FRAGMENT = re.compile(rf"id=({_ID})")
_CHAPTER_ID = re.compile(_ID)
_NUMBER = re.compile(_NUMBER_TEXT)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_PAGE_SOURCE = re.compile(rf"data/[0-9a-f]{{2}}/[0-9a-f]{{2}}/({_ID})/({_ID})/{_PAGE_FILE}")
_PAGE_URL = re.compile(re.escape(_IMAGE_SERVER) + _PAGE_SOURCE.pattern)

# Exactly what these objects hold. A field outside them could change what
# a reply means, so it fails instead of being ignored.
_SEARCH_KEYS = {"manga_list", "pagi"}
_SEARCH_ROW_KEYS = {"manga_name", "manga_cover_img", "manga_id", "ja_manga_name",
                    "manga_chapters", "score"}
_PAGING_KEYS = {"pages", "button", "cur_page", "offset"}
_EMPTY_PAGING_KEYS = {"current", "offset"}
_SERIES_KEYS = {"detail", "tags", "authors", "chapters"}
_DETAIL_KEYS = {"manga_id", "manga_name", "manga_others_name", "manga_status",
                "manga_description", "manga_date_published", "manga_updated", "manga_cover_img",
                "manga_cover_img_normal", "manga_cover_img_full", "manga_views"}
_CHAPTER_KEYS = {"chapter_id", "chapter_title", "chapter_number", "chapter_views",
                 "chapter_date_published"}
_READER_KEYS = {"prev", "next", "hidden", "chapter_detail", "options"}
_READER_DETAIL_KEYS = {"manga_id", "manga_others_name", "manga_name", "chapter_id",
                       "chapter_title", "chapter_number", "chapter_date_published",
                       "manga_cover_img", "manga_cover_img_normal", "manga_cover_img_full",
                       "tags", "chapter_content", "server", "slaves"}

_MAX_REPLY_BYTES = 16 * 1024 * 1024
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_MAX_PAGES = 1000


class RawUwuSourceError(RuntimeError):
    """Raw UwU did not serve what was asked for, or served it in a shape
    this scraper does not know."""


def _failure(error: BaseException) -> str:
    """A short description of a failed request: its status or its kind."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _no_constant(name: str):
    raise ValueError(f"not JSON: {name}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _label(text: str) -> str:
    """A chapter number in its one written form: 12, 12.5."""
    return format(Decimal(text).normalize(), "f")


def _site_parts(url: Any):
    try:
        parts = urlsplit(url)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Not a Raw UwU URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST:
        raise ValueError(f"Not a Raw UwU URL: {url}")
    return parts


def series_id(url: str) -> int:
    """The numeric id of a series URL; anything else raises ValueError."""
    parts = _site_parts(url)
    match = _SERIES_PATH.fullmatch(parts.path)
    if parts.query or parts.fragment or not match:
        raise ValueError(f"Not a Raw UwU series URL: {url}")
    return int(match.group(1))


def chapter_parts(url: str) -> Tuple[int, str, int]:
    """(series id, chapter number, chapter id) of a chapter URL."""
    parts = _site_parts(url)
    path = _CHAPTER_PATH.fullmatch(parts.path)
    fragment = _CHAPTER_FRAGMENT.fullmatch(parts.fragment)
    if parts.query or not path or not fragment or _label(path.group(2)) != path.group(2):
        raise ValueError(f"Not a Raw UwU chapter URL: {url}")
    return int(path.group(1)), path.group(2), int(fragment.group(1))


def _title(value: Any) -> str:
    if not (isinstance(value, str) and value.strip()):
        raise RawUwuSourceError("reply has no usable title")
    return value.strip()


def _cover(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _chapter_id(value: Any) -> int:
    """A chapter id, which the site serves as a number or a digit string."""
    if _is_int(value) and _CHAPTER_ID.fullmatch(str(value)):
        return value
    if isinstance(value, str) and _CHAPTER_ID.fullmatch(value):
        return int(value)
    raise RawUwuSourceError("chapter has no usable id")


def _chapter_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RawUwuSourceError("chapter has no usable number")
    text = str(value)
    if not _NUMBER.fullmatch(text):
        raise RawUwuSourceError("chapter has no usable number")
    return _label(text)


def _date(value: Any) -> Optional[str]:
    """A row's UTC date as served, or None when it has no usable one."""
    if not (isinstance(value, str) and _DATE.fullmatch(value)):
        return None
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return value


def _check_one_page(paging: Any) -> None:
    """The paging of a reply with results: it must be the only page."""
    if not isinstance(paging, dict) or set(paging) != _PAGING_KEYS:
        raise RawUwuSourceError("search paging is not in the known shape")
    button, pages = paging["button"], paging["pages"]
    if not (isinstance(button, dict) and set(button) == {"next", "prev"}
            and _is_int(button["next"]) and _is_int(button["prev"])
            and isinstance(pages, list)
            and all(isinstance(page, dict) and set(page) == {"page", "act"}
                    and _is_int(page["page"]) and isinstance(page["act"], bool)
                    for page in pages)):
        raise RawUwuSourceError("search paging is not in the known shape")
    if button["next"] != 0 or len(pages) > 1:
        raise RawUwuSourceError(
            "Raw UwU has more search results than this scraper reads; "
            "narrow the search or add the series by its URL")
    if not (len(pages) == 1 and pages[0]["page"] == 1 and pages[0]["act"] is True
            and button["prev"] == 0
            and _is_int(paging["cur_page"]) and paging["cur_page"] == 1
            and _is_int(paging["offset"]) and paging["offset"] == 0):
        raise RawUwuSourceError("search paging is not in the known shape")


def _check_empty_paging(paging: Any) -> None:
    """The paging the site serves with an empty result."""
    if not (isinstance(paging, dict) and set(paging) == _EMPTY_PAGING_KEYS
            and _is_int(paging["current"]) and paging["current"] == 1
            and _is_int(paging["offset"]) and paging["offset"] == 0):
        raise RawUwuSourceError("search paging is not in the known shape")


def _search_result(row: Any) -> Tuple[Manga, int]:
    """One search row and its series id. Its chapter fields are not read."""
    if not isinstance(row, dict) or set(row) != _SEARCH_ROW_KEYS:
        raise RawUwuSourceError("search row is not in the known shape")
    series = row["manga_id"]
    if not (_is_int(series) and _CHAPTER_ID.fullmatch(str(series))):
        raise RawUwuSourceError("search row has no usable id")
    return Manga(title=_title(row["manga_name"]), url=f"{_BASE_URL}/raw/{series}",
                 cover_url=_cover(row["manga_cover_img"])), series


def _chapter(row: Any, series: int) -> Tuple[Chapter, int]:
    """One chapter row, checked field by field, and its served id."""
    if not isinstance(row, dict) or set(row) != _CHAPTER_KEYS:
        raise RawUwuSourceError("chapter row is not in the known shape")
    chapter_id = _chapter_id(row["chapter_id"])
    number = _chapter_number(row["chapter_number"])
    title = row["chapter_title"]
    if not isinstance(title, str):
        raise RawUwuSourceError("chapter has no usable title")
    return Chapter(
        number=number,
        title=title.strip() or None,
        url=f"{_BASE_URL}/read/{series}/chapter-{number}#id={chapter_id}",
        date=_date(row["chapter_date_published"]),
    ), chapter_id


def _reader_pages(data: Any, series: int, number: str, chapter: int) -> List[str]:
    """The page URLs of a reader reply for this series and chapter."""
    if not isinstance(data, dict) or set(data) != _READER_KEYS:
        raise RawUwuSourceError("reader reply is not in the known shape")
    if not isinstance(data["hidden"], bool):
        raise RawUwuSourceError("reader reply is not in the known shape")
    detail = data["chapter_detail"]
    if not isinstance(detail, dict) or set(detail) != _READER_DETAIL_KEYS:
        raise RawUwuSourceError("reader reply is not in the known shape")
    if not (_is_int(detail["manga_id"]) and detail["manga_id"] == series):
        raise RawUwuSourceError("reader reply is not for this series")
    _title(detail["manga_name"])
    if (_chapter_id(detail["chapter_id"]) != chapter
            or _chapter_number(detail["chapter_number"]) != number):
        raise RawUwuSourceError("reader reply is not for this chapter")
    if detail["server"] != _IMAGE_SERVER:
        raise RawUwuSourceError("reader reply names an unexpected image host")
    content = detail["chapter_content"]
    if not isinstance(content, str):
        raise RawUwuSourceError("reader reply has no page list")
    images = BeautifulSoup(content, "html.parser").find_all("img")
    if not images or len(images) > _MAX_PAGES:
        raise RawUwuSourceError("reader reply has no usable page list")
    urls = []
    for image in images:
        source = image.get("data-src")
        page = _PAGE_SOURCE.fullmatch(source) if isinstance(source, str) else None
        if page is None or (int(page.group(1)), int(page.group(2))) != (series, chapter):
            raise RawUwuSourceError("reader reply lists an unusable page address")
        urls.append(_IMAGE_SERVER + source)
    if len(set(urls)) != len(urls):
        raise RawUwuSourceError("reader reply lists a page twice")
    return urls


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Raw UwU: could not remove a failed page file")


class RawUwuScraper(BaseScraper):
    """Scraper for Raw UwU (rawuwu.net).

    A chapter list is every row the series reply names; it is not a claim
    that the series is complete.
    """

    name = "rawuwu"
    base_url = _BASE_URL
    engine = "api"
    # Replies do not state a series' language, so none is claimed.
    content_language = None
    # Replies carry no rating, so the catalogue may include adult series.
    nsfw = True

    def __init__(self):
        super().__init__()
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    def _fetch(self, url: str, limit: int, referer: Optional[str] = None) -> bytes:
        """One whole response body. Redirects are not followed."""
        headers = {"Referer": referer} if referer else {}
        response = None
        try:
            response = self._request(url, stream=True, allow_redirects=False, headers=headers)
            if response.status_code != 200:
                raise RawUwuSourceError(f"Raw UwU answered HTTP {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise RawUwuSourceError("Raw UwU's reply is too large")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            raise RawUwuSourceError(f"Raw UwU did not answer ({_failure(e)})") from None
        finally:
            if response is not None:
                response.close()

    def _api(self, path: str) -> Any:
        body = self._fetch(f"{_API_URL}{path}", _MAX_REPLY_BYTES)
        try:
            return json.loads(body, parse_constant=_no_constant)
        except ValueError:
            raise RawUwuSourceError("Raw UwU's reply is not JSON") from None

    def _series(self, series: int) -> dict:
        data = self._api(f"/manga/{series}")
        if not isinstance(data, dict) or set(data) != _SERIES_KEYS:
            raise RawUwuSourceError("series reply is not in the known shape")
        detail = data["detail"]
        if not isinstance(detail, dict) or set(detail) != _DETAIL_KEYS:
            raise RawUwuSourceError("series reply is not in the known shape")
        if not (_is_int(detail["manga_id"]) and detail["manga_id"] == series):
            raise RawUwuSourceError("reply is not for this series")
        _title(detail["manga_name"])
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The series the site's search serves, in its order.

        The query is sent in composed Unicode with every character kept.
        A reply that says more results follow raises.
        """
        keyword = unicodedata.normalize("NFC", query).strip()
        if not keyword:
            return []
        data = self._api(f"/search?query={quote(keyword, safe='')}&page=1")
        if not isinstance(data, dict) or set(data) != _SEARCH_KEYS:
            raise RawUwuSourceError("search reply is not in the known shape")
        rows = data["manga_list"]
        if not isinstance(rows, list):
            raise RawUwuSourceError("search reply has no result list")
        if not rows:
            _check_empty_paging(data["pagi"])
            return []
        _check_one_page(data["pagi"])
        results, seen = [], set()
        for row in rows:
            manga, series = _search_result(row)
            if series in seen:
                raise RawUwuSourceError("a series is listed twice")
            seen.add(series)
            results.append(manga)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter row the series reply names, by number."""
        series = series_id(manga_url)
        rows = self._series(series)["chapters"]
        if not isinstance(rows, list):
            raise RawUwuSourceError("series reply has no chapter list")
        if not rows:
            raise RawUwuSourceError("series reply lists no chapters")
        chapters, ids, numbers = [], set(), set()
        for row in rows:
            chapter, chapter_id = _chapter(row, series)
            if chapter_id in ids:
                raise RawUwuSourceError("a chapter id is listed twice")
            if chapter.number in numbers:
                raise RawUwuSourceError("a chapter number is listed twice")
            ids.add(chapter_id)
            numbers.add(chapter.number)
            chapters.append(chapter)
        logger.info("Raw UwU: listing the %d chapter(s) the series reply names", len(chapters))
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover the series reply names, if any."""
        try:
            return _cover(self._series(series_id(manga_url))["detail"]["manga_cover_img"])
        except (RawUwuSourceError, ValueError):
            return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the order the reply lists them."""
        series, number, chapter = chapter_parts(chapter_url)
        return _reader_pages(self._api(f"/manga/{series}/{number}"), series, number, chapter)

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the image host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        if not (isinstance(url, str) and _PAGE_URL.fullmatch(url)):
            logger.debug("Raw UwU page refused: not a known page address")
            _discard(path)
            return False
        try:
            content = self._fetch(url, _MAX_PAGE_BYTES, referer=_REFERER)
        except RawUwuSourceError as e:
            logger.debug("Raw UwU page failed: %s", e)
            _discard(path)
            return False
        if not _identifies_as_image(content):
            logger.debug("Raw UwU page is not an image")
            _discard(path)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            logger.debug("Raw UwU page could not be saved")
            _discard(path)
            return False
        return True
