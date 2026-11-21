"""
Serein Scan scraper - Turkish manhwa reader
Site: sereinscan.com

The site runs the WordPress "MangaThemesia" theme. Search is the ``?s=`` page
of ``.listupd .bs .bsx`` cards, and a series page lists its chapters in
``#chapterlist``. A row's ``data-num`` is a number that may carry a suffix
("214 - FİNAL", "187 - 5. Sezon Finali", "0 - Promo"). The number is kept and
the suffix becomes the chapter title, so finales and promos stay listed. Dates
are Turkish ("Ocak 27, 2024").

Reader pages are in the ``ts_reader.run({...})`` call and ``#readerarea`` is
empty in the served HTML. They are read in the order served.

Only freely readable chapters are read: a row without a link or with a lock,
coin or premium class raises. A title whose own genres mark it as adult is
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

_ROW_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)(?: - (FİNAL|\d+\. Sezon Finali|Promo))?$")
_ROW_DATE = re.compile(r"^(\S+) (\d{1,2}), (\d{4})$")
_MONTHS = {
    "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6,
    "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12,
}
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({
    "yetişkin", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NO_RESULTS = "Not Found"

_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 20000


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _row_date(text: str) -> Optional[str]:
    """A served Turkish date as YYYY-MM-DD, or None."""
    match = _ROW_DATE.match(text)
    month = _MONTHS.get(match.group(1)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _has_paid_class(row) -> bool:
    return any(_PAID_CLASS.search(name)
               for element in [row, *row.find_all(True)]
               for name in element.get("class") or [])


class SereinScanScraper(MangaThemesiaSite):
    """Scraper for Serein Scan (sereinscan.com)."""

    name = "sereinscan"
    base_url = "https://sereinscan.com"
    content_language = "tr"  # Turkish-language site
    nsfw = False  # titles with an adult genre are refused

    _site_hosts = frozenset({"sereinscan.com"})
    _series_dirs = ("manga",)
    _trailing_slash = True
    _search_path = "/"
    _image_hosts = frozenset({"sereinscan.com"})
    _image_path_prefix = "/wp-content/uploads/"

    def __init__(self):
        super().__init__()
        # Series whose own genres were checked; worker copies share this set.
        self._cleared: Set[str] = set()

    def _image_path(self, url) -> Optional[str]:
        path = super()._image_path(url)
        return None if path is None or urlsplit(url).query else path

    # Search

    @staticmethod
    def _is_no_results(soup: BeautifulSoup, query: str) -> bool:
        """True only for the search page saying this query found nothing."""
        headings = soup.select("h1")
        lists = soup.select(".listupd")
        if len(headings) != 1 or len(lists) != 1 or soup.select(".bs, article"):
            return False
        expected = "Search '" + " ".join(query.split()) + "'"
        if _text(headings[0]).casefold() != expected.casefold():
            return False
        notices = lists[0].select("center > h3")
        return (len(notices) == 1 and _text(notices[0]) == _NO_RESULTS
                and _text(lists[0]) == _NO_RESULTS)

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's search."""
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
            image = card.select_one("img[src]")
            cover = image["src"].strip() if image else None
            results.append(Manga(title=title, url=series_url,
                                 cover_url=cover if self._image_path(cover) else None))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused when its own genres mark it as adult."""
        soup = BeautifulSoup(self._fetch(series_url, "series page").text, "html.parser")
        if len(soup.select("h1.entry-title")) != 1:
            raise MangaThemesiaSourceError(f"{self.name} page {series_url} is not a series page")
        for chip in soup.select("span.mgen a"):
            if _text(chip).casefold() in _ADULT_GENRES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as adult; adult titles are not supported")
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
            raw = " ".join((row.get("data-num") or "").split())
            match = _ROW_NUMBER.match(raw)
            label = row.select_one(".chapternum")
            served_date = row.select_one(".chapterdate")
            published = _row_date(_text(served_date)) if served_date else None
            if not match or not label or _text(label) != f"Chapter {raw}" or published is None:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a malformed chapter row")
            try:
                url = self._chapter_url(link["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links chapter {raw} elsewhere") from None
            number = format(Decimal(match.group(1)).normalize(), "f")
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
            cover = image["src"].strip() if image else None
            return cover if self._image_path(cover) else None
        except Exception:
            return None

    # Pages

    def _reader_images(self, html: str, chapter_url: str) -> list:
        def refused(why: str):
            return MangaThemesiaSourceError(f"{self.name} chapter {chapter_url} {why}")

        links = BeautifulSoup(html or "", "html.parser").select(".allc a[href]")
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
        sources = data.get("sources") if isinstance(data, dict) else None
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise refused("does not have one image source")
        images = sources[0].get("images")
        if not isinstance(images, list):
            raise refused("has a reader source without images")
        return images

    # Images

    def download_image(self, url: str, path) -> bool:
        """Save one page; a failure leaves no file at ``path``."""
        saved = super().download_image(url, path)
        if not saved:
            Path(path).unlink(missing_ok=True)
        return saved
