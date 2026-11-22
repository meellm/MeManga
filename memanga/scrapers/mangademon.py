"""
Manga Demon: an English manga and manhwa reader.

https://demonicscans.org

A series lists its chapters as ``/chaptered.php?manga=<id>&chapter=<number>``.
That link answers with one same-site redirect to the chapter's reader page,
``/title/<slug>/chapter/<number>/1``, which must then name the same series
id and chapter. Series slugs are kept exactly as served, double encoding
included, because decoding or encoding them again changes the address.

A reader page that links to another page of the same chapter raises, so a
paged chapter is never returned short. A chapter marked with the site's
``toffee-badge`` raises too: what the badge means is not known, and this
source reads only chapters shown without one.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString

from ..chapters import format_chapter_value
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"demonicscans.org", "www.demonicscans.org"})
_IMAGE_HOSTS = frozenset({"demoniclibs.com", "mangafifth.org"})
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_AD_IMAGE = "/img/free_ads.jpg"
_NUMBER = r"[0-9]{1,6}(?:\.[0-9]{1,3})?"
_SLUG_FORM = r"(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+"
_SLUG = re.compile(_SLUG_FORM)
_ENCODED_SEPARATOR = re.compile(r"%(?:2[EeFf]|5[Cc])")
_CHAPTER_QUERY = re.compile(rf"manga=([0-9]{{1,12}})&chapter=({_NUMBER})")
_READER_LOCATION = re.compile(rf"title/({_SLUG_FORM})/chapter/({_NUMBER})/1")
_READER_PAGE = re.compile(rf"/?title/[^/]+/chapter/({_NUMBER})/([0-9]+)")

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class MangaDemonSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected structure, a chapter with the
    site's badge, or a reader that cannot be read completely."""


class MangaDemonUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _own_text(element) -> str:
    """The element's direct text, without its children or comments."""
    return " ".join("".join(
        part for part in element.contents if type(part) is NavigableString).split())


def _is_slug(value: str) -> bool:
    return (bool(_SLUG.fullmatch(value)) and value not in (".", "..")
            and _ENCODED_SEPARATOR.search(value) is None)


def _links_to_another_page(soup: BeautifulSoup, number: str) -> bool:
    """True when the reader links to a later page of this same chapter."""
    values = [a["href"] for a in soup.select("a[href]")]
    values += [option["value"] for option in soup.select("option[value]")]
    for value in values:
        try:
            parts = urlsplit(value.strip())
        except ValueError:
            continue
        match = _READER_PAGE.fullmatch(parts.path)
        if match and match.group(1) == number and match.group(2) != "1":
            return True
        if parts.path.lstrip("/") == "reader.php":
            query = parse_qs(parts.query)
            if query.get("chapter") == [number] and query.get("pages", ["1"]) != ["1"]:
                return True
    return False


class MangaDemonScraper(BaseScraper):
    """demonicscans.org, over plain HTTP."""

    name = "mangademon"
    base_url = "https://demonicscans.org"
    content_language = "en"

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_parts(self, url: str):
        """A URL on this site, split. A login, port, fragment or relative
        URL is refused."""
        refused = MangaDemonUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise refused from None
        if (parts.scheme not in ("https", "http") or "@" in parts.netloc
                or port is not None or (parts.hostname or "") not in _SITE_HOSTS
                or parts.fragment):
            raise refused
        return parts

    def _series_slug(self, url: str) -> str:
        """The series slug, exactly as written in the URL."""
        parts = self._own_parts(url)
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        segments = path.split("/")[1:]
        if (parts.query or len(segments) != 2 or segments[0] != "manga"
                or not _is_slug(segments[1])):
            raise MangaDemonUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series id, chapter number text)`` of a served chapter link."""
        parts = self._own_parts(url)
        match = _CHAPTER_QUERY.fullmatch(parts.query)
        if parts.path != "/chaptered.php" or match is None:
            raise MangaDemonUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return match.group(1), match.group(2)

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image on one of the reader's exact image
        hosts, or None for anything else. The site serves these with raw
        spaces."""
        if not isinstance(url, str) or not url or url != url.strip() or any(
                ord(c) < 32 for c in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if (parts.scheme != "https" or parts.netloc not in _IMAGE_HOSTS
                or parts.query or parts.fragment
                or ".." in parts.path.split("/")
                or not parts.path.lower().endswith(_IMAGE_SUFFIXES)):
            return None
        return parts.path

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise MangaDemonSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise MangaDemonSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _soup(self, content: bytes, url: str) -> BeautifulSoup:
        """The page parsed from its UTF-8 bytes; the reader's stated
        charset is not a valid label."""
        try:
            return BeautifulSoup((content or b"").decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise MangaDemonSourceError(f"{self.name} page {url} is not UTF-8") from None

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The site's search results. A zero-byte answer is the site's "no
        results"; any other answer without result rows raises."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/search.php?manga={quote(query, safe='')}"
        content = self._fetch(url, "search").content
        if content == b"":
            return []
        links = self._soup(content, url).select("a[href]")
        if not links:
            raise MangaDemonSourceError(f"{self.name} search {url} did not serve results")

        results: List[Manga] = []
        seen = set()
        for link in links:
            element = link.select_one("div.seach-right > div")
            title = _own_text(element) if element else ""
            if not title:
                raise MangaDemonSourceError(
                    f"{self.name} search {url} lists a result without its title")
            try:
                slug = self._series_slug(urljoin(f"{self.base_url}/", link["href"].strip()))
            except MangaDemonUnsupportedError:
                raise MangaDemonSourceError(
                    f"{self.name} search {url} lists {link['href']!r}, not a series "
                    f"of this site") from None
            series_url = f"{self.base_url}/manga/{slug}"
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters, newest first, one per number.

        A badged chapter, a row without a link or with a label that does
        not match its link, rows of two series ids, and two links for one
        number all raise. The same link listed twice is listed once, with
        a warning.
        """
        slug = self._series_slug(manga_url)
        series_url = f"{self.base_url}/manga/{slug}"
        soup = self._soup(self._fetch(series_url, "series page").content, series_url)
        chapter_list = soup.select_one("div#chapters-list")
        if (soup.select_one("div#manga-info-container") is None
                or soup.select_one("h1.big-fat-titles") is None or chapter_list is None):
            raise MangaDemonSourceError(f"{self.name} page {series_url} is not a series page")
        if chapter_list.select_one(".toffee-badge") is not None:
            raise MangaDemonSourceError(
                f"{self.name} series {series_url} has a chapter marked with the site's "
                f"badge, which this source does not read")
        links = chapter_list.select("a")
        if not links:
            raise MangaDemonSourceError(f"{self.name} series {series_url} lists no chapters")
        if len(links) > _MAX_CHAPTERS:
            raise MangaDemonSourceError(
                f"{self.name} series {series_url} lists more chapters than this source reads")

        by_number: Dict[float, Chapter] = {}
        series_ids = set()
        repeated = 0
        for link in links:
            href = (link.get("href") or "").strip()
            if "chplinks" not in (link.get("class") or []) or not href:
                raise MangaDemonSourceError(
                    f"{self.name} series {series_url} has a chapter row without its "
                    f"link, which may be locked; this source reads free chapters only")
            try:
                manga_id, text = self._chapter_ref(urljoin(f"{self.base_url}/", href))
            except MangaDemonUnsupportedError:
                raise MangaDemonSourceError(
                    f"{self.name} series {series_url} links a chapter to {href!r}") from None
            series_ids.add(manga_id)
            if len(series_ids) > 1:
                raise MangaDemonSourceError(
                    f"{self.name} series {series_url} mixes several series ids")
            label = _own_text(link)
            if label != f"Chapter {text}":
                raise MangaDemonSourceError(
                    f"{self.name} series {series_url} has a row {label!r} that does "
                    f"not match its link to chapter {text}")
            url = f"{self.base_url}/chaptered.php?manga={manga_id}&chapter={text}"
            number = float(text)
            known = by_number.get(number)
            if known is not None:
                if known.url != url:
                    raise MangaDemonSourceError(
                        f"{self.name} series {series_url} has two links for chapter "
                        f"{format_chapter_value(number)}")
                repeated += 1
                continue
            date = link.select_one("span")
            by_number[number] = Chapter(
                number=format_chapter_value(number),
                title=label,
                url=url,
                date=(date.get_text(strip=True) or None) if date else None,
            )
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a listed chapter",
                           self.name, repeated, series_url)
        return sorted(by_number.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def _reader_url(self, link: str, number: str) -> str:
        """The reader page a chapter link redirects to: only the one same-
        site form, for this chapter, is followed."""
        hop = self._request(link, allow_redirects=False)
        location = hop.headers.get("Location") or ""
        match = _READER_LOCATION.fullmatch(location)
        if (hop.status_code != 302 or match is None or match.group(2) != number
                or not _is_slug(match.group(1))):
            raise MangaDemonSourceError(
                f"{self.name} chapter {link} answered HTTP {hop.status_code} "
                f"with location {location!r}, not its reader page")
        return f"{self.base_url}/title/{match.group(1)}/chapter/{number}/1"

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every story image of the chapter's reader, in reader order and
        exactly as served. The site's ad image is not a page. A missing,
        off-host or repeated page, a reader for another chapter, or a link
        to another page of this chapter raises."""
        manga_id, number = self._chapter_ref(chapter_url)
        link = f"{self.base_url}/chaptered.php?manga={manga_id}&chapter={number}"
        reader = self._reader_url(link, number)
        soup = self._soup(self._fetch(reader, "reader").content, reader)

        heading = soup.select_one("div.chapter-info h2")
        selected = {(o.get("value") or "").strip()
                    for o in soup.select("select option[selected]")}
        if (heading is None or heading.get_text(strip=True) != f"Chapter {number}"
                or selected != {f"/chaptered.php?manga={manga_id}&chapter={number}"}):
            raise MangaDemonSourceError(f"{self.name} reader {reader} is not this chapter")
        if soup.select_one(".toffee-badge") is not None:
            raise MangaDemonSourceError(
                f"{self.name} reader {reader} is marked with the site's badge, which "
                f"this source does not read")
        if _links_to_another_page(soup, number):
            raise MangaDemonSourceError(
                f"{self.name} reader {reader} continues on another page, which this "
                f"source does not read")

        pages: List[str] = []
        seen = set()
        for image in soup.select("img.imgholder"):
            src = image.get("src") or ""
            if image.parent is not None and image.parent.name == "a":
                target = (image.parent.get("href") or "").split("?", 1)[0]
                if src == _AD_IMAGE and target == "/premium.php":
                    continue
                raise MangaDemonSourceError(
                    f"{self.name} reader {reader} has a linked image it cannot place ({src!r})")
            path = self._image_path(src)
            if path is None:
                raise MangaDemonSourceError(
                    f"{self.name} reader {reader} has a page that is not an image of "
                    f"this site ({src!r})")
            if path in seen:
                raise MangaDemonSourceError(f"{self.name} reader {reader} shows {src} twice")
            seen.add(path)
            pages.append(src)
        if not pages:
            raise MangaDemonSourceError(f"{self.name} reader {reader} has no page images")
        if len(pages) > _MAX_PAGES:
            raise MangaDemonSourceError(
                f"{self.name} reader {reader} has more pages than this source reads")
        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if self._image_path(url) is None:
                logger.warning("%s: refused a page URL off its image hosts: %s", self.name, url)
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
