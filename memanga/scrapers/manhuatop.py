"""
ManhuaTop: an English manhua, manhwa and manga reader.

https://manhuatop.org

Search, chapter lists and reader pages come from the site's JSON API,
which takes the address of the page it serves as a ``path`` parameter.
A chapter list is read page by page at the size the site returns, and is
accepted only when the rows add up to the total it states. A row that
cannot be read as one chapter of this series raises: a list is never
returned short, and no chapter is guessed.

Fields whose meaning is unknown (a result's ``badge``, a response's
``synthetic``) are not read as locked or as free.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit

from ..chapters import format_chapter_value
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"manhuatop.org", "www.manhuatop.org"})
_IMAGE_HOST = "s3.manhuatop.org"
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
_CHAPTER_TITLE = re.compile(r"Chapter ([0-9]{1,6}(?:\.[0-9]{1,3})?)")
# A served "_1" suffix ("chapter-115_1") belongs to the link, not to the number.
_CHAPTER_SLUG = re.compile(r"chapter-([0-9]{1,6})(?:[-.]([0-9]{1,3})|_1)?")

# Upper bounds no real list comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class ManhuaTopSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a response without its expected fields, or a chapter list or
    reader that cannot be read completely."""


class ManhuaTopUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter pages."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_id(value) -> bool:
    return _is_int(value) or (isinstance(value, str) and bool(value))


class ManhuaTopScraper(BaseScraper):
    """manhuatop.org, through its JSON API."""

    name = "manhuatop"
    base_url = "https://manhuatop.org"
    engine = "api"
    content_language = "en"

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_segments(self, url: str) -> List[str]:
        """The path segments of a URL on this site. A login, port, query,
        fragment, relative URL or dot segment is refused."""
        refused = ManhuaTopUnsupportedError(f"Not a {self.name} page: {url!r}")
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
                               for s in segments):
            raise refused
        return segments

    def _series_slug(self, url: str) -> str:
        segments = self._own_segments(url)
        if len(segments) != 2 or segments[0] != "manhua":
            raise ManhuaTopUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_parts(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter slug)`` of a chapter page."""
        segments = self._own_segments(url)
        if len(segments) != 3 or segments[0] != "manhua":
            raise ManhuaTopUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return segments[1], segments[2]

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image on the site's image host, or None for
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
                or ".." in parts.path.split("/")
                or not parts.path.lower().endswith(_IMAGE_SUFFIXES)):
            return None
        return parts.path

    # ── Requests ─────────────────────────────────────────────────────

    def _json(self, url: str, what: str) -> dict:
        """A JSON object from ``url``, without following redirects."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise ManhuaTopSourceError(
                f"{self.name} {what} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise ManhuaTopSourceError(f"{self.name} {what} is too large")
        try:
            data = response.json()
        except ValueError:
            raise ManhuaTopSourceError(f"{self.name} {what} is not JSON") from None
        if not isinstance(data, dict):
            raise ManhuaTopSourceError(f"{self.name} {what} is not a JSON object")
        return data

    def _reader(self, resource: str, page_path: str, what: str) -> dict:
        url = (f"{self.base_url}/api/reader?resource={resource}"
               f"&path={quote(page_path, safe='')}")
        return self._json(url, what)

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search. An answer without its
        result list raises rather than reading as "no results"."""
        query = (query or "").strip()
        if not query:
            return []
        if len(query) < 2:
            raise ManhuaTopSourceError(f"{self.name} search needs at least 2 characters")
        # The query is one segment of the page address, and that address
        # is in turn one query value of the API URL.
        page_path = f"/search/{quote(query, safe='')}/"
        url = f"{self.base_url}/api/discovery?path={quote(page_path, safe='/')}"
        data = self._json(url, "search")
        items, has_more = data.get("items"), data.get("hasMore")
        if not isinstance(items, list) or not isinstance(has_more, bool):
            raise ManhuaTopSourceError(f"{self.name} search did not serve a result list")
        if not items and has_more:
            raise ManhuaTopSourceError(
                f"{self.name} search served no results but says there are more")

        results: List[Manga] = []
        seen = set()
        for item in items:
            title = item.get("title") if isinstance(item, dict) else None
            path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(title, str) or not title.strip() or not isinstance(path, str):
                raise ManhuaTopSourceError(
                    f"{self.name} search lists a result without its title or path")
            try:
                slug = self._series_slug(f"{self.base_url}{path}")
            except ManhuaTopUnsupportedError:
                raise ManhuaTopSourceError(
                    f"{self.name} search lists {path!r}, not a series of this site") from None
            series_url = f"{self.base_url}/manhua/{slug}/"
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title.strip(), url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _chapter_rows(self, slug: str) -> list:
        """Every row of the series' chapter list. The page size is the one
        the first page has; every page before the last must have it, and
        the rows must add up to the total every page states."""
        series_path = f"/manhua/{slug}/"
        rows: list = []
        total = size = None
        page = 1
        while True:
            what = f"chapter list of {series_path} (page {page})"
            data = self._reader("chapters", f"{series_path}?tab=chapters&chapter_page={page}",
                                what)
            items, served = data.get("items"), data.get("total")
            if not isinstance(items, list) or not _is_int(served) or served < 0:
                raise ManhuaTopSourceError(
                    f"{self.name} {what} has no chapter rows and total")
            echoed = data.get("page")
            if _is_int(echoed) and echoed != page:
                raise ManhuaTopSourceError(f"{self.name} {what} served page {echoed}")
            if total is None:
                if served == 0 or not items:
                    raise ManhuaTopSourceError(
                        f"{self.name} series {series_path} lists no chapters")
                if served > _MAX_CHAPTERS:
                    raise ManhuaTopSourceError(
                        f"{self.name} series {series_path} lists more chapters than "
                        f"this source reads")
                total, size = served, len(items)
            elif served != total:
                raise ManhuaTopSourceError(
                    f"{self.name} {what} states {served} chapters, not {total}")
            rows.extend(items)
            remaining = total - len(rows)
            if remaining < 0:
                raise ManhuaTopSourceError(
                    f"{self.name} {what} serves more rows than its total of {total}")
            has_more = data.get("hasMore")
            if isinstance(has_more, bool) and has_more != (remaining > 0):
                raise ManhuaTopSourceError(
                    f"{self.name} {what} disagrees with its total about further pages")
            if remaining == 0:
                return rows
            if len(items) != size:
                raise ManhuaTopSourceError(
                    f"{self.name} {what} has {len(items)} rows, not {size}, "
                    f"with {remaining} chapters still to come")
            page += 1

    def _row_number(self, item: dict, url: str) -> float:
        """The chapter number a row's title and slug agree on."""
        title = " ".join(item["title"].split()) if isinstance(item.get("title"), str) else ""
        slug = item.get("slug") if isinstance(item.get("slug"), str) else ""
        by_title, by_slug = _CHAPTER_TITLE.fullmatch(title), _CHAPTER_SLUG.fullmatch(slug)
        if by_title and by_slug:
            whole, part = by_slug.groups()
            number = float(by_title.group(1))
            if number == float(f"{whole}.{part}" if part else whole):
                return number
        raise ManhuaTopSourceError(
            f"{self.name} chapter {url} is not a plain numbered chapter "
            f"(title {title!r}, slug {slug!r})")

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters, newest first, one per number.

        A row without a reader link raises, as does one that belongs to
        another series or whose number is unclear, and two different
        links for one number. The same link listed twice is listed once,
        with a warning.
        """
        slug = self._series_slug(manga_url)
        by_number: Dict[float, Chapter] = {}
        number_of_url: Dict[str, float] = {}
        url_of_id: Dict[object, str] = {}
        series_ids = set()
        repeated = 0
        for item in self._chapter_rows(slug):
            if not isinstance(item, dict):
                raise ManhuaTopSourceError(f"{self.name} series {slug} has a malformed row")
            row_id, series_id = item.get("id"), item.get("mangaId")
            if not _is_id(row_id) or not _is_id(series_id):
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} has a row without its ids")
            series_ids.add(series_id)
            if len(series_ids) > 1:
                raise ManhuaTopSourceError(
                    f"{self.name} chapter list of {slug} mixes several series")
            path = item.get("path")
            if not isinstance(path, str) or not path:
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} has a chapter without a reader link")
            try:
                row_series, row_slug = self._chapter_parts(f"{self.base_url}{path}")
            except ManhuaTopUnsupportedError:
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} links a chapter to {path!r}") from None
            if row_series != slug or row_slug != item.get("slug"):
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} lists {path!r}, not a chapter of it")
            url = f"{self.base_url}/manhua/{slug}/{row_slug}/"
            number = self._row_number(item, url)

            if url_of_id.setdefault(row_id, url) != url:
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} gives one chapter id two links")
            known = number_of_url.get(url)
            if known is not None:
                if known != number:
                    raise ManhuaTopSourceError(
                        f"{self.name} series {slug} gives {url} two chapter numbers")
                repeated += 1
                continue
            if number in by_number:
                raise ManhuaTopSourceError(
                    f"{self.name} series {slug} has two links for chapter "
                    f"{format_chapter_value(number)}")
            number_of_url[url] = number
            extra = item.get("extra")
            label = " ".join(item["title"].split())
            if isinstance(extra, str) and extra.strip():
                label = f"{label} - {' '.join(extra.split())}"
            date = item.get("date")
            by_number[number] = Chapter(
                number=format_chapter_value(number),
                title=label,
                url=url,
                date=date if isinstance(date, str) and date else None,
            )
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a listed chapter",
                           self.name, repeated, slug)
        return sorted(by_number.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter, in reader order and exactly as
        served. A missing, off-host, repeated or oversized page raises;
        none is dropped, and a long strip is a normal page."""
        from ..image_limits import exceeds_pixel_limit

        slug, chapter = self._chapter_parts(chapter_url)
        page_path = f"/manhua/{slug}/{chapter}/"
        what = f"chapter {page_path}"
        data = self._reader("content", page_path, what)
        images = data.get("images")
        if not isinstance(images, list) or not images:
            raise ManhuaTopSourceError(
                f"{self.name} {what} has no page images; it may be unavailable or locked")
        if len(images) > _MAX_PAGES:
            raise ManhuaTopSourceError(f"{self.name} {what} has more pages than this source reads")
        stated = data.get("pageCount")
        if _is_int(stated) and stated != len(images):
            raise ManhuaTopSourceError(
                f"{self.name} {what} states {stated} pages but lists {len(images)}")

        pages: List[str] = []
        seen = set()
        for image in images:
            url = image.get("url") if isinstance(image, dict) else None
            path = self._image_path(url)
            if path is None:
                raise ManhuaTopSourceError(
                    f"{self.name} {what} has a page that is not an image of this site ({url!r})")
            if path in seen:
                raise ManhuaTopSourceError(f"{self.name} {what} shows page {url} twice")
            seen.add(path)
            width, height = image.get("width"), image.get("height")
            if _is_int(width) and _is_int(height) and (
                    width < 0 or height < 0 or exceeds_pixel_limit(width, height)):
                raise ManhuaTopSourceError(
                    f"{self.name} {what} states an invalid page size {width} x {height}")
            pages.append(url)

        indexes = [image.get("index") for image in images]
        if all(_is_int(i) for i in indexes) and (
                indexes[0] not in (0, 1)
                or indexes != list(range(indexes[0], indexes[0] + len(indexes)))):
            raise ManhuaTopSourceError(f"{self.name} {what} serves its pages out of order")
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
