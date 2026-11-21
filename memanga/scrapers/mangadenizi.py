"""
MangaDenizi scraper - Turkish manga, manhwa and webtoon reader
Site: mangadenizi.net

The site is a Nuxt app over a public JSON API:

* search   -> GET /api/v1/web/manga?page=1&q=<query> is a paginator whose
              ``data.manga.data`` rows carry ``title``, ``slug``,
              ``cover_url`` and ``is_adult``.
* chapters -> GET /api/v1/web/manga/<slug> returns ``data.manga`` with every
              chapter in one list. Chapter slugs are served as they are
              (``001`` ... ``099``, ``100`` ...) and are not derived from the
              chapter number.
* pages    -> GET /api/v1/reader/<slug>/<chapter-slug> returns ``pages``,
              each with ``page_number``, ``image_url`` and ``scramble``.

Reader images are served with their tiles shuffled; ``scramble`` names the
method (``tiled-v1``), the grid size and a seed. The site's reader puts the
tiles back in order before showing a page, and ``download_image`` does the
same with Pillow, saving the result losslessly. The scramble parameters ride
in the page URL's fragment, so every download worker has what it needs; the
fragment is removed before the image is requested and never logged.

Only titles the API marks as not adult are listed and downloaded.
"""

import io
import logging
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "mangadenizi.net"
_IMAGE_HOST = "img.mangadenizi.net"

# A slug as one URL path segment: what the API serves for titles and chapters.
_SLUG = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,199})"
_SLUG_RE = re.compile(rf"^{_SLUG}$")
_SERIES_PATH = re.compile(rf"^/manga/({_SLUG})/?$")
_CHAPTER_PATH = re.compile(rf"^/read/({_SLUG})/({_SLUG})/?$")
_IMAGE_PATH = re.compile(
    r"^/reader-images/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
    r"\.(webp|png|jpe?g)$", re.I)
_PLAIN_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")

# Bounds on what one answer may hold.
_MAX_SEARCH_RESULTS = 20
_MAX_CHAPTERS = 10000
_MAX_PAGES = 1000
_MAX_IMAGE_BYTES = 32 * 1024 * 1024

# The tile scramble this scraper knows how to undo.
SCRAMBLE_METHOD = "tiled-v1"
_MAX_GRID = 64
_MASK32 = 0xFFFFFFFF
# xorshift32 replaces a zero state (which would stay zero) with this one.
_ZERO_STATE = 2463534242
# Salts mixed into the page seed for the column and the row order.
_COLUMN_SALT = 2246822507
_ROW_SALT = 2654435769
_FRAGMENT_RE = re.compile(
    rf"^scramble={re.escape(SCRAMBLE_METHOD)}&grid=(\d{{1,2}})&seed=(\d{{1,10}})$")
# Pillow format each reassembled page is saved in, by URL extension. Both
# are saved losslessly; a scrambled JPEG would need a lossy re-encode and
# is refused.
_LOSSLESS_FORMATS = {".webp": "WEBP", ".png": "PNG"}


class MangaDeniziSourceError(RuntimeError):
    """mangadenizi.net answered with data this scraper cannot use."""


# ──────────────────────────────────────────────────────────────────────
# tiled-v1 tile order
# ──────────────────────────────────────────────────────────────────────


def _xorshift32(state: int) -> Iterator[int]:
    """Marsaglia's 32-bit xorshift (shifts 13, 17, 5) from ``state``."""
    state &= _MASK32
    if state == 0:
        state = _ZERO_STATE
    while True:
        state ^= (state << 13) & _MASK32
        state ^= state >> 17
        state ^= (state << 5) & _MASK32
        yield state


def tile_order(count: int, seed: int) -> List[int]:
    """The shuffled order of ``count`` bands for ``seed``.

    A Fisher-Yates shuffle of 0..count-1 from the last position down, each
    swap partner drawn as ``next % (n + 1)``. Entry ``i`` is the original
    band shown at position ``i`` of the scrambled image.
    """
    order = list(range(count))
    numbers = _xorshift32(seed)
    for n in range(count - 1, 0, -1):
        j = next(numbers) % (n + 1)
        order[n], order[j] = order[j], order[n]
    return order


def _bands(total: int, count: int) -> List[Tuple[int, int]]:
    """``count`` bands that split ``total`` pixels, as (start, end)."""
    return [(i * total // count, (i + 1) * total // count) for i in range(count)]


def unscramble(image, grid: int, seed: int):
    """Put a tiled-v1 page back in order and return the new image.

    The scrambled page packs the original columns left to right in their
    shuffled order, each keeping its own width, and the rows top to bottom
    the same way. The geometry is the decoded image's own size.
    """
    from PIL import Image

    width, height = image.size
    if not 1 <= grid <= min(width, height, _MAX_GRID):
        raise MangaDeniziSourceError(
            f"Unsupported tile grid {grid} for a {width} x {height} page")
    seed &= _MASK32
    columns = _bands(width, grid)
    rows = _bands(height, grid)
    column_order = tile_order(grid, seed ^ _COLUMN_SALT)
    row_order = tile_order(grid, seed ^ _ROW_SALT)

    result = Image.new(image.mode, image.size)
    top_in = 0
    for row in row_order:
        top, bottom = rows[row]
        left_in = 0
        for column in column_order:
            left, right = columns[column]
            box = (left_in, top_in, left_in + right - left, top_in + bottom - top)
            result.paste(image.crop(box), (left, top))
            left_in += right - left
        top_in += bottom - top
    return result


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _chapter_number(raw) -> Optional[str]:
    """A chapter ``number`` as a stable string ("12", "12.5"), or None."""
    if _is_int(raw):
        text = str(raw)
    elif isinstance(raw, float):
        if not math.isfinite(raw):
            return None
        text = repr(raw)
    elif isinstance(raw, str) and _PLAIN_NUMBER.match(raw.strip()):
        text = raw.strip()
    else:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    value = value.normalize()
    return format(value, "f")


def _page_fragment(grid: int, seed: int) -> str:
    return urlencode([("scramble", SCRAMBLE_METHOD), ("grid", grid), ("seed", seed)])


def _split_page_url(url: str) -> Tuple[str, Tuple[int, int], str]:
    """(image URL to request, (grid, seed), extension) of a page URL.

    Raises MangaDeniziSourceError, without echoing the fragment, for a page
    URL this scraper did not produce.
    """
    parts = urlsplit(url or "")
    image_url = urlunsplit(parts._replace(fragment=""))
    path_match = _IMAGE_PATH.match(parts.path)
    if (parts.scheme != "https" or (parts.hostname or "") != _IMAGE_HOST
            or parts.port is not None or parts.query or not path_match):
        raise MangaDeniziSourceError(
            f"Not a MangaDenizi page image: {image_url}")
    fragment = _FRAGMENT_RE.match(parts.fragment)
    if not fragment:
        raise MangaDeniziSourceError(
            f"Page image {image_url} carries no usable scramble parameters")
    grid, seed = int(fragment.group(1)), int(fragment.group(2))
    if not 1 <= grid <= _MAX_GRID or seed > _MASK32:
        raise MangaDeniziSourceError(
            f"Page image {image_url} carries unsupported scramble parameters")
    extension = "." + path_match.group(1).lower()
    return image_url, (grid, seed), extension


class MangaDeniziScraper(BaseScraper):
    """Scraper for MangaDenizi (mangadenizi.net)."""

    name = "mangadenizi"
    base_url = "https://mangadenizi.net"
    content_language = "tr"  # Turkish-language site
    engine = "http"
    nsfw = False  # adult titles are left out

    _API_HEADERS = {
        "Accept": "application/json",
        "Referer": base_url + "/manga",
    }
    _IMAGE_HEADERS = {"Referer": base_url + "/"}

    # URLs

    def _site_path(self, url: str) -> Optional[str]:
        parts = urlsplit(url or "")
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if parts.scheme not in ("http", "https") or host != _HOST:
            return None
        return parts.path

    def _series_slug(self, manga_url: str) -> str:
        path = self._site_path(manga_url)
        match = _SERIES_PATH.match(path) if path is not None else None
        if not match:
            raise MangaDeniziSourceError(f"Not a MangaDenizi series URL: {manga_url}")
        return match.group(1)

    def _chapter_slugs(self, chapter_url: str) -> Tuple[str, str]:
        path = self._site_path(chapter_url)
        match = _CHAPTER_PATH.match(path) if path is not None else None
        if not match:
            raise MangaDeniziSourceError(f"Not a MangaDenizi chapter URL: {chapter_url}")
        return match.group(1), match.group(2)

    def _series_url(self, slug: str) -> str:
        return f"{self.base_url}/manga/{slug}"

    def _chapter_url(self, slug: str, chapter_slug: str) -> str:
        return f"{self.base_url}/read/{slug}/{chapter_slug}"

    def _api(self, path: str):
        url = f"{self.base_url}/api/v1{path}"
        data = self._get_json(url, headers=self._API_HEADERS)
        if not isinstance(data, dict):
            raise MangaDeniziSourceError(f"MangaDenizi returned no JSON object for {url}")
        return data

    @staticmethod
    def _cover(row) -> Optional[str]:
        for key in ("cover_url", "cover_thumb_url"):
            value = row.get(key)
            if isinstance(value, str) and value.startswith("https://"):
                return value
        return None

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search titles through the site's own search API.

        Rows not marked as non-adult are left out.
        """
        query = (query or "").strip()
        if not query:
            return []
        data = self._api("/web/manga?" + urlencode({"page": 1, "q": query}))
        paginator = (data.get("data") or {}).get("manga") if isinstance(
            data.get("data"), dict) else None
        rows = paginator.get("data") if isinstance(paginator, dict) else None
        if not isinstance(rows, list):
            raise MangaDeniziSourceError(
                f"MangaDenizi search for {query!r} returned no result list")

        results = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise MangaDeniziSourceError(
                    f"MangaDenizi search for {query!r} returned a malformed row")
            title, slug = row.get("title"), row.get("slug")
            if (not isinstance(title, str) or not title.strip()
                    or not isinstance(slug, str) or not _SLUG_RE.match(slug)):
                raise MangaDeniziSourceError(
                    f"MangaDenizi search for {query!r} returned a row without "
                    f"a usable title and slug")
            if row.get("is_adult") is not False or slug in seen:
                continue
            seen.add(slug)
            results.append(Manga(
                title=title.strip(),
                url=self._series_url(slug),
                cover_url=self._cover(row),
            ))
        return results[:_MAX_SEARCH_RESULTS]

    # Series

    def _series(self, slug: str) -> Dict:
        """The ``data.manga`` object of a non-adult series."""
        data = self._api(f"/web/manga/{slug}")
        manga = data.get("data", {}).get("manga") if isinstance(
            data.get("data"), dict) else None
        if not isinstance(manga, dict):
            raise MangaDeniziSourceError(f"MangaDenizi returned no series for {slug!r}")
        if manga.get("slug") != slug:
            raise MangaDeniziSourceError(
                f"MangaDenizi answered for another series than {slug!r}")
        if manga.get("is_adult") is not False:
            raise MangaDeniziSourceError(
                f"MangaDenizi does not mark {slug!r} as a non-adult title; "
                f"only non-adult titles are supported")
        return manga

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get every chapter of a series, oldest first.

        Chapter URLs use the slugs the API serves, padding included. A
        number listed twice keeps its first listed release.
        """
        slug = self._series_slug(manga_url)
        manga = self._series(slug)
        rows = manga.get("chapters")
        if not isinstance(rows, list) or not rows:
            raise MangaDeniziSourceError(f"MangaDenizi lists no chapters for {manga_url}")
        if len(rows) > _MAX_CHAPTERS:
            raise MangaDeniziSourceError(
                f"MangaDenizi lists {len(rows)} chapters for {manga_url}, "
                f"more than the {_MAX_CHAPTERS} this scraper accepts")

        chapters = []
        seen_slugs = set()
        seen_numbers = set()
        for row in rows:
            if not isinstance(row, dict):
                raise MangaDeniziSourceError(
                    f"MangaDenizi chapter list for {manga_url} has a malformed row")
            chapter_slug = row.get("slug")
            number = _chapter_number(row.get("number"))
            if not isinstance(chapter_slug, str) or not _SLUG_RE.match(chapter_slug):
                raise MangaDeniziSourceError(
                    f"MangaDenizi chapter list for {manga_url} has a chapter "
                    f"without a usable slug")
            if number is None:
                raise MangaDeniziSourceError(
                    f"MangaDenizi chapter {chapter_slug!r} of {manga_url} has "
                    f"no usable number")
            if chapter_slug in seen_slugs:
                raise MangaDeniziSourceError(
                    f"MangaDenizi lists chapter {chapter_slug!r} of {manga_url} twice")
            seen_slugs.add(chapter_slug)
            if number in seen_numbers:
                logger.debug("MangaDenizi lists chapter %s of %s twice; keeping the first",
                             number, slug)
                continue
            seen_numbers.add(number)

            title = row.get("title")
            published = row.get("published_at")
            chapters.append(Chapter(
                number=number,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                url=self._chapter_url(slug, chapter_slug),
                date=published[:10] if isinstance(published, str) and published else None,
            ))
        return sorted(chapters)

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """The cover from the series API."""
        try:
            return self._cover(self._series(self._series_slug(manga_url)))
        except Exception:
            return None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get the ordered page images of a chapter.

        Each URL carries its scramble parameters in the fragment for
        ``download_image``. Every page must use the supported method, page
        numbers must run 1..N and N must match the chapter's page count.
        """
        slug, chapter_slug = self._chapter_slugs(chapter_url)
        data = self._api(f"/reader/{slug}/{chapter_slug}")

        chapter = data.get("chapter")
        if not isinstance(chapter, dict) or chapter.get("slug") != chapter_slug:
            raise MangaDeniziSourceError(
                f"MangaDenizi reader answered for another chapter than {chapter_url}")
        manga = data.get("manga")
        if isinstance(manga, dict) and "is_adult" in manga:
            if manga.get("is_adult") is not False:
                raise MangaDeniziSourceError(
                    f"MangaDenizi does not mark {slug!r} as a non-adult title; "
                    f"only non-adult titles are supported")
        else:
            self._series(slug)

        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            raise MangaDeniziSourceError(f"MangaDenizi reader lists no pages for {chapter_url}")
        if len(pages) > _MAX_PAGES:
            raise MangaDeniziSourceError(
                f"MangaDenizi reader lists {len(pages)} pages for {chapter_url}, "
                f"more than the {_MAX_PAGES} this scraper accepts")
        expected = chapter.get("pages_count")
        if not _is_int(expected) or expected != len(pages):
            raise MangaDeniziSourceError(
                f"MangaDenizi reader lists {len(pages)} pages for {chapter_url} "
                f"but its chapter says {expected!r}")

        by_number: Dict[int, str] = {}
        for page in pages:
            if not isinstance(page, dict):
                raise MangaDeniziSourceError(
                    f"MangaDenizi reader has a malformed page for {chapter_url}")
            number = page.get("page_number")
            if not _is_int(number) or number in by_number:
                raise MangaDeniziSourceError(
                    f"MangaDenizi reader has a missing or repeated page number "
                    f"for {chapter_url}")
            image_url = page.get("image_url")
            parts = urlsplit(image_url) if isinstance(image_url, str) else None
            if (parts is None or parts.scheme != "https"
                    or (parts.hostname or "") != _IMAGE_HOST or parts.port is not None
                    or parts.query or parts.fragment or not _IMAGE_PATH.match(parts.path)):
                raise MangaDeniziSourceError(
                    f"MangaDenizi reader has an unexpected image URL on page "
                    f"{number} of {chapter_url}")
            by_number[number] = image_url + "#" + self._scramble_fragment(
                page.get("scramble"), number, chapter_url)

        if sorted(by_number) != list(range(1, len(pages) + 1)):
            raise MangaDeniziSourceError(
                f"MangaDenizi reader page numbers for {chapter_url} are not 1..{len(pages)}")
        urls = [by_number[n] for n in sorted(by_number)]
        if len({url.split("#", 1)[0] for url in urls}) != len(urls):
            raise MangaDeniziSourceError(
                f"MangaDenizi reader lists the same image twice for {chapter_url}")
        return urls

    @staticmethod
    def _scramble_fragment(scramble, number: int, chapter_url: str) -> str:
        """The fragment for one page's scramble parameters (never logged)."""
        if not isinstance(scramble, dict) or scramble.get("method") != SCRAMBLE_METHOD:
            method = scramble.get("method") if isinstance(scramble, dict) else None
            raise MangaDeniziSourceError(
                f"MangaDenizi page {number} of {chapter_url} uses an unsupported "
                f"image format (scramble method {str(method)[:40]!r})")
        grid, seed = scramble.get("grid"), scramble.get("seed")
        if (not _is_int(grid) or not 1 <= grid <= _MAX_GRID
                or not _is_int(seed) or not 0 <= seed <= _MASK32):
            raise MangaDeniziSourceError(
                f"MangaDenizi page {number} of {chapter_url} has unsupported "
                f"scramble parameters")
        return _page_fragment(grid, seed)

    # Images

    def download_image(self, url: str, path) -> bool:
        """Download one page, put its tiles back in order and save it.

        The page is saved losslessly in its own format (WEBP or PNG). Any
        failure leaves no file at ``path``; a page over the pixel limit
        raises ImageTooLargeError like every other page.
        """
        from ..image_limits import ImageTooLargeError

        path = Path(path)
        image_url = "a MangaDenizi page"  # what failures name; never the fragment
        try:
            image_url, (grid, seed), extension = _split_page_url(url)
            response = self._request(image_url, headers=self._IMAGE_HEADERS)
            content = response.content
            if not content or len(content) > _MAX_IMAGE_BYTES:
                raise MangaDeniziSourceError(
                    f"{image_url} returned {len(content or b'')} bytes")
            if not _identifies_as_image(content):
                raise MangaDeniziSourceError(f"{image_url} did not return an image")
            data = self._reassemble(content, grid, seed, extension, image_url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return True
        except ImageTooLargeError:
            path.unlink(missing_ok=True)
            raise
        except Exception as e:
            path.unlink(missing_ok=True)
            logger.debug("Failed to download %s: %s", image_url, e)
            return False

    @staticmethod
    def _reassemble(content: bytes, grid: int, seed: int, extension: str,
                    image_url: str) -> bytes:
        """The reassembled page, encoded losslessly in its own format."""
        from ..image_limits import open_image

        target = _LOSSLESS_FORMATS.get(extension)
        with open_image(io.BytesIO(content)) as image:
            if target is None or image.format != target:
                raise MangaDeniziSourceError(
                    f"{image_url} is {image.format or 'an unknown format'}; only "
                    f"WEBP and PNG pages can be reassembled without loss")
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                has_alpha = "A" in image.mode or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
            page = unscramble(image, grid, seed)
        out = io.BytesIO()
        if target == "WEBP":
            page.save(out, format="WEBP", lossless=True)
        else:
            page.save(out, format="PNG")
        return out.getvalue()
