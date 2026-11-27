"""
Nora no Fansub scraper - Spanish manga scans
Site: www.noranofansub.com/lector

The reader runs FoOlSlide under /lector:

* search   -> POST /lector/search/ with the form field ``search``; the answer
              is one ``div.list`` headed "Resultados de búsqueda para: <q>"
              with a ``div.group`` per series. No results is that heading
              alone.
* chapters -> the series page lists ``div.element`` rows under volume groups.
              A row's link reads "Capítulo N" or "Capítulo N.M", its title
              "Vol.V Capítulo N", and it points to
              /lector/read/<series>/es-cl/<V>/<N>/ (a decimal chapter adds
              /<M>/; some rows add /0/<team>/). Dates read "YYYY.MM.DD".
* pages    -> the reader's inline ``var pages = [...]`` list, in served order.

A row served twice with the same link and the same label is listed once,
with a warning that counts the repeats. A chapter number served under
different links lists none of them, with a warning naming every link. Any
other row form raises.

Only free chapters are read. A chapter row that shows an access control (a
form or button, a link other than its chapter and team, or visible wording
about payment, locking, early access or logging in) fails the listing; CSS
class names and hidden elements alone are not taken as one. A series or
reader page that asks to log in is refused.

A reader must name its chapter and series: its own address, heading links
and title must match the row the series page lists, and every page object's
chapter id must equal the reader's own comment-thread id. Its pages must all
sit in one chapter folder of the series' own comic folder.

The group's catalogue includes titles tagged as adult, so the source is
marked NSFW. A series or chapter answered with an adult confirmation is
refused; no confirmation is ever sent.
"""

import json
import logging
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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

_HOST = "www.noranofansub.com"
_LANGUAGE = "es-cl"
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SERIES_PATH = re.compile(rf"^/lector/series/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(
    rf"^/lector/read/({_SLUG})/{_LANGUAGE}/([0-9]+)/([0-9]+)/(?:([0-9]+)/(?:({_SLUG})/)?)?$")
# A comic folder is "<series slug>_<hex>"; a chapter's pages sit in one folder below it.
_PAGE_PATH = re.compile(
    rf"^/lector/content/comics/(({_SLUG})_[0-9a-f]+)/([0-9a-z_-]+)/[^/?#\s]+\.(?:jpe?g|png|webp)$",
    re.I)
_COVER_PATH = re.compile(
    rf"^/lector/content/comics/(({_SLUG})_[0-9a-f]+)/[^/?#\s]+\.(?:jpe?g|png|webp)$", re.I)
_TEAM_PATH = re.compile(rf"^/lector/team/{_SLUG}/?$")
_ACCESS_WORDS = re.compile(
    r"\b(?:premium|vip|bloquead[oa]s?|desbloque\w*|candado|locked|comprar|compra|precio|"
    r"pagar|de pago|monedas?|coins?|puntos|patreon|ko-?fi|paypal|suscr[ií]\w*|"
    r"acceso anticipado|anticipad[oa]s?|adelantad[oa]s?|early access|"
    r"iniciar sesi[oó]n|inicia sesi[oó]n|login|reg[ií]strate)\b", re.I)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_CONTROLS = "form, input, button, select, textarea"
_LOGIN_FORM = 'input[type="password"], form[action*="/account/"], form[action*="login"]'
_LABEL = re.compile(r"^Capítulo ([0-9]+)(?:\.([0-9]+))?$")
_ROW_DATE = re.compile(r", ([0-9]{4})\.([0-9]{2})\.([0-9]{2})$")
_SEARCH_HEADING = "Resultados de búsqueda para:"
_PAGES = re.compile(r"\bvar pages = (?=\[)")
_BASE_URL = re.compile(r"\bvar base_url = '([^']*)';")
_IDENTIFIER = re.compile(r"this\.page\.identifier = 'chapter_id-([0-9]+)';")
_PAGE_URL = re.compile(r"this\.page\.url = '(https?://[^']*)';")
_INFO_GENRE = re.compile(r"^(?:g[ée]neros?|genres?|tags?|categor[íi]as?)$", re.I)
_ADULT_WORDS = frozenset({
    "adulto", "adult", "+18", "18+", "hentai", "smut",
    "lolicon", "shotacon", "loli", "shota",
})
_SITE_TITLE = "Nora no Fansub Lector"

_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024


class NoraNoFansubSourceError(RuntimeError):
    """www.noranofansub.com answered with a page this scraper cannot use."""


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
    if (parts.scheme not in ("http", "https") or port is not None
            or (parts.hostname or "").lower() not in (_HOST, _HOST[4:])
            or "@" in parts.netloc or parts.query or parts.fragment):
        return None
    return parts.path


def _own_https(url, pattern) -> Optional[str]:
    """``url`` when it is an https URL on the site's own host matching ``pattern``."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (url != url.strip() or parts.scheme != "https" or parts.hostname != _HOST
            or port is not None or "@" in parts.netloc or parts.query or parts.fragment
            or ".." in parts.path.split("/") or not pattern.match(parts.path)):
        return None
    return url


def _row_date(text: str) -> Optional[str]:
    match = _ROW_DATE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _adult_gate(soup: BeautifulSoup) -> bool:
    """True when the page asks to confirm adult content."""
    return bool(soup.select('input[name="adult"]'))


def _login_gate(soup: BeautifulSoup) -> bool:
    """True when the page asks to log in."""
    return bool(soup.select(_LOGIN_FORM))


def _access_control(row) -> Optional[str]:
    """What in a chapter row's visible content controls access, or None.

    Hidden elements are left out first, and class names are never read:
    only forms and buttons, links other than the row's own chapter link and
    its team, and visible wording (or image text) about payment, locks,
    early access or logging in count. The chapter link itself is checked by
    the listing.
    """
    visible = BeautifulSoup(str(row), "html.parser")
    for element in visible.find_all(True):
        if element.decomposed:
            continue
        if (element.has_attr("hidden") or element.get("aria-hidden") == "true"
                or _HIDDEN_STYLE.search(element.get("style") or "")):
            element.decompose()
    if visible.select(_CONTROLS):
        return "a form or button"
    root = visible.find(True)
    title = root.find("div", class_="title", recursive=False) if root else None
    own = {id(link) for link in title.find_all("a", href=True, recursive=False)} if title else set()
    for link in visible.select("a[href]"):
        path = _site_path(link["href"])
        if id(link) not in own and not (path is not None and _TEAM_PATH.match(path)):
            return f"a link to {link['href']}"
    words = [_text(visible)]
    words += [image.get(name) or "" for image in visible.find_all("img") for name in ("alt", "title")]
    match = _ACCESS_WORDS.search(" ".join(words))
    return f"the words {match.group(0)!r}" if match else None


def _page_folders(url: str) -> Tuple[str, str, str]:
    """(comic folder, its series slug, chapter folder) of a page URL already
    checked against _PAGE_PATH."""
    match = _PAGE_PATH.match(urlsplit(url).path)
    return match.group(1), match.group(2), match.group(3)


class NoraNoFansubScraper(BaseScraper):
    """Scraper for Nora no Fansub (www.noranofansub.com/lector)."""

    name = "noranofansub"
    base_url = f"https://{_HOST}"
    content_language = "es"  # Spanish-language fansub
    nsfw = True  # the catalogue includes adult-tagged titles; confirmations are refused

    _READER_ROOT = f"https://{_HOST}/lector/"
    _IMAGE_HEADERS = {"Referer": f"https://{_HOST}/lector/"}

    def __init__(self):
        super().__init__()
        # Worker copies share these: each checked series' title and comic
        # folder (from its cover, when served), and the series, label and
        # link title of each listed chapter.
        self._series: Dict[str, Tuple[str, Optional[str]]] = {}
        self._listed: Dict[str, Tuple[str, str, str]] = {}

    # URLs

    def _series_url(self, url) -> Tuple[str, str]:
        path = _site_path(url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise NoraNoFansubSourceError(f"Not a Nora no Fansub series URL: {url}")
        return f"{self.base_url}/lector/series/{match.group(1)}/", match.group(1)

    def _chapter_url(self, url):
        path = _site_path(url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise NoraNoFansubSourceError(f"Not a Nora no Fansub chapter URL: {url}")
        return f"{self.base_url}{path}", match

    # Requests

    def _get(self, url: str, what: str) -> str:
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise NoraNoFansubSourceError(
                f"Nora no Fansub answered HTTP {response.status_code} for {what} {url}")
        return response.text

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

    # Search

    def search(self, query: str) -> List[Manga]:
        """The site's search, one page; more pages raise rather than being cut."""
        query = " ".join((query or "").split())
        if not query:
            return []
        url = f"{self._READER_ROOT}search/"
        response = self._post(url, data={"search": query},
                              headers={"Origin": self.base_url, "Referer": self._READER_ROOT})
        if response.status_code != 200:
            raise NoraNoFansubSourceError(
                f"Nora no Fansub answered HTTP {response.status_code} for search {url}")
        soup = BeautifulSoup(response.text, "html.parser")
        lists = soup.select("div.list")
        heading = lists[0].find("div", class_="title", recursive=False) if len(lists) == 1 else None
        if heading is None or _text(heading) != f"{_SEARCH_HEADING} {query}":
            raise NoraNoFansubSourceError(
                f"Nora no Fansub search for {query!r} did not serve a result list")
        if soup.select("div.next, .next, a.next"):
            raise NoraNoFansubSourceError(
                f"Nora no Fansub search for {query!r} has more result pages than this "
                f"source reads")
        groups = lists[0].find_all("div", class_="group", recursive=False)
        if len(groups) != len(lists[0].select("div.group")):
            raise NoraNoFansubSourceError(
                f"Nora no Fansub search for {query!r} nests result groups")

        results: List[Manga] = []
        seen = set()
        for group in groups:
            title_block = group.find("div", class_="title", recursive=False)
            links = title_block.find_all("a", href=True, recursive=False) if title_block else []
            title = _text(links[0]) if len(links) == 1 else ""
            if not title:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub search for {query!r} lists a result without its link or title")
            try:
                series_url, _ = self._series_url(links[0]["href"])
            except NoraNoFansubSourceError:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub search for {query!r} lists a result that is not a series"
                ) from None
            if series_url in seen:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub search for {query!r} lists {series_url} twice")
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series_page(self, series_url: str, slug: str) -> BeautifulSoup:
        html = self._get(series_url, "series page")
        soup = BeautifulSoup(html, "html.parser")
        if _adult_gate(soup):
            raise NoraNoFansubSourceError(
                f"Nora no Fansub asks to confirm adult content for {series_url}; "
                f"adult titles are not supported")
        if _login_gate(soup):
            raise NoraNoFansubSourceError(
                f"Nora no Fansub asks to log in for {series_url}; "
                f"this source reads free chapters only")
        headings = soup.select("h1.title")
        page_paths = [_site_path(url) for url in _PAGE_URL.findall(html)]
        if (len(headings) != 1 or not _text(headings[0]) or len(soup.select("div.list")) != 1
                or page_paths != [f"/lector/series/{slug}/"]):
            raise NoraNoFansubSourceError(f"Nora no Fansub page {series_url} is not a series page")
        for info in soup.select("div.info"):
            for label in info.find_all("b"):
                if not _INFO_GENRE.match(_text(label)):
                    continue
                value = label.next_sibling
                words = {word.strip(" :").casefold()
                         for word in str(value or "").split(",")}
                if words & _ADULT_WORDS:
                    raise NoraNoFansubSourceError(
                        f"Nora no Fansub lists {series_url} as adult; adult titles are "
                        f"not supported")
        cover = soup.select_one("div.thumbnail img[src]")
        cover_url = _own_https(cover["src"], _COVER_PATH) if cover else None
        folder = _COVER_PATH.match(urlsplit(cover_url).path) if cover_url else None
        self._series[series_url] = (
            _text(headings[0]), folder.group(1) if folder and folder.group(2) == slug else None)
        return soup

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The numbered chapters of a series, oldest first."""
        series_url, slug = self._series_url(manga_url)
        soup = self._series_page(series_url, slug)
        rows = soup.select("div.list div.element")
        if not rows:
            raise NoraNoFansubSourceError(f"Nora no Fansub lists no chapters for {slug}")
        if len(rows) > _MAX_CHAPTERS:
            raise NoraNoFansubSourceError(f"Nora no Fansub lists too many chapters for {slug}")

        by_url: Dict[str, Tuple[str, str, Optional[str]]] = {}
        repeats: Dict[str, int] = {}
        for row in rows:
            title_block = row.find("div", class_="title", recursive=False)
            links = title_block.find_all("a", href=True, recursive=False) if title_block else []
            control = _access_control(row)
            if control is not None:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub has a locked or paid chapter row of {slug} ({control}); "
                    f"this source reads free chapters only")
            if len(links) != 1:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub has a chapter row of {slug} without one link")
            label = _text(links[0])
            link_title = " ".join((links[0].get("title") or "").split())
            try:
                url, match = self._chapter_url(links[0]["href"])
            except NoraNoFansubSourceError:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub links {label!r} of {slug} elsewhere") from None
            series, volume, whole, sub, team = match.groups()
            number = _LABEL.match(label)
            if series != slug:
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub links {label!r} of {slug} to another series")
            if (number is None or link_title != f"Vol.{int(volume)} {label}"
                    or int(whole) != int(number.group(1))
                    or (number.group(2) is None and sub not in (None, "0"))
                    or (number.group(2) is not None and (sub != number.group(2) or team))):
                raise NoraNoFansubSourceError(
                    f"Nora no Fansub has a chapter row of {slug} in an unknown form: "
                    f"{link_title!r} -> {links[0]['href']!r}")
            meta = row.find("div", class_="meta_r", recursive=False)
            entry = (label, link_title, _row_date(_text(meta)) if meta else None)
            if url in by_url:
                if by_url[url] != entry:
                    raise NoraNoFansubSourceError(
                        f"Nora no Fansub lists {url} twice for {slug} as different chapters")
                repeats[url] = repeats.get(url, 1) + 1
                continue
            by_url[url] = entry

        by_number: Dict[Decimal, List[Tuple[str, str, Tuple[str, str, Optional[str]]]]] = {}
        for url, entry in by_url.items():
            match = _LABEL.match(entry[0])
            whole = str(int(match.group(1)))
            number = f"{whole}.{match.group(2)}" if match.group(2) is not None else whole
            by_number.setdefault(Decimal(number), []).append((number, url, entry))

        chapters: List[Chapter] = []
        repeated: List[str] = []
        for entries in by_number.values():
            if len(entries) > 1:
                repeated.append(f"{entries[0][0]} ({', '.join(url for _, url, _ in entries)})")
                continue
            number, url, (label, link_title, published) = entries[0]
            chapters.append(Chapter(number=number, title=None, url=url, date=published))
            self._listed[url] = (series_url, label, link_title)
        if repeats:
            logger.warning(
                "%s: %d chapter row(s) of %s repeat another row with the same link and "
                "were counted once: %s", self.name, sum(n - 1 for n in repeats.values()),
                series_url, ", ".join(repeats))
        if repeated:
            logger.warning(
                "%s: %d chapter number(s) of %s are served under different links and none "
                "of them is listed: %s", self.name, len(repeated), series_url,
                "; ".join(repeated))
        if not chapters:
            raise NoraNoFansubSourceError(f"Nora no Fansub lists no numbered chapters for {slug}")
        return sorted(chapters, key=lambda chapter: chapter_order_key(chapter.number))

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series page, as served."""
        try:
            series_url, slug = self._series_url(manga_url)
            image = self._series_page(series_url, slug).select_one("div.thumbnail img[src]")
            # As served: the series page shows the small cover.
            return _own_https(image["src"], _COVER_PATH) if image else None
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """The page images of a chapter in reader order, all or nothing."""
        url, match = self._chapter_url(chapter_url)
        series_url = f"{self.base_url}/lector/series/{match.group(1)}/"

        def refused(why: str):
            return NoraNoFansubSourceError(f"Nora no Fansub chapter {url} {why}")

        html = self._get(url, "chapter")
        soup = BeautifulSoup(html, "html.parser")
        if _adult_gate(soup):
            raise refused("asks to confirm adult content; adult titles are not supported")
        if _login_gate(soup):
            raise refused("asks to log in; this source reads free chapters only")
        if url not in self._listed:
            self.get_chapters(series_url)
        listed = self._listed.get(url)
        if listed is None or listed[0] != series_url:
            raise refused("is not a chapter the series lists")
        _, label, link_title = listed
        series_title, series_folder = self._series[series_url]

        headings = soup.select("h1.tbtitle")
        links = headings[0].find_all("a", href=True) if len(headings) == 1 else []
        titles = soup.select("title")
        if (_BASE_URL.findall(html) != [url] or len(links) != 2
                or [link["href"] for link in links] != [series_url, url]
                or _text(links[0]) != series_title or _text(links[1]) != link_title
                or len(titles) != 1
                or _text(titles[0]) != f"{series_title} :: {label} :: {_SITE_TITLE}"):
            raise refused("does not name this chapter and its series")

        calls = list(_PAGES.finditer(html))
        if len(calls) != 1:
            raise refused(f"has {len(calls)} page lists, not one")
        try:
            pages, _ = json.JSONDecoder().raw_decode(html, calls[0].end())
        except ValueError:
            raise refused("has a page list that is not JSON") from None
        if not isinstance(pages, list) or not pages:
            raise refused("lists no pages")
        if len(pages) > _MAX_PAGES:
            raise refused(f"lists more than the {_MAX_PAGES} pages this source accepts")
        chapter_ids = {page.get("chapter_id") if isinstance(page, dict) else None for page in pages}
        identifiers = _IDENTIFIER.findall(html)
        if (len(chapter_ids) != 1 or not isinstance(next(iter(chapter_ids)), str)
                or not re.fullmatch(r"[0-9]+", next(iter(chapter_ids)))
                or identifiers != list(chapter_ids)):
            raise refused("does not name this chapter and its series")
        result: List[str] = []
        folders = set()
        for index, page in enumerate(pages, start=1):
            if page.get("hidden") != "0":
                raise refused(f"hides page {index}")
            image = _own_https(page.get("url"), _PAGE_PATH)
            if image is None:
                raise refused(f"has an unexpected image for page {index}")
            # The series' own comic folder: its slug, and the folder its
            # cover sits in when the series page serves one there.
            comic, comic_slug, chapter_folder = _page_folders(image)
            if comic_slug != match.group(1) or (series_folder and comic != series_folder):
                raise refused(f"has an image of another series for page {index}")
            folders.add((comic, chapter_folder))
            result.append(image)
        if len(folders) != 1:
            raise refused("spreads its pages over more than one folder")
        if len(set(result)) != len(result):
            raise refused("lists the same image twice")
        return result

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page as served; a failure leaves no file at ``path``."""
        path = Path(path)
        try:
            if _own_https(url, _PAGE_PATH) is None:
                raise NoraNoFansubSourceError(f"refused a page URL: {url}")
            response = self._request(url, headers=self._IMAGE_HEADERS, allow_redirects=False)
            if response.status_code != 200:
                raise NoraNoFansubSourceError(f"{url} answered HTTP {response.status_code}")
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise NoraNoFansubSourceError(f"{url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise NoraNoFansubSourceError(f"{url} did not return an image")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download a Nora no Fansub page: %s", e)
            return False
