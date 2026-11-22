"""
French scan readers on the WordPress "MangaThemesia" theme.

https://sushiscan.net
https://www.lelmanga.com

The two sites are separate and share only the theme: a search page of
``.listupd .bs .bsx`` cards, and a series page whose chapter rows carry
``data-num`` and a "Chapitre N" label. On Lelmanga ``data-num`` is the bare
number ("4"); on SushiScan it repeats the whole label ("Chapitre 112.5").
They also differ in where a chapter's pages are: SushiScan lists them in
the reader's ``ts_reader.run({...})`` call, Lelmanga as ``img`` elements in
``div#readerarea``. Each site reads only its own forms and its own image
hosts.

Only freely readable chapters are read. A chapter row without a link (how
this theme shows a locked chapter) raises instead of being passed over,
and no account, coin or unlock step exists here.
"""

import http.cookiejar
import json
import logging
import re
from abc import abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup

from ..chapters import format_chapter_value
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_CHAPTER_ROWS = "div.bxcl li[data-num], div.cl li[data-num], #chapterlist li[data-num]"
_DATA_NUM = re.compile(r"\d+(?:\.\d+)?")
_SUSHI_ROW_LABEL = re.compile(r"Chapitre ([0-9]{1,6}(?:\.[0-9]{1,3})?)")
_TS_READER = re.compile(r"ts_reader\.run\(\s*(?=\{)")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class MangaThemesiaSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected structure, a chapter row without
    a link, or a reader without a valid list of pages."""


class MangaThemesiaUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter pages."""


def _has_space_or_control(text: str) -> bool:
    return any(char.isspace() or ord(char) < 32 for char in text)


class MangaThemesiaSite(BaseScraper):
    """One site on the theme; subclasses state its observed shape."""

    engine = "http"

    # Hosts a URL of this site may name; requests always use base_url.
    _site_hosts: frozenset = frozenset()
    # First path segment of a series page, and whether pages end in "/".
    _series_dirs: Tuple[str, ...] = ()
    _trailing_slash: bool = False
    # Path the "?s=" search is sent to.
    _search_path: str = "/"
    # Page images: the exact hosts and the path they sit under.
    _image_hosts: frozenset = frozenset()
    _image_path_prefix: str = ""
    # The row label, in the site's language.
    _chapter_label = re.compile(r"chapitre\s+(\d+(?:\.\d+)?)(?![\d.])", re.I)

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_segments(self, url: str) -> List[str]:
        """The path segments of a URL on this site's own hosts. A login,
        port, query, fragment or relative URL is refused."""
        refused = MangaThemesiaUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or _has_space_or_control(url):
            raise refused
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise refused from None
        if (parts.scheme not in ("https", "http")
                or parts.username is not None or parts.password is not None
                or port is not None
                or (parts.hostname or "") not in self._site_hosts
                or parts.query or parts.fragment):
            raise refused
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        segments = path.split("/")[1:]
        if not segments or any(s in ("", ".", "..") for s in segments):
            raise refused
        return segments

    def _canonical(self, segments: List[str]) -> str:
        end = "/" if self._trailing_slash else ""
        return f"{self.base_url}/{'/'.join(segments)}{end}"

    def _series_url(self, url: str) -> str:
        segments = self._own_segments(url)
        if len(segments) != 2 or segments[0] not in self._series_dirs:
            raise MangaThemesiaUnsupportedError(
                f"Not a {self.name} series page: {url!r}")
        return self._canonical(segments)

    def _chapter_url(self, url: str) -> str:
        segments = self._own_segments(url)
        if len(segments) != 1 or segments[0] in self._series_dirs:
            raise MangaThemesiaUnsupportedError(
                f"Not a {self.name} chapter page: {url!r}")
        return self._canonical(segments)

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image on this site's exact image hosts, or
        None for anything else (another host, a theme logo, a relative or
        non-https URL)."""
        if not isinstance(url, str) or not url or _has_space_or_control(url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        path = parts.path
        if (parts.scheme != "https" or parts.netloc not in self._image_hosts
                or parts.fragment
                or not path.startswith(self._image_path_prefix)
                or ".." in path.split("/")
                or not path.lower().endswith(_IMAGE_SUFFIXES)):
            return None
        return path

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts.
        Request errors are raised as they are."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise MangaThemesiaSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise MangaThemesiaSourceError(f"{self.name} {what} {url} is too large")
        return response

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search. A page without the
        theme's result list (a challenge, a changed layout) raises rather
        than reading as "no results"."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}{self._search_path}?s={quote_plus(query)}"
        soup = BeautifulSoup(self._fetch(url, "search").text, "html.parser")
        if soup.select_one(".listupd") is None:
            raise MangaThemesiaSourceError(
                f"{self.name} search {url} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        skipped = 0
        for card in soup.select(".listupd .bs .bsx"):
            link = card.select_one("a[href][title]")
            title = (link.get("title") or "").strip() if link else ""
            if not title:
                raise MangaThemesiaSourceError(
                    f"{self.name} search {url} lists a result without its link or title")
            try:
                series_url = self._series_url(link["href"].strip())
            except MangaThemesiaUnsupportedError:
                skipped += 1
                continue
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        if skipped:
            logger.debug("%s search: %d result(s) were not series pages of this "
                         "site and were left out", self.name, skipped)
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def _row_number(self, row) -> Optional[Tuple[float, str]]:
        """``(number, label)`` of a row whose numeric ``data-num`` and
        "Chapitre N" label agree, else None: a number is never guessed from
        one alone."""
        raw = (row.get("data-num") or "").strip()
        element = row.select_one(".chapternum")
        label = " ".join(element.get_text(" ", strip=True).split()) if element else ""
        match = self._chapter_label.match(label)
        if not match or not _DATA_NUM.fullmatch(raw) or float(raw) != float(match.group(1)):
            return None
        return float(raw), label

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters, newest first, one per number.

        A row without a link raises: this theme shows locked chapters
        that way, and this source reads free chapters only. Rows that are
        not a plain "Chapitre N" are counted in a warning and not listed,
        except on SushiScan, where such a row raises.
        """
        series_url = self._series_url(manga_url)
        soup = BeautifulSoup(self._fetch(series_url, "series page").text, "html.parser")
        if soup.select_one("h1.entry-title") is None:
            raise MangaThemesiaSourceError(
                f"{self.name} page {series_url} is not a series page")
        rows = soup.select(_CHAPTER_ROWS)
        if not rows:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists more chapters than "
                f"this source reads")

        by_number: Dict[float, Chapter] = {}
        number_of_url: Dict[str, float] = {}
        unrecognised = repeated = 0
        for row in rows:
            link = row.find("a", href=True)
            if link is None:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a chapter without "
                    f"a link, which may be locked; this source reads free chapters only")
            try:
                url = self._chapter_url(link["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links a chapter to "
                    f"{link['href']!r}, not to a chapter of this site") from None
            parsed = self._row_number(row)
            if parsed is None:
                unrecognised += 1
                continue
            number, label = parsed
            known = number_of_url.get(url)
            if known is not None:
                if known != number:
                    raise MangaThemesiaSourceError(
                        f"{self.name} series page {series_url} gives {url} two "
                        f"chapter numbers")
                continue
            number_of_url[url] = number
            if number in by_number:
                repeated += 1
                continue
            date = row.select_one(".chapterdate")
            by_number[number] = Chapter(
                number=format_chapter_value(number),
                title=label,
                url=url,
                date=(date.get_text(strip=True) or None) if date else None,
            )

        if not by_number:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} has no chapter row in the "
                f"expected form")
        if unrecognised:
            logger.warning("%s: %d chapter row(s) of %s are not a plain numbered "
                           "chapter and were not listed", self.name, unrecognised, series_url)
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a number with another "
                           "link; the first listed was kept", self.name, repeated, series_url)
        return sorted(by_number.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    @abstractmethod
    def _reader_images(self, html: str, chapter_url: str) -> list:
        """The reader's page entries, in reader order, as served."""

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter's reader, in reader order and exactly
        as served. A missing, invalid or repeated page raises; none is
        dropped, and nothing is sorted or inferred from file names."""
        url = self._chapter_url(chapter_url)
        entries = self._reader_images(self._fetch(url, "chapter").text, url)
        if not entries:
            raise MangaThemesiaSourceError(f"{self.name} chapter {url} has an empty reader")
        if len(entries) > _MAX_PAGES:
            raise MangaThemesiaSourceError(
                f"{self.name} chapter {url} has more pages than this source reads")
        seen = set()
        for entry in entries:
            path = self._image_path(entry)
            if path is None:
                raise MangaThemesiaSourceError(
                    f"{self.name} chapter {url} has a page that is not an image "
                    f"of this site ({entry!r})")
            # By path: one file can be served from several image hosts.
            if path in seen:
                raise MangaThemesiaSourceError(
                    f"{self.name} chapter {url} shows page {entry} twice")
            seen.add(path)
        return list(entries)

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. An answer that
        is not an image fails, and no older file is left behind."""
        path = Path(path)
        if self._image_path(url) is None:
            logger.warning("%s: refused a page URL off its image hosts: %s", self.name, url)
            return False
        try:
            response = self._request(url, allow_redirects=False,
                                     headers={"Referer": f"{self.base_url}/"})
            content = response.content if response.status_code == 200 else b""
            if not _identifies_as_image(content):
                path.unlink(missing_ok=True)
                logger.warning("%s: page is not an image (HTTP %s, %d bytes): %s", self.name,
                               response.status_code, len(content or b""), url)
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error("%s: failed to download page %s: %s", self.name, url, e)
            return False


class SushiScanScraper(MangaThemesiaSite):
    """sushiscan.net: pages are in the reader's ``ts_reader.run`` call."""

    name = "sushiscan"
    base_url = "https://sushiscan.net"
    content_language = "fr"

    _site_hosts = frozenset({"sushiscan.net", "www.sushiscan.net"})
    _series_dirs = ("catalogue",)
    _trailing_slash = True
    _search_path = "/page/1"
    _image_hosts = frozenset({"c.sushiscan.net"})
    _image_path_prefix = "/wp-content/uploads"

    def _row_number(self, row) -> Tuple[float, str]:
        """``(number, label)`` of a row whose ``data-num`` is exactly its
        "Chapitre N" label. Any other row raises, so a chapter is neither
        guessed nor left out of the list."""
        raw = " ".join((row.get("data-num") or "").split())
        element = row.select_one(".chapternum")
        label = " ".join(element.get_text(" ", strip=True).split()) if element else ""
        match = _SUSHI_ROW_LABEL.fullmatch(raw)
        if match is None or raw != label:
            raise MangaThemesiaSourceError(
                f"{self.name} chapter row is not a plain numbered chapter "
                f"(data-num {raw!r}, label {label!r})")
        return float(match.group(1)), label

    def _reader_images(self, html: str, chapter_url: str) -> list:
        def refused(why: str):
            return MangaThemesiaSourceError(f"{self.name} chapter {chapter_url} {why}")

        calls = list(_TS_READER.finditer(html or ""))
        if len(calls) != 1:
            raise refused(f"has {len(calls)} reader page lists, not one")
        try:
            data, _ = json.JSONDecoder().raw_decode(html, calls[0].end())
        except ValueError:
            raise refused("has a reader page list that is not JSON") from None
        sources = data.get("sources") if isinstance(data, dict) else None
        if not isinstance(sources, list) or not sources:
            raise refused("has a reader without image sources")
        if len(sources) == 1:
            source = sources[0]
        else:
            named = [s for s in sources if isinstance(s, dict)
                     and s.get("source") == data.get("defaultSource")]
            if len(named) != 1:
                raise refused("does not name one default image source")
            source = named[0]
        images = source.get("images") if isinstance(source, dict) else None
        if not isinstance(images, list):
            raise refused("has a reader source without images")
        return images


class LelMangaScraper(MangaThemesiaSite):
    """www.lelmanga.com: pages are ``img`` elements in ``div#readerarea``,
    served through the wp.com image CDN with their query kept."""

    name = "lelmanga"
    base_url = "https://www.lelmanga.com"
    content_language = "fr"

    _site_hosts = frozenset({"www.lelmanga.com", "lelmanga.com"})
    _series_dirs = ("manga", "manhwa")
    _trailing_slash = False
    _search_path = "/"
    _image_hosts = frozenset({"i0.wp.com", "i1.wp.com", "i2.wp.com", "i3.wp.com"})
    _image_path_prefix = "/www.lelmanga.com/wp-content/uploads/"

    def _reader_images(self, html: str, chapter_url: str) -> list:
        readers = BeautifulSoup(html or "", "html.parser").select("div#readerarea")
        if len(readers) != 1:
            raise MangaThemesiaSourceError(
                f"{self.name} chapter {chapter_url} has {len(readers)} readers, not one")
        return [(image.get("src") or "").strip() for image in readers[0].find_all("img")]
