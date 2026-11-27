"""
Furyo Society: a French scanlation team's reader.

https://www.furyosociety.com

The catalogue is the ``/mangas`` page, which has no search of its own, so a
search matches titles there. A series page lists its chapters as links to
``/read/<series>/fr/<volume>/<chapter>[/<part>]/``, and a reader page holds
every image of its chapter.

Rows the team marks as not translated by them ("Non traduit par la team") are
left out with a warning, because their language is not the team's. Rows with
a paid, early-access or locked offer make the whole series fail, as do pages
that ask to log in or pay.
"""

import contextlib
import http.cookiejar
import logging
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment
from requests.adapters import BaseAdapter, HTTPAdapter

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "www.furyosociety.com"
_SLUG_FORM = r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?"
_SERIES_URL = re.compile(rf"https://www\.furyosociety\.com/series/({_SLUG_FORM})/")
_READ_URL = re.compile(
    rf"https://www\.furyosociety\.com/read/({_SLUG_FORM})/fr/(0|[1-9][0-9]{{0,3}})"
    r"/(0|[1-9][0-9]{0,5})/(?:([1-9][0-9]{0,2})/)?")
_CHAPTER_TEXT = re.compile(r"Chapitre ((?:0|[1-9][0-9]{0,5})(?:\.[1-9][0-9]{0,2})?)")
_PAGE_URL = re.compile(
    r"https://www\.furyosociety\.com/content/comics/([A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"/([A-Za-z0-9][A-Za-z0-9_.-]*)/([^/?#\s\"'<>\\]+)")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
# A series cover: one comic folder and a file, never a chapter page path.
_COVER_URL = re.compile(
    r"https://www\.furyosociety\.com/content/comics/[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"/[A-Za-z0-9][^/?#\s\"'<>\\]*")
# The team's own mark on chapters it lists but did not translate.
_UNTRANSLATED = "non traduit par la team"
# Words that, in a chapter row or on a reader page, mean the content is
# sold, locked or released early to some readers.
_PAID = re.compile(
    r"\b(patreon|tipeee|utip|ko-?fi|premium|vip|payant|payante|abonnement|abonnés?"
    r"|accès anticipé|acces anticipe|early access|verrouillé|verrouille|locked)\b", re.I)
_LOGIN_GATE = re.compile(
    r"\b(connectez-vous|connexion requise|vous devez être connecté|réservé aux membres)\b", re.I)
# In a chapter row's own badges, date or controls (never its story title),
# a members or login mark means the chapter is not open to everyone.
_ROW_ACCESS = re.compile(
    r"\b(réservé aux membres|membres|membre|members only|connexion|connectez-vous"
    r"|se connecter|login|log in)\b", re.I)
# Seconds between one request's completion and the next one's start, for
# every request to the site from any instance or thread.
_MIN_GAP = 2.2
_ADULT = re.compile(r"\b(hentai|smut|adultes?|adult|érotique|erotique|18\+|nsfw|mature)(?!\w)", re.I)

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list.
_MAX_SERIES = 2000
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class FuryoSocietySourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected structure, a chapter form this
    source does not read, or content that is paid, locked or adult."""


class FuryoSocietyUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _text(element) -> str:
    return " ".join(element.get_text(" ").split()) if element is not None else ""


def _is_cover_url(url) -> bool:
    return (isinstance(url, str) and _COVER_URL.fullmatch(url) is not None
            and url.lower().endswith(_IMAGE_SUFFIXES))


def _is_hidden(element) -> bool:
    style = "".join((element.get("style") or "").split()).lower()
    return element.has_attr("hidden") or "display:none" in style or "visibility:hidden" in style


def _row_marks(row, link) -> str:
    """What a chapter row shows besides its story title: text that sits
    directly in the row, its badges, date and controls, and the alt, title
    and aria-label of what they hold. The chapter link (whose title is the
    story title) and the row's name are left out, as is anything hidden."""
    def strings(element):
        return [str(s) for s in element.find_all(string=True, recursive=False)
                if not isinstance(s, Comment)]

    def skipped(element):
        node = element
        while node is not None and node is not row:
            if node is link or _is_hidden(node):
                return True
            node = node.parent
        return False

    parts = strings(row)
    for child in row.find_all(recursive=False):
        if "name" in (child.get("class") or []):
            continue
        for element in [child, *child.find_all(True)]:
            if skipped(element):
                continue
            parts.extend(element.get(attr) or "" for attr in ("alt", "title", "aria-label"))
            parts.extend(strings(element))
    return " ".join(" ".join(parts).split())


class _SpacedAdapter(BaseAdapter):
    """Sends one request to the site at a time, through to its last body
    byte, and starts each only ``gap`` seconds after the previous one
    finished, whatever the thread, instance or retry. A slow connection
    therefore cannot bring two sends closer together."""

    _lock = threading.Lock()  # shared by every adapter of this source
    _last_done = 0.0

    def __init__(self, gap: float = _MIN_GAP, inner: Optional[BaseAdapter] = None):
        super().__init__()
        self.gap = gap
        self.inner = inner if inner is not None else HTTPAdapter()

    def send(self, request, **kwargs):
        cls = type(self)
        with cls._lock:
            wait = cls._last_done + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.inner.send(request, **kwargs)
                if not kwargs.get("stream"):
                    response.content  # read the whole body before the next send
                return response
            finally:
                cls._last_done = time.monotonic()

    def close(self):
        self.inner.close()


class FuryoSocietyScraper(BaseScraper):
    """www.furyosociety.com, over plain HTTP."""

    name = "furyosociety"
    base_url = "https://www.furyosociety.com"
    engine = "http"
    content_language = "fr"
    # Series show their own genres, and an adult one is refused. The whole
    # catalogue has not been checked, so the source carries the label.
    nsfw = True

    def __init__(self):
        super().__init__()
        # The base spacing times request starts; the adapter below also
        # keeps sends one at a time, _MIN_GAP apart from each completion.
        self._rate_limit = _MIN_GAP
        self.session.mount(f"{self.base_url}/", _SpacedAdapter())
        # The site sets a session cookie it does not need; none is kept or sent.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    @staticmethod
    def _clean(url) -> Optional[str]:
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if parts.query or parts.fragment or parts.netloc != _SITE_HOST:
            return None
        return url

    def _series_slug(self, url: str) -> str:
        match = _SERIES_URL.fullmatch(self._clean(url) or "")
        if match is None:
            raise FuryoSocietyUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return match.group(1)

    def _chapter_ref(self, url: str) -> Tuple[str, str, str]:
        """``(series slug, volume, chapter number text)`` of a reader link."""
        match = _READ_URL.fullmatch(self._clean(url) or "")
        if match is None:
            raise FuryoSocietyUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        slug, volume, chapter, part = match.groups()
        return slug, volume, chapter if part is None else f"{chapter}.{part}"

    # ── Requests ─────────────────────────────────────────────────────

    def _page(self, url: str, what: str) -> BeautifulSoup:
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise FuryoSocietySourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        content = response.content or b""
        if len(content) > _MAX_BODY_BYTES:
            raise FuryoSocietySourceError(f"{self.name} {what} {url} is too large")
        try:
            return BeautifulSoup(content.decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise FuryoSocietySourceError(f"{self.name} {what} {url} is not UTF-8") from None

    # ── Search ───────────────────────────────────────────────────────

    def _catalogue(self) -> List[Manga]:
        url = f"{self.base_url}/mangas"
        soup = self._page(url, "catalogue")
        cards = soup.select("div#fs-tous div.fs-card-body")
        if not cards:
            raise FuryoSocietySourceError(f"{self.name} catalogue {url} lists no series")
        if len(cards) > _MAX_SERIES:
            raise FuryoSocietySourceError(f"{self.name} catalogue {url} is too long")
        series: Dict[str, Manga] = {}
        for card in cards:
            link = card.select_one("div.fs-card-img-container a[href]")
            title_link = card.select_one("span.fs-comic-title a[href]")
            title = _text(title_link)
            href = link.get("href") if link is not None else None
            if (href is None or title_link is None or title_link.get("href") != href
                    or not title):
                raise FuryoSocietySourceError(f"{self.name} catalogue {url} has an unreadable card")
            try:
                self._series_slug(href)
            except FuryoSocietyUnsupportedError:
                raise FuryoSocietySourceError(
                    f"{self.name} catalogue {url} links a card to {href!r}") from None
            if href in series:
                raise FuryoSocietySourceError(f"{self.name} catalogue {url} lists {href} twice")
            series[href] = Manga(title=title, url=href)
        return list(series.values())

    def search(self, query: str) -> List[Manga]:
        """Catalogue titles that contain ``query``, ignoring case. The site
        has no search of its own, so every search reads the catalogue."""
        query = " ".join((query or "").split()).casefold()
        if not query:
            return []
        return [m for m in self._catalogue() if query in m.title.casefold()]

    # ── Chapters ─────────────────────────────────────────────────────

    def _series_page(self, slug: str) -> Tuple[str, BeautifulSoup]:
        url = f"{self.base_url}/series/{slug}/"
        soup = self._page(url, "series page")
        if soup.select_one("h1.fs-comic-title") is None or soup.select_one(
                "div.fs-chapter-list") is None:
            raise FuryoSocietySourceError(f"{self.name} page {url} is not a series page")
        # Only the series' own Genre value decides: free text such as the
        # synopsis uses words like "adulte" in their everyday sense.
        for label in soup.select("div.comic-info p.fs-comic-label"):
            if _text(label).casefold() == "genre" and _ADULT.search(
                    _text(label.find_next_sibling())):
                raise FuryoSocietySourceError(
                    f"{self.name} series {slug} has an adult genre, which this source "
                    f"does not read")
        return url, soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' chapters the team translated, newest first.

        A row's number must agree between its visible text, its link and its
        title. Rows marked "Non traduit par la team" are left out with a
        warning. A row offering paid or early access makes the series fail.
        """
        slug = self._series_slug(manga_url)
        url, soup = self._series_page(slug)
        rows = [row for row in soup.select("div.fs-chapter-list div.element")]
        if not rows:
            raise FuryoSocietySourceError(f"{self.name} series {url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise FuryoSocietySourceError(f"{self.name} series {url} lists too many chapters")

        chapters: Dict[str, Chapter] = {}
        untranslated: List[str] = []
        for row in rows:
            link = row.select_one("div.title a[href]")
            if link is None:
                raise FuryoSocietySourceError(f"{self.name} series {url} has a row without a link")
            href, shown, label = link["href"], _text(link), link.get("title") or ""
            # Chapter names are story titles; only what the row shows besides
            # them (badges, date, controls and their labels) can mark an offer.
            extra = _row_marks(row, link)
            if _PAID.search(extra) or _ROW_ACCESS.search(extra):
                raise FuryoSocietySourceError(
                    f"{self.name} series {url} marks a chapter as paid, early or members-only "
                    f"access ({extra!r}); this source does not read it")
            download = f"{self.base_url}/download/"
            for other in row.select("a[href]"):
                if other is not link and not other["href"].startswith(download):
                    raise FuryoSocietySourceError(
                        f"{self.name} series {url} has a chapter control it cannot place "
                        f"({other['href']!r})")
            try:
                row_slug, volume, number = self._chapter_ref(href)
            except FuryoSocietyUnsupportedError:
                raise FuryoSocietySourceError(
                    f"{self.name} series {url} links a chapter to {href!r}") from None
            shown_match = _CHAPTER_TEXT.fullmatch(shown)
            if (row_slug != slug or shown_match is None or shown_match.group(1) != number
                    or not re.match(rf"Vol\.{volume} Chapitre {re.escape(number)}(?::|$)", label)):
                raise FuryoSocietySourceError(
                    f"{self.name} series {url} has a row whose link {href!r}, text {shown!r} "
                    f"and title {label!r} do not agree")
            name = _text(row.select_one("div.name"))
            if _UNTRANSLATED in name.casefold() or _UNTRANSLATED in label.casefold():
                untranslated.append(f"Chapitre {number}")
                continue
            if number in chapters:
                raise FuryoSocietySourceError(
                    f"{self.name} series {url} lists chapter {number} twice")
            title = f"Chapitre {number}" + (f" - {name}" if name else "")
            # The site only gives relative dates ("Il y a 4 ans"), so none is kept.
            chapters[number] = Chapter(number=number, title=title, url=href, date=None)
        if untranslated:
            logger.warning("%s: %s lists %d chapter(s) the team marks as not translated "
                           "by them, which are left out: %s",
                           self.name, url, len(untranslated), ", ".join(untranslated))
        if not chapters:
            raise FuryoSocietySourceError(f"{self.name} series {url} has no translated chapter")
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The series page's cover. Adding a series reads its page, which
        also shows whether the series exists; a failure gives no cover."""
        try:
            _url, soup = self._series_page(self._series_slug(manga_url))
        except Exception as e:
            logger.warning("%s: could not read %s: %s", self.name, manga_url, e)
            return None
        cover = soup.select_one("div.comic-info img.comic-cover")
        src = cover.get("src") if cover is not None else None
        return src if _is_cover_url(src) else None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page image of the chapter, in reader order and as served.

        The reader page must link back to this series and select this
        chapter. All images must sit in one comic and one chapter folder.
        A reader split over several pages, an inline image, or a login or
        payment prompt raises.
        """
        slug, volume, number = self._chapter_ref(chapter_url)
        soup = self._page(chapter_url, "reader")
        back = soup.select_one("div.fs-read-comic-link a[href]")
        selected = soup.select("select#fs-chapter-selector option[selected]")
        if (back is None or back["href"] != f"{self.base_url}/series/{slug}/"
                or len(selected) != 1 or selected[0].get("value") != chapter_url
                or _text(selected[0]) != f"Vol.{volume} Ch.{number}"):
            raise FuryoSocietySourceError(f"{self.name} reader {chapter_url} is not this chapter")

        for anchor in soup.select("a[href]"):
            href = anchor["href"]
            if href.startswith(chapter_url) and href != chapter_url:
                raise FuryoSocietySourceError(
                    f"{self.name} reader {chapter_url} continues on another page ({href!r}), "
                    f"which this source does not read")
        for option in soup.select("select#fs-page-selector option"):
            if not (option.get("value") or "").isdigit():
                raise FuryoSocietySourceError(
                    f"{self.name} reader {chapter_url} has a page switch it cannot read")

        reader = soup.select("div.fs-read")
        if len(reader) != 1:
            raise FuryoSocietySourceError(f"{self.name} reader {chapter_url} has no single reader")
        reader_text = _text(reader[0])
        if _PAID.search(reader_text) or _LOGIN_GATE.search(reader_text):
            raise FuryoSocietySourceError(
                f"{self.name} reader {chapter_url} asks to log in or pay ({reader_text[:80]!r})")

        pages: List[str] = []
        folders = set()
        for index, image in enumerate(reader[0].select("img")):
            src = image.get("src") or ""
            if src.startswith(("data:", "blob:")) or not src:
                raise FuryoSocietySourceError(
                    f"{self.name} reader {chapter_url} has an image without a plain address")
            holder = image.find_parent("div", attrs={"data-index": True})
            match = _PAGE_URL.fullmatch(src)
            if (image.get("id") != f"fsimg-{index}" or holder is None
                    or holder.get("data-index") != str(index) or match is None
                    or ".." in match.groups() or not src.lower().endswith(_IMAGE_SUFFIXES)):
                raise FuryoSocietySourceError(
                    f"{self.name} reader {chapter_url} has page {index + 1} out of place ({src!r})")
            folders.add(match.group(1, 2))
            if src in pages:
                raise FuryoSocietySourceError(f"{self.name} reader {chapter_url} shows {src} twice")
            pages.append(src)
        if not pages:
            raise FuryoSocietySourceError(f"{self.name} reader {chapter_url} has no page images")
        if len(pages) > _MAX_PAGES:
            raise FuryoSocietySourceError(f"{self.name} reader {chapter_url} has too many pages")
        if len(folders) != 1:
            raise FuryoSocietySourceError(
                f"{self.name} reader {chapter_url} spreads its pages over several folders")
        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, or the series cover that ``get_cover_url`` gives,
        sent with the site as Referer. Any failure returns False and leaves
        no older file behind."""
        path = Path(path)
        saved = False
        try:
            if not isinstance(url, str) or (_PAGE_URL.fullmatch(url) is None
                                            and not _is_cover_url(url)):
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
