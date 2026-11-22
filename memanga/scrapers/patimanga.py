"""
PatiManga scraper - Turkish manhwa and webtoon library
Site: www.patimanga.com

The site is WordPress on the "Yomiko" theme:

* search   -> GET /seriler/?q=<query>&view=grid lists ``article.ymk-card-view``
              cards. No results is one exact notice with a count of 0 that
              echoes the query.
* chapters -> a series page lists ``a.ymk-chapter-item`` rows. ``data-ch-num``
              may be zero-padded ("01"). A row's link is used as served, since
              some are not prefixed with the series ("/bolum-36/", "/bolum-31-2/").
              Row dates are relative, so no date is reported.
* pages    -> a reader page holds ``div.ymk-reader-page`` entries with one plain
              ``img.ymk-chapter-img`` each, counted by ``data-total-pages``.

A reader must name the listed chapter and series. Novels and titles whose own
genres mark them as adult are refused, and a row without a link or with a lock,
coin or premium class fails the listing.
"""

import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "www.patimanga.com"
_SITE_HOSTS = frozenset({_HOST, "patimanga.com"})

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/({_SLUG})/?$")
_IMAGE_PATH = re.compile(r"^/wp-content/uploads/\d{4}/\d{2}/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_POST_ID = re.compile(r"^[1-9]\d*$")
_BODY_POST_ID = re.compile(r"^postid-([1-9]\d*)$")
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({
    "yetişkin", "yetiskin", "adult", "+18", "18+", "18", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})

_NO_RESULTS = "Seçtiğiniz Filtrelere Uygun Seri Bulunamadı"
_NO_RESULTS_HINT = (
    "Arama kelimesini veya filtre seçeneklerini sıfırlayarak tüm serileri "
    "görüntüleyebilirsiniz."
)
_NO_RESULTS_COUNT = "Toplam 0 seri listeleniyor "
_NO_RESULTS_RESET = "Filtreleri Temizle"

_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class PatiMangaSourceError(RuntimeError):
    """patimanga.com answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _split(url):
    """urlsplit() of a string URL with a valid port, or None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        parts.port
    except ValueError:
        return None
    return parts


def _site_path(url) -> Optional[str]:
    """The path of a URL on this site, or None."""
    parts = _split(url)
    if (parts is None or parts.scheme not in ("http", "https")
            or (parts.hostname or "").lower() not in _SITE_HOSTS
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment):
        return None
    return parts.path


def _page_url(value) -> str:
    """``value`` if it is an image in the site's uploads, else raise."""
    parts = _split(value)
    if (parts is None or parts.scheme != "https" or parts.hostname != _HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment
            or not _IMAGE_PATH.match(parts.path)
            or any(part in (".", "..") for part in parts.path.split("/"))):
        raise PatiMangaSourceError("Unexpected PatiManga page image URL")
    return value.strip()


def _has_paid_class(row) -> bool:
    return any(_PAID_CLASS.search(name)
               for element in [row, *row.find_all(True)]
               for name in element.get("class") or [])


def _body_post_id(soup: BeautifulSoup) -> Optional[str]:
    body = soup.find("body")
    ids = [match.group(1) for match in
           (_BODY_POST_ID.match(name) for name in (body.get("class") or [] if body else []))
           if match]
    return ids[0] if len(ids) == 1 else None


class PatiMangaScraper(BaseScraper):
    """Scraper for PatiManga (www.patimanga.com)."""

    name = "patimanga"
    base_url = "https://www.patimanga.com"
    content_language = "tr"  # Turkish-language site
    nsfw = False  # titles with an adult genre are refused

    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: series whose genres were checked (with
        # their post id), and each listed chapter's (chapter id, series id).
        self._cleared: Dict[str, str] = {}
        self._listed: Dict[str, Tuple[str, str]] = {}

    # URLs

    def _series_url(self, url) -> str:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise PatiMangaSourceError(f"Not a PatiManga series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}/"

    def _chapter_url(self, url) -> str:
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise PatiMangaSourceError(f"Not a PatiManga chapter URL: {url}")
        return f"{self.base_url}/{match.group(1)}/"

    def _fetch(self, url: str, what: str) -> BeautifulSoup:
        """One page, parsed; redirects are not followed."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise PatiMangaSourceError(
                f"PatiManga answered HTTP {response.status_code} for {what} {url}")
        return BeautifulSoup(response.text, "html.parser")

    # Search

    @staticmethod
    def _notices(soup: BeautifulSoup) -> list:
        return [heading for heading in soup.find_all("h3") if _text(heading) == _NO_RESULTS]

    def _is_no_results(self, soup: BeautifulSoup, query: str) -> bool:
        """True only for the archive page saying this query found nothing."""
        inputs = soup.select('input[name="q"]')
        counts = soup.select("p.ymk-archive-subtitle")
        notices = self._notices(soup)
        if len(inputs) != 1 or len(counts) != 1 or len(notices) != 1:
            return False
        if " ".join((inputs[0].get("value") or "").split()) != " ".join(query.split()):
            return False
        if not _text(counts[0]).startswith(_NO_RESULTS_COUNT):
            return False
        box = notices[0].parent
        hints = box.find_all("p")
        links = box.find_all("a")
        return (len(hints) == 1 and _text(hints[0]) == _NO_RESULTS_HINT
                and len(links) == 1 and links[0].get("href") == f"{self.base_url}/seriler/"
                and _text(links[0]) == _NO_RESULTS_RESET)

    @staticmethod
    def _card_is_refused(card) -> bool:
        """A novel, or a title whose genre classes mark it as adult."""
        if any(_text(badge) == "Novel" for badge in card.select(".ymk-card-cover span")):
            return True
        return any(name.startswith("genres-") and name[len("genres-"):].casefold() in _ADULT_GENRES
                   for name in card.get("class") or [])

    def search(self, query: str) -> List[Manga]:
        """The first page of the archive search, without novels or adult titles."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/seriler/?q={quote_plus(query)}&view=grid"
        soup = self._fetch(url, "search")
        cards = soup.select("article.ymk-card-view")
        if not cards:
            if self._is_no_results(soup, query):
                return []
            raise PatiMangaSourceError(f"PatiManga search {url} did not serve a result list")
        if self._notices(soup):
            raise PatiMangaSourceError(
                f"PatiManga search {url} served results and a no-results notice")

        results: List[Manga] = []
        seen = set()
        for card in cards:
            link = card.select_one("a.ymk-card-title-link[href]")
            title = _text(link) if link else ""
            if not title:
                raise PatiMangaSourceError(
                    f"PatiManga search {url} lists a result without its link or title")
            try:
                series_url = self._series_url(link["href"])
                if self._series_url(card.get("data-series-url")) != series_url:
                    raise PatiMangaSourceError("mismatch")
            except PatiMangaSourceError:
                raise PatiMangaSourceError(
                    f"PatiManga search {url} lists a result that is not a series") from None
            if series_url in seen:
                raise PatiMangaSourceError(f"PatiManga search {url} lists {series_url} twice")
            seen.add(series_url)
            if self._card_is_refused(card):
                continue
            image = card.select_one("img.ymk-card-poster-img[src]")
            try:
                cover = _page_url(image["src"]) if image else None
            except PatiMangaSourceError:
                cover = None
            results.append(Manga(title=title, url=series_url, cover_url=cover))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused when its own genres mark it as adult."""
        soup = self._fetch(series_url, "series page")
        body = soup.find("body")
        post_id = _body_post_id(soup)
        if (body is None or "single-manga" not in (body.get("class") or [])
                or post_id is None or len(soup.select("h1")) != 1):
            raise PatiMangaSourceError(f"PatiManga page {series_url} is not a series page")
        for pill in soup.select("a.ymk-series-genre-pill"):
            slugs = parse_qs(urlsplit(pill.get("href") or "").query).get("genre", [])
            if {_text(pill).casefold(), *(slug.casefold() for slug in slugs)} & _ADULT_GENRES:
                raise PatiMangaSourceError(
                    f"PatiManga lists {series_url} as adult; adult titles are not supported")
        self._cleared[series_url] = post_id
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter row a series page serves, oldest first."""
        series_url = self._series_url(manga_url)
        soup = self._series_page(series_url)
        series_id = self._cleared[series_url]
        lists = soup.select("#ymkSeriesChapterListContainer")
        rows = lists[0].select("a.ymk-chapter-item") if len(lists) == 1 else []
        if not rows:
            raise PatiMangaSourceError(f"PatiManga series page {series_url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise PatiMangaSourceError(
                f"PatiManga series page {series_url} lists more chapters than this source reads")
        if len(lists[0].select(".ymk-chapter-item")) != len(rows):
            raise PatiMangaSourceError(
                f"PatiManga series page {series_url} has a chapter without a link; "
                f"this source reads free chapters only")

        chapters: Dict[str, Chapter] = {}
        listed: Dict[str, Tuple[str, str]] = {}
        chapter_ids = set()
        for row in rows:
            if _has_paid_class(row):
                raise PatiMangaSourceError(
                    f"PatiManga series page {series_url} has a locked or paid chapter; "
                    f"this source reads free chapters only")
            raw = (row.get("data-ch-num") or "").strip()
            chapter_id = (row.get("data-chapter-id") or "").strip()
            label = row.select_one(".ymk-ch-num-label")
            if (not _NUMBER.match(raw) or not _POST_ID.match(chapter_id)
                    or label is None or _text(label) != f"Bölüm {raw}"):
                raise PatiMangaSourceError(
                    f"PatiManga series page {series_url} has a malformed chapter row")
            try:
                url = self._chapter_url(row.get("href"))
            except PatiMangaSourceError:
                raise PatiMangaSourceError(
                    f"PatiManga series page {series_url} links chapter {raw} elsewhere") from None
            number = format(Decimal(raw).normalize(), "f")
            if number in chapters or url in listed or chapter_id in chapter_ids:
                raise PatiMangaSourceError(
                    f"PatiManga series page {series_url} lists chapter {number} twice")
            chapter_ids.add(chapter_id)
            listed[url] = (chapter_id, series_id)
            title = (row.get("data-ch-title") or "").strip() or None
            chapters[number] = Chapter(number=number, title=title, url=url)
        self._listed.update(listed)
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            soup = self._series_page(self._series_url(manga_url))
            meta = soup.select_one('meta[property="og:image"][content]')
            return _page_url(meta["content"]) if meta else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The ordered page images of a chapter, all or nothing."""
        url = self._chapter_url(chapter_url)
        soup = self._fetch(url, "chapter")

        def refused(why: str):
            return PatiMangaSourceError(f"PatiManga chapter {url} {why}")

        readers = soup.select("#ymkReaderContent")
        if len(readers) != 1:
            raise refused("has no reader")
        reader = readers[0]
        if reader.get("data-is-novel") != "0":
            raise refused("is not marked as an image chapter")
        chapter_id = reader.get("data-chapter-id") or ""
        series_id = reader.get("data-manga-id") or ""
        total = reader.get("data-total-pages") or ""
        if not (_POST_ID.match(chapter_id) and _POST_ID.match(series_id) and _POST_ID.match(total)):
            raise refused("does not state its chapter, series and page count")
        if _body_post_id(soup) != chapter_id:
            raise refused("answered for another chapter")
        if self._listed.get(url, (chapter_id, series_id)) != (chapter_id, series_id):
            raise refused("is not the chapter the series lists")

        back = soup.select("a.ymk-reader-back-btn[href]")
        if len(back) != 1:
            raise refused("does not name its series")
        try:
            series_url = self._series_url(back[0]["href"])
        except PatiMangaSourceError:
            raise refused("names a series elsewhere") from None
        if series_url not in self._cleared:
            self._series_page(series_url)
        if self._cleared[series_url] != series_id:
            raise refused("names another series")

        count = int(total)
        if count > _MAX_PAGES:
            raise refused(f"lists {count} pages, more than the {_MAX_PAGES} this source accepts")
        containers = soup.select("#ymkReaderPages")
        entries = containers[0].select(".ymk-reader-page") if len(containers) == 1 else []
        if len(entries) != count:
            raise refused(f"serves {len(entries)} pages but states {count}")

        pages: List[str] = []
        for index, entry in enumerate(entries):
            images = entry.find_all("img")
            if (entry.get("data-page-index") != str(index) or len(images) != 1
                    or "ymk-chapter-img" not in (images[0].get("class") or [])):
                raise refused(f"has a malformed page {index + 1}")
            source = (images[0].get("src") or "").strip()
            if source != (images[0].get("data-src") or "").strip():
                raise refused(f"has two addresses for page {index + 1}")
            try:
                pages.append(_page_url(source))
            except PatiMangaSourceError:
                raise refused(f"has an unexpected image for page {index + 1}") from None
        if len(set(pages)) != len(pages):
            raise refused("lists the same image twice")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page image; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            image_url = _page_url(url)
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise PatiMangaSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise PatiMangaSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise PatiMangaSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a PatiManga page: %s", e)
            return False
