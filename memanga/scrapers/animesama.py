"""
Anime-Sama scans: French manga scans published on anime-sama.to.

https://anime-sama.to

A series page lists its scan panels. One French panel is read: the one
labelled "Scans (noir et blanc)" when present, otherwise the only French
panel. Any other mix raises. The label is the site's; nothing here promises
which art edition its images are.

The panel's viewer builds its chapter list from a count map of
``{folder: page count}`` and the page's list commands. A chapter's folder is
its position in that list, which can differ from the number in its label:
after a special such as "One Shot", "Chapitre 1199" is folder 1200. So a
chapter keeps its label as its number and carries its folder in a client-only
``#dossier=<folder>`` fragment that is never sent to the site.

The work title is used exactly as the viewer reads it, the heading's
``innerHTML``, trailing spaces included. A list position without pages is
what the viewer shows as not yet available: it is left out with a warning.
A special has no chapter number, so the app sorts it as 0 and does not offer
it as a new update.
"""

import contextlib
import http.cookiejar
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup, NavigableString

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_SITE_HOSTS = frozenset({"anime-sama.to", "www.anime-sama.to"})
_IMAGE_HOST = "anime-sama.to"
_SLUG = re.compile(r"[A-Za-z0-9._~-]+")
_BW_PANEL = "Scans (noir et blanc)"
_FRENCH_PANEL = re.compile(r"scan[a-z0-9_-]*/vf")
_NO_RESULTS = "Aucun résultat trouvé, vérifiez bien votre recherche."
_FOLDER = re.compile(r"[1-9][0-9]{0,5}")
_FRAGMENT = re.compile(r"dossier=([1-9][0-9]{0,5})")
_IMAGE_PATH = re.compile(r"/s2/scans/[^/]+/[1-9][0-9]{0,5}/[1-9][0-9]{0,4}\.jpg")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)
_PANEL_MENTION = re.compile(r"panneauScan\(\s*[\"']")
_PANEL_CALL = re.compile(r'panneauScan\(\s*"([^"\\]*)"\s*,\s*"([^"\\]*)"\s*\)\s*;')
_LIST_CALL = re.compile(r"\b(?:resetListe|creerListe|newSPF?|finirListe)\(")
_READY_BLOCK = re.compile(r"\$\(document\)\.ready\(function\(\)\s*\{(.*)\}\s*\)\s*;?", re.S)
_COMMAND = re.compile(
    r"\s*(?:(?P<reset>resetListe)\(\s*\)"
    r"|creerListe\(\s*(?P<first>[0-9]{1,6})\s*,\s*(?P<last>[0-9]{1,6})\s*\)"
    r'|newSP\(\s*"(?P<special>[^"\\]+)"\s*\)'
    r"|finirListe\(\s*(?P<rest>[0-9]{1,6})\s*\))\s*;")

# encodeURIComponent's unescaped characters, and those a browser leaves
# as they are in a URL path.
_COMPONENT_SAFE = "-_.!~*'()"
_PATH_SAFE = "-_.!~*'()$&+,;=:@[]|"
_UNSAFE_IN_TITLE = frozenset("/\\?#%")

# Upper bounds no real page comes near. Going past one is an error, never
# a cut-off list. Search reads one page of results.
_MAX_SEARCH_RESULTS = 40
_MAX_CHAPTERS = 20000
_MAX_PAGES = 2000
_MAX_BODY_BYTES = 16 * 1024 * 1024


class AnimeSamaSourceError(RuntimeError):
    """The site did not serve what was asked for: an unexpected status or
    redirect, a page without its expected structure, an unclear choice of
    panel, or a chapter list that cannot be read as served."""


class AnimeSamaUnsupportedError(ValueError):
    """A URL that is not one of this site's series or chapter identities."""


def _live_script(text: str) -> str:
    """Script text without its block comments and whole-line comments."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _inner_html(element) -> str:
    """The element's ``innerHTML`` as a browser serializes plain text.
    Raises ValueError when it holds anything but text."""
    if any(type(part) is not NavigableString for part in element.contents):
        raise ValueError("title holds more than text")
    text = "".join(element.contents)
    return (text.replace("&", "&amp;").replace("\xa0", "&nbsp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _scan_panels(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """``(label, path)`` of every live ``panneauScan`` call."""
    panels: List[Tuple[str, str]] = []
    for script in soup.find_all("script"):
        text = _live_script(script.string or "")
        if not _PANEL_MENTION.search(text):
            continue
        if _PANEL_CALL.sub("", text).strip():
            raise ValueError("a scan panel script holds other statements")
        panels.extend(_PANEL_CALL.findall(text))
    return panels


def _choose_panel(panels: List[Tuple[str, str]]) -> str:
    """The path of the panel to read. Raises ValueError unless the choice
    is clear."""
    french = [(label, path) for label, path in panels if path.endswith("/vf")]
    for _, path in french:
        if not _FRENCH_PANEL.fullmatch(path):
            raise ValueError(f"unexpected French panel {path!r}")
    labelled = [path for label, path in french if label == _BW_PANEL]
    if len(labelled) == 1:
        return labelled[0]
    if not labelled and len(french) == 1:
        return french[0][1]
    raise ValueError(f"{len(french)} French scan panels with no single choice")


def _list_commands(soup: BeautifulSoup) -> List[tuple]:
    """The live list commands of a panel page, in order. Anything the
    viewer's list could mean differently raises ValueError."""
    blocks = [text for text in (_live_script(s.string or "") for s in soup.find_all("script"))
              if _LIST_CALL.search(text)]
    if not blocks:
        return []
    if len(blocks) != 1:
        raise ValueError("several chapter list scripts")
    ready = _READY_BLOCK.fullmatch(blocks[0].strip())
    if ready is None:
        raise ValueError("chapter list script in an unknown form")
    body = ready.group(1)
    commands: List[tuple] = []
    position = 0
    while body[position:].strip():
        match = _COMMAND.match(body, position)
        if match is None:
            raise ValueError(f"unknown list command near {body[position:position + 40].strip()!r}")
        position = match.end()
        if match["reset"]:
            commands.append(("reset",))
        elif match["first"]:
            commands.append(("range", int(match["first"]), int(match["last"])))
        elif match["rest"]:
            commands.append(("rest", int(match["rest"])))
        else:
            special = match["special"].strip()
            if not special or any(c.isdigit() for c in special):
                raise ValueError(f"special chapter in an unknown form: {special!r}")
            commands.append(("special", special))
    return commands


def _option_labels(commands: List[tuple], highest: int) -> List[str]:
    """The viewer's chapter options, in order, as it builds them. A label
    is a chapter number or a special's name. ``highest`` is the largest
    folder in the count map."""
    if not commands:
        return [str(n) for n in range(1, highest + 1)]
    labels: List[str] = []
    specials = 0

    def extend(first: int, last: int) -> None:
        if last - first + 1 + len(labels) > _MAX_CHAPTERS:
            raise ValueError("more chapters than this source reads")
        labels.extend(str(n) for n in range(first, last + 1))

    for command in commands:
        if command[0] == "reset":
            labels.clear()
        elif command[0] == "range":
            extend(command[1], command[2])
        elif command[0] == "special":
            labels.append(command[1])
            specials += 1
        else:
            extend(command[1], highest - specials)
    if len(set(labels)) != len(labels):
        raise ValueError("one chapter label on two list positions")
    return labels


class AnimeSamaScraper(BaseScraper):
    """anime-sama.to scans, through the site's published viewer."""

    name = "animesama"
    base_url = "https://anime-sama.to"
    content_language = "fr"

    def __init__(self):
        super().__init__()
        # Nothing here needs a cookie, so none are kept or sent back.
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── URLs ─────────────────────────────────────────────────────────

    def _own_parts(self, url: str):
        refused = AnimeSamaUnsupportedError(f"Not a {self.name} page: {url!r}")
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise refused
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise refused from None
        if (parts.scheme not in ("https", "http") or "@" in parts.netloc
                or port is not None or (parts.hostname or "") not in _SITE_HOSTS
                or parts.query):
            raise refused
        return parts

    def _series_slug(self, url: str) -> str:
        parts = self._own_parts(url)
        path = parts.path[:-1] if parts.path.endswith("/") else parts.path
        segments = path.split("/")[1:]
        if (parts.fragment or len(segments) != 2 or segments[0] != "catalogue"
                or not _SLUG.fullmatch(segments[1]) or segments[1] in (".", "..")):
            raise AnimeSamaUnsupportedError(f"Not a {self.name} series page: {url!r}")
        return segments[1]

    def _chapter_ref(self, url: str) -> Tuple[str, int]:
        """``(panel URL, folder)`` of a chapter identity."""
        parts = self._own_parts(url)
        match = _FRAGMENT.fullmatch(parts.fragment)
        segments = parts.path.split("/")[1:]
        if (match is None or len(segments) != 5 or segments[0] != "catalogue"
                or segments[4] != "" or not _SLUG.fullmatch(segments[1])
                or segments[1] in (".", "..")
                or not _FRENCH_PANEL.fullmatch(f"{segments[2]}/{segments[3]}")):
            raise AnimeSamaUnsupportedError(f"Not a {self.name} chapter: {url!r}")
        return (f"{self.base_url}/catalogue/{segments[1]}/{segments[2]}/{segments[3]}/",
                int(match.group(1)))

    def _image_path(self, url) -> Optional[str]:
        """The path of a page image in the viewer's form, or None."""
        if not isinstance(url, str) or not url or any(
                c.isspace() or ord(c) < 32 for c in url):
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if (parts.scheme != "https" or parts.netloc != _IMAGE_HOST
                or parts.query or parts.fragment
                or ".." in parts.path.split("/")
                or not _IMAGE_PATH.fullmatch(parts.path)):
            return None
        return parts.path

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str):
        """GET ``url`` without following redirects; only a 200 counts."""
        response = self._request(url, allow_redirects=False)
        if response.status_code != 200:
            raise AnimeSamaSourceError(
                f"{self.name} {what} {url} answered HTTP {response.status_code}")
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise AnimeSamaSourceError(f"{self.name} {what} {url} is too large")
        return response

    def _soup(self, response, what: str) -> BeautifulSoup:
        try:
            return BeautifulSoup((response.content or b"").decode("utf-8"), "html.parser")
        except UnicodeDecodeError:
            raise AnimeSamaSourceError(f"{self.name} {what} is not UTF-8") from None

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """The first page of the catalogue's scans search. No results is
        only the site's own notice; any other page without result cards
        raises. A card without the Scans badge is left out."""
        query = (query or "").strip()
        if not query:
            return []
        url = (f"{self.base_url}/catalogue/?type%5B%5D=Scans"
               f"&search={quote(query, safe='')}&page=1")
        catalog = self._soup(self._fetch(url, "search"), "search").select_one("div#list_catalog")
        if catalog is None:
            raise AnimeSamaSourceError(f"{self.name} search {url} did not serve a catalogue")
        cards = catalog.select("div.as-carte")
        notices = [" ".join(p.get_text(" ", strip=True).split()) for p in catalog.find_all("p")]
        if not cards:
            if notices == [_NO_RESULTS]:
                return []
            raise AnimeSamaSourceError(f"{self.name} search {url} did not serve results")
        if _NO_RESULTS in notices:
            raise AnimeSamaSourceError(f"{self.name} search {url} serves results and no results")

        results: List[Manga] = []
        seen = set()
        for card in cards:
            link = card.select_one("a.as-carte-lien[href]")
            heading = card.select_one("h3.as-carte-titre")
            title = " ".join(heading.get_text(" ", strip=True).split()) if heading else ""
            if link is None or not title:
                raise AnimeSamaSourceError(
                    f"{self.name} search {url} lists a result without its link or title")
            if card.select_one("span.as-badge-scan") is None:
                continue
            try:
                slug = self._series_slug(link["href"].strip())
            except AnimeSamaUnsupportedError:
                raise AnimeSamaSourceError(
                    f"{self.name} search {url} lists {link['href']!r}, not a series "
                    f"of this site") from None
            series_url = f"{self.base_url}/catalogue/{slug}/"
            if series_url in seen:
                continue
            seen.add(series_url)
            results.append(Manga(title=title, url=series_url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        return results

    # ── Panel ────────────────────────────────────────────────────────

    def _count_map(self, title: str, what: str) -> Dict[int, int]:
        url = (f"{self.base_url}/s2/scans/get_nb_chap_et_img.php"
               f"?oeuvre={quote(title, safe=_COMPONENT_SAFE)}")
        response = self._fetch(url, "page count")
        try:
            data = response.json()
        except ValueError:
            raise AnimeSamaSourceError(f"{self.name} page count of {what} is not JSON") from None
        if not isinstance(data, dict) or not data:
            raise AnimeSamaSourceError(f"{self.name} {what} has no page counts")
        counts: Dict[int, int] = {}
        for key, value in data.items():
            if (not _FOLDER.fullmatch(key) or int(key) > _MAX_CHAPTERS
                    or not isinstance(value, int) or isinstance(value, bool)
                    or not 0 <= value <= _MAX_PAGES):
                raise AnimeSamaSourceError(
                    f"{self.name} {what} has an unreadable page count ({key!r}: {value!r})")
            counts[int(key)] = value
        return counts

    def _read_panel(self, panel_url: str) -> Tuple[str, Dict[int, Tuple[str, int]], int, int]:
        """``(title, {folder: (label, pages)}, positions without pages,
        folders with pages that no list position reaches)``."""
        what = f"panel {panel_url}"
        soup = self._soup(self._fetch(panel_url, "panel"), what)
        headings = soup.select("h1#titreOeuvre")
        canonical = soup.select_one('link[rel="canonical"]')
        viewer = any((s.get("src") or "").startswith("/js/contenu/scans.js")
                     for s in soup.find_all("script"))
        if (len(headings) != 1 or canonical is None or canonical.get("href") != panel_url
                or soup.select_one("select#selectChapitres") is None or not viewer):
            raise AnimeSamaSourceError(f"{self.name} {what} is not this panel's viewer")
        try:
            title = _inner_html(headings[0])
            commands = _list_commands(soup)
        except ValueError as e:
            raise AnimeSamaSourceError(f"{self.name} {what}: {e}") from None
        if (not title.strip() or any(c in _UNSAFE_IN_TITLE or ord(c) < 32 for c in title)):
            raise AnimeSamaSourceError(f"{self.name} {what} has an unusable title {title!r}")

        counts = self._count_map(title, what)
        try:
            labels = _option_labels(commands, max(counts))
        except ValueError as e:
            raise AnimeSamaSourceError(f"{self.name} {what}: {e}") from None
        entries: Dict[int, Tuple[str, int]] = {}
        missing = 0
        for folder, label in enumerate(labels, 1):
            pages = counts.get(folder, 0)
            if pages:
                entries[folder] = (label, pages)
            else:
                missing += 1
        unlisted = sum(1 for folder, pages in counts.items() if pages and folder > len(labels))
        if not entries:
            raise AnimeSamaSourceError(f"{self.name} {what} lists no chapter with pages")
        return title, entries, missing, unlisted

    # ── Chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' chapters in the viewer's order, newest first.
        Each keeps its label as its number and its folder in the URL."""
        slug = self._series_slug(manga_url)
        series_url = f"{self.base_url}/catalogue/{slug}/"
        soup = self._soup(self._fetch(series_url, "series page"), f"series {series_url}")
        if soup.select_one("h1#titreOeuvre") is None:
            raise AnimeSamaSourceError(f"{self.name} page {series_url} is not a series page")
        try:
            panel = _choose_panel(_scan_panels(soup))
        except ValueError as e:
            raise AnimeSamaSourceError(f"{self.name} series {series_url}: {e}") from None
        panel_url = f"{series_url}{panel}/"
        _, entries, missing, unlisted = self._read_panel(panel_url)
        if missing:
            logger.warning("%s: %d chapter position(s) of %s have no pages yet and were "
                           "not listed", self.name, missing, panel_url)
        if unlisted:
            logger.warning("%s: %d folder(s) of %s have pages but no chapter position and "
                           "were not listed", self.name, unlisted, panel_url)
        return [Chapter(number=label, title=f"Chapitre {label}",
                        url=f"{panel_url}#dossier={folder}")
                for folder, (label, _) in sorted(entries.items(), reverse=True)]

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every page of the chapter's folder, as the viewer builds them.
        The panel and count map are read again, and a folder that no
        longer maps to a chapter with pages raises."""
        panel_url, folder = self._chapter_ref(chapter_url)
        title, entries, _, _ = self._read_panel(panel_url)
        entry = entries.get(folder)
        if entry is None:
            raise AnimeSamaSourceError(
                f"{self.name} panel {panel_url} has no chapter with pages in folder {folder}")
        path = quote(title, safe=_PATH_SAFE)
        return [f"{self.base_url}/s2/scans/{path}/{folder}/{n}.jpg"
                for n in range(1, entry[1] + 1)]

    def download_image(self, url: str, path: Path) -> bool:
        """Save one page, sent with the site as Referer. The bytes decide
        whether it is an image, whatever its extension says. Any failure
        returns False and leaves no older file behind."""
        path = Path(path)
        saved = False
        try:
            if self._image_path(url) is None:
                logger.warning("%s: refused a page URL off its image path: %s", self.name, url)
            else:
                response = self._request(url, allow_redirects=False,
                                         headers={"Referer": f"{self.base_url}/"})
                content = response.content if response.status_code == 200 else b""
                if _identifies_as_image(content):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    saved = True
                else:
                    logger.warning("%s: page is not an image (HTTP %s, %d bytes): %s", self.name,
                                   response.status_code, len(content or b""), url)
        except Exception as e:
            logger.error("%s: failed to download page %s: %s", self.name, url, e)
        if not saved:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        return saved
