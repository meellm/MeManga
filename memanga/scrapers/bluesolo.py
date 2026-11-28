"""
Blue Solo: a French scanlation site that hosts several teams.

https://bluesolo.org

The site serves a public JSON API. A series is ``/api/comics/<slug>``, and a
chapter is ``/api`` plus its served link,
``/read/<slug>/fr[/vol/<v>]/ch/<c>[/sub/<s>]``. The series web page
``/comics/<slug>`` is a script shell that names any slug, so a series is
known only from its API answer, which must name it.

A subchapter is listed as the decimal the site labels it with (``Ch.60.5``
is chapter 60, subchapter 5), and only when the row's own label says so.
Volume and subchapter stay in the chapter's link, so a chapter is always read
from exactly the row it came from. An unnumbered row has no number to file it
under, so it is left out with a warning rather than given one.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "bluesolo.org"
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_NUMBER = re.compile(r"0|[1-9][0-9]{0,5}")
_SUBCHAPTER = re.compile(r"[1-9]")
_PUBLISHED = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
# Pages and covers are served with a cache-busting ``?v=`` query, kept as served.
_PAGE_URL = re.compile(
    r"https://bluesolo\.org/storage/comics/[A-Za-z0-9][A-Za-z0-9_.-]*/([A-Za-z0-9][A-Za-z0-9_.-]*)/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpe?g|webp|gif)(?:\?v=[0-9]{1,12})?")
_COVER_URL = re.compile(
    r"https://bluesolo\.org/storage/comics/[A-Za-z0-9][A-Za-z0-9_.-]*/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpe?g|webp|gif)(?:\?v=[0-9]{1,12})?")
# Genres the site may give a series while leaving its ``adult`` flag at 0.
_ADULT_GENRES = frozenset({
    "mature", "adult", "adulte", "hentai", "smut", "erotique", "érotique", "nsfw"})

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 200
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class BlueSoloSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected fields, or a series or chapter
    this source does not read."""


class BlueSoloUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _marked(item: dict, *keys: str) -> bool:
    """True when any of ``keys`` holds anything but an empty flag."""
    return any(item.get(key) not in (None, 0, False) for key in keys)


def _whole(value) -> bool:
    return type(value) is int and 0 <= value <= 999999


def _read_path(slug: str, volume, chapter, subchapter) -> str:
    path = f"/read/{slug}/fr"
    if volume is not None:
        path += f"/vol/{volume}"
    path += f"/ch/{chapter}"
    if subchapter is not None:
        path += f"/sub/{subchapter}"
    return path


def _refusal(comic: dict) -> Optional[str]:
    """Why a series is not read, or None. A missing status is not a reason."""
    if _marked(comic, "adult"):
        return "marked adult"
    if _marked(comic, "hidden"):
        return "hidden"
    status = comic.get("status")
    if isinstance(status, str) and status.strip().casefold().startswith("licen"):
        return "licensed"
    genres = comic.get("genres")
    if genres is None:
        return None
    if not isinstance(genres, list):
        return "listed with unreadable genres"
    for genre in genres:
        name = genre.get("name") if isinstance(genre, dict) else None
        if not isinstance(name, str):
            return "listed with unreadable genres"
        if name.strip().casefold() in _ADULT_GENRES:
            return "marked adult by its genres"
    return None


class BlueSoloScraper(BaseScraper):
    """bluesolo.org, over its public JSON API."""

    name = "bluesolo"
    base_url = "https://bluesolo.org"
    engine = "api"
    content_language = "fr"
    # The catalogue holds a series with an adult genre and an unset adult
    # flag; such series are refused, and the source carries the label.
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
        refused = BlueSoloUnsupportedError(f"Not a {self.name} page: {url!r}")
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
        if len(segments) != 2 or segments[0] != "comics" or not _SLUG.fullmatch(segments[1]):
            raise BlueSoloUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, Optional[int], int, Optional[int]]:
        """``(slug, volume, chapter, subchapter)`` of a numbered chapter link."""
        refused = BlueSoloUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        segments = self._segments(url)
        if len(segments) < 5 or segments[:1] != ["read"] or segments[2] != "fr" \
                or not _SLUG.fullmatch(segments[1]):
            raise refused
        rest = segments[3:]
        volume = subchapter = None
        if rest[:1] == ["vol"]:
            if len(rest) < 2 or not _NUMBER.fullmatch(rest[1]):
                raise refused
            volume, rest = int(rest[1]), rest[2:]
        if len(rest) < 2 or rest[0] != "ch" or not _NUMBER.fullmatch(rest[1]):
            raise refused
        chapter, rest = int(rest[1]), rest[2:]
        if rest:
            if len(rest) != 2 or rest[0] != "sub" or not _SUBCHAPTER.fullmatch(rest[1]):
                raise refused
            subchapter = int(rest[1])
        return segments[1], volume, chapter, subchapter

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise BlueSoloSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise BlueSoloSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _json(self, url: str, what: str) -> dict:
        response = self._fetch(url, what)
        try:
            data = response.json()
        except ValueError:
            raise BlueSoloSourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise BlueSoloSourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    def _checked_comic(self, comic, slug: str, url: str) -> dict:
        """The served series, which must be ``slug``, titled, and readable."""
        title = comic.get("title") if isinstance(comic, dict) else None
        if (not isinstance(comic, dict) or comic.get("url") != f"/comics/{slug}"
                or comic.get("slug") != slug or not isinstance(title, str) or not title.strip()):
            raise BlueSoloSourceError(f"{self.name} answer {url} is not this series")
        reason = _refusal(comic)
        if reason:
            raise BlueSoloSourceError(
                f"{self.name} series {slug} is {reason}, which this source does not read")
        return comic

    def _series(self, slug: str) -> dict:
        url = f"{self.base_url}/api/comics/{slug}"
        return self._checked_comic(self._json(url, "series").get("comic"), slug, url)

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The site's search results. A series that is marked adult (by its
        flag or its genres), hidden or licensed is left out with a warning."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self.base_url}/api/search/{quote(query, safe='')}"
        comics = self._json(url, "search").get("comics")
        if not isinstance(comics, list) or len(comics) > _MAX_SEARCH_RESULTS:
            raise BlueSoloSourceError(f"{self.name} search {url} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        left_out = 0
        for comic in comics:
            slug = comic.get("slug") if isinstance(comic, dict) else None
            title = comic.get("title") if isinstance(comic, dict) else None
            if (not isinstance(slug, str) or not _SLUG.fullmatch(slug)
                    or comic.get("url") != f"/comics/{slug}"
                    or not isinstance(title, str) or not title.strip()):
                raise BlueSoloSourceError(f"{self.name} search {url} has an unreadable result")
            if _refusal(comic):
                left_out += 1
                continue
            series_url = f"{self.base_url}/comics/{slug}"
            if series_url not in seen:
                seen.add(series_url)
                results.append(Manga(title=title.strip(), url=series_url))
        if left_out:
            logger.warning("%s: %d search result(s) are marked adult, hidden or licensed "
                           "and were left out", self.name, left_out)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _chapter_number(self, row: dict, slug: str) -> str:
        """The number a row is listed under. A subchapter becomes the decimal
        the row's own label shows; any other form raises."""
        volume, chapter, sub = row.get("volume"), row.get("chapter"), row.get("subchapter")
        link = row.get("url")
        if (not _whole(chapter) or (volume is not None and not _whole(volume))
                or (sub is not None and (type(sub) is not int or not 1 <= sub <= 9))
                or link != _read_path(slug, volume, chapter, sub)):
            raise BlueSoloSourceError(
                f"{self.name} series {slug} has a chapter row this source cannot read "
                f"({link!r})")
        if sub is None:
            return str(chapter)
        number = f"{chapter}.{sub}"
        label = "[FR]" + (f" Vol.{volume}" if volume is not None else "") + f" Ch.{number}"
        if row.get("full_chapter") != label:
            raise BlueSoloSourceError(
                f"{self.name} series {slug} has subchapter row {link!r} whose label "
                f"{row.get('full_chapter')!r} does not name chapter {number}")
        return number

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' numbered French chapters, newest first.

        An unnumbered row, and a chapter marked hidden or licensed, are left
        out with a warning. Two rows with one number (for instance after a
        volume restarts its numbering) and any other row form raise.
        """
        slug = self._series_slug(manga_url)
        rows = self._series(slug).get("chapters")
        if not isinstance(rows, list) or not rows:
            raise BlueSoloSourceError(f"{self.name} series {slug} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise BlueSoloSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")

        chapters: Dict[str, Chapter] = {}
        unnumbered = withheld = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("language") != "fr":
                raise BlueSoloSourceError(
                    f"{self.name} series {slug} has a row that is not a French chapter")
            if (row.get("chapter") is None and row.get("volume") is None
                    and row.get("subchapter") is None and row.get("url") == f"/read/{slug}/fr"):
                unnumbered += 1
                continue
            number = self._chapter_number(row, slug)
            if _marked(row, "hidden", "licensed"):
                withheld += 1
                continue
            if number in chapters:
                raise BlueSoloSourceError(
                    f"{self.name} series {slug} lists chapter {number} twice")
            title = row.get("full_title")
            date = _PUBLISHED.fullmatch(row.get("published_on") or "")
            chapters[number] = Chapter(
                number=number,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                url=f"{self.base_url}{row['url']}",
                date=date.group(1) if date else None,
            )
        if unnumbered:
            logger.warning("%s: %s has %d unnumbered chapter row(s), which this source "
                           "does not read", self.name, slug, unnumbered)
        if withheld:
            logger.warning("%s: %s has %d chapter(s) marked hidden or licensed, which are "
                           "not listed", self.name, slug, withheld)
        if not chapters:
            raise BlueSoloSourceError(
                f"{self.name} series {slug} has no numbered chapter this source reads")
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page images, in served order and exactly as served.
        The answer must name this series and this volume, chapter and
        subchapter. A page off the site's storage path, in another folder or
        repeated raises."""
        slug, volume, number, sub = self._chapter_ref(chapter_url)
        path = _read_path(slug, volume, number, sub)
        url = f"{self.base_url}/api{path}"
        data = self._json(url, "reader")
        self._checked_comic(data.get("comic"), slug, url)
        chapter = data.get("chapter")
        if (not isinstance(chapter, dict) or chapter.get("url") != path
                or not _whole(chapter.get("chapter")) or chapter["chapter"] != number
                or chapter.get("volume") != volume or chapter.get("subchapter") != sub
                or type(chapter.get("volume")) not in (int, type(None))
                or type(chapter.get("subchapter")) not in (int, type(None))
                or chapter.get("language") != "fr"):
            raise BlueSoloSourceError(f"{self.name} reader {url} is not this chapter")
        if _marked(chapter, "hidden", "licensed"):
            raise BlueSoloSourceError(
                f"{self.name} chapter {url} is marked hidden or licensed, which this "
                f"source does not read")

        pages = chapter.get("pages")
        if not isinstance(pages, list) or not pages:
            raise BlueSoloSourceError(f"{self.name} reader {url} has no page images")
        if len(pages) > _MAX_PAGES:
            raise BlueSoloSourceError(
                f"{self.name} reader {url} has more pages than this source reads")
        folder = None
        seen = set()
        for value in pages:
            match = _PAGE_URL.fullmatch(value) if isinstance(value, str) else None
            if match is None:
                raise BlueSoloSourceError(
                    f"{self.name} reader {url} has a page off the site's storage ({value!r})")
            if folder is None:
                folder = match.group(1)
            elif match.group(1) != folder:
                raise BlueSoloSourceError(
                    f"{self.name} reader {url} spreads its pages over several folders")
            if value in seen:
                raise BlueSoloSourceError(f"{self.name} reader {url} shows {value} twice")
            seen.add(value)
        return list(pages)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The series' served cover, read from its API answer. This is also
        where adding a series learns whether the API knows it: a series the
        API does not name, or one this source refuses, logs a warning and
        gives no cover."""
        try:
            comic = self._series(self._series_slug(manga_url))
        except (BlueSoloSourceError, BlueSoloUnsupportedError) as e:
            logger.warning("%s: %s", self.name, e)
            return None
        except Exception as e:
            logger.warning("%s: could not confirm %s: %s", self.name, manga_url, e)
            return None
        cover = comic.get("thumbnail")
        return cover if isinstance(cover, str) and _COVER_URL.fullmatch(cover) else None

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or _PAGE_URL.fullmatch(url) is None:
                logger.warning("%s: refused a page URL off its storage path: %s", self.name, url)
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
