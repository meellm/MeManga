"""
Magical Translators: an English manga translation team.

https://mahoushoujobu.com

The site runs a guya reader with a public JSON API:

- ``/api/get_all_series/``: the catalogue, keyed by title.
- ``/api/series/<slug>/``: a series with its chapters. Each chapter has a
  ``folder`` and, per translating group, its page file names.

A page is ``/media/manga/<slug>/chapters/<folder>/<group>/<file>``, built
from those served parts; a served cache query on a file name (``01.png?v2``)
is kept as served.

Only the English series of the API catalogue are read: slugs ending in
``-ES`` or ``-PL`` are other languages. The site links to other works
outside this catalogue, one of them marked 18+, and the API serves no
genres or adult flags, so the source carries the adult label as a
precaution and reads nothing outside the catalogue.

A chapter is read from its one translating group, or from the group the
series' ``preferred_sort`` puts first; a chapter offered by several groups
with no served preference is left out with a warning, and so is one whose
release date is still to come.
"""

import contextlib
import http.cookiejar
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "mahoushoujobu.com"
_SLUG = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_OTHER_LANGUAGE = re.compile(r".+-(?:ES|PL)")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,3})?")
_URL_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:-[0-9]{1,3})?")
_FOLDER = re.compile(r"[A-Za-z0-9_-]+")
_GROUP = re.compile(r"[1-9][0-9]{0,5}")
_FILE = r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g|webp|gif)"
_FILE_NAME = re.compile(_FILE + r"(?:\?v[0-9]{1,4})?")
_PAGE_URL = re.compile(
    r"https://mahoushoujobu\.com/media/manga/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
    r"(?:/chapters/[A-Za-z0-9_-]+/[1-9][0-9]{0,5}/" + _FILE + r"(?:\?v[0-9]{1,4})?"
    r"|/volume_covers/[0-9]{1,4}/" + _FILE + r")")

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_BODY_BYTES = 16 * 1024 * 1024
_MAX_SERIES = 5000
_MAX_CHAPTERS = 5000
_MAX_PAGES = 2000


class MagicalTranslatorsSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer without its expected fields, or a series, chapter or
    page this source does not read."""


class MagicalTranslatorsUnsupportedError(ValueError):
    """A URL that is not one of this site's English series or chapter links."""


class MagicalTranslatorsScraper(BaseScraper):
    """mahoushoujobu.com, over its guya JSON API."""

    name = "magicaltranslators"
    base_url = "https://mahoushoujobu.com"
    engine = "api"
    content_language = "en"
    # The API serves no genres or adult flags, and the site links to adult
    # works outside its catalogue, so the label is kept as a precaution.
    nsfw = True

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _segments(self, url: str) -> List[str]:
        refused = MagicalTranslatorsUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
        except ValueError:
            raise refused from None
        if (parts.scheme != "https" or parts.netloc != _SITE_HOST
                or parts.query or parts.fragment):
            raise refused
        return parts.path.strip("/").split("/")

    def _english(self, slug: str, url: str) -> str:
        if _OTHER_LANGUAGE.fullmatch(slug):
            raise MagicalTranslatorsUnsupportedError(
                f"{self.name} series {slug!r} is not in English: {url!r}")
        return slug

    def _series_slug(self, url: str) -> str:
        """The slug of ``/reader/series/<slug>/`` or ``/read/manga/<slug>/``."""
        segments = self._segments(url)
        if (len(segments) != 3 or (segments[0], segments[1]) not in
                (("reader", "series"), ("read", "manga")) or not _SLUG.fullmatch(segments[2])):
            raise MagicalTranslatorsUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return self._english(segments[2], url)

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(slug, chapter number)`` of ``/read/manga/<slug>/<n>/1/``."""
        segments = self._segments(url)
        if (len(segments) != 5 or segments[:2] != ["read", "manga"]
                or not _SLUG.fullmatch(segments[2]) or not _URL_NUMBER.fullmatch(segments[3])
                or segments[4] != "1"):
            raise MagicalTranslatorsUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return self._english(segments[2], url), segments[3].replace("-", ".")

    def _series_url(self, slug: str) -> str:
        return f"{self.base_url}/reader/series/{slug}/"

    def _chapter_url(self, slug: str, number: str) -> str:
        return f"{self.base_url}/read/manga/{slug}/{number.replace('.', '-')}/1/"

    # ── Requests ─────────────────────────────────────────────────────

    def _json(self, path: str, what: str) -> dict:
        """GET an API answer without following redirects; only a 200 counts."""
        url = f"{self.base_url}{path}"
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise MagicalTranslatorsSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise MagicalTranslatorsSourceError(f"{self.name} {what} {url} is too large")
        try:
            data = response.json()
        except ValueError:
            raise MagicalTranslatorsSourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise MagicalTranslatorsSourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    def _catalogue(self) -> List[Tuple[str, dict]]:
        """``(title, entry)`` of every series in the API catalogue."""
        data = self._json("/api/get_all_series/", "catalogue")
        if not data or len(data) > _MAX_SERIES:
            raise MagicalTranslatorsSourceError(f"{self.name} catalogue lists no series")
        entries, slugs = [], set()
        for title, entry in data.items():
            slug = entry.get("slug") if isinstance(entry, dict) else None
            if (not title.strip() or not isinstance(slug, str) or not _SLUG.fullmatch(slug)
                    or slug in slugs):
                raise MagicalTranslatorsSourceError(
                    f"{self.name} catalogue has an unreadable series ({title!r})")
            slugs.add(slug)
            entries.append((" ".join(title.split()), entry))
        return entries

    def _listed(self, slug: str) -> None:
        """Refuse a slug that the API catalogue does not list."""
        if all(entry["slug"] != slug for _, entry in self._catalogue()):
            raise MagicalTranslatorsSourceError(
                f"{self.name} series {slug!r} is not in the site's catalogue")

    def _series(self, slug: str) -> dict:
        data = self._json(f"/api/series/{slug}/", "series")
        chapters = data.get("chapters")
        if data.get("slug") != slug or not isinstance(chapters, dict):
            raise MagicalTranslatorsSourceError(f"{self.name} answer for {slug!r} is not this series")
        if len(chapters) > _MAX_CHAPTERS:
            raise MagicalTranslatorsSourceError(
                f"{self.name} series {slug!r} lists more chapters than this source reads")
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """English catalogue series whose title contains ``query``, ignoring
        case and spacing."""
        wanted = " ".join((query or "").split()).casefold()
        if not wanted:
            return []
        results = []
        for title, entry in self._catalogue():
            if wanted not in title.casefold() or _OTHER_LANGUAGE.fullmatch(entry["slug"]):
                continue
            cover = entry.get("cover")
            cover_url = f"{self.base_url}{cover}" if isinstance(cover, str) else None
            if cover_url is not None and _PAGE_URL.fullmatch(cover_url) is None:
                cover_url = None
            results.append(Manga(title=title, url=self._series_url(entry["slug"]),
                                 cover_url=cover_url))
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    @staticmethod
    def _group(chapter: dict, preferred) -> Optional[str]:
        """The chapter's one group, or the first of ``preferred`` it has."""
        groups = chapter.get("groups")
        if not isinstance(groups, dict) or not groups:
            return None
        if len(groups) == 1:
            return next(iter(groups))
        if isinstance(preferred, list):
            for group in preferred:
                if isinstance(group, str) and group in groups:
                    return group
        return None

    def _rows(self, slug: str, data: dict):
        """``(number, chapter, group, release time)`` of each readable chapter;
        the left-out ones are counted in a warning."""
        now = time.time()
        rows, several, upcoming = [], [], []
        for number, chapter in data["chapters"].items():
            if not _NUMBER.fullmatch(number) or not isinstance(chapter, dict) \
                    or not isinstance(chapter.get("folder"), str) \
                    or not _FOLDER.fullmatch(chapter["folder"]):
                raise MagicalTranslatorsSourceError(
                    f"{self.name} series {slug!r} has a chapter this source cannot read "
                    f"({number!r})")
            group = self._group(chapter, data.get("preferred_sort"))
            if group is None:
                several.append(number)
                continue
            dates = chapter.get("release_date")
            if dates is not None and not isinstance(dates, dict):
                raise MagicalTranslatorsSourceError(
                    f"{self.name} series {slug!r} chapter {number} has unreadable dates")
            released = (dates or {}).get(group)
            if released is not None and (type(released) not in (int, float) or released < 0):
                raise MagicalTranslatorsSourceError(
                    f"{self.name} series {slug!r} chapter {number} has an unreadable date")
            if released is not None and released > now:
                upcoming.append(number)
                continue
            rows.append((number, chapter, group, released))
        if several:
            logger.warning("%s: %s: %d chapter(s) are offered by several groups with no "
                           "preferred one and were left out: %s", self.name, slug,
                           len(several), ", ".join(several))
        if upcoming:
            logger.warning("%s: %s: %d chapter(s) are not released yet and were left out: %s",
                           self.name, slug, len(upcoming), ", ".join(upcoming))
        return rows

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' readable chapters, newest first."""
        slug = self._series_slug(manga_url)
        self._listed(slug)
        chapters = []
        for number, chapter, _, released in self._rows(slug, self._series(slug)):
            title = chapter.get("title")
            date = (datetime.fromtimestamp(released, tz=timezone.utc).date().isoformat()
                    if released is not None else None)
            chapters.append(Chapter(
                number=number,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                url=self._chapter_url(slug, number),
                date=date,
            ))
        return sorted(chapters, key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's pages from its group, in served order."""
        slug, number = self._chapter_ref(chapter_url)
        self._listed(slug)
        rows = {row[0]: row for row in self._rows(slug, self._series(slug))}
        if number not in rows:
            raise MagicalTranslatorsSourceError(
                f"{self.name} series {slug!r} has no readable chapter {number}")
        _, chapter, group, _ = rows[number]
        files = chapter["groups"][group]
        if (not _GROUP.fullmatch(group) or not isinstance(files, list) or not files
                or len(files) > _MAX_PAGES
                or not all(isinstance(f, str) and _FILE_NAME.fullmatch(f) for f in files)
                or len(set(files)) != len(files)):
            raise MagicalTranslatorsSourceError(
                f"{self.name} chapter {number} of {slug!r} has no readable page list")
        base = f"{self.base_url}/media/manga/{slug}/chapters/{chapter['folder']}/{group}"
        return [f"{base}/{name}" for name in files]

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """No request is sent when a series is added; search results carry
        the catalogue's served cover."""
        return None

    # ── Download ─────────────────────────────────────────────────────

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page or cover from the site's media path, sent with the
        site as Referer and without following redirects. Any failure returns
        False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or _PAGE_URL.fullmatch(url) is None:
                logger.warning("%s: refused a URL off its media path: %s", self.name, url)
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
