"""
Mangaraw.ink raw manga scraper
https://mangaraw.ink

Search, series and chapter pages are plain HTML. Search reads the first page
of results. The search route also serves the site's browse list, so a page
counts as this search only when its pager repeats the query. An empty result
is an empty list with that pager, because the site shows no notice.

A chapter list is every row the series page serves. Rows show only a relative
age ("2 週間前"), so no date is recorded. The list says nothing about chapters
the site does not carry.

A chapter page must state the requested chapter in its title, heading,
breadcrumb and social title, and its canonical address must be the requested
one. Pages come from its one reader list, on the one image host.

Pages carry the site's advertising scripts. Nothing here runs them.

Pages do not state a series' language or rating, so neither is claimed.
"""

import http.cookiejar
import logging
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlsplit

import requests
from bs4 import BeautifulSoup, Tag

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "mangaraw.ink"
_BASE_URL = f"https://{_HOST}"
_SEARCH_PATH = "/search/manga"
_SEARCH_SORT = "10"
_IMAGE_HOST = "iphotomg.com"
_IMAGE_HEADERS = {"Referer": f"{_BASE_URL}/", "Accept": "image/avif,image/webp,*/*"}

_SLUG = r"[A-Za-z0-9%][A-Za-z0-9%._~-]*"
_NUMBER_TEXT = r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?"

_SERIES_PATH = re.compile(rf"/manga/({_SLUG})/?")
_CHAPTER_PATH = re.compile(rf"/manga/({_SLUG})/chapter-({_NUMBER_TEXT})")
_STATED_NUMBER = re.compile(rf"第({_NUMBER_TEXT})話")
_PAGER_NUMBER = re.compile(r"[1-9][0-9]{0,5}")
_IMAGE_URL = re.compile(
    rf"https://{re.escape(_IMAGE_HOST)}(?:/[A-Za-z0-9][A-Za-z0-9._~%-]*)+\.webp")

_MAX_HTML_BYTES = 16 * 1024 * 1024
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_MAX_PAGES = 1000


class MangarawInkSourceError(RuntimeError):
    """Mangaraw.ink did not serve what was asked for, or served it in a
    shape this scraper does not know."""


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
        raise ValueError(f"Not a Mangaraw.ink URL: {url}") from None
    if parts.scheme != "https" or parts.netloc != _HOST:
        raise ValueError(f"Not a Mangaraw.ink URL: {url}")
    return parts


def series_url(url: str) -> str:
    """The canonical form of a series URL; anything else raises ValueError."""
    parts = _site_parts(url)
    match = _SERIES_PATH.fullmatch(parts.path)
    if parts.query or parts.fragment or not match:
        raise ValueError(f"Not a Mangaraw.ink series URL: {url}")
    return f"{_BASE_URL}/manga/{match.group(1)}"


def chapter_parts(url: str) -> Tuple[str, str]:
    """(series slug, chapter number as written) of a chapter URL."""
    parts = _site_parts(url)
    match = _CHAPTER_PATH.fullmatch(parts.path)
    if parts.query or parts.fragment or not match:
        raise ValueError(f"Not a Mangaraw.ink chapter URL: {url}")
    return match.group(1), match.group(2)


def _text(element: Tag) -> str:
    return " ".join(element.get_text(" ").split())


def _comparable(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip().casefold()


def _stated_number(text: Any) -> Optional[Decimal]:
    """The one chapter number a text states, or None."""
    if not isinstance(text, str):
        return None
    numbers = _STATED_NUMBER.findall(text)
    return Decimal(numbers[0]) if len(numbers) == 1 else None


def _check_pager(soup: BeautifulSoup, keyword: str, has_results: bool) -> None:
    """The page's pager must repeat this search."""
    pagers = soup.select("div.page_redirect")
    links = pagers[0].find_all("a", href=True) if len(pagers) == 1 else []
    if not links:
        raise MangarawInkSourceError("search page has no known pager")
    for link in links:
        try:
            parts = urlsplit(link["href"])
            params = parse_qs(parts.query, keep_blank_values=True)
        except ValueError:
            raise MangarawInkSourceError("search page has no known pager") from None
        echoed, page = params.get("keyword", []), params.get("page", [])
        if (parts.scheme or parts.netloc or parts.path != _SEARCH_PATH
                or len(echoed) != 1 or _comparable(echoed[0]) != _comparable(keyword)
                or params.get("sort") != [_SEARCH_SORT]
                or len(page) != 1 or not _PAGER_NUMBER.fullmatch(page[0])):
            raise MangarawInkSourceError("search page is not for this query")
    active = [_text(mark) for mark in pagers[0].select("p.active")]
    if active != (["1"] if has_results else []):
        raise MangarawInkSourceError("search page has no known pager")


def _search_results(html: str, keyword: str) -> List[Manga]:
    """The cards of one search page, or none for its known empty form."""
    soup = BeautifulSoup(html, "html.parser")
    grids = soup.select("ul.list_grid")
    if len(grids) != 1:
        raise MangarawInkSourceError("search page has no known result list")
    names = grids[0].select("div.book_name a")
    avatars = grids[0].select("div.book_avatar")
    _check_pager(soup, keyword, bool(names))
    if not names:
        if avatars or grids[0].find(True) is not None or grids[0].get_text(strip=True):
            raise MangarawInkSourceError("search page has no known result list")
        return []
    if len(names) != len(avatars):
        raise MangarawInkSourceError("search card is not in the known shape")

    results, seen = [], set()
    for name, avatar in zip(names, avatars):
        title = _text(name)
        link = avatar.find("a", href=True)
        try:
            url = series_url(name.get("href"))
        except ValueError:
            raise MangarawInkSourceError("search card has an unusable link") from None
        if not title or link is None or link["href"] != name["href"]:
            raise MangarawInkSourceError("search card is not in the known shape")
        if url in seen:
            raise MangarawInkSourceError("a series is listed twice")
        seen.add(url)
        image = avatar.find("img")
        cover = image.get("data-original") if image is not None else None
        results.append(Manga(title=title, url=url, cover_url=_cover(cover)))
    return results


def _cover(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _chapter(row: Tag, slug: str) -> Chapter:
    """One chapter row. Its link and label must state the same number."""
    links = row.select(".name-chap a")
    if len(links) != 1:
        raise MangarawInkSourceError("chapter row is not in the known shape")
    url = links[0].get("href")
    try:
        row_slug, number = chapter_parts(url)
    except ValueError:
        raise MangarawInkSourceError("chapter row has an unusable link") from None
    if row_slug != slug:
        raise MangarawInkSourceError("chapter row links to another series")
    label = _text(links[0])
    stated = _STATED_NUMBER.match(label)
    if stated is None or Decimal(stated.group(1)) != Decimal(number):
        raise MangarawInkSourceError("a chapter's label and link disagree")
    return Chapter(
        number=format(Decimal(number).normalize(), "f"),
        title=label[stated.end():].strip() or None,
        url=url,
        date=None,
    )


def _reader_images(html: str, slug: str, written: str) -> List[str]:
    """The page images of this chapter, after the page has identified it."""
    soup = BeautifulSoup(html, "html.parser")
    series = f"{_BASE_URL}/manga/{slug}"
    chapter = f"{series}/chapter-{written}"
    number = Decimal(written)

    canonical = soup.find_all("link", rel="canonical")
    social = soup.find_all("meta", property="og:title")
    headings = soup.select("h1.detail-title")
    trails = soup.select("ol.breadcrumb")
    if not (len(canonical) == 1 and canonical[0].get("href") == chapter
            and soup.title is not None and len(social) == 1
            and len(headings) == 1 and trails):
        raise MangarawInkSourceError("page is not this chapter")
    heading_links = headings[0].find_all("a", href=True)
    if len(heading_links) != 1 or heading_links[0]["href"] != series:
        raise MangarawInkSourceError("page is not this chapter")
    stated = [_text(soup.title), social[0].get("content"), _text(headings[0])]
    for trail in trails:
        current = trail.select("a.active")
        if (len(current) != 1 or current[0].get("href") != chapter
                or not any(link.get("href") == series for link in trail.find_all("a"))):
            raise MangarawInkSourceError("page is not this chapter")
        stated.append(_text(current[0]))
    if any(_stated_number(text) != number for text in stated):
        raise MangarawInkSourceError("page is not this chapter")

    containers = soup.select("div.page-chapter")
    if not containers or len(containers) > _MAX_PAGES:
        raise MangarawInkSourceError("page has no usable image list")
    urls = []
    for container in containers:
        images = container.find_all("img")
        source = images[0].get("data-original") if len(images) == 1 else None
        if not (isinstance(source, str) and _IMAGE_URL.fullmatch(source)):
            raise MangarawInkSourceError("page lists an image at an unknown address")
        urls.append(source)
    if len(set(urls)) != len(urls):
        raise MangarawInkSourceError("page lists an image twice")
    return urls


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Mangaraw.ink: could not remove a failed page file")


class MangarawInkScraper(BaseScraper):
    """Scraper for Mangaraw.ink (mangaraw.ink).

    A chapter list is every row the series page serves; it is not a claim
    that the series is complete.
    """

    name = "mangarawink"
    base_url = _BASE_URL
    engine = "http"
    # Pages do not state a series' language, so none is claimed.
    content_language = None

    def __init__(self):
        super().__init__()
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    def _fetch(self, url: str, limit: int,
               headers: Optional[Dict[str, str]] = None) -> bytes:
        """One whole response body. Redirects are not followed."""
        response = None
        try:
            response = self._request(url, stream=True, allow_redirects=False,
                                     headers=headers or {})
            if response.status_code != 200:
                raise MangarawInkSourceError(
                    f"Mangaraw.ink answered HTTP {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise MangarawInkSourceError("Mangaraw.ink's reply is too large")
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as e:
            failed = getattr(e, "response", None)
            if failed is not None:
                failed.close()
            raise MangarawInkSourceError(
                f"Mangaraw.ink did not answer ({_failure(e)})") from None
        finally:
            if response is not None:
                response.close()

    def _html(self, url: str) -> str:
        return self._fetch(url, _MAX_HTML_BYTES).decode("utf-8", "replace")

    def _series(self, url: str) -> BeautifulSoup:
        soup = BeautifulSoup(self._html(url), "html.parser")
        canonical = soup.find_all("link", rel="canonical")
        headings = soup.select("h1")
        if not (len(canonical) == 1 and canonical[0].get("href") == url
                and len(headings) == 1 and _text(headings[0])):
            raise MangarawInkSourceError("page is not this series")
        return soup

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search, in its order."""
        keyword = unicodedata.normalize("NFC", query).strip()
        if not keyword:
            return []
        url = (f"{_BASE_URL}{_SEARCH_PATH}?keyword={quote(keyword, safe='')}"
               f"&sort={_SEARCH_SORT}&page=1")
        return _search_results(self._html(url), keyword)

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter row the series page serves, by number."""
        url = series_url(manga_url)
        rows = self._series(url).select("div.works-chapter-item")
        if not rows:
            raise MangarawInkSourceError("series page lists no chapters")
        slug = url.rsplit("/", 1)[1]
        chapters, numbers = [], set()
        for row in rows:
            chapter = _chapter(row, slug)
            if chapter.number in numbers:
                raise MangarawInkSourceError("a chapter number is listed twice")
            numbers.add(chapter.number)
            chapters.append(chapter)
        logger.info("Mangaraw.ink: listing the %d chapter(s) the series page serves",
                    len(chapters))
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover the series page shows, if any."""
        try:
            soup = self._series(series_url(manga_url))
        except (MangarawInkSourceError, ValueError):
            return None
        image = soup.select_one("div.book_info div.book_avatar img[itemprop=image]")
        return _cover(image.get("src")) if image is not None else None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page image URLs, in the order the page lists them."""
        slug, written = chapter_parts(chapter_url)
        return _reader_images(self._html(chapter_url), slug, written)

    def download_image(self, url: str, path) -> bool:
        """Download one page. A page that is off the image host, refused,
        too large or not an image fails, and removes any older file."""
        path = Path(path)
        if not (isinstance(url, str) and _IMAGE_URL.fullmatch(url)):
            logger.debug("Mangaraw.ink page refused: not a known page address")
            _discard(path)
            return False
        try:
            content = self._fetch(url, _MAX_PAGE_BYTES, headers=dict(_IMAGE_HEADERS))
        except MangarawInkSourceError as e:
            logger.debug("Mangaraw.ink page failed: %s", e)
            _discard(path)
            return False
        if not _identifies_as_image(content):
            logger.debug("Mangaraw.ink page is not an image")
            _discard(path)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError:
            logger.debug("Mangaraw.ink page could not be saved")
            _discard(path)
            return False
        return True
