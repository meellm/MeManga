"""
Rakuen Translations scraper - Spanish manga scans
Site: rakuentranslations.com

The site runs the WordPress "MangaThemesia" theme:

* search   -> the catalogue's ``/manga/?title=`` filter, a list of
              ``.listupd .bs .bsx`` cards; no results is a list holding only
              "-- No se encontraron publicaciones --".
* chapters -> the series page lists ``#chapterlist li`` rows labelled
              "Capítulo N" or "Capítulo N.M" with a matching ``data-num``
              (zero-padded for low numbers: "001", "09"). Chapter pages sit
              at the site root under slugs that do not always match the label.
* pages    -> the reader's ``ts_reader.run({...})`` call, in served order,
              on the i0-i3.wp.com image proxy, matching the reader area's
              own image list.

A chapter number served by more than one row with different links lists none
of those rows: one warning counts and names them with their links, and no
row is preferred. Any row form other than a numbered "Capítulo" raises.

A reader must name its chapter and its series: its page, post and chapter
identifiers, the series link and the title heading must all agree with the
series page and its listed row.

The catalogue mixes adult titles with others, so the source is marked NSFW;
titles whose own genres mark them as adult, and novels, are refused.
"""

import json
import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import Chapter, Manga, _identifies_as_image
from .mangathemesia_sites import (
    _TS_READER,
    MangaThemesiaSite,
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)

logger = logging.getLogger(__name__)

_HOST = "rakuentranslations.com"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATA_NUM = re.compile(r"^(\d+)(?:\.(\d+))?$")
_ROW_DATE = re.compile(r"^(\S+) (\d{1,2}), (\d{4})$")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_PAGE_PATH = re.compile(
    rf"^/{re.escape(_HOST)}/wp-content/uploads/\d{{4}}/\d{{2}}/[^/?#\s]+\.(?:jpe?g|png|webp)$",
    re.I)
_COVER = re.compile(
    rf"^https://i[0-3]\.wp\.com/{re.escape(_HOST)}/wp-content/uploads/\d{{4}}/\d{{2}}/"
    r"[^/?#\s]+\.(?:jpe?g|png|webp)(?:\?resize=\d+,\d+)?$", re.I)
_POST_ID = re.compile(r"^post-(\d+)$")
_SHORTLINK = re.compile(rf"^https://{re.escape(_HOST)}/\?p=(\d+)$")
_HEADING = re.compile(r"^(.+) cap[ií]tulo (\S+)$", re.I)
_ITEM_KEY = re.compile(r'"item"\s*:\s*(?=\{)')
_PAID_CLASS = re.compile(r"(?:^|[-_])(?:locked|lock|coins?|premium|vip|paid)(?:$|[-_])", re.I)
_ADULT_GENRES = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NOVEL_TYPES = frozenset({"novel", "novela"})
_NO_RESULTS = "-- No se encontraron publicaciones --"
_LIST_HEADING = "Lista de mangas"

_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _row_date(text: str) -> Optional[str]:
    """A served Spanish date ("noviembre 25, 2026") as YYYY-MM-DD, or None."""
    match = _ROW_DATE.match(text)
    month = _MONTHS.get(match.group(1)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _number(raw: str) -> Optional[str]:
    """A served chapter number without the zero padding of its whole part
    ("001" -> "1", "09" -> "9"); its decimal digits are kept as served."""
    match = _DATA_NUM.match(raw) if raw.isascii() else None
    if not match:
        return None
    whole = str(int(match.group(1)))
    return f"{whole}.{match.group(2)}" if match.group(2) is not None else whole


def _has_paid_class(row) -> bool:
    return any(_PAID_CLASS.search(name)
               for element in [row, *row.find_all(True)]
               for name in element.get("class") or [])


def _cover(url) -> Optional[str]:
    url = url.strip() if isinstance(url, str) else ""
    return url if _COVER.match(url) else None


def _post_id(soup: BeautifulSoup) -> Optional[str]:
    """The page's own post id, where its one article and its shortlink agree."""
    articles = soup.select("article[id]")
    shortlinks = soup.select('link[rel="shortlink"]')
    article = _POST_ID.match(articles[0]["id"]) if len(articles) == 1 else None
    short = _SHORTLINK.match(shortlinks[0].get("href") or "") if len(shortlinks) == 1 else None
    if article and short and article.group(1) == short.group(1):
        return article.group(1)
    return None


class RakuenTranslationsScraper(MangaThemesiaSite):
    """Scraper for Rakuen Translations (rakuentranslations.com)."""

    name = "rakuentranslations"
    base_url = f"https://{_HOST}"
    content_language = "es"  # Spanish-language site
    nsfw = True  # the catalogue holds adult titles; those are refused here

    _site_hosts = frozenset({_HOST})
    _series_dirs = ("manga",)
    _trailing_slash = True
    _image_hosts = frozenset({"i0.wp.com", "i1.wp.com", "i2.wp.com", "i3.wp.com"})
    _image_path_prefix = f"/{_HOST}/wp-content/uploads/"
    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: each checked series' title and post id,
        # and the series and served number of each listed chapter.
        self._series: Dict[str, Tuple[str, str]] = {}
        self._listed: Dict[str, Tuple[str, str]] = {}

    # URLs

    def _chapter_url(self, url: str) -> str:
        """A chapter page: /<slug>/ at the site root."""
        segments = self._own_segments(url)
        if len(segments) != 1 or segments[0] in self._series_dirs or not _SLUG.match(segments[0]):
            raise MangaThemesiaUnsupportedError(f"Not a {self.name} chapter page: {url!r}")
        return self._canonical(segments)

    def _series_url(self, url: str) -> str:
        series_url = super()._series_url(url)
        if not _SLUG.match(self._own_segments(series_url)[1]):
            raise MangaThemesiaUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return series_url

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
        """The first page of the catalogue filtered by title, without novels."""
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
        if any(card.select_one(".bsx") for card in cards):
            raise MangaThemesiaSourceError(f"{self.name} search {url} nests result cards")

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
        headings = soup.select("article h1.entry-title")
        post_id = _post_id(soup)
        if (len(canonical) != 1 or canonical[0].get("href") != series_url
                or len(soup.select("h1.entry-title")) != 1 or len(headings) != 1
                or not _text(headings[0]) or post_id is None):
            raise MangaThemesiaSourceError(f"{self.name} page {series_url} is not a series page")
        article = soup.select_one("article[id]")
        # The title's own genres and type only, not those of other titles
        # the page lists beside it.
        for chip in article.select(".mgen a"):
            if _text(chip).casefold() in _ADULT_GENRES:
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as adult; adult titles are not supported")
        for row in article.select(".tsinfo .imptdt"):
            words = _text(row).split(" ", 1)
            if (len(words) == 2 and words[0] in ("Tipo", "Type")
                    and words[1].casefold() in _NOVEL_TYPES):
                raise MangaThemesiaSourceError(
                    f"{self.name} lists {series_url} as a novel; only comics are supported")
        self._series[series_url] = (_text(headings[0]), post_id)
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The numbered chapters of a series, oldest first."""
        series_url = self._series_url(manga_url)
        soup = self._series_page(series_url)
        lists = soup.select("#chapterlist")
        rows = lists[0].select("li") if len(lists) == 1 else []
        if not rows:
            raise MangaThemesiaSourceError(f"{self.name} series page {series_url} lists no chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists more chapters than this source reads")

        by_value: Dict[Decimal, List[Tuple[str, str, str, Optional[str]]]] = {}
        urls = set()
        for row in rows:
            links = row.select("a[href]")
            if len(links) != 1 or _has_paid_class(row):
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a locked or paid chapter; "
                    f"this source reads free chapters only")
            raw = (row.get("data-num") or "").strip()
            label = row.select_one(".chapternum")
            label_text = _text(label) if label else ""
            try:
                url = self._chapter_url(links[0]["href"].strip())
            except MangaThemesiaUnsupportedError:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links chapter {raw!r} elsewhere") from None
            if url in urls:
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} links {url} twice")
            urls.add(url)
            number = _number(raw)
            if number is None or label_text != f"Capítulo {raw}":
                raise MangaThemesiaSourceError(
                    f"{self.name} series page {series_url} has a chapter row in an unknown "
                    f"form: {label_text!r}")
            served_date = row.select_one(".chapterdate")
            published = _row_date(_text(served_date)) if served_date else None
            by_value.setdefault(Decimal(number), []).append((raw, number, url, published))

        chapters: List[Chapter] = []
        repeated: List[str] = []
        for entries in by_value.values():
            if len(entries) > 1:
                repeated.append(f"{entries[0][1]} ({', '.join(url for _, _, url, _ in entries)})")
                continue
            raw, number, url, published = entries[0]
            chapters.append(Chapter(number=number, title=None, url=url, date=published))
            self._listed[url] = (series_url, raw)
        if repeated:
            logger.warning(
                "%s: %d chapter number(s) of %s are served by more than one row with "
                "different links and none of those rows is listed: %s",
                self.name, len(repeated), series_url, "; ".join(repeated))
        if not chapters:
            raise MangaThemesiaSourceError(
                f"{self.name} series page {series_url} lists no numbered chapters")
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            soup = self._series_page(self._series_url(manga_url))
            image = soup.select_one("article .thumb img[src]")
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
        crumbs = [link.get("href", "").strip()
                  for link in soup.select(".ts-breadcrumb a[href]")]
        if crumbs[1:] != [series_url, chapter_url]:
            raise refused("does not name this chapter and its series")
        if chapter_url not in self._listed:
            self.get_chapters(series_url)
        listed = self._listed.get(chapter_url)
        if listed is None or listed[0] != series_url:
            raise refused("is not a chapter the series lists")
        raw = listed[1]
        series_title, series_id = self._series[series_url]

        post_id = _post_id(soup)
        headings = soup.select("article h1.entry-title")
        heading = _HEADING.match(_text(headings[0])) if len(headings) == 1 else None
        if (post_id is None or heading is None or heading.group(1) != series_title
                or heading.group(2) != raw or _text(links[0]) != series_title):
            raise refused("does not name this chapter and its series")
        items = list(_ITEM_KEY.finditer(html))
        try:
            item = json.JSONDecoder().raw_decode(html, items[0].end())[0] if len(items) == 1 else None
        except ValueError:
            item = None
        if (not isinstance(item, dict) or str(item.get("mid")) != series_id
                or str(item.get("cid")) != post_id or item.get("c") != raw):
            raise refused("does not name this chapter and its series")

        calls = list(_TS_READER.finditer(html))
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
        if str(data.get("post_id")) != post_id:
            raise refused("does not name this chapter and its series")
        sources = data.get("sources")
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise refused("does not have one image source")
        images = sources[0].get("images")
        if not isinstance(images, list) or not all(isinstance(image, str) for image in images):
            raise refused("has a reader source without images")
        # The reader area lists the same pages, in a <noscript> block.
        areas = soup.select("#readerarea")
        served = [image.get("src") for image in areas[0].select("img")] if len(areas) == 1 else []
        if served != images:
            raise refused("lists different pages in its reader area")
        return images

    # Images

    def download_image(self, url: str, path) -> bool:
        """Save one page as served, sent with the site root as Referer; a
        failure leaves no file at ``path``."""
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
            logger.debug("Failed to download a Rakuen Translations page: %s", e)
            return False
