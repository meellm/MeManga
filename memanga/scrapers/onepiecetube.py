"""
OnePiece-Tube scraper
https://onepiece.tube

A German-language site for one franchise, One Piece. This scraper reads the
site's main chapter list ("Manga Kapitel"). The site's other lists
(spin-offs, one-shots, artbooks and so on) are not read.

List and reader pages embed their data in a ``window.__data`` assignment,
which is parsed as strict JSON and never executed.

A chapter list is the entries the main list marks available in German. The
list also names chapters the site does not currently serve; those are
checked with the rest but not offered.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "onepiece.tube"
_BASE_URL = f"https://{_HOST}"
# The page whose menu names the site's lists.
_MENU_URL = f"{_BASE_URL}/manga/spin-off-mangaliste"
_MENU_TEXT = "Manga Kapitel"
_LIST_PATH = re.compile(r"/manga/kapitel-mangaliste/?")
_LIST_URL = f"{_BASE_URL}/manga/kapitel-mangaliste"
# Tagged so it does not collide with the same series from another source.
_TITLE = "One Piece [DE]"
_SEARCH_NAME = "one piece"
_LANGUAGE = "ger"
_CATEGORY = 3

_CHAPTER_PATH = re.compile(r"/manga/kapitel/([1-9][0-9]{0,5})/1")
_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_ASSIGNMENT = re.compile(r"\s*=\s*")
_WORD = re.compile(r"[^\W_]+")
_MAX_PAGE_BYTES = 64 * 1024 * 1024


class OnePieceTubeSourceError(RuntimeError):
    """OnePiece-Tube did not serve what was asked for, or served it in a
    shape this scraper does not know."""


def _no_constant(name: str):
    raise ValueError(f"not JSON: {name}")


_DECODER = json.JSONDecoder(parse_constant=_no_constant)


def _failure(error: BaseException) -> str:
    """A short description of a failed request: its status or its kind."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalized(text: str) -> str:
    """Text reduced to its lower-case words, for comparing names."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _site_path(url: Any) -> str:
    try:
        parts = urlsplit(url)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Not an OnePiece-Tube URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST or parts.query or parts.fragment:
        raise ValueError(f"Not an OnePiece-Tube URL: {url}")
    return parts.path


def chapter_number(url: Any) -> int:
    """The chapter number in a reader URL; anything else raises ValueError."""
    match = _CHAPTER_PATH.fullmatch(_site_path(url))
    if not match:
        raise ValueError(f"Not an OnePiece-Tube chapter URL: {url}")
    return int(match.group(1))


def page_data(html: str) -> Optional[dict]:
    """The page's ``window.__data`` object, or None when it has none.
    Anything but one strict JSON object assignment raises."""
    scripts = [script for script in BeautifulSoup(html or "", "html.parser").find_all("script")
               if "window.__data" in (script.string or "")]
    if not scripts:
        return None
    if len(scripts) != 1:
        raise OnePieceTubeSourceError("page carries more than one data script")
    text = scripts[0].string
    assignment = _ASSIGNMENT.match(text, text.index("window.__data") + len("window.__data"))
    if not assignment:
        raise OnePieceTubeSourceError("page data is not an assignment")
    try:
        data, end = _DECODER.raw_decode(text, assignment.end())
    except ValueError:
        raise OnePieceTubeSourceError("page data is not valid JSON") from None
    if text[end:].strip() not in ("", ";") or not isinstance(data, dict):
        raise OnePieceTubeSourceError("page data is not one JSON object")
    return data


def _iso_date(value: Any) -> Optional[str]:
    """A ``dd.mm.yyyy`` date as ISO 8601. The shape is required; a value in
    that shape that is no calendar date gives no date."""
    if not (isinstance(value, str) and _DATE.fullmatch(value)):
        raise OnePieceTubeSourceError("list entry has no usable date")
    day, month, year = value.split(".")
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class _Entry:
    id: int
    number: int
    url: str
    available: bool
    language: str
    title: str
    date: Optional[str]


def _entry(row: Any) -> _Entry:
    """One row of the main list, checked field by field."""
    if not isinstance(row, dict):
        raise OnePieceTubeSourceError("list entry is not an object")
    entry_id, number = row.get("id"), row.get("number")
    if not (_is_int(entry_id) and entry_id > 0 and _is_int(number) and number > 0):
        raise OnePieceTubeSourceError("list entry has no usable id or number")
    available, language, name = row.get("is_available"), row.get("lang"), row.get("name")
    if not (isinstance(available, bool) and isinstance(language, str) and language
            and isinstance(name, str) and name.strip()):
        raise OnePieceTubeSourceError("list entry is missing a required field")
    category, special = row.get("category_id"), row.get("specials_id")
    if not (_is_int(category) and category == _CATEGORY and _is_int(special) and special == 0):
        raise OnePieceTubeSourceError("list entry is not from the main chapter list")
    url = row.get("href")
    try:
        served_number = chapter_number(url)
    except ValueError:
        raise OnePieceTubeSourceError("list entry has an unusable link") from None
    if served_number != number:
        raise OnePieceTubeSourceError("a list entry's link and number disagree")
    return _Entry(entry_id, number, url, available, language, name.strip(),
                  _iso_date(row.get("date")))


def _page_url(page: Any) -> str:
    """A page's image URL on the site's own host; anything else raises."""
    value = page.get("url") if isinstance(page, dict) else None
    if (not isinstance(value, str) or "?" in value or "#" in value or "\\" in value
            or any(ch.isspace() or ord(ch) < 32 for ch in value)):
        raise OnePieceTubeSourceError("page has an unusable image URL")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise OnePieceTubeSourceError("page has an unusable image URL") from None
    segments = parts.path.split("/")
    if (parts.scheme != "https" or parts.netloc != _HOST
            or not parts.path.startswith("/") or not segments[-1]
            or "." in segments or ".." in segments):
        raise OnePieceTubeSourceError("page image is on an unexpected host or path")
    return value


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("OnePiece-Tube: could not remove a failed page file")


class OnePieceTubeScraper(BaseScraper):
    """Scraper for OnePiece-Tube's main German chapter list (onepiece.tube).

    One franchise, not a general German catalogue. A chapter list is the
    entries the site's main list marks available in German.
    """

    name = "onepiecetube"
    base_url = _BASE_URL
    content_language = "de"

    def _get(self, url: str) -> str:
        """One page. Redirects are not followed."""
        try:
            response = self._request(url, allow_redirects=False)
        except requests.RequestException as e:
            raise OnePieceTubeSourceError(
                f"OnePiece-Tube did not answer ({_failure(e)})") from None
        if response.status_code != 200:
            raise OnePieceTubeSourceError(f"OnePiece-Tube answered HTTP {response.status_code}")
        if (response.headers.get("cf-mitigated") or "").lower() == "challenge":
            raise OnePieceTubeSourceError("OnePiece-Tube answered with a challenge page")
        return response.text

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The site's one series, when the query names it. The query is
        matched here; a match confirms the list in the site's own menu."""
        wanted = _normalized(query)
        if not wanted or f" {wanted}" not in f" {_SEARCH_NAME}":
            return []
        soup = BeautifulSoup(self._get(_MENU_URL), "html.parser")
        links = {link.get("href")
                 for link in soup.select('a.dropdown-item[href$="-mangaliste"]')
                 if link.get_text(" ", strip=True) == _MENU_TEXT}
        if links != {_LIST_URL}:
            raise OnePieceTubeSourceError("the site's menu does not name its chapter list")
        return [Manga(title=_TITLE, url=_LIST_URL)]

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The main list's entries marked available in German, by number."""
        if not _LIST_PATH.fullmatch(_site_path(manga_url)):
            raise ValueError(f"Not OnePiece-Tube's main chapter list: {manga_url}")
        data = page_data(self._get(_LIST_URL))
        if data is None:
            raise OnePieceTubeSourceError("the chapter list page carries no data")
        rows = data.get("entries")
        if not isinstance(rows, list) or not rows:
            raise OnePieceTubeSourceError("the chapter list names no entries")

        entries, ids, numbers = [], set(), set()
        for row in rows:
            entry = _entry(row)
            if entry.id in ids:
                raise OnePieceTubeSourceError("a chapter id is listed twice")
            if entry.number in numbers:
                raise OnePieceTubeSourceError("a chapter number is listed twice")
            ids.add(entry.id)
            numbers.add(entry.number)
            entries.append(entry)

        listed = [e for e in entries if e.available and e.language == _LANGUAGE]
        if not listed:
            raise OnePieceTubeSourceError("the chapter list marks no German chapter available")
        logger.info("OnePiece-Tube: listing %d of the %d chapter(s) its main list names "
                    "(those marked available in German)", len(listed), len(entries))
        return [Chapter(number=str(e.number), title=None if e.title == "-" else e.title,
                        url=e.url, date=e.date)
                for e in sorted(listed, key=lambda e: e.number)]

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The site has no series covers."""
        return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the order the reader serves."""
        number = chapter_number(chapter_url)
        data = page_data(self._get(chapter_url))
        if data is None:
            raise OnePieceTubeSourceError(f"chapter {number} is not available")
        chapter = data.get("chapter")
        pages = chapter.get("pages") if isinstance(chapter, dict) else None
        if not isinstance(pages, list):
            raise OnePieceTubeSourceError("reader page has no page list")
        if not pages:
            raise OnePieceTubeSourceError("reader page lists no pages")
        urls = [_page_url(page) for page in pages]
        if len(set(urls)) != len(urls):
            raise OnePieceTubeSourceError("reader lists one page twice")
        return urls

    def _fetch_page(self, url: str) -> Optional[bytes]:
        """A page's bytes, or None when it was not served whole."""
        response = None
        try:
            response = self._request(url, stream=True, allow_redirects=False,
                                     headers={"Referer": f"{_BASE_URL}/"})
            if response.status_code != 200:
                logger.debug("OnePiece-Tube page: HTTP %d", response.status_code)
                return None
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > _MAX_PAGE_BYTES:
                    logger.debug("OnePiece-Tube page is too large")
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            logger.debug("OnePiece-Tube page failed (%s)", _failure(e))
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            return None
        finally:
            if response is not None:
                response.close()

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the site's host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        try:
            _page_url({"url": url})
        except OnePieceTubeSourceError:
            logger.debug("OnePiece-Tube page refused: not on %s", _HOST)
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
            logger.debug("OnePiece-Tube page could not be saved")
            _discard(path)
            return False
        return True
