"""
Dynasty Scans: English yuri manga scanlations.

https://dynasty-scans.com

Search reads the first page of the site's search and keeps its series. A
series and a chapter are the site's public JSON at ``/series/<slug>.json`` and
``/chapters/<slug>_ch<number>.json``. A chapter must name its series and be
listed by it, and the list is ordered by chapter number because the site's
release dates are not in reading order.

The catalogue is mixed, so the source is marked NSFW. A series or chapter
with an explicit adult tag, or a series marked Licensed, is refused before
any chapter or image request. Other content tags are left to the reader.
Only the numbered "Chapter N" series form is read. A list with volume headers,
further pages or other chapter names raises instead of being read in part.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..chapters import format_chapter_value
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"dynasty-scans.com", "www.dynasty-scans.com"})
_IMAGE_HOST = "dynasty-scans.com"
_SLUG = re.compile(r"[A-Za-z0-9_-]+")
_CHAPTER_SLUG = re.compile(r"(?P<series>[A-Za-z0-9_-]+)_ch(?P<number>[0-9]{1,6})")
_ROW_TITLE = re.compile(r"Chapter ([0-9]{1,6})(?:: .+)?", re.S)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PAGE_PATH = re.compile(
    r"/system/releases/[0-9]{3}/[0-9]{3}/[0-9]{3}/[A-Za-z0-9_.-]+\.(?:webp|jpe?g|png|gif)", re.I)
_COVER_PATH = re.compile(
    r"/system/tag_contents_covers/[0-9]{3}/[0-9]{3}/[0-9]{3}/[a-z]+/"
    r"[A-Za-z0-9_.-]+\.(?:webp|jpe?g|png|gif)(?:\?[0-9]+)?", re.I)
_NO_RESULTS = "Sorry, nothing matching your query could be found"
_OTHER_KINDS = frozenset({"chapters", "doujins", "anthologies", "issues"})
_ADULT_TAGS = frozenset({"nsfw", "lots of sex", "smut", "hentai", "adult", "explicit"})

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class DynastySourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, an answer in an unknown form, or a refused adult or licensed
    title."""


class DynastyUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter pages."""


def _checked_tags(value, what: str) -> List[dict]:
    if not isinstance(value, list) or any(
            not isinstance(tag, dict) or not isinstance(tag.get("type"), str)
            or not isinstance(tag.get("name"), str) for tag in value):
        raise DynastySourceError(f"dynasty {what} has tags in an unknown form")
    return value


def _refusal(tags: List[dict]) -> Optional[str]:
    """Why these served tags refuse a title: "adult", "licensed" or None."""
    for tag in tags:
        name = tag["name"].strip().casefold()
        if tag["type"] == "General" and name in _ADULT_TAGS:
            return "adult"
        if tag["type"] == "Status" and "licensed" in name:
            return "licensed"
    return None


def _series_links(tags: List[dict]) -> List[object]:
    return [tag.get("permalink") for tag in tags if tag["type"] == "Series"]


class DynastyScraper(BaseScraper):
    """dynasty-scans.com series, through its public JSON."""

    name = "dynasty"
    base_url = "https://dynasty-scans.com"
    engine = "api"
    content_language = "en"
    # A mixed catalogue: some series carry explicit adult tags.
    nsfw = True

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_segments(self, url: str) -> List[str]:
        refused = DynastyUnsupportedError(f"Not a {self.name} page: {url!r}")
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
        if not segments or any(not s for s in segments):
            raise refused
        return segments

    def _series_slug(self, url: str) -> str:
        segments = self._own_segments(url)
        if len(segments) != 2 or segments[0] != "series" or not _SLUG.fullmatch(segments[1]):
            raise DynastyUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(chapter permalink, series slug)`` of a chapter page."""
        segments = self._own_segments(url)
        match = _CHAPTER_SLUG.fullmatch(segments[1]) if len(segments) == 2 else None
        if match is None or segments[0] != "chapters":
            raise DynastyUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return segments[1], match["series"]

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image on the site's own host, or None."""
        if not isinstance(url, str) or not url or any(
                c.isspace() or ord(c) < 32 for c in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if (parts.scheme != "https" or parts.netloc != _IMAGE_HOST
                or parts.query or parts.fragment
                or not _PAGE_PATH.fullmatch(parts.path)):
            return None
        return parts.path

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise DynastySourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise DynastySourceError(f"{self.name} {what} {url} is too large")
        return response

    def _json(self, url: str, what: str) -> dict:
        response = self._fetch(url, what)
        try:
            data = response.json()
        except ValueError:
            raise DynastySourceError(f"{self.name} {what} {url} is not JSON") from None
        if not isinstance(data, dict):
            raise DynastySourceError(f"{self.name} {what} {url} is not a JSON object")
        return data

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Series on the first page of the site's search. No results is
        only the site's own notice; any other page without rows raises.
        Series with an explicit adult tag are left out, with a warning."""
        query = (query or "").strip()
        if not query:
            return []
        url = (f"{self.base_url}/search?q={quote(query, safe='')}"
               f"&sort=&classes%5B%5D=Series&classes%5B%5D=Chapter")
        response = self._fetch(url, "search")
        try:
            soup = BeautifulSoup((response.content or b"").decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise DynastySourceError(f"{self.name} search {url} is not UTF-8") from None
        lists = soup.select("dl.chapter-list")
        if len(lists) != 1:
            raise DynastySourceError(f"{self.name} search {url} did not serve a result list")
        rows = lists[0].select("dd")
        notices = [" ".join(n.get_text(" ", strip=True).split())
                   for n in soup.select("div.no_results")]
        if not rows:
            if notices == [_NO_RESULTS]:
                return []
            raise DynastySourceError(f"{self.name} search {url} did not serve a result list")
        if notices:
            raise DynastySourceError(f"{self.name} search {url} serves results and no results")

        results: List[Manga] = []
        seen = set()
        adult = 0
        for row in rows:
            link = row.select_one("a.name[href]")
            title = " ".join(link.get_text(" ", strip=True).split()) if link else ""
            if not title:
                raise DynastySourceError(
                    f"{self.name} search {url} lists a result without its link or title")
            href = link["href"].strip()
            try:
                segments = self._own_segments(urljoin(f"{self.base_url}/", href))
            except DynastyUnsupportedError:
                raise DynastySourceError(
                    f"{self.name} search {url} lists {href!r}, not a page of this site") from None
            if segments[0] in _OTHER_KINDS:
                continue
            if len(segments) != 2 or segments[0] != "series" or not _SLUG.fullmatch(segments[1]):
                raise DynastySourceError(
                    f"{self.name} search {url} lists {href!r}, not a series of this site")
            labels = {a.get_text(" ", strip=True).casefold()
                      for a in row.select("span.tags a.label")}
            if labels & _ADULT_TAGS:
                adult += 1
                continue
            series_url = f"{self.base_url}/series/{segments[1]}"
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        if adult:
            logger.warning("%s: %d search result(s) carry an explicit adult tag and were "
                           "left out", self.name, adult)
        return results

    # ── Series ───────────────────────────────────────────────────────

    def _series_data(self, slug: str) -> dict:
        """The series JSON, checked. An adult or licensed series raises."""
        what = f"series {slug}"
        data = self._json(f"{self.base_url}/series/{slug}.json", "series")
        name = data.get("name")
        if (data.get("type") != "Series" or data.get("permalink") != slug
                or not isinstance(name, str) or not name.strip()):
            raise DynastySourceError(f"{self.name} {what} is not this series")
        reason = _refusal(_checked_tags(data.get("tags"), what))
        if reason:
            raise DynastySourceError(
                f"{self.name} {what} is marked {reason}, which this source does not read")
        return data

    def _read_series(self, slug: str) -> Tuple[Dict[str, Chapter], Dict[str, str]]:
        """``({permalink: chapter}, {refused permalink: reason})``."""
        what = f"series {slug}"
        data = self._series_data(slug)
        if "total_pages" in data and (
                not isinstance(data["total_pages"], int) or isinstance(data["total_pages"], bool)
                or data["total_pages"] != 1):
            raise DynastySourceError(
                f"{self.name} {what} lists its chapters over several pages, which this "
                f"source does not read")
        rows = data.get("taggings")
        if not isinstance(rows, list):
            raise DynastySourceError(f"{self.name} {what} has no chapter list")
        if not rows:
            raise DynastySourceError(f"{self.name} {what} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise DynastySourceError(f"{self.name} {what} lists more chapters than this source reads")

        chapters: Dict[str, Chapter] = {}
        refused: Dict[str, str] = {}
        number_of: Dict[str, int] = {}
        link_of: Dict[int, str] = {}
        repeated = 0
        for row in rows:
            if not isinstance(row, dict) or "header" in row:
                raise DynastySourceError(f"{self.name} {what} has a list row in an unknown form")
            permalink, title = row.get("permalink"), row.get("title")
            slug_match = _CHAPTER_SLUG.fullmatch(permalink) if isinstance(permalink, str) else None
            title_match = _ROW_TITLE.fullmatch(title) if isinstance(title, str) else None
            if (slug_match is None or title_match is None or slug_match["series"] != slug
                    or int(slug_match["number"]) != int(title_match.group(1))):
                raise DynastySourceError(
                    f"{self.name} {what} has a chapter that is not a plain numbered chapter "
                    f"({title!r}, {permalink!r})")
            tags = _checked_tags(row.get("tags"), f"chapter {permalink}")
            if _series_links(tags) != [slug]:
                raise DynastySourceError(
                    f"{self.name} {what} lists {permalink}, not a chapter of it")
            number = int(title_match.group(1))
            if permalink in number_of:
                repeated += 1
                continue
            if number in link_of:
                raise DynastySourceError(
                    f"{self.name} {what} has two links for chapter {number}")
            number_of[permalink] = number
            link_of[number] = permalink
            reason = _refusal(tags)
            if reason:
                refused[permalink] = reason
                continue
            date = row.get("released_on")
            chapters[permalink] = Chapter(
                number=format_chapter_value(number),
                title=title,
                url=f"{self.base_url}/chapters/{permalink}",
                date=date if isinstance(date, str) and _DATE.fullmatch(date) else None,
            )
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a listed chapter",
                           self.name, repeated, slug)
        return chapters, refused

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters, highest number first. A chapter with an
        explicit adult tag is left out, with a warning."""
        slug = self._series_slug(manga_url)
        chapters, refused = self._read_series(slug)
        if refused:
            logger.warning("%s: %d chapter(s) of %s carry an explicit adult tag and were "
                           "not listed", self.name, len(refused), slug)
        if not chapters:
            raise DynastySourceError(f"{self.name} series {slug} has no chapter this source reads")
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover the series JSON names, or None."""
        try:
            cover = self._series_data(self._series_slug(manga_url)).get("cover")
        except Exception as e:
            logger.debug("%s: no cover for %s: %s", self.name, manga_url, e)
            return None
        if isinstance(cover, str) and _COVER_PATH.fullmatch(cover):
            return f"{self.base_url}{cover}"
        return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter, in served order. The series is read
        first, so a refused or unlisted chapter is never requested. The
        chapter must then name itself and its series."""
        permalink, slug = self._chapter_ref(chapter_url)
        chapters, refused = self._read_series(slug)
        what = f"chapter {permalink}"
        if permalink in refused:
            raise DynastySourceError(
                f"{self.name} {what} is marked {refused[permalink]}, which this source "
                f"does not read")
        if permalink not in chapters:
            raise DynastySourceError(f"{self.name} {what} is not listed by its series")

        data = self._json(f"{self.base_url}/chapters/{permalink}.json", "chapter")
        tags = _checked_tags(data.get("tags"), what)
        if data.get("permalink") != permalink or _series_links(tags) != [slug]:
            raise DynastySourceError(f"{self.name} {what} answered for another chapter")
        reason = _refusal(tags)
        if reason:
            raise DynastySourceError(
                f"{self.name} {what} is marked {reason}, which this source does not read")
        entries = data.get("pages")
        if not isinstance(entries, list) or not entries:
            raise DynastySourceError(f"{self.name} {what} has no pages")
        if len(entries) > _MAX_PAGES:
            raise DynastySourceError(f"{self.name} {what} has more pages than this source reads")

        pages: List[str] = []
        seen = set()
        for entry in entries:
            path = entry.get("url") if isinstance(entry, dict) else None
            if not isinstance(path, str) or not _PAGE_PATH.fullmatch(path):
                raise DynastySourceError(
                    f"{self.name} {what} has a page that is not an image of this site ({path!r})")
            if path in seen:
                raise DynastySourceError(f"{self.name} {what} shows page {path} twice")
            seen.add(path)
            pages.append(f"{self.base_url}{path}")
        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if self._image_path(url) is None:
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
