"""
Tritinia Scans scraper - English manga scans
Site: tritinia.org

The site runs the WordPress "Madara" theme with series under /manga/:

* search   -> GET /?s=<query>&post_type=wp-manga, the site's own search form;
              results are ``.c-tabs-item__content`` rows, and no results is
              the theme's "No matches found" block.
* chapters -> POST <series>/ajax/chapters/ returns ``li.wp-manga-chapter``
              rows reading "Ch. N" or "Ch. N.M". A series page lists only the
              chapters the site keeps on it; when they do not start at
              chapter 1 a warning says so, and no older route is looked for.
* pages    -> the reader is served in paged style: its bound
              ``div.reading-content`` holds the first page as an
              ``img.wp-manga-chapter-img`` and the whole chapter as the plain
              ``chapter_preloaded_images`` array, which both page pickers
              count. The array is read as data, in served order.

A row or reader with a lock, coin or premium marker raises, an encrypted
(protected) page list raises, and titles whose own genres or type mark them
as adult or a novel are refused.
"""

import http.cookiejar
import json
import logging
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus, urlsplit

import requests
from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import (
    BaseScraper,
    Chapter,
    Manga,
    _identifies_as_image,
    _retry,
    is_retryable_request_error,
)

logger = logging.getLogger(__name__)

_HOST = "tritinia.org"
_SLUG = r"[a-z0-9]+(?:[-_][a-z0-9]+)*"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/manga/({_SLUG})/({_SLUG})/?$")
_IMAGE_PATH = re.compile(
    r"^(/wp-content/uploads/WP-manga/data/manga_[0-9a-f]+/[0-9a-f]{32})/"
    r"[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_COVER_PATH = re.compile(r"^/wp-content/uploads/\d{4}/\d{2}/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)

_LABEL = re.compile(r"^Ch\. (\d+(?:\.\d+)?)$")
_ROW_DATE = re.compile(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$")
_MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
_INLINE_SERIES = re.compile(r'"manga_id":"(\d+)"')
_INLINE_CHAPTER = re.compile(r'"chapter_slug":"([^"]*)"')
_PRELOADED = re.compile(r"var chapter_preloaded_images\s*=\s*(?=\[)")
_POST_ID = re.compile(r"^postid-(\d+)$")
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({"adult", "18+", "+18", "hentai", "smut", "mature"})
_NOVEL_TYPES = frozenset({"novel", "light novel", "web novel"})

_MAX_SEARCH_RESULTS = 25
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class TritiniaSourceError(RuntimeError):
    """tritinia.org answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _split(url):
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
    if (parts is None or parts.scheme != "https" or parts.hostname != _HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment):
        return None
    return parts.path


def _own_url(url, pattern) -> Optional[str]:
    """``url`` as an https URL of this site whose path matches ``pattern``."""
    path = _site_path(url)
    if path is None or not pattern.match(path) or ".." in path.split("/"):
        return None
    return url.strip()


def _row_date(text: str) -> Optional[str]:
    match = _ROW_DATE.match(text)
    month = _MONTHS.get(match.group(1)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _has_paid_class(element) -> bool:
    return any(_PAID_CLASS.search(name)
               for node in [element, *element.find_all(True)]
               for name in node.get("class") or [])


def _post_id(soup: BeautifulSoup) -> Optional[str]:
    body = soup.find("body")
    ids = [match.group(1) for match in
           (_POST_ID.match(name) for name in (body.get("class") or [] if body else []))
           if match]
    return ids[0] if len(ids) == 1 else None


class TritiniaScraper(BaseScraper):
    """Scraper for Tritinia Scans (tritinia.org)."""

    name = "tritinia"
    base_url = f"https://{_HOST}"
    content_language = "en"
    nsfw = False  # titles with an adult genre or badge are refused

    _AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        # Worker copies share these: each checked series' post id.
        self._series_ids: Dict[str, str] = {}

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise TritiniaSourceError(f"Not a Tritinia series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}/", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, str, str]:
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise TritiniaSourceError(f"Not a Tritinia chapter URL: {url}")
        series, chapter = match.groups()
        return f"{self.base_url}/manga/{series}/{chapter}/", series, chapter

    # Requests

    def _post(self, url: str, headers=None):
        """POST an empty form with the source's request spacing and retry
        rules, without following redirects."""
        def send():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            response = self.session.post(url, headers=headers, timeout=30,
                                         allow_redirects=False)
            response.raise_for_status()
            return response

        return _retry(send, max_attempts=3, base_delay=1.0,
                      exceptions=(requests.RequestException,),
                      retry_if=is_retryable_request_error)

    def _checked(self, response, what: str, url: str):
        if response.status_code != 200:
            raise TritiniaSourceError(
                f"Tritinia answered HTTP {response.status_code} for {what} {url}")
        return response

    def _page(self, url: str, what: str) -> BeautifulSoup:
        response = self._checked(self._request(url, allow_redirects=False), what, url)
        return BeautifulSoup(response.text, "html.parser")

    # Search

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's own search form."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/?s={quote_plus(query)}&post_type=wp-manga"
        soup = self._page(url, "search")
        rows = soup.select(".c-tabs-item__content")
        if not rows:
            if soup.select_one(".not-found-content") is not None:
                return []
            raise TritiniaSourceError(
                f"Tritinia search for {query!r} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            link = row.select_one(".post-title a[href]")
            title = _text(link) if link else ""
            if not title:
                raise TritiniaSourceError(
                    f"Tritinia search for {query!r} lists a result without a title")
            try:
                series_url, _ = self._series_parts(link["href"])
            except TritiniaSourceError:
                raise TritiniaSourceError(
                    f"Tritinia search for {query!r} lists a result that is not a series") from None
            if series_url in seen:
                raise TritiniaSourceError(
                    f"Tritinia search for {query!r} lists {series_url} twice")
            seen.add(series_url)
            image = row.select_one(".tab-thumb img")
            source = (image.get("data-src") or image.get("src") or "") if image else ""
            results.append(Manga(title=title, url=series_url,
                                 cover_url=_own_url(source, _COVER_PATH)))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for novels and adult titles."""
        soup = self._page(series_url, "series page")
        canonical = soup.select('link[rel="canonical"]')
        post_id = _post_id(soup)
        if (len(canonical) != 1 or canonical[0].get("href") != series_url
                or len(soup.select("div.post-title h1")) != 1 or post_id is None
                or len(soup.select("#manga-chapters-holder")) != 1):
            raise TritiniaSourceError(f"Tritinia page {series_url} is not a series page")
        badges = {_text(badge).casefold() for badge in soup.select(".manga-title-badges")}
        genres = {_text(link).casefold() for link in soup.select("div.genres-content a")}
        if (genres | badges) & _ADULT_GENRES:
            raise TritiniaSourceError(
                f"Tritinia lists {series_url} as adult; adult titles are not supported")
        for item in soup.select(".post-content_item"):
            heading = item.select_one(".summary-heading")
            content = item.select_one(".summary-content")
            if (heading is not None and content is not None and _text(heading) == "Type"
                    and _text(content).casefold() in _NOVEL_TYPES):
                raise TritiniaSourceError(
                    f"Tritinia lists {series_url} as a novel; only comics are supported")
        if badges & _NOVEL_TYPES:
            raise TritiniaSourceError(
                f"Tritinia lists {series_url} as a novel; only comics are supported")
        self._series_ids[series_url] = post_id
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The chapters a series serves, oldest first."""
        series_url, slug = self._series_parts(manga_url)
        self._series_page(series_url)
        ajax_url = f"{series_url}ajax/chapters/"
        headers = dict(self._AJAX_HEADERS, Referer=series_url)
        response = self._checked(self._post(ajax_url, headers=headers), "chapter list", ajax_url)
        rows = BeautifulSoup(response.text, "html.parser").select("li.wp-manga-chapter")
        if not rows:
            raise TritiniaSourceError(f"Tritinia lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise TritiniaSourceError(f"Tritinia lists too many chapters for {slug}")

        chapters: List[Chapter] = []
        numbers: Set[str] = set()
        urls: Set[str] = set()
        for row in rows:
            links = row.select("a[href]")
            if len(links) != 1 or _has_paid_class(row):
                raise TritiniaSourceError(
                    f"Tritinia has a locked or paid chapter of {slug}; "
                    f"this source reads free chapters only")
            label = _text(links[0])
            match = _LABEL.match(label)
            if match is None:
                raise TritiniaSourceError(
                    f"Tritinia has a chapter row of {slug} in an unknown form: {label!r}")
            number = format(Decimal(match.group(1)).normalize(), "f")
            try:
                url, row_series, _ = self._chapter_parts(links[0]["href"])
            except TritiniaSourceError:
                raise TritiniaSourceError(f"Tritinia links {label!r} of {slug} elsewhere") from None
            if row_series != slug:
                raise TritiniaSourceError(f"Tritinia links {label!r} of {slug} to another series")
            if url in urls or number in numbers:
                raise TritiniaSourceError(f"Tritinia lists chapter {number} of {slug} twice")
            urls.add(url)
            numbers.add(number)
            served_date = row.select_one("span.chapter-release-date")
            published = _row_date(_text(served_date)) if served_date else None
            chapters.append(Chapter(number=number, title=None, url=url, date=published))

        chapters.sort(key=lambda chapter: chapter_order_key(chapter.number))
        if chapters[0].numeric > 1:
            logger.warning("%s: %s lists %d chapter(s), %s to %s; earlier chapters are not "
                           "on the site's series page and are not listed", self.name,
                           series_url, len(chapters), chapters[0].number, chapters[-1].number)
        return chapters

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_url, _ = self._series_parts(manga_url)
            image = self._series_page(series_url).select_one("div.summary_image img")
            source = (image.get("data-src") or image.get("src") or "") if image else ""
            return _own_url(source, _COVER_PATH)
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in reader order, all or nothing."""
        url, series_slug, chapter_slug = self._chapter_parts(chapter_url)
        series_url = f"{self.base_url}/manga/{series_slug}/"

        def refused(why: str):
            return TritiniaSourceError(f"Tritinia chapter {url} {why}")

        html = self._checked(self._request(url, allow_redirects=False), "chapter", url).text
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if len(canonical) != 1 or canonical[0].get("href") != url:
            raise refused("answered for another page")
        crumbs = {link.get("href") for link in soup.select("ol.breadcrumb a[href]")
                  if "/manga/" in (link.get("href") or "")}
        current = soup.select("#wp-manga-current-chap")
        inline_series = _INLINE_SERIES.findall(html)
        inline_chapter = _INLINE_CHAPTER.findall(html)
        if (crumbs != {series_url} or len(current) != 1
                or current[0].get("value") != chapter_slug
                or inline_chapter != [chapter_slug] or len(set(inline_series)) != 1
                or _post_id(soup) != inline_series[0]):
            raise refused("does not name this chapter and its series")
        if series_url not in self._series_ids:
            self._series_page(series_url)
        if self._series_ids[series_url] != inline_series[0]:
            raise refused("names another series")
        if soup.select_one("#chapter-protector-data") is not None:
            raise refused("serves a protected page list, which this source does not read")
        readers = soup.select("div.reading-content")
        if len(readers) != 1:
            raise refused("lists no pages")
        if _has_paid_class(readers[0]):
            raise refused("is locked or paid; this source reads free chapters only")

        calls = list(_PRELOADED.finditer(html))
        if len(calls) != 1:
            raise refused(f"has {len(calls)} page lists, not one")
        try:
            pages, _ = json.JSONDecoder().raw_decode(html, calls[0].end())
        except ValueError:
            raise refused("has a page list that is not data this source reads") from None
        if not isinstance(pages, list) or not pages:
            raise refused("lists no pages")
        if len(pages) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        folders = set()
        for index, page in enumerate(pages):
            path = _site_path(page) if isinstance(page, str) else None
            match = _IMAGE_PATH.match(path) if path is not None else None
            if match is None or ".." in path.split("/"):
                raise refused(f"has an unexpected image for page {index + 1}")
            folders.add(match.group(1))
        if len(folders) != 1:
            raise refused("mixes images of several chapters")
        if len(set(pages)) != len(pages):
            raise refused("lists the same image twice")

        first = readers[0].select("img.wp-manga-chapter-img")
        if len(first) != 1 or (first[0].get("data-src") or first[0].get("src") or "").strip() \
                != pages[0]:
            raise refused("shows a first page that is not its list's first page")
        pickers = soup.select("select#single-pager")
        if not pickers or any(len(picker.select("option[value]")) != len(pages)
                              for picker in pickers):
            raise refused("counts its pages differently from its page list")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _own_url(url, _IMAGE_PATH) or _own_url(url, _COVER_PATH)
            if image_url is None:
                raise TritiniaSourceError(f"refused a page URL: {url}")
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise TritiniaSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise TritiniaSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise TritiniaSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a Tritinia page: %s", e)
            return False
