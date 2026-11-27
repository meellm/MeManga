"""
InManga scraper - Spanish manga library
Site: inmanga.com

* search   -> POST /manga/getMangasConsultResult with the site's own filter
              form answers a fragment of ``a.manga-result`` cards linked as
              /ver/manga/<slug>/<series id>. No results is a fragment with
              no card and the site's "suggest a manga" note.
* chapters -> GET /chapter/getall?mangaIdentification=<series id> answers
              JSON whose ``data`` is itself a JSON document listing every
              chapter: its id, number, link number and registration date.
* pages    -> GET /chapter/chapterIndexControls?identification=<chapter id>
              lists the page ids in reader order (``img.ImageContainer``; the
              ``src`` there is a loading placeholder). The chapter's reader
              page serves the image address template ``pu``, and each page is
              that template with the page id in place of "identification",
              on cdn1.intomanga.com.

Ids are served in upper case in the chapter list and in lower case on the
reader, so they are compared without regard to case. Pages are saved as
served; the site serves WEBP bytes under .jpg addresses, so the bytes, not
the address or the content type, decide that a page is an image.

The reader carries the site's own adult-content flag; a chapter whose flag
is not "False" is refused and no confirmation is ever sent. So the source
is marked NSFW: no adult title was observed, but the site expects them.
"""

import json
import logging
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

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

_HOST = "inmanga.com"
_CDN = "cdn1.intomanga.com"
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_SLUG = r"[A-Za-z0-9](?:[A-Za-z0-9._~-]*[A-Za-z0-9])?"
_SERIES_PATH = re.compile(rf"^/ver/manga/({_SLUG})/({_UUID})$")
_CHAPTER_PATH = re.compile(rf"^/ver/manga/({_SLUG})/([0-9]+(?:-[0-9]+)?)/({_UUID})$")
_PAGE_URL = re.compile(rf"^https://{re.escape(_CDN)}/i/m/({_UUID})/c/({_UUID})/o/({_UUID})\.jpg$")
_COVER_URL = re.compile(rf"^https://{re.escape(_CDN)}/i/m/({_UUID})/t/o/({_UUID})\.jpg$")
_PAGE_TEMPLATE = "identification.jpg"
_REGISTERED = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})T[0-9:.]+$")
_ACCESS_KEY = re.compile(r"lock|price|coin|premium|vip|paid|purchase|unlock|point", re.I)


def _script_var(name: str) -> re.Pattern:
    return re.compile(rf"\bvar {name} = '([^'\\]*)';")


_READER_VARS = {name: _script_var(name) for name in ("pu", "cid", "mid", "cu")}

# The search form the site's own client sends; only the query is filled in.
_SEARCH_FORM: Tuple[Tuple[str, str], ...] = (
    ("filter[generes][]", "-1"),
    ("filter[queryString]", ""),
    ("filter[skip]", "0"),
    ("filter[take]", "10"),
    ("filter[sortby]", "1"),
    ("filter[broadcastStatus]", "0"),
    ("filter[onlyFavorites]", "false"),
    ("d", ""),
)

_MAX_CHAPTERS = 20000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class InMangaSourceError(RuntimeError):
    """inmanga.com answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _site_path(url) -> Optional[str]:
    """The path of a URL on this site (with or without "www."), or None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme == "" and parts.netloc == "" and url.strip().startswith("/"):
        return parts.path if not (parts.query or parts.fragment) else None
    if (parts.scheme not in ("http", "https")
            or (parts.hostname or "").lower() not in (_HOST, f"www.{_HOST}")
            or port is not None or "@" in parts.netloc or parts.query or parts.fragment):
        return None
    return parts.path


def _number(value) -> Optional[str]:
    """A served chapter ``Number`` as a label ("1", "912.5"), or None."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0:
        return None
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def _registered(value) -> Optional[str]:
    """A served ``RegistrationDate`` as YYYY-MM-DD, or None."""
    match = _REGISTERED.match(value) if isinstance(value, str) else None
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def _listing_key(chapter_url: str) -> str:
    """A chapter URL with its id in lower case, as ids are served in both cases."""
    head, _, chapter_id = chapter_url.rpartition("/")
    return f"{head}/{chapter_id.lower()}"


def _one_input(soup: BeautifulSoup, element_id: str) -> Optional[str]:
    inputs = soup.select(f"input#{element_id}")
    return inputs[0].get("value") if len(inputs) == 1 else None


class InMangaScraper(BaseScraper):
    """Scraper for InManga (inmanga.com)."""

    name = "inmanga"
    base_url = f"https://{_HOST}"
    content_language = "es"  # Spanish-language site
    nsfw = True  # the reader carries an adult flag; flagged chapters are refused

    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        # Worker copies share this: for each listed chapter, its series URL,
        # served chapter id and page count.
        self._listed: Dict[str, Tuple[str, str, int]] = {}

    # URLs

    def _series_parts(self, url) -> Tuple[str, str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise InMangaSourceError(f"Not an InManga series URL: {url}")
        slug, series_id = match.group(1), match.group(2).lower()
        return f"{self.base_url}/ver/manga/{slug}/{series_id}", slug, series_id

    def _chapter_parts(self, url) -> Tuple[str, str, str, str]:
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise InMangaSourceError(f"Not an InManga chapter URL: {url}")
        slug, link_number, chapter_id = match.groups()
        return (f"{self.base_url}/ver/manga/{slug}/{link_number}/{chapter_id}",
                slug, link_number, chapter_id)

    # Requests

    def _post(self, url: str, data=None):
        """POST with the source's request spacing and retry rules, without
        following redirects."""
        def send():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            response = self.session.post(url, data=data, timeout=30, allow_redirects=False)
            response.raise_for_status()
            return response

        return _retry(send, max_attempts=3, base_delay=1.0,
                      exceptions=(requests.RequestException,),
                      retry_if=is_retryable_request_error)

    def _checked(self, response, what: str, url: str):
        if response.status_code != 200:
            raise InMangaSourceError(
                f"InManga answered HTTP {response.status_code} for {what} {url}")
        return response

    def _get(self, url: str, what: str) -> str:
        return self._checked(self._request(url, allow_redirects=False), what, url).text

    # Search

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's own search."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/manga/getMangasConsultResult"
        form = [(key, query if key == "filter[queryString]" else value)
                for key, value in _SEARCH_FORM]
        soup = BeautifulSoup(self._checked(self._post(url, data=form), "search", url).text,
                             "html.parser")
        rows = soup.select("a.manga-result")
        if not rows:
            if soup.select("#suggestManga"):
                return []
            raise InMangaSourceError(
                f"InManga search for {query!r} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            titles = row.select("h4.m0")
            title = _text(titles[0]) if len(titles) == 1 else ""
            if not title:
                raise InMangaSourceError(
                    f"InManga search for {query!r} lists a result without a title")
            try:
                series_url, _, series_id = self._series_parts(row.get("href"))
            except InMangaSourceError:
                raise InMangaSourceError(
                    f"InManga search for {query!r} lists a result that is not a series"
                ) from None
            if series_url in seen:
                raise InMangaSourceError(f"InManga search for {query!r} lists {series_url} twice")
            seen.add(series_url)
            image = row.select_one("img[data-src]")
            cover = (image["data-src"].strip() if image else "")
            match = _COVER_URL.match(cover)
            if not (match and match.group(1).lower() == series_id == match.group(2).lower()):
                cover = None
            results.append(Manga(title=title, url=series_url, cover_url=cover))
        return results

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The numbered chapters of a series, oldest first."""
        series_url, slug, series_id = self._series_parts(manga_url)
        url = f"{self.base_url}/chapter/getall?mangaIdentification={series_id}"
        body = self._get(url, "chapter list")
        try:
            inner = json.loads(json.loads(body)["data"], parse_float=Decimal)
        except (ValueError, TypeError, KeyError):
            raise InMangaSourceError(
                f"InManga served an unreadable chapter list for {slug}") from None
        rows = inner.get("result") if isinstance(inner, dict) else None
        if (not isinstance(inner, dict) or inner.get("success") is not True
                or not isinstance(rows, list)):
            raise InMangaSourceError(f"InManga did not list the chapters of {slug}")
        if not rows:
            raise InMangaSourceError(f"InManga lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise InMangaSourceError(f"InManga lists too many chapters for {slug}")

        by_number: Dict[Decimal, List[Tuple[str, str, str, int, Optional[str]]]] = {}
        ids = set()
        for row in rows:
            if not isinstance(row, dict):
                raise InMangaSourceError(f"InManga has a malformed chapter row for {slug}")
            for key, value in row.items():
                if _ACCESS_KEY.search(key) and value not in (None, False, 0, "", [], {}):
                    raise InMangaSourceError(
                        f"InManga marks a chapter of {slug} with {key}={value!r}; "
                        f"this source reads free chapters only")
            number = _number(row.get("Number"))
            chapter_id = row.get("Identification")
            link_number = row.get("FriendlyChapterNumberUrl")
            pages = row.get("PagesCount")
            if (number is None or not isinstance(chapter_id, str)
                    or not re.fullmatch(_UUID, chapter_id)
                    or link_number != number.replace(".", "-")
                    or isinstance(pages, bool) or not isinstance(pages, int) or pages <= 0):
                raise InMangaSourceError(
                    f"InManga has a chapter row of {slug} in an unknown form: "
                    f"Number={row.get('Number')!r}, link {link_number!r}")
            if chapter_id.lower() in ids:
                raise InMangaSourceError(f"InManga lists chapter id {chapter_id} twice for {slug}")
            ids.add(chapter_id.lower())
            chapter_url = f"{self.base_url}/ver/manga/{slug}/{link_number}/{chapter_id}"
            by_number.setdefault(Decimal(number), []).append(
                (number, chapter_url, chapter_id, pages, _registered(row.get("RegistrationDate"))))

        chapters: List[Chapter] = []
        for entries in by_number.values():
            if len(entries) > 1:
                logger.warning(
                    "%s: chapter %s of %s is served %d times with different ids (%s); "
                    "none of them is listed", self.name, entries[0][0], series_url,
                    len(entries), ", ".join(entry[2] for entry in entries))
                continue
            number, chapter_url, chapter_id, pages, published = entries[0]
            chapters.append(Chapter(number=number, title=None, url=chapter_url, date=published))
            self._listed[_listing_key(chapter_url)] = (series_url, chapter_id, pages)
        if not chapters:
            raise InMangaSourceError(f"InManga lists no usable chapters for {slug}")
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The series cover in the form the site's search cards serve
        (/i/m/<id>/t/o/<id>.jpg on its image host); no request is sent."""
        try:
            _, _, series_id = self._series_parts(manga_url)
        except InMangaSourceError:
            return None
        return f"https://{_CDN}/i/m/{series_id}/t/o/{series_id}.jpg"

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in reader order, all or nothing."""
        url, slug, link_number, chapter_id = self._chapter_parts(chapter_url)

        def refused(why: str):
            return InMangaSourceError(f"InManga chapter {url} {why}")

        html = self._get(url, "chapter")
        reader = BeautifulSoup(html, "html.parser")
        adult = reader.select("input#IsAdultContent")
        if len(adult) != 1 or adult[0].get("value") != "False":
            raise refused("is flagged as adult content or does not say; this source reads "
                          "non-adult chapters only")
        values = {}
        for name, pattern in _READER_VARS.items():
            found = pattern.findall(html)
            values[name] = found[0] if len(found) == 1 else None
        og_url = reader.select('meta[property="og:url"]')
        series_id = (values["mid"] or "").lower()
        if (values["cid"] is None or values["cid"].lower() != chapter_id.lower()
                or not re.fullmatch(_UUID, series_id)
                or values["pu"] != f"https://{_CDN}/i/m/{values['mid']}/c/{values['cid']}/o/"
                                   f"{_PAGE_TEMPLATE}"
                or values["cu"] != f"/ver/manga/{slug}/chapterNumber/identification"
                or len(og_url) != 1
                or (og_url[0].get("content") or "").lower() != urlsplit(url).path.lower()):
            raise refused("does not name this chapter and its series")

        series_url = f"{self.base_url}/ver/manga/{slug}/{series_id}"
        if _listing_key(url) not in self._listed:
            self.get_chapters(series_url)
        listed = self._listed.get(_listing_key(url))
        if listed is None or listed[0] != series_url:
            raise refused("is not a chapter the series lists")
        _, listed_id, page_count = listed

        controls_url = f"{self.base_url}/chapter/chapterIndexControls?identification={listed_id}"
        controls = BeautifulSoup(self._get(controls_url, "page list"), "html.parser")
        if ((_one_input(controls, "ChapterIdentification") or "").lower() != chapter_id.lower()
                or (_one_input(controls, "MangaIdentification") or "").lower() != series_id
                or _one_input(controls, "FriendlyMangaName") != slug
                or _one_input(controls, "FriendlyChapterNumberUrl") != link_number):
            raise refused("has a page list for another chapter")

        images = controls.select("img.ImageContainer")
        if not images:
            raise refused("lists no pages")
        if len(images) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        prefix = values["pu"][:-len(_PAGE_TEMPLATE)]
        pages: List[str] = []
        for index, image in enumerate(images, start=1):
            page_id = image.get("id") or ""
            if image.get("data-pagenumber") != str(index) or not re.fullmatch(_UUID, page_id):
                raise refused(f"has a malformed page {index}")
            pages.append(f"{prefix}{page_id}.jpg")
        if len(set(page.lower() for page in pages)) != len(pages):
            raise refused("lists the same page twice")
        if len(pages) != page_count:
            raise refused(f"lists {len(pages)} pages where the chapter list says {page_count}")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page as served; a failure leaves no file at ``path``.
        The site serves WEBP bytes under .jpg addresses and an image/jpg
        content type, so the bytes decide that a page is an image."""
        path = Path(path)
        try:
            if not isinstance(url, str) or not _PAGE_URL.match(url):
                raise InMangaSourceError(f"refused a page URL: {url}")
            response = self._request(url, headers=self._IMAGE_HEADERS, allow_redirects=False)
            if response.status_code != 200:
                raise InMangaSourceError(f"{url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise InMangaSourceError(f"{url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise InMangaSourceError(f"{url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download an InManga page: %s", e)
            return False
