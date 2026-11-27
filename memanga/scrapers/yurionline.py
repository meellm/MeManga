"""
Yuri-Online scraper - Spanish yuri manga scans
Site: yuri-online.com

The site runs the WordPress "Madara" theme with series under /manga/:

* search   -> POST /wp-admin/admin-ajax.php with ``action=madara_load_more``
              returns ``div.page-item-detail`` cards; no results is an empty
              body. Cards badged "18+" are left out.
* chapters -> POST <series>/ajax/chapters/ returns ``li.wp-manga-chapter``
              rows labelled "Capítulo N" or "Capítulo N.M", linked as
              /manga/<series>/capitulo-N[-M]/. Dates read "noviembre 20, 2026"; the
              newest row may show only a relative "new" tag, which gives no
              date.
* pages    -> the reader lists ``.reading-content div.page-break img`` with the
              image in ``data-src``, in reader order, under the site's own
              /__img/ path.

Rows labelled "Extra ..." carry no chapter number and are left out with one
warning that counts and names them. A number served twice with different
links lists neither row. Any other label raises.

The catalogue includes adult titles, and not all of them carry a badge, so
the source is marked NSFW: a title whose own genres or tags mark it as adult,
or that asks to confirm adult content, is refused before its chapters are
read, and so are novels. A chapter row showing a lock, price or other access
control, or a reader asking to log in, is refused.
"""

import json
import logging
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from ..chapters import chapter_order_key
from .base import (
    BaseScraper,
    Chapter,
    Manga,
    _identifies_as_image,
    _retry,
    is_retryable_request_error,
)

logger = logging.getLogger(__name__)

_HOST = "yuri-online.com"
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/manga/({_SLUG})/({_SLUG})/?$")
_RESERVED_SLUGS = frozenset({"page", "feed"})
_IMAGE_PATH = re.compile(
    r"^/__img/(manga_[0-9a-f]+)/([0-9a-f]{32})/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_COVER_PATH = re.compile(r"^/wp-content/uploads/\d{4}/\d{2}/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)

_LABEL_NUMBERED = re.compile(r"^Capítulo ([0-9]+)(?:\.([0-9]+))?$")
_LABEL_EXTRA = re.compile(r"^Extra(?: Volumen [0-9]+)?$")
_MONTH_DATE = re.compile(r"^([a-z]+) ([0-9]{1,2}), ([0-9]{4})$")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}
_POST_ID = re.compile(r"^postid-([0-9]+)$")
_SHORTLINK = re.compile(rf"^https://{re.escape(_HOST)}/\?p=([0-9]+)$")
_INLINE_MANGA = re.compile(r"\bvar manga = (?=\{)")
_ADULT_WORDS = frozenset({
    "adultos", "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_NOVEL_TYPES = frozenset({"novela", "novel", "novela ligera", "light novel"})
_ACCESS_WORDS = re.compile(
    r"\b(?:premium|vip|bloquead[oa]s?|desbloque\w*|candado|locked|comprar|precio|"
    r"monedas?|coins?|puntos|patreon|ko-?fi|suscr[ií]\w*|acceso anticipado|"
    r"anticipad[oa]s?|adelantad[oa]s?|iniciar sesi[oó]n|inicia sesi[oó]n)\b", re.I)
_TYPE_HEADING = "Tipo de obra"

# The search form the site's own archive sends; only the query is added.
_SEARCH_FORM: Tuple[Tuple[str, str], ...] = (
    ("action", "madara_load_more"),
    ("page", "0"),
    ("template", "madara-core/content/content-archive"),
    ("vars[paged]", "1"),
    ("vars[template]", "archive"),
    ("vars[posts_per_page]", "25"),
    ("vars[post_type]", "wp-manga"),
    ("vars[post_status]", "publish"),
    ("vars[manga_archives_item_layout]", "big_thumbnail"),
    ("vars[meta_query][0][key]", "_wp_manga_chapter_type"),
    ("vars[meta_query][0][value]", "manga"),
)

_MAX_SEARCH_RESULTS = 25
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class YuriOnlineSourceError(RuntimeError):
    """yuri-online.com answered with a page this scraper cannot use."""


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def _site_path(url) -> Optional[str]:
    """The path of a URL on this site (with or without "www."), or None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme not in ("http", "https")
            or (parts.hostname or "").lower() not in (_HOST, f"www.{_HOST}")
            or port is not None or "@" in parts.netloc or parts.query or parts.fragment):
        return None
    return parts.path


def _own_url(url, pattern) -> Optional[str]:
    """``url``, stripped of surrounding whitespace, when it is an https URL of
    this site whose path matches ``pattern``."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.hostname != _HOST or port is not None
            or "@" in parts.netloc or parts.query or parts.fragment
            or ".." in parts.path.split("/") or not pattern.match(parts.path)
            or any(char.isspace() for char in url)):
        return None
    return url


def _row_date(text: str) -> Optional[str]:
    """A served Spanish date ("noviembre 20, 2026") as YYYY-MM-DD, or None."""
    match = _MONTH_DATE.match(text)
    month = _MONTHS.get(match.group(1)) if match else None
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _badges(element) -> Set[str]:
    words = set()
    for badge in element.select(".manga-title-badges"):
        words.add(_text(badge).casefold())
        words.update(name.casefold() for name in badge.get("class") or [])
    return words


def _post_id(soup: BeautifulSoup) -> Optional[str]:
    body = soup.find("body")
    ids = [match.group(1) for match in
           (_POST_ID.match(name) for name in (body.get("class") or [] if body else []))
           if match]
    return ids[0] if len(ids) == 1 else None


def _access_control(row, chapter_url: str) -> Optional[str]:
    """What in a chapter row's visible content controls access, or None.

    Class names and hidden elements are not read; forms and buttons, links
    other than the row's own chapter link (its "new" tag links there too),
    and visible wording about payment, locks or early access count.
    """
    visible = BeautifulSoup(str(row), "html.parser")
    for element in visible.find_all(True):
        if not element.decomposed and (
                element.has_attr("hidden") or element.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none", element.get("style") or "", re.I)):
            element.decompose()
    if visible.select("form, input, button, select, textarea"):
        return "a form or button"
    for link in visible.select("a[href]"):
        if link["href"].strip() != chapter_url:
            return f"a link to {link['href'].strip()}"
    texts = [_text(visible)] + [image.get(name) or "" for image in visible.find_all("img")
                                for name in ("alt", "title")]
    match = _ACCESS_WORDS.search(" ".join(texts))
    return f"the words {match.group(0)!r}" if match else None


class YuriOnlineScraper(BaseScraper):
    """Scraper for Yuri-Online (yuri-online.com)."""

    name = "yurionline"
    base_url = f"https://{_HOST}"
    content_language = "es"  # Spanish-language site
    nsfw = True  # the catalogue holds adult titles; those found marked adult are refused

    _AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: each checked series' title and post id,
        # and the series, chapter slug and label of each listed chapter.
        self._series: Dict[str, Tuple[str, str]] = {}
        self._listed: Dict[str, Tuple[str, str, str]] = {}

    # URLs

    def _series_parts(self, url) -> Tuple[str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match or match.group(1) in _RESERVED_SLUGS:
            raise YuriOnlineSourceError(f"Not a Yuri-Online series URL: {url}")
        return f"{self.base_url}/manga/{match.group(1)}/", match.group(1)

    def _chapter_parts(self, url) -> Tuple[str, str, str]:
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match or match.group(1) in _RESERVED_SLUGS:
            raise YuriOnlineSourceError(f"Not a Yuri-Online chapter URL: {url}")
        series, chapter = match.groups()
        return f"{self.base_url}/manga/{series}/{chapter}/", series, chapter

    # Requests

    def _post(self, url: str, data=None, headers=None):
        """POST with the source's request spacing and retry rules, without
        following redirects."""
        def send():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()
            response = self.session.post(url, data=data, headers=headers, timeout=30,
                                         allow_redirects=False)
            response.raise_for_status()
            return response

        return _retry(send, max_attempts=3, base_delay=1.0,
                      exceptions=(requests.RequestException,),
                      retry_if=is_retryable_request_error)

    def _checked(self, response, what: str, url: str):
        if response.status_code != 200:
            raise YuriOnlineSourceError(
                f"Yuri-Online answered HTTP {response.status_code} for {what} {url}")
        return response

    def _get(self, url: str, what: str) -> str:
        return self._checked(self._request(url, allow_redirects=False), what, url).text

    # Search

    def search(self, query: str) -> List[Manga]:
        """The first page of the site's archive search, without badged adult titles."""
        query = (query or "").strip()
        if not query:
            return []
        url = f"{self.base_url}/wp-admin/admin-ajax.php"
        headers = dict(self._AJAX_HEADERS, Referer=f"{self.base_url}/")
        response = self._checked(
            self._post(url, data=[*_SEARCH_FORM, ("vars[s]", query)], headers=headers),
            "search", url)
        if response.content == b"":
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("div.page-item-detail")
        if not rows:
            raise YuriOnlineSourceError(
                f"Yuri-Online search for {query!r} did not serve a result list")
        if any(row.select_one("div.page-item-detail") for row in rows):
            raise YuriOnlineSourceError(f"Yuri-Online search for {query!r} nests result rows")

        results: List[Manga] = []
        seen = set()
        for row in rows:
            link = row.select_one(".post-title a[href]")
            title = _text(link) if link else ""
            if not title:
                raise YuriOnlineSourceError(
                    f"Yuri-Online search for {query!r} lists a result without a title")
            try:
                series_url, _ = self._series_parts(link["href"])
            except YuriOnlineSourceError:
                raise YuriOnlineSourceError(
                    f"Yuri-Online search for {query!r} lists a result that is not a series"
                ) from None
            if series_url in seen:
                raise YuriOnlineSourceError(
                    f"Yuri-Online search for {query!r} lists {series_url} twice")
            seen.add(series_url)
            if _badges(row) & _ADULT_WORDS:
                continue
            image = row.select_one("img[data-src]")
            cover = _own_url(image["data-src"], _COVER_PATH) if image else None
            results.append(Manga(title=title, url=series_url, cover_url=cover))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str) -> BeautifulSoup:
        """A series page, refused for adult titles and novels."""
        soup = BeautifulSoup(self._get(series_url, "series page"), "html.parser")
        canonical = soup.select('link[rel="canonical"]')
        shortlinks = soup.select('link[rel="shortlink"]')
        short = _SHORTLINK.match(shortlinks[0].get("href") or "") if len(shortlinks) == 1 else None
        post_id = _post_id(soup)
        holders = soup.select("#manga-chapters-holder")
        headings = soup.select("div.post-title h1")
        if (len(canonical) != 1 or canonical[0].get("href") != series_url or post_id is None
                or short is None or short.group(1) != post_id or len(holders) != 1
                or holders[0].get("data-id") != post_id or len(headings) != 1
                or not _text(headings[0])):
            raise YuriOnlineSourceError(f"Yuri-Online page {series_url} is not a series page")
        if soup.select("#adult_modal"):
            raise YuriOnlineSourceError(
                f"Yuri-Online asks to confirm adult content for {series_url}; "
                f"adult titles are not supported")
        article = soup.select_one(f"div.post-{post_id}")
        scope = article if article is not None else soup
        words = {_text(link).casefold()
                 for link in scope.select("div.genres-content a, div.tags-content a")}
        words |= _badges(headings[0].parent)
        classes = {name for name in (article.get("class") or [] if article is not None else [])}
        if words & _ADULT_WORDS or "wp-manga-tag-adultos" in classes:
            raise YuriOnlineSourceError(
                f"Yuri-Online lists {series_url} as adult; adult titles are not supported")
        for item in scope.select(".post-content_item"):
            heading = item.select_one(".summary-heading")
            content = item.select_one(".summary-content")
            if (heading is not None and content is not None
                    and _text(heading).startswith(_TYPE_HEADING)
                    and _text(content).casefold() in _NOVEL_TYPES):
                raise YuriOnlineSourceError(
                    f"Yuri-Online lists {series_url} as a novel; only comics are supported")
        self._series[series_url] = (_text(headings[0]), post_id)
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The numbered chapters of a series, oldest first."""
        series_url, slug = self._series_parts(manga_url)
        self._series_page(series_url)
        ajax_url = f"{series_url.rstrip('/')}/ajax/chapters/"
        headers = dict(self._AJAX_HEADERS, Referer=series_url)
        response = self._checked(self._post(ajax_url, headers=headers), "chapter list", ajax_url)
        rows = BeautifulSoup(response.text, "html.parser").select("li.wp-manga-chapter")
        if not rows:
            raise YuriOnlineSourceError(f"Yuri-Online lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise YuriOnlineSourceError(f"Yuri-Online lists too many chapters for {slug}")

        by_number: Dict[Decimal, List[Tuple[str, str, str, str, Optional[str]]]] = {}
        extras: List[str] = []
        urls: Set[str] = set()
        for row in rows:
            links = row.select("a[href]")
            if not links:
                raise YuriOnlineSourceError(
                    f"Yuri-Online has a chapter row of {slug} without a link")
            label = _text(links[0])
            try:
                url, row_series, chapter_slug = self._chapter_parts(links[0]["href"])
            except YuriOnlineSourceError:
                raise YuriOnlineSourceError(
                    f"Yuri-Online links {label!r} of {slug} elsewhere") from None
            if row_series != slug:
                raise YuriOnlineSourceError(
                    f"Yuri-Online links {label!r} of {slug} to another series")
            control = _access_control(row, links[0]["href"].strip())
            if control is not None:
                raise YuriOnlineSourceError(
                    f"Yuri-Online has a locked or paid chapter row of {slug} ({control}); "
                    f"this source reads free chapters only")
            if url in urls:
                raise YuriOnlineSourceError(f"Yuri-Online links {url} twice for {slug}")
            urls.add(url)

            match = _LABEL_NUMBERED.match(label)
            if match:
                whole, part = match.groups()
                if chapter_slug != "-".join(["capitulo", whole] + ([part] if part else [])):
                    raise YuriOnlineSourceError(
                        f"Yuri-Online links {label!r} of {slug} to {url}, "
                        f"which names another chapter")
                number = str(int(whole)) + (f".{part}" if part is not None else "")
                served_date = row.select_one("span.chapter-release-date i")
                by_number.setdefault(Decimal(number), []).append((
                    number, url, chapter_slug, label,
                    _row_date(_text(served_date)) if served_date else None))
            elif _LABEL_EXTRA.match(label):
                extras.append(label)
            else:
                raise YuriOnlineSourceError(
                    f"Yuri-Online has a chapter row of {slug} in an unknown form: {label!r}")

        chapters: List[Chapter] = []
        for entries in by_number.values():
            if len(entries) > 1:
                logger.warning(
                    "%s: chapter %s of %s is served %d times with different links (%s); "
                    "none of them is listed", self.name, entries[0][0], series_url,
                    len(entries), ", ".join(entry[1] for entry in entries))
                continue
            number, url, chapter_slug, label, published = entries[0]
            chapters.append(Chapter(number=number, title=None, url=url, date=published))
            self._listed[url] = (series_url, chapter_slug, label)
        if extras:
            logger.warning(
                "%s: %d chapter row(s) of %s have no chapter number and were not listed: %s",
                self.name, len(extras), series_url, ", ".join(extras))
        if not chapters:
            raise YuriOnlineSourceError(f"Yuri-Online lists no numbered chapters for {slug}")
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page."""
        try:
            series_url, _ = self._series_parts(manga_url)
            image = self._series_page(series_url).select_one("div.summary_image img[data-src]")
            return _own_url(image["data-src"], _COVER_PATH) if image else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in reader order, all or nothing."""
        url, series_slug, chapter_slug = self._chapter_parts(chapter_url)
        series_url = f"{self.base_url}/manga/{series_slug}/"

        def refused(why: str):
            return YuriOnlineSourceError(f"Yuri-Online chapter {url} {why}")

        html = self._get(url, "chapter")
        soup = BeautifulSoup(html, "html.parser")
        readers = soup.select(".reading-content")
        if len(readers) != 1:
            raise refused("lists no pages")
        if readers[0].select('input[type="password"], form') or soup.select("#adult_modal"):
            raise refused("asks to log in or to confirm adult content; this source reads "
                          "free, non-adult chapters only")
        if soup.select("#chapter-protector-data"):
            raise refused("serves its pages encrypted; this source does not decode them")
        if url not in self._listed:
            self.get_chapters(series_url)
        listed = self._listed.get(url)
        if listed is None or listed[0] != series_url:
            raise refused("is not a chapter the series lists")
        _, listed_slug, label = listed
        series_title, series_id = self._series[series_url]

        canonical = soup.select('link[rel="canonical"]')
        headings = soup.select("h1#chapter-heading")
        current = soup.select("#wp-manga-current-chap")
        calls = list(_INLINE_MANGA.finditer(html))
        inline = None
        if len(calls) == 1:
            try:
                inline = json.JSONDecoder().raw_decode(html, calls[0].end())[0]
            except ValueError:
                pass
        if (len(canonical) != 1 or canonical[0].get("href") != url
                or listed_slug != chapter_slug or _post_id(soup) != series_id
                or len(current) != 1 or current[0].get("value") != chapter_slug
                or len(headings) != 1 or _text(headings[0]) != f"{series_title} - {label}"
                or not isinstance(inline, dict) or inline.get("base_url") != series_url
                or str(inline.get("manga_id")) != series_id
                or inline.get("chapter_slug") != chapter_slug):
            raise refused("does not name this chapter and its series")

        breaks = readers[0].select("div.page-break")
        if not breaks:
            raise refused("lists no pages")
        if len(breaks) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        pages: List[str] = []
        folders = set()
        for index, block in enumerate(breaks):
            images = block.find_all("img")
            image = images[0] if len(images) == 1 else None
            if image is None or image.get("id") != f"image-{index}":
                raise refused(f"has a malformed page {index + 1}")
            page = _own_url(image.get("data-src"), _IMAGE_PATH)
            if page is None:
                raise refused(f"has an unexpected image for page {index + 1}")
            if image.get("src") is not None and image.get("src").strip() != page:
                raise refused(f"has a malformed page {index + 1}")
            folders.add(_IMAGE_PATH.match(urlsplit(page).path).groups())
            pages.append(page)
        if len(folders) != 1:
            raise refused("spreads its pages over more than one folder")
        if len(set(pages)) != len(pages):
            raise refused("lists the same image twice")
        return pages

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page as served; a failure leaves no file at ``path``.
        The site serves images as application/octet-stream, so the bytes,
        not the content type, decide."""
        path = Path(path)
        try:
            image_url = _own_url(url, _IMAGE_PATH)
            if image_url is None or image_url != url:
                raise YuriOnlineSourceError(f"refused a page URL: {url}")
            response = self._request(image_url, headers=self._IMAGE_HEADERS,
                                     allow_redirects=False)
            if response.status_code != 200:
                raise YuriOnlineSourceError(f"{image_url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise YuriOnlineSourceError(f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise YuriOnlineSourceError(f"{image_url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a Yuri-Online page: %s", e)
            return False
