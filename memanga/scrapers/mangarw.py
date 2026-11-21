"""
MangaRW raw manga scraper
https://mangarw.com

A series is identified by the number at the end of its address,
https://mangarw.com/manga/<slug>/<id>; the slug is decoration and is never
read. Series details, search, chapter lists and page lists come from the
site's public JSON API. Search rows can lag the chapter list, so nothing
about a series' chapters is read from them.

A chapter list is every row the API names for a series, checked against
the count the series states. It says nothing about chapters the site no
longer lists. A chapter's address carries its series in a fragment, and a
page's address carries its chapter the same way. Fragments are never sent:
they let a page list be checked against both ids, and let each image be
requested from its own reader page.

Replies do not state the language of a series' pages, so none is claimed.
The API flags adult series one by one, so the catalogue is treated as one
that may include them.
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

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "mangarw.com"
_BASE_URL = f"https://{_HOST}"
_API_URL = "https://api.mangarw.com/api/v1"
_STORAGE_URL = "https://storage.mangabuzz.org"
_REFERER = f"{_BASE_URL}/"

_ID = r"[1-9][0-9]{0,11}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SERIES_PATH = re.compile(rf"/manga/([^/]+)/({_ID})/?")
_READ_QUERY = re.compile(rf"id=({_ID})")
_READ_FRAGMENT = re.compile(rf"series=({_ID})")
_NUMBER = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,6})?")
_TITLE_NUMBER = re.compile(r"第([0-9]{1,9}(?:\.[0-9]{1,6})?)話")
_CREATED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_PAGE_TEMPLATE = re.compile(rf"/{_UUID}/\{{page\}}\.webp")
_PAGE_URL = re.compile(
    rf"({re.escape(_STORAGE_URL)}/{_UUID}/(?:0|[1-9][0-9]{{0,4}})\.webp)#chapter=({_ID})")

# Exactly what these objects hold. A field outside them could change what
# a row or page list means, so it fails instead of being ignored.
_SEARCH_KEYS = {"id", "title", "image", "status", "updatedAt", "latestChapter"}
_CHAPTER_KEYS = {"id", "title", "index", "createdAt"}
_READER_KEYS = {"id", "title", "mangaId", "manga", "storageUrl", "content"}
_READER_SERIES_KEYS = {"id", "title", "image", "isAdult"}
_CONTENT_KEYS = {"type", "data"}
_RANGE_KEYS = {"from", "to", "url"}

_MAX_REPLY_BYTES = 8 * 1024 * 1024
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_MAX_PAGES = 1000
_MAX_PAGE_NUMBER = 99999


class MangaRwSourceError(RuntimeError):
    """MangaRW did not serve what was asked for, or served it in a shape
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


def _site_parts(url: Any):
    try:
        parts = urlsplit(url)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Not a MangaRW URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST:
        raise ValueError(f"Not a MangaRW URL: {url}")
    return parts


def series_id(url: str) -> int:
    """The numeric id of a series URL; anything else raises ValueError."""
    parts = _site_parts(url)
    match = _SERIES_PATH.fullmatch(parts.path)
    if (parts.query or parts.fragment or not match
            or match.group(1) in (".", "..")):
        raise ValueError(f"Not a MangaRW series URL: {url}")
    return int(match.group(2))


def chapter_ids(url: str) -> Tuple[int, int]:
    """(series id, chapter id) of a chapter URL; anything else raises."""
    parts = _site_parts(url)
    chapter = _READ_QUERY.fullmatch(parts.query)
    series = _READ_FRAGMENT.fullmatch(parts.fragment)
    if parts.path != "/read" or not chapter or not series:
        raise ValueError(f"Not a MangaRW chapter URL: {url}")
    return int(series.group(1)), int(chapter.group(1))


def _title(value: Any) -> str:
    if not (isinstance(value, str) and value.strip()):
        raise MangaRwSourceError("reply has no usable title")
    return value.strip()


def _cover(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _search_result(row: Any) -> Tuple[Manga, int]:
    """One search row and its series id. Its chapter fields are not read."""
    if not isinstance(row, dict) or set(row) != _SEARCH_KEYS:
        raise MangaRwSourceError("search row is not in the known shape")
    series = row["id"]
    if not (_is_int(series) and series > 0):
        raise MangaRwSourceError("search row has no usable id")
    title = _title(row["title"])
    slug = quote(title, safe="", errors="replace")
    url = f"{_BASE_URL}/manga/{'manga' if slug in ('.', '..') else slug}/{series}"
    try:
        if series_id(url) != series:
            raise ValueError
    except ValueError:
        raise MangaRwSourceError("search row has no usable id") from None
    return Manga(title=title, url=url, cover_url=_cover(row["image"])), series


def _chapter_index(value: Any) -> Decimal:
    """A chapter's index as served: a whole or decimal JSON number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MangaRwSourceError("chapter has no usable index")
    text = str(value)
    if not _NUMBER.fullmatch(text):
        raise MangaRwSourceError("chapter has no usable index")
    return Decimal(text)


def _created_at(value: Any) -> str:
    """A chapter's UTC creation time, kept as served."""
    if not (isinstance(value, str) and _CREATED_AT.fullmatch(value)):
        raise MangaRwSourceError("chapter has no usable date")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise MangaRwSourceError("chapter has no usable date") from None
    return value


def _chapter(row: Any, series: int) -> Tuple[Chapter, int]:
    """One chapter row, checked field by field, and its served id."""
    if not isinstance(row, dict) or set(row) != _CHAPTER_KEYS:
        raise MangaRwSourceError("chapter row is not in the known shape")
    chapter_id = row["id"]
    if not (_is_int(chapter_id) and chapter_id > 0):
        raise MangaRwSourceError("chapter has no usable id")
    index = _chapter_index(row["index"])
    title = _title(row["title"])
    named = _TITLE_NUMBER.match(title)
    if named and Decimal(named.group(1)) != index:
        raise MangaRwSourceError("a chapter's title and index disagree")
    # A title that only repeats the number adds nothing to the label.
    only_number = named is not None and named.end() == len(title)
    return Chapter(
        number=format(index.normalize(), "f"),
        title=None if only_number else title,
        url=f"{_BASE_URL}/read?id={chapter_id}#series={series}",
        date=_created_at(row["createdAt"]),
    ), chapter_id


def _reader_pages(data: Any, series: int, chapter: int) -> List[str]:
    """The page URLs of a reader reply for this series and chapter."""
    if not isinstance(data, dict) or set(data) != _READER_KEYS:
        raise MangaRwSourceError("reader reply is not in the known shape")
    if not (_is_int(data["id"]) and data["id"] == chapter):
        raise MangaRwSourceError("reader reply is not for this chapter")
    _title(data["title"])
    owner = data["manga"]
    if not (_is_int(data["mangaId"]) and data["mangaId"] == series
            and isinstance(owner, dict) and set(owner) == _READER_SERIES_KEYS
            and _is_int(owner["id"]) and owner["id"] == series
            and isinstance(owner["isAdult"], bool)):
        raise MangaRwSourceError("reader reply is not for this series")
    _title(owner["title"])
    if data["storageUrl"] != _STORAGE_URL:
        raise MangaRwSourceError("reader reply names an unexpected image host")

    content = data["content"]
    if not (isinstance(content, list) and len(content) == 1):
        raise MangaRwSourceError("reader reply has an unsupported page list")
    block = content[0]
    if not isinstance(block, dict) or set(block) != _CONTENT_KEYS or block["type"] != "selfhosted":
        raise MangaRwSourceError("reader reply has an unsupported page list")
    pages = block["data"]
    if not isinstance(pages, dict) or set(pages) != _RANGE_KEYS:
        raise MangaRwSourceError("reader reply has an unsupported page list")
    first, last, template = pages["from"], pages["to"], pages["url"]
    if not (_is_int(first) and _is_int(last) and 0 <= first <= last <= _MAX_PAGE_NUMBER
            and last - first < _MAX_PAGES):
        raise MangaRwSourceError("reader reply has an unusable page range")
    if not (isinstance(template, str) and _PAGE_TEMPLATE.fullmatch(template)):
        raise MangaRwSourceError("reader reply has an unusable page address")
    return [f"{_STORAGE_URL}{template.replace('{page}', str(number))}#chapter={chapter}"
            for number in range(first, last + 1)]


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("MangaRW: could not remove a failed page file")


class MangaRwScraper(BaseScraper):
    """Scraper for MangaRW (mangarw.com).

    A chapter list is every row the API names for the series; it is not a
    claim about chapters the site no longer lists.
    """

    name = "mangarw"
    base_url = _BASE_URL
    engine = "api"
    # Replies do not state a series' language, so none is claimed.
    content_language = None
    # The API flags adult series, so the catalogue may include them.
    nsfw = True

    def __init__(self):
        super().__init__()
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    def _fetch(self, url: str, limit: int, referer: str = _REFERER) -> bytes:
        """One whole response body. Redirects are not followed."""
        response = None
        try:
            response = self._request(url, stream=True, allow_redirects=False,
                                     headers={"Referer": referer})
            if response.status_code != 200:
                raise MangaRwSourceError(f"MangaRW answered HTTP {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise MangaRwSourceError("MangaRW's reply is too large")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            raise MangaRwSourceError(f"MangaRW did not answer ({_failure(e)})") from None
        finally:
            if response is not None:
                response.close()

    def _api(self, path: str) -> Any:
        """The ``data`` of one API reply."""
        body = self._fetch(f"{_API_URL}{path}", _MAX_REPLY_BYTES)
        try:
            reply = json.loads(body, parse_constant=_no_constant)
        except ValueError:
            raise MangaRwSourceError("MangaRW's reply is not JSON") from None
        if not isinstance(reply, dict) or set(reply) != {"data"}:
            raise MangaRwSourceError("MangaRW's reply is not in the known shape")
        return reply["data"]

    def _series(self, series: int) -> dict:
        data = self._api(f"/manga/{series}")
        if not (isinstance(data, dict) and _is_int(data.get("id")) and data["id"] == series):
            raise MangaRwSourceError("reply is not for this series")
        _title(data.get("title"))
        if not isinstance(data.get("isAdult"), bool):
            raise MangaRwSourceError("series reply is not in the known shape")
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The series the site's search serves, in its order.

        The query is sent in composed Unicode with every character kept,
        so a voiced or semi-voiced kana stays distinct from its plain form.
        The reply has no paging, so one request is the whole result.
        """
        keyword = unicodedata.normalize("NFC", query).strip()
        if not keyword:
            return []
        rows = self._api(f"/search/?keyword={quote(keyword, safe='')}")
        if not isinstance(rows, list):
            raise MangaRwSourceError("search reply has no result list")
        results, seen = [], set()
        for row in rows:
            manga, series = _search_result(row)
            if series in seen:
                raise MangaRwSourceError("a series is listed twice")
            seen.add(series)
            results.append(manga)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter row the API names for the series, by number."""
        series = series_id(manga_url)
        stated = self._series(series).get("chapterCount")
        if not (_is_int(stated) and stated >= 0):
            raise MangaRwSourceError("series reply states no chapter count")
        rows = self._api(f"/manga/{series}/chapters?order=desc")
        if not isinstance(rows, list):
            raise MangaRwSourceError("chapter reply has no chapter list")
        if not rows:
            raise MangaRwSourceError("chapter reply lists no chapters")
        if len(rows) != stated:
            raise MangaRwSourceError(
                f"chapter reply lists {len(rows)} chapters, the series states {stated}")

        chapters, ids, numbers = [], set(), set()
        for row in rows:
            chapter, chapter_id = _chapter(row, series)
            if chapter_id in ids:
                raise MangaRwSourceError("a chapter id is listed twice")
            if chapter.number in numbers:
                raise MangaRwSourceError("a chapter number is listed twice")
            ids.add(chapter_id)
            numbers.add(chapter.number)
            chapters.append(chapter)
        logger.info("MangaRW: listing the %d chapter(s) the API names for this series",
                    len(chapters))
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover the series reply names, if any."""
        try:
            return _cover(self._series(series_id(manga_url)).get("image"))
        except (MangaRwSourceError, ValueError):
            return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the range the reader serves."""
        series, chapter = chapter_ids(chapter_url)
        return _reader_pages(self._api(f"/chapter/{chapter}"), series, chapter)

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the image host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        page = _PAGE_URL.fullmatch(url) if isinstance(url, str) else None
        if page is None:
            logger.debug("MangaRW page refused: not a known page address")
            _discard(path)
            return False
        try:
            content = self._fetch(page.group(1), _MAX_PAGE_BYTES,
                                  referer=f"{_BASE_URL}/read?id={page.group(2)}")
        except MangaRwSourceError as e:
            logger.debug("MangaRW page failed: %s", e)
            _discard(path)
            return False
        if not _identifies_as_image(content):
            logger.debug("MangaRW page is not an image")
            _discard(path)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            logger.debug("MangaRW page could not be saved")
            _discard(path)
            return False
        return True
