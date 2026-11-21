"""
Rawkuma raw manga scraper
https://rawkuma.net

A series page embeds its chapter list, and each row's served link is used
as it stands. A chapter page lists its images in one marked section, in
reading order. Search is the site's own form: a public token, then one
multipart request that answers with HTML result cards or a fixed notice.
Only the first page of results is read.

A chapter list is every row the page serves. It says nothing about
chapters the site no longer lists. A chapter that does not serve its image
section fails. Words such as "Premium" appear in the site's menus and
options, outside that section, and are not read as a statement about a
chapter.

Pages do not state a series' language or rating, so no language is claimed
and the catalogue is treated as one that may include adult series.
"""

import http.cookiejar
import logging
import re
import time
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup, NavigableString, SoupStrainer, Tag

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "rawkuma.net"
_BASE_URL = f"https://{_HOST}"
_AJAX_URL = f"{_BASE_URL}/wp-admin/admin-ajax.php"
_NONCE_URL = f"{_AJAX_URL}?type=search_form&action=get_nonce"
_SEARCH_URL = f"{_AJAX_URL}?action=advanced_search"
_IMAGE_HOST = "cdn.rawkuma.com"

_SLUG = r"[A-Za-z0-9%][A-Za-z0-9%._~-]*"
_CHAPTER_NAME = r"chapter-[0-9A-Za-z%_~.-]+?\.[1-9][0-9]{0,11}"
_IMAGE_PATH = r"(?:/[A-Za-z0-9][A-Za-z0-9._~%-]*)+\.(?:jpe?g|png|webp)"
_NUMBER_TEXT = r"[0-9]{1,9}(?:\.[0-9]{1,6})?"

_SERIES_PATH = re.compile(rf"/manga/({_SLUG})/?")
_CHAPTER_PATH = re.compile(
    rf"/manga/({_SLUG})/(chapter-([0-9A-Za-z%_~.-]+?)\.([1-9][0-9]{{0,11}}))/")
_NUMBER = re.compile(_NUMBER_TEXT)
_LABEL = re.compile(rf"Chapter ({_NUMBER_TEXT})")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|\+00:00)")
_NONCE = re.compile(r"<input type='hidden' name='search_nonce' value='([0-9a-f]{10})'>")
_IMAGE_URL = re.compile(rf"https://{re.escape(_IMAGE_HOST)}{_IMAGE_PATH}")
_PAGE_URL = re.compile(
    rf"(https://{re.escape(_IMAGE_HOST)}{_IMAGE_PATH})#chapter=({_SLUG})/({_CHAPTER_NAME})")

_NO_RESULTS = "No results found for your search."
_NOTICE_CLASSES = {"col-span-full", "py-4", "my-10", "text-center"}
# Each result is served twice, once for each of the site's two layouts.
_ROW_LAYOUT = "group-data-[mode=vertical]:hidden"
_GRID_LAYOUT = "group-data-[mode=horizontal]:hidden"

_MAX_TEXT_BYTES = 8 * 1024 * 1024
_MAX_SERIES_BYTES = 32 * 1024 * 1024
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_MAX_PAGES = 1000


class RawkumaSourceError(RuntimeError):
    """Rawkuma did not serve what was asked for, or served it in a shape
    this scraper does not know."""


def _failure(error: BaseException) -> str:
    """A short description of a failed request: its status or its kind."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _site_parts(url: Any):
    try:
        parts = urlsplit(url)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Not a Rawkuma URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST:
        raise ValueError(f"Not a Rawkuma URL: {url}")
    return parts


def series_url(url: str) -> str:
    """The canonical form of a series URL; anything else raises ValueError."""
    parts = _site_parts(url)
    match = _SERIES_PATH.fullmatch(parts.path)
    if parts.query or parts.fragment or not match:
        raise ValueError(f"Not a Rawkuma series URL: {url}")
    return f"{_BASE_URL}/manga/{match.group(1)}/"


def chapter_parts(url: str) -> Tuple[str, str, str, int]:
    """(series slug, chapter name, number text, post id) of a chapter URL."""
    parts = _site_parts(url)
    match = _CHAPTER_PATH.fullmatch(parts.path)
    if parts.query or parts.fragment or not match:
        raise ValueError(f"Not a Rawkuma chapter URL: {url}")
    return match.group(1), match.group(2), match.group(3), int(match.group(4))


def _text(element: Tag) -> str:
    return " ".join(element.get_text(" ").split())


def _date(value: Any) -> Optional[str]:
    """A row's UTC date as served, or None when it has no usable one."""
    if not (isinstance(value, str) and _DATE.fullmatch(value)):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _chapter(row: Tag, slug: str) -> Chapter:
    """One embedded chapter row, keeping the link the site served."""
    raw = (row.get("data-chapter-number") or "").strip()
    if not _NUMBER.fullmatch(raw):
        raise RawkumaSourceError("chapter row has no usable number")
    number = Decimal(raw)
    link = row.find("a", href=True)
    if link is None:
        raise RawkumaSourceError("chapter row has no link")
    url = link["href"]
    try:
        row_slug, _, url_number, _ = chapter_parts(url)
    except ValueError:
        raise RawkumaSourceError("chapter row has an unusable link") from None
    if row_slug != slug:
        raise RawkumaSourceError("chapter row links to another series")
    # Only a plain number in the address can be compared: how the site
    # writes a decimal chapter there is not assumed.
    if url_number.isdigit() and Decimal(url_number) != number:
        raise RawkumaSourceError("a chapter's link and number disagree")

    name = row.find("span")
    title = _text(name) if name is not None else ""
    label = _LABEL.match(title)
    if label and Decimal(label.group(1)) != number:
        raise RawkumaSourceError("a chapter's label and number disagree")
    # A label that only repeats the number adds nothing.
    if label and label.end() == len(title):
        title = ""
    when = row.find("time")
    return Chapter(
        number=format(number.normalize(), "f"),
        title=title or None,
        url=url,
        date=_date(when.get("datetime")) if when is not None else None,
    )


def _reader_images(html: str, slug: str, post: int) -> List[str]:
    """The page images of this chapter, in the order the page lists them."""
    soup = BeautifulSoup(html, "html.parser")
    classes = soup.body.get("class", []) if soup.body is not None else []
    if "single-chapter" not in classes or f"postid-{post}" not in classes:
        raise RawkumaSourceError("page is not this chapter")
    canonical = soup.find("link", rel="canonical")
    if canonical is None or canonical.get("href") != f"{_BASE_URL}/manga/{slug}/":
        raise RawkumaSourceError("page is not in this series")
    sections = soup.select("section[data-image-data]")
    if len(sections) != 1 or sections[0].get("data-image-data") != "1":
        raise RawkumaSourceError("page has no known image section")
    images = sections[0].find_all("img")
    if not images or len(images) > _MAX_PAGES:
        raise RawkumaSourceError("page has no usable image list")
    urls = []
    for image in images:
        src = image.get("src")
        if not (isinstance(src, str) and _IMAGE_URL.fullmatch(src)):
            raise RawkumaSourceError("page lists an image at an unknown address")
        urls.append(src)
    if len(set(urls)) != len(urls):
        raise RawkumaSourceError("page lists an image twice")
    return urls


def _nonce(body: bytes) -> str:
    match = _NONCE.fullmatch(body.decode("utf-8", "replace").strip())
    if match is None:
        raise RawkumaSourceError("search token is not in the known shape")
    return match.group(1)


def _card(card: Tag) -> Tuple[str, str, Optional[str]]:
    """(series URL, title, cover) of one layout of a result card."""
    urls, titles = set(), set()
    for link in card.find_all("a", href=True):
        try:
            url = series_url(link["href"])
        except ValueError:
            continue  # the card's latest-chapter links
        urls.add(url)
        if _text(link):
            titles.add(_text(link))
    if len(urls) != 1 or len(titles) != 1:
        raise RawkumaSourceError("search card is not in the known shape")
    image = card.find("img", class_="wp-post-image")
    cover = image.get("src") if image is not None else None
    if not (isinstance(cover, str) and cover.startswith("https://")):
        cover = None
    return urls.pop(), titles.pop(), cover


def _search_results(html: str) -> List[Manga]:
    """Result cards, the known no-results notice, or an error."""
    soup = BeautifulSoup(html, "html.parser")
    top = [node for node in soup.contents if isinstance(node, Tag)]
    if any(isinstance(node, NavigableString) and node.strip() for node in soup.contents):
        raise RawkumaSourceError("search reply is not in the known shape")
    if (len(top) == 1 and top[0].name == "div"
            and set(top[0].get("class", [])) == _NOTICE_CLASSES
            and _text(top[0]) == _NO_RESULTS):
        return []
    rows = soup.find_all(class_=_ROW_LAYOUT)
    grids = soup.find_all(class_=_GRID_LAYOUT)
    if not rows or len(rows) != len(grids) or _NO_RESULTS in _text(soup):
        raise RawkumaSourceError("search reply is not in the known shape")

    results, seen = [], set()
    for row, grid in zip(rows, grids):
        url, title, cover = _card(row)
        if _card(grid)[:2] != (url, title):
            raise RawkumaSourceError("a search card's two layouts disagree")
        if url not in seen:
            seen.add(url)
            results.append(Manga(title=title, url=url, cover_url=cover))
    return results


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Rawkuma: could not remove a failed page file")


class RawkumaScraper(BaseScraper):
    """Scraper for Rawkuma (rawkuma.net).

    A chapter list is every row the series page serves; it is not a claim
    about chapters the site no longer lists.
    """

    name = "rawkuma"
    base_url = _BASE_URL
    engine = "http"
    # Pages do not state a series' language, so none is claimed.
    content_language = None
    # Pages carry no rating, so the catalogue may include adult series.
    nsfw = True

    def __init__(self):
        super().__init__()
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    def _read(self, send: Callable[[], requests.Response], limit: int) -> bytes:
        """One whole response body."""
        response = None
        try:
            response = send()
            if response.status_code != 200:
                raise RawkumaSourceError(f"Rawkuma answered HTTP {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise RawkumaSourceError("Rawkuma's reply is too large")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            raise RawkumaSourceError(f"Rawkuma did not answer ({_failure(e)})") from None
        finally:
            if response is not None:
                response.close()

    def _fetch(self, url: str, limit: int, referer: Optional[str] = None) -> bytes:
        """One GET body. Redirects are not followed."""
        headers = {"Referer": referer} if referer else {}
        return self._read(
            lambda: self._request(url, stream=True, allow_redirects=False, headers=headers),
            limit)

    def _post(self, url: str, **kwargs) -> requests.Response:
        """One POST, spaced like every other request and never repeated."""
        with self._rate_lock:
            elapsed = time.time() - self._last_request
            if elapsed < self._rate_limit:
                time.sleep(self._rate_limit - elapsed)
            self._last_request = time.time()
        return self.session.post(url, timeout=30, **kwargs)

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search, in its order."""
        keyword = unicodedata.normalize("NFC", query).strip()
        if not keyword:
            return []
        keyword.encode("utf-8")
        nonce = _nonce(self._fetch(_NONCE_URL, _MAX_TEXT_BYTES))
        fields = [
            ("nonce", nonce), ("inclusion", "OR"), ("exclusion", "OR"), ("page", "1"),
            ("genre", "[]"), ("genre_exclude", "[]"), ("author", "[]"), ("artist", "[]"),
            ("project", "0"), ("type", "[]"), ("status", "[]"), ("order", "desc"),
            ("orderby", "popular"), ("query", keyword),
        ]
        form = [(name, (None, value)) for name, value in fields]
        body = self._read(
            lambda: self._post(_SEARCH_URL, files=form, stream=True, allow_redirects=False),
            _MAX_TEXT_BYTES)
        return _search_results(body.decode("utf-8", "replace"))

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter row the series page embeds, by number."""
        url = series_url(manga_url)
        slug = url.rstrip("/").rsplit("/", 1)[1]
        html = self._fetch(url, _MAX_SERIES_BYTES).decode("utf-8", "replace")
        # The page is several megabytes; only the list is parsed.
        only_list = SoupStrainer(id="chapter-list")
        lists = BeautifulSoup(html, "html.parser", parse_only=only_list).find_all(id="chapter-list")
        if len(lists) != 1:
            raise RawkumaSourceError("series page has no known chapter list")
        rows = lists[0].find_all("div", attrs={"data-chapter-number": True})
        if not rows:
            raise RawkumaSourceError("series page lists no chapters")

        chapters, numbers, urls = [], set(), set()
        for row in rows:
            chapter = _chapter(row, slug)
            if chapter.number in numbers:
                raise RawkumaSourceError("a chapter number is listed twice")
            if chapter.url in urls:
                raise RawkumaSourceError("a chapter link is listed twice")
            numbers.add(chapter.number)
            urls.add(chapter.url)
            chapters.append(chapter)
        logger.info("Rawkuma: listing the %d chapter(s) the series page serves", len(chapters))
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """None, without a request. Covers come with search results; the
        series page is too large to fetch for one."""
        return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the order the page lists them.

        Each carries its chapter in a fragment, which is never sent, so
        the image can be requested from its own reader page.
        """
        slug, name, _, post = chapter_parts(chapter_url)
        html = self._fetch(chapter_url, _MAX_TEXT_BYTES).decode("utf-8", "replace")
        return [f"{url}#chapter={slug}/{name}" for url in _reader_images(html, slug, post)]

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the image host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        page = _PAGE_URL.fullmatch(url) if isinstance(url, str) else None
        if page is None:
            logger.debug("Rawkuma page refused: not a known page address")
            _discard(path)
            return False
        reader = f"{_BASE_URL}/manga/{page.group(2)}/{page.group(3)}/"
        try:
            content = self._fetch(page.group(1), _MAX_PAGE_BYTES, referer=reader)
        except RawkumaSourceError as e:
            logger.debug("Rawkuma page failed: %s", e)
            _discard(path)
            return False
        if not _identifies_as_image(content):
            logger.debug("Rawkuma page is not an image")
            _discard(path)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            logger.debug("Rawkuma page could not be saved")
            _discard(path)
            return False
        return True
