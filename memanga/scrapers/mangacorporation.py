"""
Manga-Corporation: a French manga translation team's reader.

https://manga-corporation.com

The site serves a public JSON API. A series is ``/api/comics/<slug>``; each
chapter row carries its own reader path, ``/read/<slug>/fr/ch/<n>``,
optionally with ``/vol/<v>`` before and ``/sub/<s>`` after the chapter. The
reader answer, ``/api`` followed by that path, echoes the series and the
chapter and serves the page images as absolute URLs on
``images.manga-corporation.com``, read as served.

A chapter's number is its served chapter, with the subchapter after a dot
(``0.3``). Unnumbered rows (one-shots served as ``/read/<slug>/fr``) have no
number to file them under and are left out with a warning, as are rows in
another language, rows marked hidden or licensed, and rows published later
than now. A series marked adult, hidden or licensed is not read.
"""

import contextlib
import http.cookiejar
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "manga-corporation.com"
_SLUG_FORM = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_SLUG = re.compile(_SLUG_FORM)
_INT = r"(?:0|[1-9][0-9]{0,5})"
_READ_PATH = re.compile(
    rf"/read/({_SLUG_FORM})/fr(?:/vol/({_INT}))?/ch/({_INT})(?:/sub/({_INT}))?")
_PUBLISHED = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
# Pages as the reader serves them: a numbered chapter folder and a hex name.
_PAGE_URL = re.compile(
    r"https://images\.manga-corporation\.com/chapters/[0-9]{1,9}/[0-9a-f]{64}"
    r"\.(?:jpe?g|png|webp|gif)")
# Covers as the API serves them (``thumbnail``), with an optional ``?v=``.
_COVER_URL = re.compile(
    r"https://manga-corporation\.com/storage/comics/[A-Za-z0-9_-]+/(?:cover-variants/)?"
    r"[A-Za-z0-9%._-]+\.(?:jpe?g|png|webp|gif)(?:\?v=[0-9]{1,12})?")

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 200
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class MangaCorporationSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected fields, or a series, chapter or
    page this source does not read."""


class MangaCorporationUnsupportedError(ValueError):
    """A URL that is not one of this site's series or numbered chapter links."""


def _marked(item: dict, *keys: str) -> bool:
    """True when any of ``keys`` holds anything but an empty flag."""
    return any(item.get(key) not in (None, 0, False) for key in keys)


def _refusal(comic: dict) -> Optional[str]:
    """Why a series is not read, or None."""
    if _marked(comic, "adult"):
        return "marked adult"
    if _marked(comic, "hidden"):
        return "hidden"
    status = comic.get("status")
    if isinstance(status, str) and status.strip().casefold().startswith("licen"):
        return "licensed"
    return None


def _number(chapter: int, subchapter: Optional[int]) -> str:
    return str(chapter) if subchapter is None else f"{chapter}.{subchapter}"


class MangaCorporationScraper(BaseScraper):
    """manga-corporation.com, over its public JSON API."""

    name = "mangacorporation"
    base_url = "https://manga-corporation.com"
    engine = "api"
    content_language = "fr"
    # Every series carries a served adult flag, and flagged series are
    # refused.
    nsfw = False

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _path(self, url: str) -> str:
        """The path of a URL on this exact host, without a trailing slash."""
        refused = MangaCorporationUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
        except ValueError:
            raise refused from None
        if (parts.scheme != "https" or parts.netloc != _SITE_HOST
                or parts.query or parts.fragment):
            raise refused
        return parts.path[:-1] if parts.path.endswith("/") else parts.path

    def _series_slug(self, url: str) -> str:
        segments = self._path(url).split("/")[1:]
        if len(segments) != 2 or segments[0] != "comics" or not _SLUG.fullmatch(segments[1]):
            raise MangaCorporationUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str):
        """``(path, slug, volume, chapter, subchapter)`` of a numbered
        French reader link; unnumbered one-shot links are refused."""
        path = self._path(url)
        match = _READ_PATH.fullmatch(path)
        if match is None:
            raise MangaCorporationUnsupportedError(
                f"Not a {self.name} numbered chapter link: {url!r}")
        slug, volume, chapter, sub = match.groups()
        return (path, slug, None if volume is None else int(volume), int(chapter),
                None if sub is None else int(sub))

    # ── Requests ─────────────────────────────────────────────────────

    def _json(self, url: str, what: str) -> dict:
        """GET an API answer without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise MangaCorporationSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise MangaCorporationSourceError(f"{self.name} {what} {url} is too large")
        try:
            data = response.json()
        except ValueError:
            raise MangaCorporationSourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise MangaCorporationSourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    def _checked_comic(self, comic, slug: str, url: str) -> dict:
        """The served series, which must be ``slug`` and readable."""
        if (not isinstance(comic, dict) or comic.get("url") != f"/comics/{slug}"
                or comic.get("slug") != slug):
            raise MangaCorporationSourceError(f"{self.name} answer {url} is not this series")
        reason = _refusal(comic)
        if reason:
            raise MangaCorporationSourceError(
                f"{self.name} series {slug} is {reason}, which this source does not read")
        return comic

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The site's search results. A series marked adult, hidden or
        licensed is left out with a warning."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self.base_url}/api/search/{quote(query, safe='')}"
        comics = self._json(url, "search").get("comics")
        if not isinstance(comics, list) or len(comics) > _MAX_SEARCH_RESULTS:
            raise MangaCorporationSourceError(f"{self.name} search {url} did not serve a result list")

        results: List[Manga] = []
        left_out = 0
        for comic in comics:
            slug = comic.get("slug") if isinstance(comic, dict) else None
            title = comic.get("title") if isinstance(comic, dict) else None
            if (not isinstance(slug, str) or not _SLUG.fullmatch(slug)
                    or comic.get("url") != f"/comics/{slug}"
                    or not isinstance(title, str) or not title.strip()):
                raise MangaCorporationSourceError(f"{self.name} search {url} has an unreadable result")
            if _refusal(comic):
                left_out += 1
                continue
            series_url = f"{self.base_url}/comics/{slug}"
            if all(m.url != series_url for m in results):
                cover = comic.get("thumbnail")
                results.append(Manga(
                    title=" ".join(title.split()), url=series_url,
                    cover_url=cover if isinstance(cover, str) and _COVER_URL.fullmatch(cover)
                    else None))
        if left_out:
            logger.warning("%s: %d search result(s) are marked adult, hidden or licensed "
                           "and were left out", self.name, left_out)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' numbered French chapters, newest first.

        Each row's served path must agree with its volume, chapter and
        subchapter. A row in another form fails the listing; the rows this
        source does not read are left out with one counted warning each.
        """
        slug = self._series_slug(manga_url)
        url = f"{self.base_url}/api/comics/{slug}"
        comic = self._checked_comic(self._json(url, "series").get("comic"), slug, url)
        rows = comic.get("chapters")
        if not isinstance(rows, list):
            raise MangaCorporationSourceError(f"{self.name} series {slug} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaCorporationSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")

        now = datetime.now(timezone.utc)
        chapters, numbers, paths = [], {}, set()
        left_out = {"unnumbered": [], "another language": [], "hidden or licensed": [],
                    "not published yet": []}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                raise MangaCorporationSourceError(
                    f"{self.name} series {slug} has an unreadable chapter row")
            path = row["url"]
            label = row.get("full_title") if isinstance(row.get("full_title"), str) else path
            if row.get("language") != "fr":
                left_out["another language"].append(label)
                continue
            if row.get("chapter") is None and path == f"/read/{slug}/fr":
                left_out["unnumbered"].append(label)
                continue
            match = _READ_PATH.fullmatch(path)
            volume, chapter, sub = row.get("volume"), row.get("chapter"), row.get("subchapter")
            if (match is None or match.group(1) != slug or type(chapter) is not int
                    or not all(v is None or type(v) is int for v in (volume, sub))
                    or match.group(2) != (None if volume is None else str(volume))
                    or match.group(3) != str(chapter)
                    or match.group(4) != (None if sub is None else str(sub))):
                raise MangaCorporationSourceError(
                    f"{self.name} series {slug} has a chapter row this source cannot read "
                    f"yet ({path!r})")
            if _marked(row, "hidden", "licensed"):
                left_out["hidden or licensed"].append(label)
                continue
            published = _PUBLISHED.fullmatch(row.get("published_on") or "")
            when = (datetime.strptime(row["published_on"][:19], "%Y-%m-%dT%H:%M:%S")
                    .replace(tzinfo=timezone.utc) if published else None)
            if when is not None and when > now:
                left_out["not published yet"].append(label)
                continue
            number = _number(chapter, sub)
            if path in paths or number in numbers:
                raise MangaCorporationSourceError(
                    f"{self.name} series {slug} lists chapter {number} twice")
            paths.add(path)
            title = row.get("title")
            chapter_obj = Chapter(
                number=number,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                url=f"{self.base_url}{path}",
                date=published.group(1) if published else None,
            )
            if any(c.numeric == chapter_obj.numeric for c in numbers.values()):
                raise MangaCorporationSourceError(
                    f"{self.name} series {slug} has two chapters numbered like {number}")
            numbers[number] = chapter_obj
            chapters.append(chapter_obj)
        for reason, labels in left_out.items():
            if labels:
                logger.warning("%s: %s: %d chapter row(s) left out (%s): %s", self.name, slug,
                               len(labels), reason, "; ".join(labels))
        return sorted(chapters, key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page images, in served order.

        The reader must echo this series and this chapter; every page is a
        served image URL on the site's image host.
        """
        path, slug, volume, chapter, sub = self._chapter_ref(chapter_url)
        url = f"{self.base_url}/api{path}"
        data = self._json(url, "reader")
        self._checked_comic(data.get("comic"), slug, url)
        row = data.get("chapter")
        if (not isinstance(row, dict) or row.get("url") != path or row.get("language") != "fr"
                or row.get("chapter") != chapter or row.get("volume") != volume
                or row.get("subchapter") != sub):
            raise MangaCorporationSourceError(f"{self.name} reader {url} is not this chapter")
        if _marked(row, "hidden", "licensed"):
            raise MangaCorporationSourceError(
                f"{self.name} chapter {url} is marked hidden or licensed, which this source "
                f"does not read")
        pages = row.get("pages")
        if not isinstance(pages, list) or not pages:
            raise MangaCorporationSourceError(f"{self.name} reader {url} has no page images")
        if len(pages) > _MAX_PAGES:
            raise MangaCorporationSourceError(
                f"{self.name} reader {url} has more pages than this source reads")
        for index, page in enumerate(pages):
            if not isinstance(page, str) or _PAGE_URL.fullmatch(page) is None:
                raise MangaCorporationSourceError(
                    f"{self.name} reader {url} has page {index + 1} off the image host "
                    f"({str(page)[:80]!r})")
        if len(set(pages)) != len(pages):
            raise MangaCorporationSourceError(f"{self.name} reader {url} shows a page twice")
        return list(pages)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """No request is sent when a series is added; search results carry
        the served cover."""
        return None

    # ── Download ─────────────────────────────────────────────────────

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page or cover from its served host and path, sent with
        the site as Referer and without following redirects. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or not (_PAGE_URL.fullmatch(url)
                                                or _COVER_URL.fullmatch(url)):
                logger.warning("%s: refused a URL off its image paths: %s", self.name, url)
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
