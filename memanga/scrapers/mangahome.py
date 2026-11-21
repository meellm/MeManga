"""
MangaHome: an English manga reader.

https://www.mangahome.com

The reader's page images come from ``chapterfun.ashx``, which answers
with packed JavaScript. It is read as text and never run. A call for page
N lists that page first and may list page N + 1 after it, so every page
is asked for once and each answer must agree with the one before it. The
result must hold exactly the number of pages the chapter page states.

A title the site marks as licensed raises an explicit error.
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
from .mangahere import _PACKED_RE, _unpack

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"www.mangahome.com", "mangahome.com"})
_IMAGE_HOST = "zjcdn.mangahere.org"
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
_VOLUME = re.compile(r"v[A-Za-z0-9._-]+")
_CHAPTER = re.compile(r"c([0-9]{1,6}(?:\.[0-9]{1,3})?)")
_CHAPTER_ID = re.compile(r"\bvar\s+chapter_id\s*=\s*(\d+)")
_IMAGE_COUNT = re.compile(r"\bvar\s+imagecount\s*=\s*(\d+)")
_PIX = re.compile(r'\bvar\s+pix\s*=\s*"([^"]+)"')
_PVALUE = re.compile(r"\bvar\s+pvalue\s*=\s*\[([^\]]*)\]")
_PVALUE_LIST = re.compile(r'"[^"]+"(?:\s*,\s*"[^"]+")*')
_NO_RESULTS = "Oh dear, we searched and searched…but we found nothing for"

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024
_MAX_SCRIPT_BYTES = 64 * 1024


class MangaHomeSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected structure, a licensed title, or
    a reader whose pages cannot be read completely."""


class MangaHomeUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter pages."""


def _is_licensed(soup: BeautifulSoup) -> bool:
    return any("has been licensed" in "".join(div.find_all(string=True, recursive=False)).lower()
               for div in soup.find_all("div"))


def _is_no_results(content: bytes, query: str) -> bool:
    """True for the site's own UTF-8 "found nothing" page for exactly this
    query: one notice, and no result list or rows."""
    try:
        soup = BeautifulSoup(content.decode("utf-8"), "html.parser")
    except UnicodeDecodeError:
        return False
    notices = soup.select("div.search-none")
    if len(notices) != 1 or soup.select_one("ul.manga-list, .post") is not None:
        return False
    text = " ".join(notices[0].get_text(" ", strip=True).split())
    return text == f"{_NO_RESULTS} {' '.join(query.split())}."


def _reader_values(script: str) -> Tuple[str, List[str]]:
    """``(pix, pvalue entries)`` of a chapterfun answer, read as data.
    Raises ValueError for anything but one packed script holding both."""
    packed = _PACKED_RE.findall(script)
    if len(packed) != 1:
        raise ValueError("not one packed script")
    _, radix, count, symbols = packed[0]
    if not 2 <= int(radix) <= 62 or int(count) > len(symbols.split("|")):
        raise ValueError("malformed packed script")
    code = _unpack(script)
    pix, values = _PIX.findall(code), _PVALUE.findall(code)
    if len(pix) != 1 or len(values) != 1 or not _PVALUE_LIST.fullmatch(values[0].strip()):
        raise ValueError("no single image list")
    return pix[0], re.findall(r'"([^"]+)"', values[0])


class MangaHomeScraper(BaseScraper):
    """www.mangahome.com, over plain HTTP."""

    name = "mangahome"
    base_url = "https://www.mangahome.com"
    content_language = "en"
    # A general catalogue that includes adult titles.
    nsfw = True

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_segments(self, url: str) -> List[str]:
        """The path segments of a URL on this site. A login, port, query,
        fragment, relative URL or dot segment is refused."""
        refused = MangaHomeUnsupportedError(f"Not a {self.name} page: {url!r}")
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
        if len(segments) != 2 or segments[0] != "manga":
            raise MangaHomeUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_parts(self, url: str) -> Tuple[str, str, str]:
        """``(series slug, chapter number text, canonical URL)``. The whole
        path is the chapter's identity, its volume segment included."""
        segments = self._own_segments(url)
        match = _CHAPTER.fullmatch(segments[-1])
        if (len(segments) not in (3, 4) or segments[0] != "manga" or match is None
                or (len(segments) == 4 and not _VOLUME.fullmatch(segments[2]))):
            raise MangaHomeUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return segments[1], match.group(1), f"{self.base_url}/{'/'.join(segments)}"

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image on the reader's image host, or None
        for anything else."""
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

    def _fetch(self, url: str, what: str, limit: int = _MAX_BODY_BYTES, **kwargs):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise MangaHomeSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > limit:
            raise MangaHomeSourceError(f"{self.name} {what} {url} is too large")
        return response

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search. "No results" is only the
        site's own notice for this query; any other page without result
        rows (a challenge, a changed layout) raises."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/search?page=1&name_method=cw&name={quote(query, safe='')}"
        response = self._fetch(url, "search")
        if _is_no_results(response.content, query):
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        posts = soup.select("ul.manga-list .post")
        if not posts or soup.select_one("div.search-none") is not None:
            raise MangaHomeSourceError(f"{self.name} search {url} did not serve a result list")

        results: List[Manga] = []
        seen = set()
        for post in posts:
            link = post.select_one("p.title a[href]")
            title = " ".join(link.get_text(" ", strip=True).split()) if link else ""
            # The link text of a long title is cut with "...".
            if title.endswith("..."):
                title = " ".join((link.get("title") or "").split())
            if not title:
                raise MangaHomeSourceError(
                    f"{self.name} search {url} lists a result without its link or title")
            try:
                slug = self._series_slug(urljoin(f"{self.base_url}/", link["href"].strip()))
            except MangaHomeUnsupportedError:
                raise MangaHomeSourceError(
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

        A licensed title raises, as does a row without a link or linked
        outside this series, and two different links for one number (a
        numbering that restarts per volume). The same link listed twice
        is listed once, with a warning.
        """
        slug = self._series_slug(manga_url)
        series_url = f"{self.base_url}/manga/{slug}"
        soup = BeautifulSoup(self._fetch(series_url, "series page").text, "html.parser")
        if _is_licensed(soup):
            raise MangaHomeSourceError(
                f"{self.name} series {series_url} has been licensed and is not available")
        if soup.select_one("ul.detail-chlist") is None:
            raise MangaHomeSourceError(f"{self.name} page {series_url} is not a series page")
        rows = soup.select("ul.detail-chlist > li")
        if not rows:
            raise MangaHomeSourceError(f"{self.name} series {series_url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaHomeSourceError(
                f"{self.name} series {series_url} lists more chapters than this source reads")

        by_number: Dict[float, Chapter] = {}
        seen_urls = set()
        repeated = 0
        for row in rows:
            link = row.select_one("a[href]")
            if link is None:
                raise MangaHomeSourceError(
                    f"{self.name} series {series_url} has a chapter without a link, "
                    f"which may be locked; this source reads free chapters only")
            try:
                row_slug, text, url = self._chapter_parts(
                    urljoin(f"{self.base_url}/", link["href"].strip()))
            except MangaHomeUnsupportedError:
                raise MangaHomeSourceError(
                    f"{self.name} series {series_url} links a chapter to "
                    f"{link['href']!r}") from None
            if row_slug != slug:
                raise MangaHomeSourceError(
                    f"{self.name} series {series_url} lists {url}, not a chapter of it")
            if url in seen_urls:
                repeated += 1
                continue
            seen_urls.add(url)
            number = float(text)
            if number in by_number:
                raise MangaHomeSourceError(
                    f"{self.name} series {series_url} has two links for chapter "
                    f"{format_chapter_value(number)}")
            label = " ".join(link.get_text(" ", strip=True).split())
            date = row.select_one("span.time")
            by_number[number] = Chapter(
                number=format_chapter_value(number),
                title=label or None,
                url=url,
                date=(date.get_text(strip=True) or None) if date else None,
            )
        if repeated:
            logger.warning("%s: %d chapter row(s) of %s repeat a listed chapter",
                           self.name, repeated, series_url)
        return sorted(by_number.values(), key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    @staticmethod
    def _stated_count(soup: BeautifulSoup, html: str, url: str) -> Tuple[str, int]:
        """``(chapter id, page count)`` from the chapter page. The count
        must equal every numeric page selector the reader shows."""
        ids, counts = set(_CHAPTER_ID.findall(html)), set(_IMAGE_COUNT.findall(html))
        if len(ids) != 1 or len(counts) != 1:
            raise MangaHomeSourceError(
                f"mangahome chapter {url} does not state one chapter id and page count")
        count = int(counts.pop())
        if not 1 <= count <= _MAX_PAGES:
            raise MangaHomeSourceError(f"mangahome chapter {url} states {count} pages")
        selectors = [sum(1 for o in s.select("option") if o.get_text(strip=True).isascii()
                         and o.get_text(strip=True).isdigit())
                     for s in soup.select("select")]
        selectors = [n for n in selectors if n]
        if not selectors or any(n != count for n in selectors):
            raise MangaHomeSourceError(
                f"mangahome chapter {url} states {count} pages but its page "
                f"selectors show {selectors}")
        return ids.pop(), count

    def _call_images(self, chapter: str, chapter_id: str, page: int) -> List[str]:
        """The one or two page images a chapterfun call for ``page`` lists."""
        url = f"{chapter}/chapterfun.ashx?cid={chapter_id}&page={page}&key="
        response = self._fetch(url, "reader", _MAX_SCRIPT_BYTES, headers={
            "Referer": chapter, "X-Requested-With": "XMLHttpRequest"})
        try:
            pix, entries = _reader_values(response.text or "")
        except ValueError as e:
            raise MangaHomeSourceError(
                f"{self.name} chapter {chapter} page {page}: unreadable reader answer ({e})"
            ) from None
        if len(entries) > 2 or not pix.startswith("//"):
            raise MangaHomeSourceError(
                f"{self.name} chapter {chapter} page {page}: unexpected reader answer")
        images = []
        for entry in entries:
            image = f"https:{pix}{entry}"
            if (not entry.startswith("/") or entry.startswith("//")
                    or self._image_path(image) is None):
                raise MangaHomeSourceError(
                    f"{self.name} chapter {chapter} page {page} is not an image of "
                    f"this site ({image!r})")
            images.append(image)
        return images

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter, in reader order.

        Each page is asked for once and is the first image of its answer.
        A second image must be the next call's first; a disagreement, a
        repeated page or a count other than the stated one raises, and
        no page is dropped or inferred.
        """
        _, _, url = self._chapter_parts(chapter_url)
        html = self._fetch(url, "chapter").text or ""
        soup = BeautifulSoup(html, "html.parser")
        if _is_licensed(soup):
            raise MangaHomeSourceError(
                f"{self.name} chapter {url} has been licensed and is not available")
        chapter_id, count = self._stated_count(soup, html, url)

        pages: List[str] = []
        seen = set()
        expected = None
        for page in range(1, count + 1):
            images = self._call_images(url, chapter_id, page)
            current = images[0]
            if expected is not None and current != expected:
                raise MangaHomeSourceError(
                    f"{self.name} chapter {url}: page {page} disagrees with the "
                    f"answer for page {page - 1}")
            path = self._image_path(current)
            if path in seen:
                raise MangaHomeSourceError(f"{self.name} chapter {url} shows page {current} twice")
            seen.add(path)
            pages.append(current)
            expected = images[1] if len(images) == 2 else None
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
