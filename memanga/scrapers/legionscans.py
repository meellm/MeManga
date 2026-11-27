"""
Legion Scans scraper - Spanish manga, manhwa and manhua scans
Site: legionscans.com/wp

The site runs the WordPress "MangaThemesia" theme under the /wp path.
Search is the catalogue's ``?title=`` filter, a list of ``.listupd .bs .bsx``
cards; no results is a list holding only "-- No Post Found --". A series page
lists its chapters in ``#chapterlist``, and each chapter page lives under a
dated path (/wp/2024/03/12/<slug>/) whose slug does not always match the label.

Numbered rows read "Chapter N", optionally followed by " - <text>". Rows
labelled as extras ("Chapter Extra", "Chapter EX15", "Chapter ex15") carry no
chapter number; they are left out of the list with a warning that counts them,
so no extra is shown under the number of a regular chapter. Any other row form
raises.

Reader pages are in the ``ts_reader.run({...})`` call, in served order, on the
wp.com image proxy. Only freely readable chapters are read: a row without a link
or with a lock, coin or premium class raises, and so does a reader marked
protected or holding an unlock value. Novels and titles whose own genres mark
them as adult are refused.
"""

import json
import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from .base import Chapter, Manga, _identifies_as_image
from .mangathemesia_sites import (
    _TS_READER,
    MangaThemesiaSite,
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)

logger = logging.getLogger(__name__)

_SITE_ROOT = "https://legionscans.com"
_PATH_PREFIX = "wp"
_NUMBERED_LABEL = re.compile(r"^Chapter (\d+)(?: - (.+))?$")
_EXTRA_NUM = re.compile(r"^(?:extra|ex)\d*$", re.I)
_ROW_DATE = re.compile(r"^(\S+) (\d{1,2}), (\d{4})$")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_CHAPTER_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PAGE_PATH = re.compile(
    r"^/imagizer\.imageshack\.com/v2/[A-Za-z0-9]+/\d+/[A-Za-z0-9]+\.(?:png|jpe?g|webp)$")
_COVER = re.compile(
    r"^https://i[0-3]\.wp\.com/legionscans\.com/wp/wp-content/uploads/\d{4}/\d{2}/"
    r"[^/?#\s]+\.(?:jpe?g|png|webp)(?:\?resize=\d+,\d+)?$", re.I)
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NOVEL_TYPES = frozenset({"novel", "novela"})
_NO_RESULTS = "-- No Post Found --"
_LIST_HEADING = "Manga Lists"

_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 20000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _row_date(text: str) -> Optional[str]:
    """A served Spanish date ("noviembre 19, 2026") as YYYY-MM-DD, or None."""
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


def _cover(url) -> Optional[str]:
    url = url.strip() if isinstance(url, str) else ""
    return url if _COVER.match(url) else None


class LegionScansScraper(MangaThemesiaSite):
    """Scraper for Legion Scans (legionscans.com/wp)."""

    name = "legionscans"
    base_url = f"{_SITE_ROOT}/{_PATH_PREFIX}"
    content_language = "es"  # Spanish-language site
    nsfw = False  # titles with an adult genre are refused

    _site_hosts = frozenset({"legionscans.com"})
    _series_dirs = ("manga",)
    _trailing_slash = True
    _image_hosts = frozenset({"i0.wp.com", "i1.wp.com", "i2.wp.com", "i3.wp.com"})
    _image_path_prefix = "/imagizer.imageshack.com/"
    _IMAGE_HEADERS = {"Referer": f"{_SITE_ROOT}/"}

    def __init__(self):
        super().__init__()
        # Series whose own genres were checked; worker copies share this set.
        self._cleared: Set[str] = set()

    # URLs

    def _own_segments(self, url: str) -> List[str]:
        """The path segments after /wp of a URL on this site."""
        segments = super()._own_segments(url)
        if len(segments) < 2 or segments[0] != _PATH_PREFIX:
            raise MangaThemesiaUnsupportedError(f"Not a {self.name} page: {url!r}")
        return segments[1:]

    def _chapter_url(self, url: str) -> str:
        """A chapter page: /wp/YYYY/MM/DD/<slug>/."""
        segments = self._own_segments(url)
        if (len(segments) != 4 or not re.fullmatch(r"\d{4}", segments[0])
                or not re.fullmatch(r"\d{2}", segments[1])
                or not re.fullmatch(r"\d{2}", segments[2])
                or not _CHAPTER_SLUG.match(segments[3])):
            raise MangaThemesiaUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return self._canonical(segments)

    def _image_path(self, url) -> Optional[str]:
        path = super()._image_path(url)
        if path is None or urlsplit(url).query or not _PAGE_PATH.match(path):
            return None
        return path

    # Search

    @staticmethod
    def _is_no_results(soup: BeautifulSoup) -> bool:
        """True only for the catalogue page saying the filter found nothing."""
        headings = soup.select("h1")
        lists = soup.select(".listupd")
        if (len(headings) != 1 or _text(headings[0]) != _LIST_HEADING
                or len(lists) != 1 or lists[0].select(".bs")):
            return False
        notices = lists[0].select("center.noresult")
        return (len(notices) == 1 and _text(notices[0]) == _NO_RESULTS
                and _text(lists[0]) == _NO_RESULTS and not lists[0].select("a"))

    def search(self, query: str) -> List[Manga]:
        """The first page of the catalogue filtered by title."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/manga/?title={quote(query, safe='')}&page=1"
        soup = BeautifulSoup(self._fetch(url, "search").text, "html.parser")
        lists = soup.select(".listupd")
        cards = lists[0].select(".bs .bsx") if len(lists) == 1 else []
        if not cards:
            if self._is_no_results(soup):
                return []
            raise MangaThemesiaSourceError(
                f"{self.name} search {url} did not serve a result list")
        if lists[0].select("center.noresult"):
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
            image = card.select_one("img[data-src]")
            results.append(Manga(title=title, url=series_url,
                                 cover_url=_cover(image["data-src"]) if image else None))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for novels and adult titles."""
        soup = BeautifulSoup(self._fetch(series_url, "series page").text, "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        if (len(soup.select("h1.entry-title")) != 1 or len(canonical) != 1
                or canonical[0].get("href") != series_url):
            raise MangaThemesiaSourceError(f"{self.name} page {series_url} is not a series page")
        for chip in soup.select(".seriestugenre a, .mgen a, div.gnr a"):
            if _text(chip).casefold() in _ADULT_GENRES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as adult; adult titles are not supported")
        for row in soup.select("table.infotable tr"):
            cells = [_text(cell) for cell in row.find_all("td")]
            if len(cells) == 2 and cells[0] == "Type" and cells[1].casefold() in _NOVEL_TYPES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as a novel; only comics are supported")
        self._cleared.add(series_url)
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every numbered chapter of a series, oldest first."""
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
        extras: List[str] = []
        for row in rows:
            links = row.select("a[href]")
            if len(links) != 1 or _has_paid_class(row):
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a locked or paid chapter; "
                    f"this source reads free chapters only")
            raw = (row.get("data-num") or "").strip()
            label = row.select_one(".chapternum")
            label_text = _text(label) if label else ""
            served_date = row.select_one(".chapterdate")
            published = _row_date(_text(served_date)) if served_date else None
            try:
                url = self._chapter_url(links[0]["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links chapter {raw!r} elsewhere") from None
            if published is None:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a malformed chapter row")
            if url in urls:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links {url} twice")
            urls.add(url)

            match = _NUMBERED_LABEL.match(label_text)
            if raw.isdigit() and raw.isascii() and match and match.group(1) == raw:
                number = format(Decimal(raw).normalize(), "f")
                if number in chapters:
                    raise MangaThemesiaSourceError(
                        f"{self.name} series page {series_url} lists chapter {number} twice")
                title = match.group(2)
                if title is not None and title.strip() == raw:
                    title = None
                chapters[number] = Chapter(number=number, title=title, url=url, date=published)
            elif _EXTRA_NUM.match(raw) and label_text == f"Chapter {raw}":
                extras.append(raw)
            else:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a malformed chapter row")

        if not chapters:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists no numbered chapters")
        if extras:
            logger.warning("%s: %d extra chapter row(s) of %s have no chapter number and "
                           "were not listed: %s", self.name, len(extras), series_url,
                           ", ".join(extras))
        return sorted(chapters.values())

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            soup = self._series_page(self._series_url(manga_url))
            for image in soup.select(".thumb img"):
                cover = _cover(image.get("src")) or _cover(image.get("data-src"))
                if cover:
                    return cover
            return None
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
        """Save one page, sent with the site root as Referer; a failure leaves
        no file at ``path``."""
        path = Path(path)
        try:
            if self._image_path(url) is None:
                raise MangaThemesiaSourceError(f"{self.name} refused a page URL: {url}")
            response = self._request(url, headers=self._IMAGE_HEADERS, allow_redirects=False)
            if response.status_code != 200:
                raise MangaThemesiaSourceError(f"{url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise MangaThemesiaSourceError(f"{url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise MangaThemesiaSourceError(f"{url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a Legion Scans page: %s", e)
            return False
