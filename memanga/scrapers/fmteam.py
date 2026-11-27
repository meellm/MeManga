"""
FMTEAM: a French scanlation team's reader.

https://fmteam.fr

The site serves a public JSON API. A series is ``/api/comics/<slug>`` and a
chapter is ``/api/read/<slug>/fr/ch/<number>``. The chapter's answer embeds
its series, which must be the one asked for.

Only plain numbered French chapters are read. A row with a volume or a
subchapter, in another language or in another URL form fails the listing
until that form is known. An unnumbered one-shot has no number to file it
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

_SITE_HOST = "fmteam.fr"
_SLUG_FORM = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_SLUG = re.compile(_SLUG_FORM)
_NUMBER = re.compile(r"0|[1-9][0-9]{0,5}")
_PUBLISHED = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
# Pages are served with a cache-busting ``?v=`` query, kept as served.
_PAGE_URL = re.compile(
    r"https://fmteam\.fr/storage/comics/[A-Za-z0-9][A-Za-z0-9_.-]*/([A-Za-z0-9][A-Za-z0-9_.-]*)/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpe?g|webp|gif)(?:\?v=[0-9]{1,12})?")

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 200
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class FMTeamSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected fields, or a series or chapter
    this source does not read."""


class FMTeamUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


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


class FMTeamScraper(BaseScraper):
    """fmteam.fr, over its public JSON API."""

    name = "fmteam"
    base_url = "https://fmteam.fr"
    engine = "api"
    content_language = "fr"

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _segments(self, url: str) -> List[str]:
        """The path segments of a URL on this exact host. A login, port,
        query, fragment or relative URL is refused."""
        refused = FMTeamUnsupportedError(f"Not a {self.name} page: {url!r}")
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
            raise FMTeamUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter number text)`` of a numbered chapter link."""
        segments = self._segments(url)
        if (len(segments) != 5 or segments[0] != "read" or not _SLUG.fullmatch(segments[1])
                or segments[2:4] != ["fr", "ch"] or not _NUMBER.fullmatch(segments[4])):
            raise FMTeamUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return segments[1], segments[4]

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise FMTeamSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise FMTeamSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _json(self, url: str, what: str) -> dict:
        response = self._fetch(url, what)
        try:
            data = response.json()
        except ValueError:
            raise FMTeamSourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise FMTeamSourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    def _checked_comic(self, comic, slug: str, url: str) -> dict:
        """The served series, which must be ``slug`` and readable."""
        if (not isinstance(comic, dict) or comic.get("url") != f"/comics/{slug}"
                or comic.get("slug") != slug):
            raise FMTeamSourceError(f"{self.name} answer {url} is not this series")
        reason = _refusal(comic)
        if reason:
            raise FMTeamSourceError(
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
            raise FMTeamSourceError(f"{self.name} search {url} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        left_out = 0
        for comic in comics:
            slug = comic.get("slug") if isinstance(comic, dict) else None
            title = comic.get("title") if isinstance(comic, dict) else None
            if (not isinstance(slug, str) or not _SLUG.fullmatch(slug)
                    or comic.get("url") != f"/comics/{slug}"
                    or not isinstance(title, str) or not title.strip()):
                raise FMTeamSourceError(f"{self.name} search {url} has an unreadable result")
            if _refusal(comic):
                left_out += 1
                continue
            series_url = f"{self.base_url}/manga/{slug}"
            if series_url not in seen:
                seen.add(series_url)
                results.append(Manga(title=title.strip(), url=series_url))
        if left_out:
            logger.warning("%s: %d search result(s) are marked adult, hidden or licensed "
                           "and were left out", self.name, left_out)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' numbered French chapters, newest first.

        An unnumbered one-shot, and a chapter marked hidden or licensed, are
        left out with a warning. Any other row form raises.
        """
        slug = self._series_slug(manga_url)
        url = f"{self.base_url}/api/comics/{slug}"
        comic = self._checked_comic(self._json(url, "series").get("comic"), slug, url)
        rows = comic.get("chapters")
        if not isinstance(rows, list) or not rows:
            raise FMTeamSourceError(f"{self.name} series {slug} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise FMTeamSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")

        chapters: Dict[str, Chapter] = {}
        oneshots = withheld = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("language") != "fr":
                raise FMTeamSourceError(
                    f"{self.name} series {slug} has a row that is not a French chapter")
            number, link = row.get("chapter"), row.get("url")
            if (number is None and row.get("volume") is None
                    and row.get("subchapter") is None and link == f"/read/{slug}/fr"):
                oneshots += 1
                continue
            if (type(number) is not int or not 0 <= number <= 999999
                    or row.get("volume") is not None or row.get("subchapter") is not None
                    or link != f"/read/{slug}/fr/ch/{number}"):
                raise FMTeamSourceError(
                    f"{self.name} series {slug} has a chapter row this source cannot read "
                    f"yet ({link!r}); only plain numbered chapters are read")
            if _marked(row, "hidden", "licensed"):
                withheld += 1
                continue
            text = str(number)
            if text in chapters:
                raise FMTeamSourceError(f"{self.name} series {slug} lists chapter {text} twice")
            title = row.get("full_title")
            date = _PUBLISHED.fullmatch(row.get("published_on") or "")
            chapters[text] = Chapter(
                number=text,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                url=f"{self.base_url}/read/{slug}/fr/ch/{text}",
                date=date.group(1) if date else None,
            )
        if oneshots:
            logger.warning("%s: %s has %d unnumbered one-shot(s), which this source does "
                           "not read", self.name, slug, oneshots)
        if withheld:
            logger.warning("%s: %s has %d chapter(s) marked hidden or licensed, which are "
                           "not listed", self.name, slug, withheld)
        if not chapters:
            raise FMTeamSourceError(
                f"{self.name} series {slug} has no numbered chapter this source reads")
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page images, in served order and exactly as served.
        The answer must name this series and chapter. A page off the site's
        storage path, in another folder or repeated raises."""
        slug, number = self._chapter_ref(chapter_url)
        url = f"{self.base_url}/api/read/{slug}/fr/ch/{number}"
        data = self._json(url, "reader")
        self._checked_comic(data.get("comic"), slug, url)
        chapter = data.get("chapter")
        if (not isinstance(chapter, dict) or chapter.get("url") != f"/read/{slug}/fr/ch/{number}"
                or type(chapter.get("chapter")) is not int or str(chapter["chapter"]) != number
                or chapter.get("volume") is not None or chapter.get("subchapter") is not None
                or chapter.get("language") != "fr"):
            raise FMTeamSourceError(f"{self.name} reader {url} is not this chapter")
        if _marked(chapter, "hidden", "licensed"):
            raise FMTeamSourceError(
                f"{self.name} chapter {url} is marked hidden or licensed, which this "
                f"source does not read")

        pages = chapter.get("pages")
        if not isinstance(pages, list) or not pages:
            raise FMTeamSourceError(f"{self.name} reader {url} has no page images")
        if len(pages) > _MAX_PAGES:
            raise FMTeamSourceError(
                f"{self.name} reader {url} has more pages than this source reads")
        folder = None
        seen = set()
        for value in pages:
            match = _PAGE_URL.fullmatch(value) if isinstance(value, str) else None
            if match is None:
                raise FMTeamSourceError(
                    f"{self.name} reader {url} has a page off the site's storage ({value!r})")
            if folder is None:
                folder = match.group(1)
            elif match.group(1) != folder:
                raise FMTeamSourceError(
                    f"{self.name} reader {url} spreads its pages over several folders")
            if value in seen:
                raise FMTeamSourceError(f"{self.name} reader {url} shows {value} twice")
            seen.add(value)
        return list(pages)

    def get_cover_url(self, manga_url: str):
        """No cover is read, so adding a series sends no request."""
        return None

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
