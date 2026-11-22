"""
HeavenManga scraper - Spanish manhwa, manga and manhua library
Site: heavenmanga.com

* search   -> GET /buscar?query=<query> (at least 3 characters). Result rows sit
              inside a wrapper of the same class. No results is "0 resultados",
              the echoed query and one empty result container.
* chapters -> a series page, then the same URL as a DataTables request returns
              ``data`` rows. The chapter number is the slug without "-es"
              ("1.1-es" is 1.1). The row's ``number`` field is an HTML panel
              with the label and the reader link; its ``number`` attribute
              drops the dot and is not used.
* pages    -> /manga/ver/<id> holds ``var pUrl = [...]``, read as JSON and never
              run, with ``var cid`` and ``var mid`` naming the chapter and series.

Rows with ``estreno`` set stay listed, titled as unavailable, and are not read:
what the flag means has not been established.

Novels and titles whose own type or genres mark them as adult are refused.
"""

import json
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"heavenmanga.com", "www.heavenmanga.com"})
_IMAGE_HOST = "blogger.googleusercontent.com"

_SLUG = r"[a-z0-9_-]+"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(r"^/manga/ver/([1-9]\d*)/?$")
_RESERVED_SLUGS = frozenset({"ver", "leer"})
_CHAPTER_SLUG = re.compile(r"^(\d+(?:\.\d+)?)-es$")
_CREATED_AT = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}$")
_IMAGE_PATH = re.compile(
    r"^/img/b/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/s16000/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)$", re.I)
_COVER_PATH = re.compile(rf"^/uploads/manga/{_SLUG}/cover/cover_250x350\.(?:webp|jpe?g|png)$")

_READER_CID = re.compile(r"\bvar\s+cid\s*=\s*\"([^\"]*)\"")
_READER_MID = re.compile(r"\bvar\s+mid\s*=\s*\"([^\"]*)\"")
_READER_LIST = re.compile(r"\bvar\s+pUrl\s*=\s*(?=\[)")
_READER_COUNT = re.compile(r"'pages'\s*:\s*(\d+)")

_COMIC_TYPES = frozenset({"manga", "manhwa", "manhua"})
_ADULT_GENRES = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_LIST_KEYS = frozenset({"draw", "recordsTotal", "recordsFiltered", "data"})
_ROW_KEYS = frozenset({
    "id", "slug", "name", "number", "volume", "manga_id", "user_id", "scan_id",
    "descarga", "estreno", "tipo", "descripcion", "created_at", "updated_at",
})
_PAGE_KEYS = frozenset({"npage", "imgURL"})

_MIN_QUERY = 3
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024

_RESULT_BOX = "div.c-tabs-item__content"
_NO_RESULTS = "0 resultados"
_UNAVAILABLE_TITLE = "Unavailable (estreno)"
_UNAVAILABLE_FRAGMENT = "estreno"
_CHAPTER_LIST_QUERY = urlencode([
    ("columns[0][data]", "number"),
    ("columns[0][orderable]", "true"),
    ("columns[1][data]", "created_at"),
    ("columns[1][searchable]", "true"),
    ("order[0][column]", "1"),
    ("order[0][dir]", "desc"),
    ("start", "0"),
    ("length", str(_MAX_CHAPTERS)),
])


class HeavenMangaSourceError(RuntimeError):
    """heavenmanga.com answered with data this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _is_int(value) -> bool:
    return type(value) is int


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


def _on_site(parts) -> bool:
    return (parts is not None and parts.scheme in ("http", "https")
            and (parts.hostname or "").lower() in _SITE_HOSTS
            and parts.port is None and "@" not in parts.netloc and not parts.query)


def _page_url(value) -> str:
    """``value`` if it is a page image on the image host, else raise."""
    parts = _split(value)
    if (parts is None or parts.scheme != "https" or parts.hostname != _IMAGE_HOST
            or parts.port is not None or "@" in parts.netloc
            or parts.query or parts.fragment or not _IMAGE_PATH.match(parts.path)):
        raise HeavenMangaSourceError("Unexpected HeavenManga page image URL")
    return value.strip()


def _cover(url) -> Optional[str]:
    parts = _split(url)
    if (parts is None or parts.scheme != "https" or parts.hostname != "heavenmanga.com"
            or parts.port is not None or parts.query or parts.fragment
            or not _COVER_PATH.match(parts.path)):
        return None
    return url.strip()


class HeavenMangaScraper(BaseScraper):
    """Scraper for HeavenManga (heavenmanga.com)."""

    name = "heavenmanga"
    base_url = "https://heavenmanga.com"
    content_language = "es"  # Spanish-language site
    nsfw = False  # titles of an adult type or genre are refused

    _LIST_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: each listed chapter id's series slug, and
        # the listed chapter ids that carry the estreno flag.
        self._listed: Dict[str, str] = {}
        self._unavailable: Set[str] = set()

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        parts = _split(url)
        match = (_SERIES_PATH.match(parts.path)
                 if _on_site(parts) and not parts.fragment else None)
        if not match or match.group(1) in _RESERVED_SLUGS:
            raise HeavenMangaSourceError(f"Not a HeavenManga series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, bool]:
        """A reader URL's chapter id, and whether it carries the estreno mark."""
        parts = _split(url)
        match = _CHAPTER_PATH.match(parts.path) if _on_site(parts) else None
        if not match or parts.fragment not in ("", _UNAVAILABLE_FRAGMENT):
            raise HeavenMangaSourceError(f"Not a HeavenManga chapter URL: {url}")
        return match.group(1), parts.fragment == _UNAVAILABLE_FRAGMENT

    def _get(self, url: str, what: str, **kwargs):
        """One 200 response; redirects are not followed."""
        response = self._request(url, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise HeavenMangaSourceError(
                f"HeavenManga answered HTTP {response.status_code} for {what} {url}")
        return response

    # Search

    @staticmethod
    def _is_no_results(soup: BeautifulSoup, containers: list, query: str) -> bool:
        """True only for the search page saying this query found nothing."""
        counts = [heading for heading in soup.find_all("h4") if _text(heading) == _NO_RESULTS]
        echoes = soup.select(".c-nav-tabs span")
        return (len(containers) == 1 and len(counts) == 1 and len(echoes) == 1
                and _text(echoes[0]) == "busqueda: " + " ".join(query.split()))

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search."""
        query = (query or "").strip()
        if not query:
            return []
        if len(query) < _MIN_QUERY:
            raise HeavenMangaSourceError(
                f"HeavenManga search needs at least {_MIN_QUERY} characters")
        url = f"{self.base_url}/buscar?query={quote_plus(query)}"
        soup = BeautifulSoup(self._get(url, "search").text, "html.parser")
        containers = soup.select(_RESULT_BOX)
        # Rows sit inside a wrapper of the same class, so a row is a box
        # with content and no box inside it.
        rows = [box for box in containers
                if (box.find(True) or _text(box)) and not box.select_one(_RESULT_BOX)]
        if not rows:
            if self._is_no_results(soup, containers, query):
                return []
            raise HeavenMangaSourceError(f"HeavenManga search {url} did not serve a result list")
        if any(_text(heading) == _NO_RESULTS for heading in soup.find_all("h4")):
            raise HeavenMangaSourceError(
                f"HeavenManga search {url} served results and a no-results notice")
        for link in soup.select(f"{_RESULT_BOX} h4 a[href]"):
            if link.find_parent("div", class_="c-tabs-item__content").select_one(_RESULT_BOX):
                raise HeavenMangaSourceError(
                    f"HeavenManga search {url} lists a result outside a result row")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            link = row.select_one("h4 a[href]")
            title = _text(link) if link else ""
            if not title:
                raise HeavenMangaSourceError(
                    f"HeavenManga search {url} lists a result without its link or title")
            try:
                series_url, _ = self._series_parts(urljoin(self.base_url + "/", link["href"]))
            except HeavenMangaSourceError:
                raise HeavenMangaSourceError(
                    f"HeavenManga search {url} lists a result that is not a series") from None
            if series_url in seen:
                raise HeavenMangaSourceError(f"HeavenManga search {url} lists {series_url} twice")
            seen.add(series_url)
            image = row.select_one("img[data-src]")
            results.append(Manga(title=title, url=series_url,
                                 cover_url=_cover(image["data-src"]) if image else None))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for novels and adult titles."""
        soup = BeautifulSoup(self._get(series_url, "series page").text, "html.parser")
        summaries = soup.select("div.tab-summary")
        canonical = soup.select('link[rel="canonical"]')
        if (len(summaries) != 1 or len(canonical) != 1
                or canonical[0].get("href") != series_url):
            raise HeavenMangaSourceError(f"HeavenManga page {series_url} is not a series page")
        types = []
        for item in summaries[0].select(".post-content_item"):
            heading = item.select_one(".summary-heading")
            content = item.select_one(".summary-content")
            if heading is not None and content is not None and _text(heading) == "Type":
                types.append(_text(content).casefold())
        if len(types) != 1:
            raise HeavenMangaSourceError(f"HeavenManga page {series_url} does not state its type")
        genres = {_text(link).casefold() for link in summaries[0].select("div.genres-content a")}
        if types[0] == "hentai" or genres & _ADULT_GENRES:
            raise HeavenMangaSourceError(
                f"HeavenManga lists {series_url} as adult; adult titles are not supported")
        if types[0] not in _COMIC_TYPES:
            raise HeavenMangaSourceError(
                f"HeavenManga lists {series_url} as {types[0]}; only comics are supported")
        return soup

    def _chapter_rows(self, series_url: str) -> list:
        url = f"{series_url}?{_CHAPTER_LIST_QUERY}"
        response = self._get(url, "chapter list", headers=self._LIST_HEADERS)
        try:
            data = response.json()
        except ValueError:
            raise HeavenMangaSourceError(
                f"HeavenManga returned no chapter list for {series_url}") from None
        if not isinstance(data, dict) or set(data) != _LIST_KEYS:
            raise HeavenMangaSourceError(
                f"HeavenManga returned an unexpected chapter list for {series_url}")
        rows = data["data"]
        if (not isinstance(rows, list) or not rows or len(rows) >= _MAX_CHAPTERS
                or data["recordsTotal"] != len(rows) or data["recordsFiltered"] != len(rows)):
            raise HeavenMangaSourceError(
                f"HeavenManga chapter list for {series_url} is empty or incomplete")
        return rows

    def _row_number(self, row, series_url: str) -> Tuple[str, str]:
        """A row's chapter number and served reader link, checked against its panel."""
        def malformed():
            return HeavenMangaSourceError(
                f"HeavenManga chapter list for {series_url} has a malformed row")

        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise malformed()
        slug = row["slug"]
        match = _CHAPTER_SLUG.match(slug) if isinstance(slug, str) else None
        if (not match or not _is_int(row["id"]) or row["id"] <= 0
                or not _is_int(row["estreno"]) or row["estreno"] not in (0, 1)
                or not _is_int(row["manga_id"]) or not isinstance(row["name"], str)
                or not isinstance(row["number"], str)
                or not isinstance(row["created_at"], str)
                or not _CREATED_AT.match(row["created_at"])):
            raise malformed()
        panel = BeautifulSoup(row["number"], "html.parser")
        label = panel.select_one(".c_title")
        link = f"{self.base_url}/manga/ver/{row['id']}"
        readers = {anchor["href"] for anchor in panel.select("a[href]")
                   if "/manga/ver/" in anchor["href"]}
        if label is None or _text(label) != f"Capítulo {match.group(1)}" or readers != {link}:
            raise malformed()
        return format(Decimal(match.group(1)).normalize(), "f"), link

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter a series serves, oldest first; flagged ones stay visible."""
        series_url, slug = self._series_parts(manga_url)
        self._series_page(series_url)
        rows = self._chapter_rows(series_url)

        chapters: Dict[str, Chapter] = {}
        ids = set()
        series_ids = set()
        flagged = set()
        for row in rows:
            number, link = self._row_number(row, series_url)
            chapter_id = str(row["id"])
            if number in chapters or chapter_id in ids:
                raise HeavenMangaSourceError(
                    f"HeavenManga lists chapter {number} of {slug} twice")
            ids.add(chapter_id)
            series_ids.add(row["manga_id"])
            date = row["created_at"][:10]
            if row["estreno"]:
                flagged.add(chapter_id)
                chapters[number] = Chapter(number=number, title=_UNAVAILABLE_TITLE,
                                           url=f"{link}#{_UNAVAILABLE_FRAGMENT}", date=date)
            else:
                chapters[number] = Chapter(number=number, title=row["name"].strip() or None,
                                           url=link, date=date)
        if len(series_ids) != 1:
            raise HeavenMangaSourceError(f"HeavenManga lists chapters of several series for {slug}")
        for chapter_id in ids:
            self._listed[chapter_id] = slug
        self._unavailable.difference_update(ids)
        self._unavailable.update(flagged)
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_url, _ = self._series_parts(manga_url)
            meta = self._series_page(series_url).select_one('meta[property="og:image"][content]')
            return _cover(meta["content"]) if meta else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in served order, all or nothing."""
        chapter_id, marked = self._chapter_parts(chapter_url)
        url = f"{self.base_url}/manga/ver/{chapter_id}"

        def refused(why: str):
            return HeavenMangaSourceError(f"HeavenManga chapter {url} {why}")

        def unavailable():
            return refused("is marked estreno; what that means is unknown, so it is not read")

        if marked or chapter_id in self._unavailable:
            raise unavailable()
        html = self._get(url, "chapter").text
        cids, mids = _READER_CID.findall(html), _READER_MID.findall(html)
        if len(cids) != 1 or cids[0] != f"ver/{chapter_id}":
            raise refused("answered for another chapter")
        if len(mids) != 1 or not mids[0].startswith("manga/"):
            raise refused("does not name its series")
        series_url, slug = self._series_parts(f"{self.base_url}/{mids[0]}")
        if chapter_id not in self._listed:
            self.get_chapters(series_url)
        if self._listed.get(chapter_id) != slug:
            raise refused("is not listed by the series it names")
        if chapter_id in self._unavailable:
            raise unavailable()

        lists = list(_READER_LIST.finditer(html))
        if len(lists) != 1:
            raise refused(f"has {len(lists)} page lists, not one")
        try:
            entries, _ = json.JSONDecoder().raw_decode(html, lists[0].end())
        except ValueError:
            raise refused("has a page list that is not JSON") from None
        counts = _READER_COUNT.findall(html)
        if not isinstance(entries, list) or not entries:
            raise refused("lists no pages")
        if len(entries) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        if counts != [str(len(entries))]:
            raise refused("states another page count than it lists")

        pages: List[str] = []
        for index, entry in enumerate(entries, 1):
            if (not isinstance(entry, dict) or set(entry) != _PAGE_KEYS
                    or not _is_int(entry["npage"]) or entry["npage"] != index):
                raise refused(f"has a malformed page {index}")
            try:
                pages.append(_page_url(entry["imgURL"]))
            except HeavenMangaSourceError:
                raise refused(f"has an unexpected image for page {index}") from None
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
                raise HeavenMangaSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise HeavenMangaSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise HeavenMangaSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a HeavenManga page: %s", e)
            return False
