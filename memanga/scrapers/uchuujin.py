"""
Uchuujin scraper - Spanish manga and manhwa reader
Site: uchuujinmangas.com

The site runs the WordPress "MangaThemesia" theme. Search is the ``?s=`` page of
``.listupd .bs .bsx`` cards; no results is one exact "No encontrado" notice
under a heading that names the query. A series page lists its chapters in
``#chapterlist``: ``data-num`` is the number, and the label is "Capítulo N" with
an optional " - title". Dates are Spanish ("11 de diciembre de 2024"). Chapter
pages live under a dated path (/2024/12/11/<slug>/).

Reader pages are in the ``ts_reader.run({...})`` call, in served order. When
``#readerarea`` also lists images, the two must agree.

Only freely readable chapters are read: a row without a link or with a lock,
coin or premium class raises, and so does a reader marked protected or holding
an unlock value. Novels and titles whose own genres mark them as adult are
refused.
"""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup

from .base import Chapter, Manga
from .mangathemesia_sites import (
    _TS_READER,
    MangaThemesiaSite,
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)

_ROW_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_ROW_LABEL = re.compile(r"^Capítulo (\d+(?:\.\d+)?)(?: - (.+))?$")
_ROW_DATE = re.compile(r"^(\d{1,2}) de (\S+) de (\d{4})$")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_CHAPTER_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COVER = re.compile(
    r"^https://(?:uchuujinmangas\.com/wp-content/uploads|img\.uchuujinmangas\.com)"
    r"/\d{4}/\d{2}/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NOVEL_TYPES = frozenset({"novel", "novela"})
_NO_RESULTS = "No encontrado"

_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 20000


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _row_date(text: str) -> Optional[str]:
    """A served Spanish date as YYYY-MM-DD, or None."""
    match = _ROW_DATE.match(text)
    month = _MONTHS.get(match.group(2)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def _has_paid_class(row) -> bool:
    return any(_PAID_CLASS.search(name)
               for element in [row, *row.find_all(True)]
               for name in element.get("class") or [])


def _cover(url) -> Optional[str]:
    url = url.strip() if isinstance(url, str) else ""
    return url if _COVER.match(url) else None


class UchuujinScraper(MangaThemesiaSite):
    """Scraper for Uchuujin (uchuujinmangas.com)."""

    name = "uchuujin"
    base_url = "https://uchuujinmangas.com"
    content_language = "es"  # Spanish-language site
    nsfw = False  # titles with an adult genre are refused

    _site_hosts = frozenset({"uchuujinmangas.com"})
    _series_dirs = ("manga",)
    _trailing_slash = True
    _search_path = "/"
    _image_hosts = frozenset({"uchuujinmangas.com"})
    _image_path_prefix = "/wp-content/uploads/"

    def __init__(self):
        super().__init__()
        # Series whose own genres were checked; worker copies share this set.
        self._cleared: Set[str] = set()

    def _chapter_url(self, url: str) -> str:
        """A chapter page: /YYYY/MM/DD/<slug>/."""
        segments = self._own_segments(url)
        if (len(segments) != 4 or not re.fullmatch(r"\d{4}", segments[0])
                or not re.fullmatch(r"\d{2}", segments[1])
                or not re.fullmatch(r"\d{2}", segments[2])
                or not _CHAPTER_SLUG.match(segments[3])):
            raise MangaThemesiaUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return self._canonical(segments)

    def _image_path(self, url) -> Optional[str]:
        path = super()._image_path(url)
        return None if path is None or urlsplit(url).query else path

    # Search

    @staticmethod
    def _is_no_results(soup: BeautifulSoup, query: str) -> bool:
        """True only for the search page saying this query found nothing."""
        wanted = " ".join(query.split())
        headings = soup.select("h1")
        lists = soup.select(".listupd")
        if len(headings) != 1 or len(lists) != 1 or soup.select(".bs, article"):
            return False
        if _text(headings[0]) != f"Buscar '{wanted}'":
            return False
        echoes = {" ".join((box.get("value") or "").split())
                  for box in soup.select('input[name="s"]')} - {""}
        if echoes != {wanted}:
            return False
        notices = lists[0].select("center > h3")
        return (len(notices) == 1 and _text(notices[0]) == _NO_RESULTS
                and _text(lists[0]) == _NO_RESULTS)

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search, without novels."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}{self._search_path}?s={quote_plus(query)}"
        soup = BeautifulSoup(self._fetch(url, "search").text, "html.parser")
        cards = soup.select(".listupd .bs .bsx")
        if not cards:
            if self._is_no_results(soup, query):
                return []
            raise MangaThemesiaSourceError(
                f"{self.name} search {url} did not serve a result list")
        if any(_text(notice) == _NO_RESULTS for notice in soup.select(".listupd center > h3")):
            raise MangaThemesiaSourceError(
                f"{self.name} search {url} served results and a no-results notice")

        results: List[Manga] = []
        seen = set()
        for card in cards:
            link = card.select_one("a[href][title]")
            title = (link.get("title") or "").strip() if link else ""
            if not title:
                raise MangaThemesiaSourceError(
                    f"{self.name} search {url} lists a result without its link or title")
            try:
                series_url = self._series_url(link["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} search {url} lists a result that is not a series") from None
            if series_url in seen:
                raise MangaThemesiaSourceError(
                    f"{self.name} search {url} lists {series_url} twice")
            seen.add(series_url)
            kinds = {name.casefold() for badge in card.select("span.type")
                     for name in badge.get("class") or []}
            if kinds & _NOVEL_TYPES:
                continue
            image = card.select_one("img[src]")
            results.append(Manga(title=title, url=series_url,
                                 cover_url=_cover(image["src"]) if image else None))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for novels and adult titles."""
        soup = BeautifulSoup(self._fetch(series_url, "series page").text, "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if (len(soup.select("h1.entry-title")) != 1 or len(canonical) != 1
                or canonical[0].get("href") != series_url):
            raise MangaThemesiaSourceError(f"{self.name} page {series_url} is not a series page")
        for chip in soup.select("span.mgen a"):
            if _text(chip).casefold() in _ADULT_GENRES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as adult; adult titles are not supported")
        for fact in soup.select(".imptdt"):
            label, _, value = _text(fact).partition(" ")
            if label == "Tipo" and value.casefold() in _NOVEL_TYPES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as a novel; only comics are supported")
        self._cleared.add(series_url)
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every chapter of a series, oldest first."""
        series_url = self._series_url(manga_url)
        soup = self._series_page(series_url)
        lists = soup.select("#chapterlist")
        rows = lists[0].select("li") if len(lists) == 1 else []
        if not rows:
            raise MangaThemesiaSourceError(f"{self.name} series page {series_url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists more chapters than this source reads")

        chapters: Dict[str, Chapter] = {}
        urls = set()
        for row in rows:
            link = row.find("a", href=True)
            if link is None or _has_paid_class(row):
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a locked or paid chapter; "
                    f"this source reads free chapters only")
            raw = (row.get("data-num") or "").strip()
            label = row.select_one(".chapternum")
            match = _ROW_LABEL.match(_text(label)) if label else None
            served_date = row.select_one(".chapterdate")
            published = _row_date(_text(served_date)) if served_date else None
            if (not _ROW_NUMBER.match(raw) or match is None or match.group(1) != raw
                    or published is None):
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a malformed chapter row")
            try:
                url = self._chapter_url(link["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links chapter {raw} elsewhere") from None
            number = format(Decimal(raw).normalize(), "f")
            if number in chapters or url in urls:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} lists chapter {number} twice")
            urls.add(url)
            chapters[number] = Chapter(number=number, title=match.group(2), url=url,
                                       date=published)
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            image = self._series_page(self._series_url(manga_url)).select_one(".thumb img[src]")
            return _cover(image["src"]) if image else None
        except Exception:
            return None

    # Pages

    def _reader_images(self, html: str, chapter_url: str) -> list:
        def refused(why: str):
            return MangaThemesiaSourceError(f"{self.name} chapter {chapter_url} {why}")

        soup = BeautifulSoup(html or "", "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if len(canonical) != 1 or canonical[0].get("href") != chapter_url:
            raise refused("answered for another page")
        links = soup.select(".allc a[href]")
        if len(links) != 1:
            raise refused("does not name its series")
        try:
            series_url = self._series_url(links[0]["href"].strip())
        except MangaThemesiaUnsupportedError:
            raise refused("names a series elsewhere") from None
        if series_url not in self._cleared:
            self._series_page(series_url)

        calls = list(_TS_READER.finditer(html or ""))
        if len(calls) != 1:
            raise refused(f"has {len(calls)} reader page lists, not one")
        try:
            data, _ = json.JSONDecoder().raw_decode(html, calls[0].end())
        except ValueError:
            raise refused("has a reader page list that is not JSON") from None
        if not isinstance(data, dict):
            raise refused("has a reader page list that is not an object")
        if (data.get("protected") is not False or data.get("is_novel") is not False
                or any(key.startswith("unlock") and value is not None
                       for key, value in data.items())):
            raise refused("is protected, locked or not a comic")
        sources = data.get("sources")
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise refused("does not have one image source")
        images = sources[0].get("images")
        if not isinstance(images, list):
            raise refused("has a reader source without images")
        served = [image.get("src") for image in soup.select("#readerarea img")]
        if served and served != images:
            raise refused("lists different pages in its reader area")
        return images

    # Images

    def download_image(self, url: str, path) -> bool:
        """Save one page; a failure leaves no file at ``path``."""
        saved = super().download_image(url, path)
        if not saved:
            Path(path).unlink(missing_ok=True)
        return saved
