"""
KadoComi (カドコミ, formerly ComicWalker) scraper
https://comic-walker.com

KADOKAWA's official manga site. Only publicly free episodes are read,
anonymously; nothing behind a login, purchase or other wall is touched.

Search results and a work's episode list come from the public pages,
which embed the site's own data in their Next.js state (``__NEXT_DATA__``).
A chapter's pages come from the site's viewer endpoint
(``/api/contents/viewer``), the same anonymous request the site's own
reader makes. The page images it lists are served XOR-encoded with a
per-page key; they are decoded here, in memory, before being saved.

What a chapter list means: the episodes this work's public page exposes
that the site currently marks active. That is the work's current public
free selection, not its whole history or every free episode the site has
offered; episodes the page does not list, and specials numbered at or
below an already downloaded episode, may not show up as updates.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

import requests

from ..chapters import chapter_order_key
from ..image_limits import ImageTooLargeError, open_image
from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "comic-walker.com"
_BASE_URL = f"https://{_HOST}"
_PAGE_HOST = "cdn.comic-walker.com"

_WORK_QUERY = "/api/contents/details/work"
_EPISODE_QUERY = "/api/contents/details/episode"
_SEARCH_QUERY = "/api/search/keywords"
_VIEWER_PATH = "/api/contents/viewer"
# The page width the site's viewer asks for. Pages may come back
# narrower; their own width and height are what a page is checked against.
_VIEWER_SIZE = "width:1284"

_WORK_CODE = re.compile(r"KC_\d+_S")
_EPISODE_CODE = re.compile(r"KC_\d+_E")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_PAGE_KEY = re.compile(r"[0-9a-fA-F]{16}")
_WORK_PATH = re.compile(r"/detail/([^/?#]+)/?")
_EPISODE_PATH = re.compile(r"/detail/([^/?#]+)/episodes/([^/?#]+)/?")
_EXPIRES_AT = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z")
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_CHALLENGE_MARKERS = ("<title>just a moment", "cf-chl")


class KadoComiSourceError(RuntimeError):
    """comic-walker.com did not serve what was asked for, or served it in
    a shape this scraper does not know."""


def _failure(error: BaseException) -> str:
    """A short description of a failed request: its status, or the kind
    of failure. Never the URL, which the requests message contains."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(error).__name__


def _xor(data: bytes, key: bytes) -> bytes:
    """`data` XORed with `key` repeated from its first byte."""
    if not key:
        raise ValueError("empty key")
    repeats = len(data) // len(key) + 1
    stream = (key * repeats)[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(
        len(data), "big")


def parse_expires_at(value) -> datetime:
    """The UTC time of an ``expiresAt`` value such as
    ``2026-11-20T22:47:33.1234567Z``; anything else raises ValueError."""
    match = _EXPIRES_AT.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError("unexpected expiresAt format")
    year, month, day, hour, minute, second, fraction = match.groups()
    micro = int((fraction or "0").ljust(6, "0")[:6])
    return datetime(int(year), int(month), int(day), int(hour), int(minute),
                    int(second), micro, tzinfo=timezone.utc)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def next_data_queries(html: str) -> List[dict]:
    """The React Query entries a page embeds in its ``__NEXT_DATA__``."""
    from bs4 import BeautifulSoup

    script = BeautifulSoup(html or "", "html.parser").find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise KadoComiSourceError("page carries no __NEXT_DATA__ state")
    try:
        state = json.loads(script.string)
    except ValueError:
        raise KadoComiSourceError("page state is not valid JSON") from None
    try:
        queries = state["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        raise KadoComiSourceError("page state has no query list") from None
    if not isinstance(queries, list):
        raise KadoComiSourceError("page state has no query list")
    return queries


def query_data(queries: List[dict], path: str, accept=lambda data: True):
    """The ``data`` of the one successful query for `path` that `accept`
    takes; anything else raises KadoComiSourceError."""
    found = []
    for query in queries:
        if not isinstance(query, dict):
            continue
        key = query.get("queryKey")
        if not (isinstance(key, list) and key and key[0] == path):
            continue
        state = query.get("state")
        if not isinstance(state, dict) or state.get("status") != "success":
            raise KadoComiSourceError(f"page query {path} did not succeed")
        data = state.get("data")
        if isinstance(data, dict) and accept(data):
            found.append(data)
    if len(found) != 1:
        raise KadoComiSourceError(
            f"page carries {len(found)} usable {path} queries, expected 1")
    return found[0]


# ── Episode list ─────────────────────────────────────────────────────


# Where the work query lists episodes: (top-level key, kind). A
# "list" holds {total, result}; a "comic" holds one volume's episodes;
# "comics" holds {total, result} of volumes. labelWorks (related works)
# is deliberately not read.
_EPISODE_SOURCES = (
    ("firstEpisodes", "list"),
    ("latestEpisodes", "list"),
    ("comics", "comics"),
    ("firstComic", "comic"),
    ("latestComic", "comic"),
)


@dataclass(frozen=True)
class _Episode:
    id: str
    code: str
    type: str
    number: int
    active: bool
    title: str
    date: Optional[str]


def _episode(row) -> _Episode:
    """One episode row of the work query, checked field by field."""
    if not isinstance(row, dict):
        raise KadoComiSourceError("episode row is not an object")
    internal = row.get("internal")
    code, episode_id, kind = row.get("code"), row.get("id"), row.get("type")
    active, title = row.get("isActive"), row.get("title")
    number = internal.get("episodeNo") if isinstance(internal, dict) else None
    if not (isinstance(code, str) and _EPISODE_CODE.fullmatch(code)
            and isinstance(episode_id, str) and _UUID.fullmatch(episode_id)
            and isinstance(kind, str) and kind
            and isinstance(active, bool) and _is_int(number)
            and isinstance(title, str)):
        raise KadoComiSourceError("episode row is missing a required field")
    subtitle = row.get("subTitle")
    if isinstance(subtitle, str) and subtitle.strip():
        title = f"{title} {subtitle.strip()}"
    date = row.get("updateDate")
    return _Episode(episode_id, code, kind, number, active, title.strip(),
                    date if isinstance(date, str) else None)


def _episode_rows(data: dict) -> Tuple[List[dict], int]:
    """Every episode row the work query lists, and how many of its
    volumes list none."""
    rows: List[dict] = []
    empty_volumes = 0
    for key, kind in _EPISODE_SOURCES:
        value = data.get(key)
        if kind == "list":
            if not isinstance(value, dict) or not isinstance(value.get("result"), list):
                raise KadoComiSourceError(f"work data has no {key} list")
            rows.extend(value["result"])
        elif kind == "comics":
            if not isinstance(value, dict) or not isinstance(value.get("result"), list):
                raise KadoComiSourceError("work data has no volume list")
            for volume in value["result"]:
                if not isinstance(volume, dict) or not isinstance(volume.get("episodes"), list):
                    raise KadoComiSourceError("volume has no episode list")
                if not volume["episodes"]:
                    empty_volumes += 1
                rows.extend(volume["episodes"])
        else:  # one volume, or none at all
            if value is None:
                continue
            if not isinstance(value, dict) or not isinstance(value.get("episodes"), list):
                raise KadoComiSourceError(f"work data has a malformed {key}")
            rows.extend(value["episodes"])
    return rows, empty_volumes


def work_episodes(data: dict) -> Tuple[List[_Episode], int]:
    """The work's distinct episodes, and how many volumes list none.

    The same episode appears in several lists; its copies must agree on
    its id, kind, number and whether it is active. Copies that disagree,
    or one id under two codes, raise rather than one being picked. The
    first copy's title and date are kept."""
    rows, empty_volumes = _episode_rows(data)
    by_code: Dict[str, _Episode] = {}
    code_by_id: Dict[str, str] = {}
    for row in rows:
        episode = _episode(row)
        known = by_code.get(episode.code)
        if known is not None:
            if (known.id, known.type, known.number, known.active) != (
                    episode.id, episode.type, episode.number, episode.active):
                raise KadoComiSourceError("an episode is listed twice with different details")
            continue
        if code_by_id.setdefault(episode.id, episode.code) != episode.code:
            raise KadoComiSourceError("one episode id is listed under two codes")
        by_code[episode.code] = episode
    return list(by_code.values()), empty_volumes


def chapter_labels(episodes: List[_Episode]) -> Dict[str, str]:
    """Chapter label per episode code.

    A regular episode is its own number ("12"); any other kind is its kind
    and number ("Extra 1"), so it never takes a regular episode's place.
    Episodes that would share a label all get their code appended."""
    base = {}
    for episode in episodes:
        if episode.type == "normal":
            base[episode.code] = str(episode.number)
        else:
            base[episode.code] = f"{episode.type.capitalize()} {episode.number}"
    counts: Dict[str, int] = {}
    for label in base.values():
        counts[label] = counts.get(label, 0) + 1
    return {code: (f"{label} ({code})" if counts[label] > 1 else label)
            for code, label in base.items()}


# ── Pages ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Page:
    """What downloading one page needs; held in memory only."""
    key: bytes
    width: int
    height: int
    expires: datetime
    episode: str


def viewer_pages(payload, page_count: int) -> Tuple[datetime, List[Tuple[str, "_Page"]]]:
    """The page image URLs of a viewer reply, in page order, each with
    what decoding it needs. Anything this scraper cannot decode exactly
    as the site serves it raises; no page is left out."""
    if not isinstance(payload, dict):
        raise KadoComiSourceError("viewer reply is not an object")
    try:
        expires = parse_expires_at(payload.get("expiresAt"))
    except ValueError:
        raise KadoComiSourceError("viewer reply has an unknown expiry format") from None
    if expires <= datetime.now(timezone.utc):
        raise KadoComiSourceError("viewer reply has already expired")
    if payload.get("scrollDirection") != "rtl":
        raise KadoComiSourceError("viewer reply has an unsupported reading direction")
    manuscripts = payload.get("manuscripts")
    if not isinstance(manuscripts, list):
        raise KadoComiSourceError("viewer reply has no page list")
    if not manuscripts:
        raise KadoComiSourceError("episode is not publicly available")
    if len(manuscripts) != page_count:
        raise KadoComiSourceError(
            f"viewer lists {len(manuscripts)} pages, the episode has {page_count}")

    pages = []
    for item in manuscripts:
        if not isinstance(item, dict):
            raise KadoComiSourceError("viewer page entry is not an object")
        number, width, height = item.get("page"), item.get("width"), item.get("height")
        if not (_is_int(number) and number > 0 and _is_int(width) and width > 0
                and _is_int(height) and height > 0):
            raise KadoComiSourceError("viewer page entry has no usable position or size")
        if item.get("drmMode") != "xor":
            raise KadoComiSourceError("viewer page has an unsupported encoding")
        page_key = item.get("drmHash")
        if not (isinstance(page_key, str) and _PAGE_KEY.fullmatch(page_key)):
            raise KadoComiSourceError("viewer page has an unsupported key format")
        url = item.get("drmImageUrl")
        parts = urlsplit(url) if isinstance(url, str) else None
        if (parts is None or parts.scheme != "https" or parts.netloc != _PAGE_HOST
                or parts.fragment):
            raise KadoComiSourceError("viewer page is on an unexpected host")
        pages.append((number, url, _Page(bytes.fromhex(page_key), width, height,
                                         expires, "")))

    numbers = sorted(number for number, _, _ in pages)
    if numbers != list(range(1, page_count + 1)):
        raise KadoComiSourceError("viewer page positions do not run 1 to the page count")
    pages.sort(key=lambda entry: entry[0])
    return expires, [(url, page) for _, url, page in pages]


class KadoComiScraper(BaseScraper):
    """Scraper for KadoComi (comic-walker.com).

    A chapter list is the active episodes this work's public page exposes:
    the site's current public free selection for the work, not its whole
    lifetime catalogue nor every free episode. Episodes the page does not
    list are not offered, and a special numbered at or below an already
    downloaded episode is listed but may not be offered as an update.
    """

    name = "kadocomi"
    base_url = _BASE_URL
    content_language = "ja"
    reading_direction = "rtl"

    def __init__(self):
        super().__init__()
        # Page URL -> what downloading it needs. Worker copies share this
        # map and its lock (worker_copy copies the scraper shallowly).
        self._pages: Dict[str, _Page] = {}
        self._pages_lock = threading.Lock()

    def _get_html(self, url: str) -> str:
        """A public page; a page the site did not serve raises."""
        try:
            response = self._request(url)
        except requests.RequestException as e:
            raise KadoComiSourceError(f"KadoComi did not serve a page ({_failure(e)})") from None
        text = response.text or ""
        if (response.headers.get("cf-mitigated") or "").lower() == "challenge" or any(
                marker in text[:20000].lower() for marker in _CHALLENGE_MARKERS):
            raise KadoComiSourceError("KadoComi answered with a challenge page")
        return text

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Search by keyword: the first page of results the site's search
        page shows (it lists up to 32)."""
        url = f"{self.base_url}/search?{urlencode({'keyword': query})}"
        queries = next_data_queries(self._get_html(url))
        data = query_data(queries, _SEARCH_QUERY)
        results, pagination = data.get("result"), data.get("pagination")
        if not isinstance(results, list) or not (
                isinstance(pagination, dict) and _is_int(pagination.get("total"))):
            raise KadoComiSourceError("search results are not in the expected shape")
        found = []
        for item in results:
            code = item.get("code") if isinstance(item, dict) else None
            title = item.get("title") if isinstance(item, dict) else None
            if not (isinstance(code, str) and _WORK_CODE.fullmatch(code)
                    and isinstance(title, str) and title.strip()):
                raise KadoComiSourceError("search result is missing a required field")
            cover = item.get("bookCover") or item.get("thumbnail") or item.get("originalThumbnail")
            found.append(Manga(title=title.strip(), url=f"{self.base_url}/detail/{code}",
                               cover_url=cover if isinstance(cover, str) else None))
        return found

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The active episodes the work's public page exposes."""
        match = _WORK_PATH.fullmatch(urlsplit(manga_url).path)
        if not match or not _WORK_CODE.fullmatch(match.group(1)):
            raise ValueError(f"Not a KadoComi work URL: {manga_url}")
        work_code = match.group(1)
        queries = next_data_queries(self._get_html(f"{self.base_url}/detail/{work_code}"))
        data = query_data(
            queries, _WORK_QUERY,
            lambda d: isinstance(d.get("work"), dict) and d["work"].get("code") == work_code)
        episodes, empty_volumes = work_episodes(data)
        labels = chapter_labels(episodes)

        active = [episode for episode in episodes if episode.active]
        chapters = [Chapter(number=labels[episode.code], title=episode.title,
                            url=f"{self.base_url}/detail/{work_code}/episodes/{episode.code}",
                            date=episode.date)
                    for episode in active]
        logger.info(
            "KadoComi: listing %d active episode(s) this work's public page exposes "
            "(its current public selection, not every episode; %d inactive, "
            "%d volume(s) list none)",
            len(active), len(episodes) - len(active), empty_volumes)
        return sorted(chapters, key=lambda c: chapter_order_key(c.number))

    # ── Pages ────────────────────────────────────────────────────────

    def _viewer_reply(self, episode_id: str):
        """The site's viewer reply for one episode. Sent directly, not
        through _request: its retries log the request URL, which carries
        the episode id."""
        url = (f"{self.base_url}{_VIEWER_PATH}?"
               f"{urlencode({'episodeId': episode_id, 'imageSizeType': _VIEWER_SIZE})}")
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise KadoComiSourceError(f"KadoComi viewer did not answer ({_failure(e)})") from None
        except ValueError:
            raise KadoComiSourceError("KadoComi viewer reply is not JSON") from None

    def get_pages(self, chapter_url: str) -> List[str]:
        """The episode's page image URLs, in page order.

        Each call reads the episode's public page and the viewer afresh:
        the page list is signed for a limited time and never reused."""
        match = _EPISODE_PATH.fullmatch(urlsplit(chapter_url).path)
        if not (match and _WORK_CODE.fullmatch(match.group(1))
                and _EPISODE_CODE.fullmatch(match.group(2))):
            raise ValueError(f"Not a KadoComi episode URL: {chapter_url}")
        work_code, episode_code = match.groups()
        queries = next_data_queries(
            self._get_html(f"{self.base_url}/detail/{work_code}/episodes/{episode_code}"))
        data = query_data(
            queries, _EPISODE_QUERY,
            lambda d: isinstance(d.get("episode"), dict)
            and d["episode"].get("code") == episode_code)
        episode = data["episode"]
        internal = episode.get("internal")
        page_count = internal.get("pageCount") if isinstance(internal, dict) else None
        if episode.get("isActive") is not True:
            raise KadoComiSourceError(f"episode {episode_code} is not publicly available")
        if not (isinstance(episode.get("id"), str) and _UUID.fullmatch(episode["id"])):
            raise KadoComiSourceError(f"episode {episode_code} has no usable id")
        if not (_is_int(page_count) and page_count > 0):
            raise KadoComiSourceError(f"episode {episode_code} has no usable page count")

        try:
            _, pages = viewer_pages(self._viewer_reply(episode["id"]), page_count)
        except KadoComiSourceError as e:
            raise KadoComiSourceError(f"episode {episode_code}: {e}") from None
        with self._pages_lock:
            for url in [u for u, p in self._pages.items() if p.episode == episode_code]:
                del self._pages[url]
            for url, page in pages:
                self._pages[url] = _Page(page.key, page.width, page.height,
                                         page.expires, episode_code)
        return [url for url, _ in pages]

    def download_image(self, url: str, path) -> bool:
        """Download one page and decode it.

        Only pages from the latest get_pages() call of their episode can be
        decoded. A page that is unknown, expired, refused, too large or not
        an image once decoded fails, and any older file at ``path`` is
        removed. Logs name the page host and status, never the URL."""
        path = Path(path)
        with self._pages_lock:
            page = self._pages.get(url)
        if page is None:
            logger.debug("KadoComi page on %s is not from a current page list", _PAGE_HOST)
            return False
        if page.expires <= datetime.now(timezone.utc):
            logger.debug("KadoComi page on %s: its page list has expired", _PAGE_HOST)
            path.unlink(missing_ok=True)
            return False
        try:
            response = self.session.get(url, timeout=30, stream=True, headers={
                "Referer": f"{self.base_url}/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            })
            try:
                if response.status_code >= 400:
                    logger.debug("KadoComi page on %s: HTTP %d", _PAGE_HOST,
                                 response.status_code)
                    path.unlink(missing_ok=True)
                    return False
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > _MAX_PAGE_BYTES:
                        logger.debug("KadoComi page on %s is too large", _PAGE_HOST)
                        path.unlink(missing_ok=True)
                        return False
                    chunks.append(chunk)
            finally:
                response.close()
        except requests.RequestException as e:
            logger.debug("KadoComi page on %s failed (%s)", _PAGE_HOST, type(e).__name__)
            path.unlink(missing_ok=True)
            return False

        content = _xor(b"".join(chunks), page.key)
        if not self._is_page(content, page):
            path.unlink(missing_ok=True)
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return True

    @staticmethod
    def _is_page(content: bytes, page: _Page) -> bool:
        """Whether decoded bytes are an image of the page's own size."""
        if not _identifies_as_image(content):
            logger.debug("KadoComi page on %s is not an image once decoded", _PAGE_HOST)
            return False
        try:
            with open_image(BytesIO(content)) as image:
                size = image.size
        except ImageTooLargeError:
            logger.debug("KadoComi page on %s is over the page size limit", _PAGE_HOST)
            return False
        except Exception as e:
            logger.debug("KadoComi page on %s could not be read (%s)", _PAGE_HOST,
                         type(e).__name__)
            return False
        if size != (page.width, page.height):
            logger.debug("KadoComi page on %s is %dx%d, its page list says %dx%d",
                         _PAGE_HOST, size[0], size[1], page.width, page.height)
            return False
        return True
