"""
ChaosTrad: a French Sonic fan translation team.

https://chaostrad.fr

Only the Shadow the Hedgehog manga (``/comics/shadow-manga``) is read.
The site's other series are refused before any request: their origin and
reader have not been checked, and some are Western comics. A series page
lists its chapters as ``/comics/<series>/<number>`` cards, and a chapter's
reader shows every page as an ``img.comic-image``. The reader must name
the chapter asked for and link back to its series.

Search reads the site's own series menu on the home page and matches its
link labels on this device. The site has no search address of its own
for series, and a label can differ from the series page heading.
"""

import contextlib
import http.cookiejar
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "chaostrad.fr"
# The series this source reads. Any other series link is refused.
_SUPPORTED_SERIES = frozenset({"shadow-manga"})
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NUMBER = re.compile(r"[1-9][0-9]{0,5}")
_MENU_PREFIX = "Chapitre de "
_COUNT = re.compile(r"([0-9]+)\s+Comics")
_RELEASE = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}")
_TITLE_NUMBER = re.compile(r"#([0-9]+)\s+-\s+ChaosTrad")
# A page as the reader serves it, before and after the library encodes it.
_PAGE_SRC = re.compile(r"/uploads/chapter_images/([^/?#]+)/([0-9a-f]{32})\.(?:webp|jpe?g|png)")
_PAGE_URL = re.compile(
    r"https://chaostrad\.fr/uploads/chapter_images/[^/?#\s]+/[0-9a-f]{32}\.(?:webp|jpe?g|png)")

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_CHAPTERS = 5000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 4 * 1024 * 1024


class ChaosTradSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected parts, or a chapter or page form
    this source does not read."""


class ChaosTradUnsupportedError(ValueError):
    """A URL that is not a supported series or chapter link of this site."""


def _text(node) -> str:
    return " ".join(node.get_text(" ").split()) if node is not None else ""


def _meta(soup, **attrs) -> Optional[str]:
    tag = soup.find("meta", attrs=attrs)
    value = tag.get("content") if tag is not None else None
    return value.strip() if isinstance(value, str) else None


def _canonical(soup) -> Optional[str]:
    tag = soup.find("link", rel="canonical")
    value = tag.get("href") if tag is not None else None
    return value.strip() if isinstance(value, str) else None


class ChaosTradScraper(BaseScraper):
    """chaostrad.fr, limited to its Shadow the Hedgehog manga."""

    name = "chaostrad"
    base_url = "https://chaostrad.fr"
    engine = "http"
    content_language = "fr"
    nsfw = False

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _segments(self, url: str) -> List[str]:
        """The path segments of a URL on this exact host. A login, port,
        query, fragment or relative URL is refused."""
        refused = ChaosTradUnsupportedError(f"Not a {self.name} page: {url!r}")
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

    def _supported(self, slug: str, url: str) -> str:
        if slug not in _SUPPORTED_SERIES:
            raise ChaosTradUnsupportedError(
                f"{self.name} series {slug!r} is not supported; only the Shadow the Hedgehog "
                f"manga is read: {url!r}")
        return slug

    def _series_slug(self, url: str) -> str:
        segments = self._segments(url)
        if len(segments) != 2 or segments[0] != "comics" or not _SLUG.fullmatch(segments[1]):
            raise ChaosTradUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return self._supported(segments[1], url)

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter number)`` of a ``/comics/<series>/<n>``
        link. Only whole chapter numbers are read."""
        segments = self._segments(url)
        if (len(segments) != 3 or segments[0] != "comics" or not _SLUG.fullmatch(segments[1])
                or not _NUMBER.fullmatch(segments[2])):
            raise ChaosTradUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        return self._supported(segments[1], url), segments[2]

    def _series_url(self, slug: str) -> str:
        return f"{self.base_url}/comics/{slug}"

    # ── Requests ─────────────────────────────────────────────────────

    def _soup(self, url: str, what: str) -> BeautifulSoup:
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise ChaosTradSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise ChaosTradSourceError(f"{self.name} {what} {url} is too large")
        return BeautifulSoup(response.text, "html.parser")

    def _bound(self, soup, url: str, what: str) -> None:
        """The page must name ``url`` as its canonical and shared address."""
        if _canonical(soup) != url or _meta(soup, property="og:url") != url:
            raise ChaosTradSourceError(f"{self.name} {what} {url} is not the page asked for")

    # ── Search ───────────────────────────────────────────────────────

    def _menu(self) -> List[Tuple[str, str]]:
        """``(label, href)`` of every link in the home page's series menu."""
        url = f"{self.base_url}/"
        soup = self._soup(url, "home page")
        menus = soup.select("div#comics-submenu")
        links = menus[0].select("a[href]") if len(menus) == 1 else []
        if not links:
            raise ChaosTradSourceError(f"{self.name} home page {url} has no series menu")
        entries = []
        for link in links:
            label = _text(link)
            if not label:
                title = " ".join((link.get("title") or "").split())
                label = title[len(_MENU_PREFIX):] if title.startswith(_MENU_PREFIX) else title
            entries.append((label.strip(), link["href"].strip()))
        return entries

    def search(self, query: str) -> List[Manga]:
        """Supported series whose menu label contains ``query``, ignoring
        case and spacing. A matching series this source does not read is
        left out with a warning."""
        wanted = " ".join((query or "").split()).casefold()
        if not wanted:
            return []
        results: List[Manga] = []
        left_out = []
        for label, href in self._menu():
            if not label or wanted not in label.casefold():
                continue
            segments = urlsplit(urljoin(f"{self.base_url}/", href))
            path = segments.path.rstrip("/").split("/")[1:]
            slug = path[1] if (segments.netloc == _SITE_HOST and len(path) == 2
                               and path[0] == "comics") else None
            if slug not in _SUPPORTED_SERIES:
                left_out.append(label)
                continue
            series_url = self._series_url(slug)
            if all(m.url != series_url for m in results):
                results.append(Manga(title=label, url=series_url))
        if left_out:
            logger.warning("%s: %d matching series are not supported and were left out: %s",
                           self.name, len(left_out), ", ".join(left_out))
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' chapters, newest first.

        Every card must link to a whole-numbered chapter of this series,
        agree with its card number, and appear once; the list must be as
        long as the page's "N Comics" count.
        """
        slug = self._series_slug(manga_url)
        url = self._series_url(slug)
        soup = self._soup(url, "series")
        self._bound(soup, url, "series")
        count = _COUNT.fullmatch(_text(soup.select_one("div#TagFilter h2")))
        if count is None:
            raise ChaosTradSourceError(f"{self.name} series {slug} does not state its count")
        cards = soup.select("a.comic-link")
        if not cards:
            raise ChaosTradSourceError(f"{self.name} series {slug} lists no chapters")
        if len(cards) > _MAX_CHAPTERS:
            raise ChaosTradSourceError(
                f"{self.name} series {slug} lists more chapters than this source reads")
        if int(count.group(1)) != len(cards):
            raise ChaosTradSourceError(
                f"{self.name} series {slug} shows {len(cards)} chapters but counts "
                f"{count.group(1)}")

        chapters = {}
        for card in cards:
            href = (card.get("href") or "").strip()
            link = urljoin(f"{self.base_url}/", href)
            try:
                card_slug, number = self._chapter_ref(link)
            except ChaosTradUnsupportedError:
                raise ChaosTradSourceError(
                    f"{self.name} series {slug} has a chapter link this source cannot read "
                    f"yet ({href!r})") from None
            holder = card.find_parent(attrs={"data-number": True})
            if card_slug != slug or (holder is not None and holder["data-number"] != number):
                raise ChaosTradSourceError(
                    f"{self.name} series {slug} has chapter link {href!r} out of place")
            if number in chapters:
                raise ChaosTradSourceError(
                    f"{self.name} series {slug} lists chapter {number} twice")
            chapters[number] = Chapter(number=number, title=None, url=link,
                                       date=self._release(card))
        return sorted(chapters.values(), key=lambda c: c.numeric, reverse=True)

    @staticmethod
    def _release(card) -> Optional[str]:
        """The card's ``dd.mm.yyyy`` release date as ``yyyy-mm-dd``."""
        text = _text(card.select_one("p.release-date"))
        if not _RELEASE.fullmatch(text):
            return None
        try:
            return datetime.strptime(text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            return None

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's page images, in served order.

        The reader must name this chapter in its title, canonical and
        shared address and chapter menu, and link back to its series. All
        pages sit in one upload folder on this host.
        """
        slug, number = self._chapter_ref(chapter_url)
        url = f"{self._series_url(slug)}/{number}"
        soup = self._soup(url, "reader")
        self._bound(soup, url, "reader")
        title = _TITLE_NUMBER.search(_text(soup.title))
        selected = soup.select("select#chapitreSelect option[selected]")
        backlinks = [a.get("href") for a in soup.select("ul.links a[href]")]
        if (title is None or title.group(1) != number or len(selected) != 1
                or selected[0].get("value") != f"/comics/{slug}/{number}"
                or f"/comics/{slug}" not in backlinks):
            raise ChaosTradSourceError(f"{self.name} reader {url} is not this chapter")

        holders = soup.select("div#tel")
        images = holders[0].select("img.comic-image") if len(holders) == 1 else []
        if not images:
            raise ChaosTradSourceError(f"{self.name} reader {url} has no page images")
        if len(images) > _MAX_PAGES:
            raise ChaosTradSourceError(
                f"{self.name} reader {url} has more pages than this source reads")
        result: List[str] = []
        folders = set()
        for index, image in enumerate(images):
            src = (image.get("src") or "").strip()
            match = _PAGE_SRC.fullmatch(src)
            if match is None:
                raise ChaosTradSourceError(
                    f"{self.name} reader {url} has page {index + 1} in a form this source does "
                    f"not read ({src[:80]!r})")
            folders.add(match.group(1))
            page = requote_uri(urljoin(f"{self.base_url}/", src))
            if page in result:
                raise ChaosTradSourceError(f"{self.name} reader {url} shows page {src!r} twice")
            result.append(page)
        if len(folders) != 1:
            raise ChaosTradSourceError(
                f"{self.name} reader {url} mixes pages from {len(folders)} upload folders")
        return result

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The site serves no series cover (its shared image is the team
        logo), so none is read and no request is sent."""
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
