"""
Punk Records: a manga reader with a public JSON API.

https://punkrecordz.com

A series is ``/api/mangas/<slug>`` and a chapter's pages are
``/api/mangas/<slug>/chapters/<chapter slug>/reader``. The API is the
authority for identity: the reader must name the series and chapter asked
for, and every page path carries that series' and chapter's ids.

The catalogue mixes languages without saying which a series is in, so this
source declares none. Each page's plain ``url`` is read. A page that also
offers a ``coloredUrl`` edition raises, because which edition to read has
not been settled; no colour or black-and-white edition is promised.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "punkrecordz.com"
_IMAGE_HOST = "s3-preprod3.punkrecordz.com"
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NUMBER = re.compile(r"0|[1-9][0-9]{0,5}")
_ID_FORM = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ID = re.compile(_ID_FORM)
_PAGE_URL = re.compile(
    rf"https://s3-preprod3\.punkrecordz\.com/punk-records/mangas/({_ID_FORM})"
    rf"/chapters/({_ID_FORM})/pages/([0-9]{{4}})-({_ID_FORM})\.webp")
# Paths that are the site's own routes, never a series slug.
_RESERVED = frozenset({"api", "manga", "connexion", "compte", "equipe"})
# Keys that would mark a series, chapter or page as not freely readable.
_ACCESS_KEYS = ("adult", "nsfw", "mature", "hidden", "premium", "isPremium", "vip",
                "locked", "price", "coins", "paid", "licensed")
_ADULT_TAGS = frozenset({"adulte", "adult", "mature", "hentai", "smut",
                         "érotique", "erotique", "18+", "nsfw"})

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 200
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class PunkRecordsSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected fields, or a series, chapter or
    page form this source does not read."""


class PunkRecordsUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _marked(item) -> bool:
    """True when ``item`` (a dict) holds a set access or adult flag."""
    return any(item.get(key) not in (None, 0, False) for key in _ACCESS_KEYS)


def _is_id(value) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


class PunkRecordsScraper(BaseScraper):
    """punkrecordz.com, over its public JSON API."""

    name = "punkrecords"
    base_url = "https://punkrecordz.com"
    engine = "api"
    # Series are in different languages and none is labelled.
    content_language = None
    # Series carry no served genres or tags, so adult scope is unknown; the
    # source carries the label.
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
        refused = PunkRecordsUnsupportedError(f"Not a {self.name} page: {url!r}")
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
        if (len(segments) != 2 or segments[0] != "manga" or not _SLUG.fullmatch(segments[1])
                or segments[1] in _RESERVED):
            raise PunkRecordsUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter slug)`` of a chapter link, in the site's
        own ``/<series>/<chapter>`` form."""
        segments = self._segments(url)
        if (len(segments) != 2 or not _SLUG.fullmatch(segments[0]) or segments[0] in _RESERVED
                or not _NUMBER.fullmatch(segments[1])):
            raise PunkRecordsUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return segments[0], segments[1]

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise PunkRecordsSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise PunkRecordsSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _json(self, url: str, what: str) -> dict:
        response = self._fetch(url, what)
        try:
            data = response.json()
        except ValueError:
            raise PunkRecordsSourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise PunkRecordsSourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The site's search results, which must fit on one page. A series
        with an access or adult flag is left out with a warning."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self.base_url}/api/search?q={quote_plus(query)}&page=1&perPage=24"
        data = self._json(url, "search")
        items = data.get("items")
        if (not isinstance(items, list) or len(items) > _MAX_SEARCH_RESULTS
                or data.get("page") != 1 or type(data.get("total")) is not int):
            raise PunkRecordsSourceError(f"{self.name} search {url} did not serve a result list")
        if data.get("totalPages") != 1 or data["total"] != len(items):
            raise PunkRecordsSourceError(
                f"{self.name} search {url} spans {data.get('totalPages')!r} pages "
                f"({data['total']} results); only a single page is read")

        results: List[Manga] = []
        seen = set()
        left_out = 0
        for item in items:
            slug = item.get("slug") if isinstance(item, dict) else None
            title = item.get("title") if isinstance(item, dict) else None
            if (not isinstance(slug, str) or not _SLUG.fullmatch(slug) or slug in _RESERVED
                    or not _is_id(item.get("id"))
                    or not isinstance(title, str) or not title.strip()):
                raise PunkRecordsSourceError(f"{self.name} search {url} has an unreadable result")
            if _marked(item):
                left_out += 1
                continue
            series_url = f"{self.base_url}/manga/{slug}"
            if series_url not in seen:
                seen.add(series_url)
                results.append(Manga(title=title.strip(), url=series_url))
        if left_out:
            logger.warning("%s: %d search result(s) are marked adult or restricted and "
                           "were left out", self.name, left_out)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _checked_series(self, manga, slug: str, url: str) -> dict:
        title = manga.get("title") if isinstance(manga, dict) else None
        if (not isinstance(manga, dict) or manga.get("slug") != slug or not _is_id(manga.get("id"))
                or not isinstance(title, str) or not title.strip()):
            raise PunkRecordsSourceError(f"{self.name} answer {url} is not this series")
        if _marked(manga):
            raise PunkRecordsSourceError(
                f"{self.name} series {slug} is marked adult or restricted, which this source "
                f"does not read")
        for key in ("genres", "tags"):
            values = manga.get(key, [])
            if values is None:
                continue
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise PunkRecordsSourceError(f"{self.name} series {slug} has unreadable {key}")
            if any(v.strip().casefold() in _ADULT_TAGS for v in values):
                raise PunkRecordsSourceError(
                    f"{self.name} series {slug} is tagged adult, which this source does not read")
        return manga

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' chapters, newest first.

        Only whole chapter numbers whose slug is that number are read; a
        decimal or other chapter form raises until one is observed. The list
        must be as long as the series says it is.
        """
        slug = self._series_slug(manga_url)
        url = f"{self.base_url}/api/mangas/{slug}"
        data = self._json(url, "series")
        manga = self._checked_series(data.get("manga"), slug, url)
        rows = data.get("chapters")
        if not isinstance(rows, list) or not rows:
            raise PunkRecordsSourceError(f"{self.name} series {slug} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise PunkRecordsSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")
        if manga.get("chapterCount") != len(rows):
            raise PunkRecordsSourceError(
                f"{self.name} series {slug} lists {len(rows)} chapters but counts "
                f"{manga.get('chapterCount')!r}")

        chapters: Dict[str, Chapter] = {}
        ids = set()
        for row in rows:
            number = row.get("number") if isinstance(row, dict) else None
            if (not isinstance(row, dict) or type(number) is not int
                    or not 0 <= number <= 999999 or row.get("slug") != str(number)
                    or not _is_id(row.get("id")) or not isinstance(row.get("title"), str)):
                raise PunkRecordsSourceError(
                    f"{self.name} series {slug} has a chapter row this source cannot read yet "
                    f"({row.get('slug') if isinstance(row, dict) else row!r})")
            if _marked(row):
                raise PunkRecordsSourceError(
                    f"{self.name} series {slug} has chapter {number} marked restricted")
            text = str(number)
            if text in chapters or row["id"] in ids:
                raise PunkRecordsSourceError(
                    f"{self.name} series {slug} lists chapter {text} twice")
            ids.add(row["id"])
            title = row["title"].strip()
            # ``publishedAt`` looks like an import time, so it is not kept.
            chapters[text] = Chapter(
                number=text,
                title=title or None,
                url=f"{self.base_url}/{slug}/{text}",
                date=None,
            )
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's plain page images, in served order.

        The reader must name this series and chapter; each page must be in
        order by ``pageIndex`` and sit at the path built from the series,
        chapter and page ids. A page offering a ``coloredUrl`` raises.
        """
        slug, chapter_slug = self._chapter_ref(chapter_url)
        url = f"{self.base_url}/api/mangas/{slug}/chapters/{chapter_slug}/reader"
        data = self._json(url, "reader")
        manga, chapter = data.get("manga"), data.get("chapter")
        if (not isinstance(manga, dict) or not isinstance(chapter, dict)
                or manga.get("slug") != slug or not _is_id(manga.get("id"))
                or chapter.get("mangaId") != manga["id"] or not _is_id(chapter.get("id"))
                or chapter.get("slug") != chapter_slug
                or type(chapter.get("number")) is not int
                or str(chapter["number"]) != chapter_slug):
            raise PunkRecordsSourceError(f"{self.name} reader {url} is not this chapter")
        if _marked(manga) or _marked(chapter):
            raise PunkRecordsSourceError(
                f"{self.name} chapter {url} is marked adult or restricted, which this source "
                f"does not read")

        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            raise PunkRecordsSourceError(f"{self.name} reader {url} has no page images")
        if len(pages) > _MAX_PAGES:
            raise PunkRecordsSourceError(
                f"{self.name} reader {url} has more pages than this source reads")
        result: List[str] = []
        page_ids = set()
        for index, page in enumerate(pages):
            if not isinstance(page, dict):
                raise PunkRecordsSourceError(f"{self.name} reader {url} has an unreadable page")
            if page.get("coloredUrl") is not None:
                raise PunkRecordsSourceError(
                    f"{self.name} reader {url} offers a coloured edition of page {index + 1}, "
                    f"which this source does not choose between")
            if _marked(page):
                raise PunkRecordsSourceError(
                    f"{self.name} reader {url} has page {index + 1} marked restricted")
            value = page.get("url")
            match = _PAGE_URL.fullmatch(value) if isinstance(value, str) else None
            if (match is None or page.get("pageIndex") != index
                    or match.group(1) != manga["id"] or match.group(2) != chapter["id"]
                    or match.group(3) != f"{index:04d}" or match.group(4) != page.get("id")):
                raise PunkRecordsSourceError(
                    f"{self.name} reader {url} has page {index + 1} out of place ({value!r})")
            if value in result or page["id"] in page_ids:
                raise PunkRecordsSourceError(
                    f"{self.name} reader {url} shows page {page['id']} twice")
            page_ids.add(page["id"])
            result.append(value)
        return result

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """No cover is read, so adding a series sends no request and does not
        check that the series exists."""
        return None

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or _PAGE_URL.fullmatch(url) is None:
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
