"""
Lelscan VF: a French manga reader.

https://www.lelscanfr.com

A series page lists its chapters in pages of up to 100 rows, newest first.
This source reads the first page only. A longer series is returned short,
with a warning that counts the pages left unread, so its list must never be
taken for the whole series.

Row dates are relative French phrases ("il y a 2 jours"), so none is kept.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import List, Tuple
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "www.lelscanfr.com"
_SLUG_FORM = r"[A-Za-z0-9](?:[A-Za-z0-9._~-]*[A-Za-z0-9])?"
_NUMBER_FORM = r"0|[1-9][0-9]{0,5}"
_SLUG = re.compile(_SLUG_FORM)
_NUMBER = re.compile(_NUMBER_FORM)
_CHAPTER_LABEL = re.compile(rf"Chapitre ({_NUMBER_FORM})")
_LIST_PAGE = re.compile(r"Page ([0-9]{1,4}) of ([0-9]{1,4})")
_IMAGE_URL = re.compile(
    rf"https://www\.lelscanfr\.com/storage/content/({_SLUG_FORM})/({_NUMBER_FORM})/"
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:webp|jpe?g|png|gif)")
_RESULT_GRID_CLASS = "xlg:grid-cols-8"
_AD_CLASS = "lelscanfr-above-images-chapter-ad"
_EMPTY_NOTICE = "Aucune donnée n'a été trouvée"

# A chapter-list page holds up to this many rows.
_LIST_PAGE_SIZE = 100

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 200
_MAX_ROWS = 200
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class LelscanVFSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, or a page without its expected structure."""


class LelscanVFUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _text(element) -> str:
    """The element's text with its whitespace collapsed."""
    return " ".join(element.get_text().split())


class LelscanVFScraper(BaseScraper):
    """www.lelscanfr.com, over plain HTTP."""

    name = "lelscanvf"
    base_url = "https://www.lelscanfr.com"
    engine = "http"
    content_language = "fr"
    # The catalogue's filters offer adult genres. Single titles are not
    # classified here, so the whole source carries the label.
    nsfw = True

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _segments(self, url: str) -> List[str]:
        """The path segments of a URL on this exact host. A login, port,
        query, fragment or relative URL is refused."""
        refused = LelscanVFUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
        except ValueError:
            raise refused from None
        if (parts.scheme != "https" or parts.netloc != _SITE_HOST
                or parts.query or parts.fragment):
            raise refused
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        return path.split("/")[1:]

    def _series_slug(self, url: str) -> str:
        segments = self._segments(url)
        if len(segments) != 2 or segments[0] != "manga" or not _SLUG.fullmatch(segments[1]):
            raise LelscanVFUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter number text)`` of a chapter link."""
        segments = self._segments(url)
        if (len(segments) != 3 or segments[0] != "manga"
                or not _SLUG.fullmatch(segments[1]) or not _NUMBER.fullmatch(segments[2])):
            raise LelscanVFUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return segments[1], segments[2]

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise LelscanVFSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise LelscanVFSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _soup(self, content: bytes, url: str) -> BeautifulSoup:
        try:
            return BeautifulSoup((content or b"").decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise LelscanVFSourceError(f"{self.name} page {url} is not UTF-8") from None

    @staticmethod
    def _canonical(soup: BeautifulSoup) -> str:
        """The page's one canonical URL, or an empty string."""
        links = soup.select('link[rel="canonical"]')
        return (links[0].get("href") or "") if len(links) == 1 else ""

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's results. The site's own empty answer
        is an empty list; any other page without result cards raises."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self.base_url}/manga?title={quote(query, safe='')}"
        soup = self._soup(self._fetch(url, "search").content, url)

        grids = soup.find_all("div", class_=_RESULT_GRID_CLASS)
        echoes = soup.select('input#title[name="title"]')
        if len(grids) != 1 or len(echoes) != 1 or echoes[0].get("value") != query:
            raise LelscanVFSourceError(f"{self.name} search {url} is not a result page")
        grid = grids[0]
        cards = grid.select("div#card-real")
        loaders = grid.select("div#card-loader")
        if not cards and not loaders:
            notices = [p for p in soup.find_all("p") if _text(p) == _EMPTY_NOTICE]
            if len(notices) == 1 and grid.find(True) is None:
                return []
            raise LelscanVFSourceError(f"{self.name} search {url} did not serve results")
        if len(cards) != len(loaders) or len(cards) > _MAX_SEARCH_RESULTS:
            raise LelscanVFSourceError(f"{self.name} search {url} has an unreadable result grid")

        results: List[Manga] = []
        seen = set()
        for card in cards:
            links = card.select("a[href]")
            # Each card repeats its title in a hover overlay.
            titles = [_text(h2) for h2 in card.select("h2.text-sm")]
            if len(links) != 1 or not titles or not titles[0] or len(set(titles)) != 1:
                raise LelscanVFSourceError(f"{self.name} search {url} has an unreadable card")
            try:
                slug = self._series_slug(links[0]["href"])
            except LelscanVFUnsupportedError:
                raise LelscanVFSourceError(
                    f"{self.name} search {url} lists {links[0]['href']!r}, not a series "
                    f"of this site") from None
            series_url = f"{self.base_url}/manga/{slug}"
            if series_url not in seen:
                seen.add(series_url)
                results.append(Manga(title=titles[0], url=series_url))
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _list_page_count(self, chapter_list, series_url: str, rows: int) -> int:
        """How many pages the chapter list has, read from the page-1 pager.
        No pager means one page, unless that page is full."""
        labels = chapter_list.select("nav h3")
        pagers = chapter_list.select("ul.pagination")
        if not labels and not pagers:
            if rows >= _LIST_PAGE_SIZE:
                raise LelscanVFSourceError(
                    f"{self.name} series {series_url} has a full chapter page without "
                    f"a pager, so its length is unknown")
            return 1
        match = _LIST_PAGE.fullmatch(_text(labels[0])) if len(labels) == 1 else None
        active = pagers[0].select('li[aria-current="page"]') if len(pagers) == 1 else []
        if (match is None or match.group(1) != "1" or int(match.group(2)) < 1
                or len(active) != 1 or _text(active[0]) != "1"):
            raise LelscanVFSourceError(
                f"{self.name} series {series_url} has a chapter pager this source cannot read")
        return int(match.group(2))

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The chapters on page 1 of the series' list, newest first.

        When the list has more pages they are not read: a warning names how
        many, and the result is not the whole series. A row that does not
        match its link, a decimal or named chapter, and a repeated row raise.
        """
        slug = self._series_slug(manga_url)
        series_url = f"{self.base_url}/manga/{slug}"
        soup = self._soup(self._fetch(series_url, "series page").content, series_url)
        lists = soup.select("div#chapters-list")
        if self._canonical(soup) != series_url or len(lists) != 1:
            raise LelscanVFSourceError(f"{self.name} page {series_url} is not this series")
        chapter_list = lists[0]
        rows = chapter_list.find_all("a", recursive=False)
        if not rows:
            raise LelscanVFSourceError(f"{self.name} series {series_url} lists no chapters")
        if len(rows) > _MAX_ROWS:
            raise LelscanVFSourceError(
                f"{self.name} series {series_url} lists more rows than this source reads")
        if len(chapter_list.find_all("a")) != len(rows):
            raise LelscanVFSourceError(
                f"{self.name} series {series_url} has a link outside its chapter rows")

        chapters: List[Chapter] = []
        seen = set()
        for row in rows:
            span = row.find("span")
            label = _text(span) if span is not None else ""
            match = _CHAPTER_LABEL.fullmatch(label)
            if match is None:
                raise LelscanVFSourceError(
                    f"{self.name} series {series_url} has a row {label!r} this source "
                    f"cannot read")
            number = match.group(1)
            url = f"{series_url}/{number}"
            if row.get("href") != url:
                raise LelscanVFSourceError(
                    f"{self.name} series {series_url} links {label!r} to "
                    f"{row.get('href')!r}")
            if number in seen:
                raise LelscanVFSourceError(
                    f"{self.name} series {series_url} lists chapter {number} twice")
            seen.add(number)
            chapters.append(Chapter(number=number, title=label, url=url, date=None))

        pages = self._list_page_count(chapter_list, series_url, len(rows))
        if pages > 1:
            # Only a newest-first list makes page 1 the part worth reading.
            values = [int(chapter.number) for chapter in chapters]
            if any(earlier <= later for earlier, later in zip(values, values[1:])):
                raise LelscanVFSourceError(
                    f"{self.name} series {series_url} is not listed newest first")
            logger.warning(
                "%s: %s lists its chapters on %d pages; only page 1 (%d chapters) is "
                "read, and the chapters on the other %d page(s) are missing",
                self.name, series_url, pages, len(chapters), pages - 1)
        return sorted(chapters, key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page image of the chapter, in reader order and as served.
        A page without exactly one address, off this chapter's image path,
        out of order or repeated raises."""
        slug, number = self._chapter_ref(chapter_url)
        reader = f"{self.base_url}/manga/{slug}/{number}"
        soup = self._soup(self._fetch(reader, "reader").content, reader)
        containers = soup.select("div#chapter-container")
        if self._canonical(soup) != reader or len(containers) != 1:
            raise LelscanVFSourceError(f"{self.name} reader {reader} is not this chapter")
        container = containers[0]

        pages: List[str] = []
        seen = set()
        for image in container.find_all("img"):
            if image.parent is not container:
                if image.find_parent("div", class_=_AD_CLASS) is not None:
                    continue
                raise LelscanVFSourceError(
                    f"{self.name} reader {reader} has an image it cannot place")
            src, lazy = image.get("src"), image.get("data-src")
            if (src is None) == (lazy is None):
                raise LelscanVFSourceError(
                    f"{self.name} reader {reader} has a page without exactly one address")
            value = src if lazy is None else lazy
            match = _IMAGE_URL.fullmatch(value)
            if match is None or match.group(1) != slug or match.group(2) != number:
                raise LelscanVFSourceError(
                    f"{self.name} reader {reader} has a page off this chapter ({value!r})")
            if ("chapter-image" not in (image.get("class") or [])
                    or image.get("data-id") != str(len(pages))):
                raise LelscanVFSourceError(
                    f"{self.name} reader {reader} has a page out of order ({value!r})")
            if value in seen:
                raise LelscanVFSourceError(f"{self.name} reader {reader} shows {value} twice")
            seen.add(value)
            pages.append(value)
        if not pages:
            raise LelscanVFSourceError(f"{self.name} reader {reader} has no page images")
        if len(pages) > _MAX_PAGES:
            raise LelscanVFSourceError(
                f"{self.name} reader {reader} has more pages than this source reads")
        return pages

    def get_cover_url(self, manga_url: str):
        """The series page serves no ``og:image``, so no request is made."""
        return None

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or _IMAGE_URL.fullmatch(url) is None:
                logger.warning("%s: refused a page URL off its image path: %s", self.name, url)
            else:
                response = self._request(url, allow_redirects=False,
                                         headers={"Referer": f"{self.base_url}/"})
                content = response.content if response.status_code == 200 else b""
                if _identifies_as_image(content):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    saved = True
                else:
                    logger.warning("%s: page is not an image (HTTP %s, %d bytes): %s", self.name,
                                   response.status_code, len(content or b""), url)
        except Exception as e:
            logger.error("%s: failed to download page %s: %s", self.name, url, e)
        if not saved:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        return saved
