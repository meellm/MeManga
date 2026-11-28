"""
LanorTrad: a French manga translation team.

https://lanortrad.com

The site's reader is a single page app that loads its data from three
script files, read here as data and never run:

- ``/js/data/series.js``: the catalogue, a ``window.SERIES = [...]``
  object literal (unquoted keys, ``//`` comment lines).
- ``/js/data/chapters.js``: the chapter index, the argument of
  ``return expand({...})``, and ``window.CHAPTER_PAGES``, the pages file
  of each series. ``expand`` is checked to apply only the folder rule
  this source reads: a row's ``f`` folder, else its or the series' ``p``
  prefix followed by the chapter number. Any other form fails.
- ``/js/data/pages/<series>.js``: each chapter's page file names.

A page is ``/Manga/<series id>/<folder>/<file>`` on the site, built from
those served parts. The site answers it with a redirect to the same path
on ``images.lanortrad.com``; that one redirect is followed and nothing
else.

The catalogue marks with ``demo: true`` the series whose chapters are
actually on the site ("chapitres reellement copies et lisibles"). Only
those are read; the others are refused with a message. One-shots, and
series that are not manga, manhwa, manhua or webtoons or carry an adult
genre, are refused too.
"""

import contextlib
import http.cookiejar
import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOST = "lanortrad.com"
_IMAGE_HOST = "images.lanortrad.com"
_SERIES_FILE = "js/data/series.js"
_INDEX_FILE = "js/data/chapters.js"
_PAGES_FILE = re.compile(r"js/data/pages/[A-Za-z0-9._-]+\.js")
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]*\.(?:webp|jpe?g|png)")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,3})?")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CHAPTER_SEGMENT = re.compile(r"chapitre-(" + _NUMBER.pattern + r")")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PAGE_URL = re.compile(r"https://lanortrad\.com/Manga/[^?#\s]+")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
# The folder rule of the site's ``expand``, the only one this source reads.
_EXPAND_FOLDER = ("var folder = o.f !== undefined ? o.f : "
                  "(o.p !== undefined ? o.p : d.p) + c[0];")
_EXPAND_ENTRY = "var e = { num: c[0], folder: folder, pages: c[1] };"

_SERIES_TYPES = frozenset({"manga", "manhwa", "manhua", "webtoon"})
_ADULT_GENRES = frozenset({"adulte", "adult", "hentai", "smut", "érotique", "erotique",
                           "18+", "nsfw"})

# Upper bounds no real answer comes near. Going past one is an error, never
# a cut-off list.
_MAX_BODY_BYTES = 16 * 1024 * 1024
_MAX_CHAPTERS = 5000
_MAX_PAGES = 2000


class LanorTradSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a data file this source cannot read, or a series, chapter or
    page form it does not support."""


class LanorTradUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter links."""


def _slugify(text: str) -> str:
    """The site's URL name of a series id, as its links build it."""
    plain = "".join(c for c in unicodedata.normalize("NFD", text)
                    if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower()


def _quote_keys(text: str) -> str:
    """``text`` with every unquoted object key quoted, outside strings."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            k = j
            while k < n and text[k].isspace():
                k += 1
            if k < n and text[k] == ":":
                out.append(f'"{text[i:j]}":')
                i = k + 1
            else:
                out.append(text[i:j])
                i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _literal_after(text: str, marker: str, what: str):
    """The JSON value that follows the single ``marker`` in ``text``, and
    the text after it."""
    if text.count(marker) != 1:
        raise LanorTradSourceError(f"lanortrad {what} does not hold one {marker!r}")
    rest = text.split(marker, 1)[1].lstrip()
    try:
        value, end = json.JSONDecoder().raw_decode(rest)
    except ValueError:
        raise LanorTradSourceError(f"lanortrad {what} is not data this source reads") from None
    return value, rest[end:]


def _valid_date(value) -> Optional[str]:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


class LanorTradScraper(BaseScraper):
    """lanortrad.com, over the data files its reader loads."""

    name = "lanortrad"
    base_url = "https://lanortrad.com"
    engine = "http"
    content_language = "fr"
    # Adult genres are refused; none was served.
    nsfw = False

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── Requests ─────────────────────────────────────────────────────

    def _text(self, path: str, what: str) -> str:
        """GET a site file without following redirects; only a 200 counts."""
        url = f"{self.base_url}/{path}"
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise LanorTradSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise LanorTradSourceError(f"{self.name} {what} {url} is too large")
        return response.text

    # ── Data files ───────────────────────────────────────────────────

    def _catalogue(self) -> List[dict]:
        text = self._text(_SERIES_FILE, "catalogue")
        kept = "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("//"))
        value, rest = _literal_after(_quote_keys(kept), "window.SERIES =", "catalogue")
        if rest.strip() not in (";", ""):
            raise LanorTradSourceError(f"{self.name} catalogue has text after its list")
        if not isinstance(value, list) or not value:
            raise LanorTradSourceError(f"{self.name} catalogue lists no series")
        ids = set()
        for entry in value:
            if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                    or not entry["id"].strip() or not isinstance(entry.get("title"), str)
                    or not entry["title"].strip() or entry["id"] in ids):
                raise LanorTradSourceError(f"{self.name} catalogue has an unreadable series")
            ids.add(entry["id"])
        return value

    def _index(self) -> Tuple[dict, Dict[str, str]]:
        """``(chapter index, pages file of each series)``."""
        text = self._text(_INDEX_FILE, "chapter index")
        code = " ".join(text.split())
        if _EXPAND_FOLDER not in code or _EXPAND_ENTRY not in code:
            raise LanorTradSourceError(
                f"{self.name} chapter index builds its folders in a way this source does "
                f"not read")
        index, rest = _literal_after(text, "return expand(", "chapter index")
        if not rest.startswith(")") or not isinstance(index, dict):
            raise LanorTradSourceError(f"{self.name} chapter index is not data this source reads")
        pages, _ = _literal_after(text, "window.CHAPTER_PAGES =", "chapter index")
        if (not isinstance(pages, dict)
                or not all(isinstance(k, str) and isinstance(v, str) and _PAGES_FILE.fullmatch(v)
                           for k, v in pages.items())):
            raise LanorTradSourceError(f"{self.name} chapter index has an unreadable pages map")
        return index, pages

    # ── Series ───────────────────────────────────────────────────────

    def _series_url(self, entry: dict) -> str:
        """The catalogue's own link to a series, which must name its id."""
        url = urljoin(f"{self.base_url}/", entry.get("url") or "")
        parts = urlsplit(url)
        if (parts.netloc != _SITE_HOST or parts.path != "/manga.html"
                or parse_qs(parts.query).get("id") != [entry["id"]]):
            raise LanorTradSourceError(
                f"{self.name} series {entry['id']!r} links to {entry.get('url')!r}")
        return url

    def _refusal(self, entry: dict) -> Optional[str]:
        """Why a series is not read, or None."""
        kind = entry.get("type")
        genres = entry.get("genres", [])
        if not isinstance(genres, list) or not all(isinstance(g, str) for g in genres):
            return "its genres are unreadable"
        if any(g.strip().casefold() in _ADULT_GENRES for g in genres):
            return "it has an adult genre"
        if kind == "oneshot":
            return "one-shots are not read yet"
        if not isinstance(kind, str) or kind.casefold() not in _SERIES_TYPES:
            return f"its type {kind!r} is not manga, manhwa, manhua or webtoon"
        if entry.get("demo") is not True:
            return "the site does not mark its chapters as readable (demo)"
        return None

    def _parse_series_url(self, url: str) -> Tuple[str, str]:
        """``("id", value)`` or ``("slug", value)`` of a series link."""
        refused = LanorTradUnsupportedError(f"Not a {self.name} series page: {url!r}")
        if not isinstance(url, str) or any(ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
        except ValueError:
            raise refused from None
        if parts.scheme != "https" or parts.netloc != _SITE_HOST or parts.fragment:
            raise refused
        if parts.path == "/manga.html":
            ids = parse_qs(parts.query).get("id")
            if not ids or len(ids) != 1 or not ids[0].strip():
                raise refused
            return "id", ids[0]
        segments = parts.path.strip("/").split("/")
        if parts.query or len(segments) != 2 or segments[0] != "manga" \
                or not _SLUG.fullmatch(segments[1]):
            raise refused
        return "slug", segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, str]:
        """``(series slug, chapter number)`` of a chapter link."""
        refused = LanorTradUnsupportedError(f"Not a {self.name} chapter link: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
        except ValueError:
            raise refused from None
        segments = parts.path.strip("/").split("/")
        if (parts.scheme != "https" or parts.netloc != _SITE_HOST or parts.query
                or parts.fragment or len(segments) != 3 or segments[0] != "manga"
                or not _SLUG.fullmatch(segments[1])):
            raise refused
        match = _CHAPTER_SEGMENT.fullmatch(segments[2])
        if match is None:
            raise refused
        return segments[1], match.group(1)

    def _find(self, catalogue: List[dict], kind: str, value: str) -> dict:
        if kind == "id":
            found = [e for e in catalogue if e["id"] == value]
        else:
            found = [e for e in catalogue if _slugify(e["id"]) == value]
        if len(found) != 1:
            raise LanorTradSourceError(
                f"{self.name} catalogue has {len(found)} series for {value!r}")
        return found[0]

    def _readable(self, catalogue: List[dict], kind: str, value: str) -> dict:
        entry = self._find(catalogue, kind, value)
        reason = self._refusal(entry)
        if reason:
            raise LanorTradSourceError(
                f"{self.name} series {entry['id']!r} is not read: {reason}")
        return entry

    def _rows(self, index: dict, series_id: str) -> List[Tuple[str, int, str, Optional[str]]]:
        """``(number, page count, folder, date)`` of each indexed chapter."""
        node = index.get(series_id)
        rows = node.get("c") if isinstance(node, dict) else None
        if not isinstance(rows, list) or not rows:
            raise LanorTradSourceError(f"{self.name} series {series_id!r} has no indexed chapters")
        if len(rows) > _MAX_CHAPTERS:
            raise LanorTradSourceError(
                f"{self.name} series {series_id!r} lists more chapters than this source reads")
        result = []
        for row in rows:
            opts = row[2] if isinstance(row, list) and len(row) == 3 else {}
            if (not isinstance(row, list) or len(row) not in (2, 3)
                    or not isinstance(row[0], str) or not _NUMBER.fullmatch(row[0])
                    or type(row[1]) is not int or not 0 < row[1] <= _MAX_PAGES
                    or not isinstance(opts, dict)):
                raise LanorTradSourceError(
                    f"{self.name} series {series_id!r} has an index row this source cannot "
                    f"read ({row!r:.80})")
            if "f" in opts:
                folder = opts["f"]
            else:
                prefix = opts.get("p", node.get("p"))
                folder = prefix + row[0] if isinstance(prefix, str) else None
            parts = folder.split("/") if isinstance(folder, str) else []
            if not parts or any(not p or p in (".", "..") or p != p.strip() for p in parts):
                raise LanorTradSourceError(
                    f"{self.name} series {series_id!r} chapter {row[0]} has no usable folder")
            result.append((row[0], row[1], folder, _valid_date(opts.get("d"))))
        numbers = [r[0] for r in result]
        if len(set(numbers)) != len(numbers):
            raise LanorTradSourceError(f"{self.name} series {series_id!r} lists a chapter twice")
        return result

    def _chapter_url(self, series_id: str, number: str) -> str:
        return f"{self.base_url}/manga/{_slugify(series_id)}/chapitre-{number}/"

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Readable series whose title contains ``query``, ignoring case and
        spacing. A matching series that is not read is left out with a
        warning."""
        wanted = " ".join((query or "").split()).casefold()
        if not wanted:
            return []
        results: List[Manga] = []
        left_out = []
        for entry in self._catalogue():
            title = " ".join(entry["title"].split())
            if wanted not in title.casefold():
                continue
            reason = self._refusal(entry)
            if reason:
                left_out.append(f"{title} ({reason})")
                continue
            results.append(Manga(title=title, url=self._series_url(entry)))
        if left_out:
            logger.warning("%s: %d matching series are not read and were left out: %s",
                           self.name, len(left_out), "; ".join(left_out))
        return results

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The series' indexed chapters, newest first."""
        kind, value = self._parse_series_url(manga_url)
        entry = self._readable(self._catalogue(), kind, value)
        index, pages = self._index()
        if entry["id"] not in pages:
            raise LanorTradSourceError(f"{self.name} series {entry['id']!r} has no pages file")
        chapters = [Chapter(number=number, title=None, url=self._chapter_url(entry["id"], number),
                            date=date)
                    for number, _, _, date in self._rows(index, entry["id"])]
        return sorted(chapters, key=lambda c: c.numeric, reverse=True)

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """The chapter's pages in served order, at the site paths built from
        the series id, the index folder and the pages file names."""
        slug, number = self._chapter_ref(chapter_url)
        entry = self._readable(self._catalogue(), "slug", slug)
        series_id = entry["id"]
        index, pages_files = self._index()
        rows = {r[0]: r for r in self._rows(index, series_id)}
        if number not in rows or series_id not in pages_files:
            raise LanorTradSourceError(
                f"{self.name} series {series_id!r} has no indexed chapter {number}")
        _, count, folder, _ = rows[number]

        text = self._text(pages_files[series_id], "pages file")
        marker = f"window.CHAPTER_FILES[{json.dumps(series_id, ensure_ascii=False)}] ="
        files_map, rest = _literal_after(text, marker, "pages file")
        if not rest.startswith(";") or not isinstance(files_map, dict):
            raise LanorTradSourceError(f"{self.name} pages file of {series_id!r} is unreadable")
        chapter = files_map.get(number)
        files = chapter.get("f") if isinstance(chapter, dict) else None
        if (not isinstance(files, list) or not files
                or not all(isinstance(f, str) and _FILE_NAME.fullmatch(f) for f in files)):
            raise LanorTradSourceError(
                f"{self.name} pages file of {series_id!r} has no readable pages for "
                f"chapter {number}")
        if len(files) != count or len(set(files)) != len(files):
            raise LanorTradSourceError(
                f"{self.name} chapter {number} of {series_id!r} lists {len(files)} pages "
                f"but its index counts {count}")
        base = "/".join(quote(part, safe="") for part in [series_id, *folder.split("/")])
        return [f"{self.base_url}/Manga/{base}/{quote(name, safe='')}" for name in files]

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """No cover is read, so adding a series sends no request."""
        return None

    # ── Download ─────────────────────────────────────────────────────

    def _image_location(self, url: str, response) -> Optional[str]:
        """The redirect target when it is the same path on the image host."""
        location = urljoin(url, response.headers.get("Location") or "")
        target, origin = urlsplit(location), urlsplit(url)
        if (target.scheme == "https" and target.netloc == _IMAGE_HOST
                and target.path == origin.path and not target.fragment):
            return location
        return None

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page. The site path is asked first; its one redirect to
        the same path on the image host is followed. Both are sent with the
        site as Referer. Any failure returns False and leaves no older file
        behind."""
        path = Path(path)
        saved = False
        headers = {"Referer": f"{self.base_url}/"}
        try:
            if not isinstance(url, str) or _PAGE_URL.fullmatch(url) is None:
                logger.warning("%s: refused a page URL off its image path: %s", self.name, url)
            else:
                response = self._request(url, allow_redirects=False, headers=headers)
                if response.status_code in _REDIRECTS:
                    location = self._image_location(url, response)
                    if location is None:
                        logger.warning("%s: page %s redirects off its image path: %r", self.name,
                                       url, response.headers.get("Location"))
                        response = None
                    else:
                        response = self._request(location, allow_redirects=False,
                                                 headers=headers)
                content = (response.content if response is not None
                           and response.status_code == 200 else b"")
                if _identifies_as_image(content):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    saved = True
                elif response is not None:
                    logger.warning("%s: page is not an image (HTTP %s, %d bytes): %s", self.name,
                                   response.status_code, len(content or b""), url)
        except Exception as e:
            logger.error("%s: failed to download page %s: %s", self.name, url, e)
        if not saved:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        return saved
