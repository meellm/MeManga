"""
Mangas-Origines: a French manga, manhwa and manhua reader.

https://mangas-origines.fr

Search is the theme's catalogue action, a form POST answered with JSON
that holds an HTML fragment. The site's search is fuzzy, so its results
are returned as served and the app's own title filter applies to them.
A series' chapters come from a POST answered with HTML. Every row is in
that answer, including those the page folds behind "Voir plus".

Pages are the reader's ``data-src`` images, on the site's own host, and
the reader must name the requested chapter.
"""

import contextlib
import http.cookiejar
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from ..chapters import format_chapter_value
from .base import (BaseScraper, Chapter, Manga, _identifies_as_image, _retry,
                   is_retryable_request_error)

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"mangas-origines.fr", "www.mangas-origines.fr"})
_IMAGE_HOST = "mangas-origines.fr"
_IMAGE_PREFIX = "/wp-content/uploads/WP-manga/data/"
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SEGMENT = re.compile(r"(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+")
_ENCODED_SEPARATOR = re.compile(r"%(?:2[EeFf]|5[Cc])")
_NUMBER = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,3})?")
_CHAPTER_SLUG = re.compile(r"chapitre-([0-9]{1,6})(?:[-.]([0-9]{1,3}))?")

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class MangasOriginesSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected structure, or a chapter list
    or reader that cannot be read completely."""


class MangasOriginesUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter pages."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class MangasOriginesScraper(BaseScraper):
    """mangas-origines.fr, over plain HTTP."""

    name = "mangasorigines"
    base_url = "https://mangas-origines.fr"
    content_language = "fr"

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_segments(self, url: str) -> List[str]:
        """The path segments of a URL on this site. A login, port, query,
        fragment, relative URL or dot segment is refused."""
        refused = MangasOriginesUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise refused from None
        if (parts.scheme not in ("https", "http") or "@" in parts.netloc
                or port is not None or (parts.hostname or "") not in _SITE_HOSTS
                or parts.query or parts.fragment):
            raise refused
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        segments = path.split("/")[1:]
        if not segments or any(not _SEGMENT.fullmatch(s) or s in (".", "..")
                               or _ENCODED_SEPARATOR.search(s) for s in segments):
            raise refused
        return segments

    def _series_slug(self, url: str) -> str:
        segments = self._own_segments(url)
        if len(segments) != 2 or segments[0] != "oeuvre":
            raise MangasOriginesUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_parts(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter slug)`` of a chapter page."""
        segments = self._own_segments(url)
        if len(segments) != 3 or segments[0] != "oeuvre":
            raise MangasOriginesUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return segments[1], segments[2]

    def _image_path(self, url) -> Optional[str]:
        """The path of a chapter image on the site's own host, or None for
        anything else."""
        if not isinstance(url, str) or not url or any(
                c.isspace() or ord(c) < 32 for c in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if (parts.scheme != "https" or parts.netloc != _IMAGE_HOST
                or parts.query or parts.fragment
                or not parts.path.startswith(_IMAGE_PREFIX)
                or ".." in parts.path.split("/")
                or not parts.path.lower().endswith(_IMAGE_SUFFIXES)):
            return None
        return parts.path

    # ── Requests ─────────────────────────────────────────────────────

    @staticmethod
    def _check(response, what: str, name: str):
        if response.status_code != 200:
            raise MangasOriginesSourceError(
                f"{name} {what} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise MangasOriginesSourceError(f"{name} {what} is too large")
        return response

    def _post(self, url: str, what: str, data: Optional[dict] = None):
        """POST with the source's request spacing and retry rules, without
        following redirects; only a 200 counts."""
        def send():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            response = self.session.post(url, data=data, timeout=30, allow_redirects=False)
            response.raise_for_status()
            return response

        response = _retry(send, max_attempts=3, base_delay=1.0,
                          exceptions=(requests.RequestException,),
                          retry_if=is_retryable_request_error)
        return self._check(response, what, self.name)

    def _soup(self, content: bytes, what: str) -> BeautifulSoup:
        try:
            return BeautifulSoup((content or b"").decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise MangasOriginesSourceError(f"{self.name} {what} is not UTF-8") from None

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the catalogue search. No results is only an
        answer with empty HTML, no more pages and a total of 0."""
        query = (query or "").strip()
        if not query:
            return []
        response = self._post(f"{self.base_url}/wp-admin/admin-ajax.php", "search",
                              {"action": "madara_child_catalogue", "s": query, "page": "1"})
        try:
            answer = response.json()
        except ValueError:
            raise MangasOriginesSourceError(f"{self.name} search is not JSON") from None
        data = answer.get("data") if isinstance(answer, dict) else None
        if (not isinstance(answer, dict) or answer.get("success") is not True
                or not isinstance(data, dict) or not isinstance(data.get("html"), str)
                or not isinstance(data.get("more"), bool)
                or not _is_int(data.get("total")) or data["total"] < 0):
            raise MangasOriginesSourceError(f"{self.name} search did not serve a result list")
        html, more, total = data["html"], data["more"], data["total"]
        if html == "":
            if more or total != 0:
                raise MangasOriginesSourceError(
                    f"{self.name} search served no results but states {total}")
            return []

        cards = BeautifulSoup(html, "html.parser").select("a.ori-card")
        if not cards or (len(cards) >= total if more else len(cards) != total):
            raise MangasOriginesSourceError(
                f"{self.name} search served {len(cards)} results but states {total}")
        results: List[Manga] = []
        seen = set()
        for card in cards:
            element = card.select_one("span.ori-card-title")
            title = " ".join(element.get_text(" ", strip=True).split()) if element else ""
            if not title:
                raise MangasOriginesSourceError(
                    f"{self.name} search lists a result without its title")
            href = (card.get("href") or "").strip()
            try:
                slug = self._series_slug(href)
            except MangasOriginesUnsupportedError:
                raise MangasOriginesSourceError(
                    f"{self.name} search lists {href!r}, not a series of this site") from None
            series_url = f"{self.base_url}/oeuvre/{slug}/"
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _row_number(self, row, chapter_slug: str, url: str) -> Tuple[float, str]:
        """``(number, label)`` that a row's number, label and link agree on."""
        raw = (row.get("data-num") or "").strip()
        element = row.select_one("span.ori-chl-nom-long")
        label = " ".join(element.get_text(" ", strip=True).split()) if element else ""
        by_slug = _CHAPTER_SLUG.fullmatch(chapter_slug)
        if _NUMBER.fullmatch(raw) and label == f"Chapitre {raw}" and by_slug:
            whole, part = by_slug.groups()
            number = float(raw)
            if number == float(f"{whole}.{part}" if part else whole):
                return number, label
        raise MangasOriginesSourceError(
            f"{self.name} chapter {url} is not a plain numbered chapter "
            f"(number {raw!r}, label {label!r})")

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters, newest first, one per number.

        A row without a link raises, as does one that belongs to another
        series or whose number is unclear, one id with two links, and two
        links for one number. The same link listed twice is listed once,
        with a warning.
        """
        slug = self._series_slug(manga_url)
        what = f"chapter list of /oeuvre/{slug}/"
        response = self._post(f"{self.base_url}/oeuvre/{slug}/ajax/chapters/", what)
        rows = self._soup(response.content, what).select("div.ori-chl-row")
        if not rows:
            raise MangasOriginesSourceError(f"{self.name} series {slug} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangasOriginesSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")

        by_number: Dict[float, Chapter] = {}
        number_of_url: Dict[str, float] = {}
        url_of_id: Dict[str, str] = {}
        repeated = 0
        for row in rows:
            link = row.select_one("a.ori-chl-corps[href]")
            if link is None:
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} has a chapter without a link, which may "
                    f"be locked; this source reads free chapters only")
            href = link["href"].strip()
            try:
                row_series, chapter_slug = self._chapter_parts(href)
            except MangasOriginesUnsupportedError:
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} links a chapter to {href!r}") from None
            if row_series != slug:
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} lists {href!r}, not a chapter of it")
            url = f"{self.base_url}/oeuvre/{slug}/{chapter_slug}/"
            chapter_id = (row.get("data-chapitre") or "").strip()
            if not chapter_id.isascii() or not chapter_id.isdigit():
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} has a row without its chapter id")
            number, label = self._row_number(row, chapter_slug, url)
            if url_of_id.setdefault(chapter_id, url) != url:
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} gives one chapter id two links")
            known = number_of_url.get(url)
            if known is not None:
                if known != number:
                    raise MangasOriginesSourceError(
                        f"{self.name} series {slug} gives {url} two chapter numbers")
                repeated += 1
                continue
            if number in by_number:
                raise MangasOriginesSourceError(
                    f"{self.name} series {slug} has two links for chapter "
                    f"{format_chapter_value(number)}")
            number_of_url[url] = number
            date = row.select_one("span.ori-chl-date")
            by_number[number] = Chapter(
                number=format_chapter_value(number),
                title=label,
                url=url,
                date=((date.get("title") or "").strip() or None) if date else None,
            )
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a listed chapter",
                           self.name, repeated, slug)
        return sorted(by_number.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter, in reader order. A reader for another
        chapter, or a missing, off-host, out-of-order or repeated page
        raises, and none is dropped."""
        slug, chapter = self._chapter_parts(chapter_url)
        url = f"{self.base_url}/oeuvre/{slug}/{chapter}/"
        what = f"chapter {url}"
        response = self._check(self._request(f"{url}?style=list", allow_redirects=False),
                               what, self.name)
        soup = self._soup(response.content, what)
        current = soup.select_one("input#wp-manga-current-chap")
        canonical = soup.select_one('link[rel="canonical"]')
        if (current is None or current.get("value") != chapter
                or canonical is None or canonical.get("href") != url):
            raise MangasOriginesSourceError(f"{self.name} reader {url} is not this chapter")
        readers = soup.select("div.reading-content")
        if len(readers) != 1:
            raise MangasOriginesSourceError(
                f"{self.name} chapter {url} has {len(readers)} readers, not one")
        images = readers[0].select("img.wp-manga-chapter-img")
        if not images:
            raise MangasOriginesSourceError(
                f"{self.name} chapter {url} has no page images; it may be unavailable "
                f"or locked")
        if len(images) > _MAX_PAGES:
            raise MangasOriginesSourceError(
                f"{self.name} chapter {url} has more pages than this source reads")

        pages: List[str] = []
        seen = set()
        for index, image in enumerate(images):
            if image.get("id") != f"image-{index}":
                raise MangasOriginesSourceError(
                    f"{self.name} chapter {url} serves its pages out of order")
            # The site writes this attribute with a leading space.
            src = (image.get("data-src") or "").strip()
            path = self._image_path(src)
            if path is None:
                raise MangasOriginesSourceError(
                    f"{self.name} chapter {url} has a page that is not an image of "
                    f"this site ({src!r})")
            if path in seen:
                raise MangasOriginesSourceError(f"{self.name} chapter {url} shows {src} twice")
            seen.add(path)
            pages.append(src)
        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if self._image_path(url) is None:
                logger.warning("%s: refused a page URL off its image host: %s", self.name, url)
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
