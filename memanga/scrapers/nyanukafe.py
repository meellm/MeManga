"""
Nyanu Kafe scraper - English manga translations
Site: nyanukafe.com

* search   -> GET /series?q=<query>, the site's own search page. It lists the
              whole catalogue whatever the query, so the served cards
              (``#searched_series_page > button``) are matched on their title
              here.
* series   -> GET /series/<id>/ serves the title, genres, type and every
              chapter as ``#chapters > a`` rows reading "Chapter N" or
              "Chapter N.M", optionally followed by " - <title>".
* pages    -> GET /chapter/<series id>-<chapter id>/ names its series and
              chapter in its heading, and lists the pages as
              ``#pages > img[uid]`` in served order. The page script serves the
              image address as ``https://cdn.meowing.org/uploads/<uid>``; that
              served form is the only one read.

The site's theme carries a purchase dialog for chapters it marks with
``id="paid-chapter"`` or a coin image. Such a row is refused, and so is a
reader showing one; no purchase step is ever taken. Series whose own genres
mark them as explicitly adult, or whose type is a novel, are refused.
"""

import http.cookiejar
import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Set, Tuple
from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "nyanukafe.com"
_ID = r"[0-9a-f]{11}"
_SERIES_PATH = re.compile(rf"^/series/({_ID})/?$")
_CHAPTER_PATH = re.compile(rf"^/chapter/({_ID})-({_ID})/?$")
_LABEL = re.compile(r"^Chapter (\d+(?:\.\d+)?)(?: - (.+))?$")
_ROW_DATE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_UID = re.compile(r"^[0-9a-f]{11}\.(?:avif|webp|jpe?g|png)$")
_CDN_PREFIX = "https://cdn.meowing.org/uploads/"
_CDN_SCRIPT = re.compile(r"let realUrl = `(https://[^`$]+/uploads/)\$\{uid\}`;")
_PAGE_URL = re.compile(r"^https://cdn\.meowing\.org/uploads/[0-9a-f]{11}\.(?:avif|webp|jpe?g|png)$")
_ADULT_GENRES = frozenset({"adult", "18+", "+18", "hentai", "smut", "pornographic"})
_NOVEL = "novel"

_MAX_SEARCH_RESULTS = 50
_MAX_CHAPTERS = 5000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class NyanuKafeSourceError(RuntimeError):
    """nyanukafe.com answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _path(url) -> Optional[str]:
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        parts.port
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.hostname != _HOST or parts.port is not None
            or "@" in parts.netloc or parts.query or parts.fragment):
        return None
    return parts.path


def _row_date(text: str) -> Optional[str]:
    match = _ROW_DATE.match(text or "")
    month = _MONTHS.get(match.group(1)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _is_paid(element) -> bool:
    """A row or page marked paid the way the theme marks it."""
    return (element.get("id") == "paid-chapter"
            or element.select_one('[id="paid-chapter"]') is not None
            or any("coin" in (image.get("alt") or "").casefold()
                   for image in element.find_all("img")))


class NyanuKafeScraper(BaseScraper):
    """Scraper for Nyanu Kafe (nyanukafe.com)."""

    name = "nyanukafe"
    base_url = f"https://{_HOST}"
    content_language = "en"
    nsfw = False  # series with an explicitly adult genre are refused

    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        path = _path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise NyanuKafeSourceError(f"Not a Nyanu Kafe series URL: {url}")
        return f"{self.base_url}/series/{match.group(1)}/", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, str, str]:
        path = _path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise NyanuKafeSourceError(f"Not a Nyanu Kafe chapter URL: {url}")
        series, chapter = match.groups()
        return f"{self.base_url}/chapter/{series}-{chapter}/", series, chapter

    # Requests

    def _page(self, url: str, what: str) -> BeautifulSoup:
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise NyanuKafeSourceError(
                f"Nyanu Kafe answered HTTP {response.status_code} for {what} {url}")
        return BeautifulSoup(response.text, "html.parser")

    # Search

    def search(self, query: str) -> List[Manga]:
        """Catalogue series whose served title contains ``query``."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self.base_url}/series?q={quote_plus(query)}"
        soup = self._page(url, "search")
        grids = soup.select("#searched_series_page")
        if len(grids) != 1:
            raise NyanuKafeSourceError(f"Nyanu Kafe search {url} did not serve a result list")
        cards = grids[0].find_all("button", recursive=False)
        if len(cards) > _MAX_SEARCH_RESULTS:
            raise NyanuKafeSourceError(f"Nyanu Kafe search {url} lists too many series")

        wanted = query.casefold()
        results: List[Manga] = []
        seen: Set[str] = set()
        for card in cards:
            title = " ".join((card.get("title") or "").split())
            link = card.select_one("a[href]")
            if not title or link is None:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe search {url} lists a series without its title or link")
            try:
                series_url, _ = self._series_parts(f"{self.base_url}{link['href']}")
            except NyanuKafeSourceError:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe search {url} lists a result that is not a series") from None
            if series_url in seen:
                raise NyanuKafeSourceError(f"Nyanu Kafe search {url} lists {series_url} twice")
            seen.add(series_url)
            if (card.get("data-type") or "").casefold() == _NOVEL or wanted not in title.casefold():
                continue
            results.append(Manga(title=title, url=series_url))
        return results

    # Series

    def _info(self, soup: BeautifulSoup, label: str) -> Optional[str]:
        for span in soup.select("div.font-medium > span"):
            if _text(span) == label:
                value = span.parent.find_next_sibling("div")
                return _text(value) if value is not None else None
        return None

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The chapters a series serves, oldest first."""
        series_url, series_id = self._series_parts(manga_url)
        soup = self._page(series_url, "series page")
        canonical = soup.select('link[rel="canonical"]')
        if (len(canonical) != 1 or canonical[0].get("href") != series_url
                or len(soup.select("h1")) != 1):
            raise NyanuKafeSourceError(f"Nyanu Kafe page {series_url} is not a series page")
        genres = {_text(link).rstrip(",").strip().casefold()
                  for link in soup.select('a[href^="/series/?genre="]')}
        if genres & _ADULT_GENRES:
            raise NyanuKafeSourceError(
                f"Nyanu Kafe lists {series_url} as adult; adult titles are not supported")
        if (self._info(soup, "Type") or "").casefold() == _NOVEL or _NOVEL in genres:
            raise NyanuKafeSourceError(
                f"Nyanu Kafe lists {series_url} as a novel; only comics are supported")

        holders = soup.select("#chapters")
        rows = holders[0].find_all(["a", "div"], recursive=False) if len(holders) == 1 else []
        if not rows:
            raise NyanuKafeSourceError(f"Nyanu Kafe lists no chapters for {series_url}")
        if len(rows) > _MAX_CHAPTERS:
            raise NyanuKafeSourceError(f"Nyanu Kafe lists too many chapters for {series_url}")

        chapters: List[Chapter] = []
        numbers: Set[str] = set()
        urls: Set[str] = set()
        for row in rows:
            if _is_paid(row) or "upcoming" in _text(row).casefold():
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe has a paid or upcoming chapter of {series_url}; "
                    f"this source reads free chapters only")
            if row.name != "a" or not row.get("href"):
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe has a chapter of {series_url} without a link")
            label = " ".join((row.get("title") or "").split())
            match = _LABEL.match(label)
            if match is None:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe has a chapter row of {series_url} in an unknown form: {label!r}")
            try:
                url, row_series, _ = self._chapter_parts(f"{self.base_url}{row['href']}")
            except NyanuKafeSourceError:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe links {label!r} of {series_url} elsewhere") from None
            if row_series != series_id:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe links {label!r} of {series_url} to another series")
            number = format(Decimal(match.group(1)).normalize(), "f")
            if url in urls or number in numbers:
                raise NyanuKafeSourceError(
                    f"Nyanu Kafe lists chapter {number} of {series_url} twice")
            urls.add(url)
            numbers.add(number)
            chapters.append(Chapter(number=number, title=match.group(2), url=url,
                                    date=_row_date(" ".join((row.get("d") or "").split()))))
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """No cover is read (the site serves covers through an image proxy),
        so adding a series sends no request."""
        return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in served order, all or nothing."""
        url, series_id, _ = self._chapter_parts(chapter_url)
        series_url = f"{self.base_url}/series/{series_id}/"

        def refused(why: str):
            return NyanuKafeSourceError(f"Nyanu Kafe chapter {url} {why}")

        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise refused(f"answered HTTP {response.status_code}")
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if len(canonical) != 1 or canonical[0].get("href") != url:
            raise refused("answered for another page")
        headings = soup.select("h1")
        crumbs = [link.get("href") for link in headings[0].select("a[href]")] if headings else []
        if (len(headings) != 1 or crumbs != [f"/series/{series_id}/"]
                or not re.search(r" - Chapter \d+(?:\.\d+)?", _text(headings[0]))):
            raise refused("does not name this chapter and its series")
        if soup.select_one('[id="paid-chapter"]') is not None:
            raise refused("is marked paid; this source reads free chapters only")

        holders = soup.select("#pages")
        images = holders[0].find_all("img", recursive=False) if len(holders) == 1 else []
        if not images:
            raise refused("lists no pages")
        if len(images) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        prefixes = _CDN_SCRIPT.findall(html)
        if prefixes != [_CDN_PREFIX]:
            raise refused("does not serve its page address in the known form")
        pages: List[str] = []
        for index, image in enumerate(images):
            uid = (image.get("uid") or "").strip()
            if not _UID.match(uid) or image.get("count") != str(index):
                raise refused(f"has a malformed page {index + 1}")
            pages.append(f"{_CDN_PREFIX}{uid}")
        if len(set(pages)) != len(pages):
            raise refused("lists the same image twice")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            if not isinstance(url, str) or not _PAGE_URL.match(url):
                raise NyanuKafeSourceError(f"refused a page URL: {url}")
            response = self._request(url, headers=self._IMAGE_HEADERS, allow_redirects=False)
            if response.status_code != 200:
                raise NyanuKafeSourceError(f"{url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise NyanuKafeSourceError(f"{url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise NyanuKafeSourceError(f"{url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a Nyanu Kafe page: %s", e)
            return False
