"""
MangaBolt scraper
https://mangabolt.com

Search uses the site's /search?q= results. Series pages live at
/series/<id>/<slug> and list their chapters as /chapters/<id> links.
A chapter page lists its pages in a reader-manifest JSON script.
"""

import json
import logging
import re
from typing import Dict, List
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import (BaseScraper, Chapter, Manga, BROWSER_USER_AGENT_SHORT,
                   _identifies_as_image)

logger = logging.getLogger(__name__)

_HOST = "mangabolt.com"
_SERIES_PATH = re.compile(r"^/series/([A-Za-z0-9]+)/([^/]+)/?$")
# The address saved series had before the site moved to /series/<id>/<slug>.
_LEGACY_SERIES_PATH = re.compile(r"^/manga/([^/]+)/?$")
_CHAPTER_PATH = re.compile(r"^/chapters/[A-Za-z0-9]+/?$")
# A series page names its own chapters "Chapter 12" or "Chapter 12.5",
# followed by how long ago they were added; links to other series'
# chapters put the series title first.
_OWN_CHAPTER_TEXT = re.compile(r"^Chapter\s+(\d+(?:\.\d+)?)(?!\S)", re.I)
_COVER_PREFIX = "cover for "
# Reader page images: https://cdn.mangabolt.com/file/mangap/<n>/<n>/<n>.<ext>
_PAGE_HOST = "cdn.mangabolt.com"
_PAGE_PATH = re.compile(r"^/file/mangap/\d+/\d+/\d+\.(?:jpe?g|png|webp)$", re.I)
_PAGE_COUNTER = re.compile(r"\bPage\s+\d+\s+of\s+(\d+)\b", re.I)


class MangaBoltSourceError(RuntimeError):
    """mangabolt.com answered with a page this scraper cannot read."""


class MangaBoltScraper(BaseScraper):
    """Scraper for MangaBolt.com"""

    name = "mangabolt"
    base_url = "https://mangabolt.com"

    def _site_path(self, href: str):
        """The path of ``href`` if it points at mangabolt.com, else None."""
        target = urlparse(urljoin(self.base_url + "/", href))
        host = target.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return target.path if host == _HOST else None

    def _search_series(self, query: str) -> List[Manga]:
        """Every series the site's search lists for ``query``, in its order."""
        url = f"{self.base_url}/search?{urlencode({'q': query})}"
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        # Each result links its series twice: once from the cover image
        # ("Cover for <title>") and once from the title.
        found: Dict[str, dict] = {}
        for link in soup.find_all("a", href=True):
            path = self._site_path(link["href"])
            match = _SERIES_PATH.match(path) if path else None
            if not match:
                continue
            series_url = f"{self.base_url}/series/{match.group(1)}/{match.group(2)}"
            entry = found.setdefault(series_url, {"title": "", "alt": "", "cover": None})

            img = link.find("img")
            if img is not None:
                src = img.get("src") or img.get("data-src")
                if src and not entry["cover"]:
                    entry["cover"] = urljoin(self.base_url + "/", src)
                alt = (img.get("alt") or "").strip()
                if alt.lower().startswith(_COVER_PREFIX):
                    alt = alt[len(_COVER_PREFIX):].strip()
                if alt and not entry["alt"]:
                    entry["alt"] = alt

            text = link.get_text(" ", strip=True)
            if text and not text.lower().startswith(_COVER_PREFIX) and not entry["title"]:
                entry["title"] = text

        results = []
        for series_url, entry in found.items():
            title = entry["title"] or entry["alt"]
            if title:
                results.append(Manga(title=title, url=series_url, cover_url=entry["cover"]))
        return results

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title through the site's own search."""
        return self._search_series(query)[:20]

    def _series_url(self, manga_url: str) -> str:
        """The current series page for ``manga_url``.

        A saved entry may still carry the old /manga/<slug>/ address. The
        site no longer serves it, so the series is looked up by the site's
        search and kept only when exactly one result has that same slug.
        """
        path = self._site_path(manga_url)
        if path is not None:
            match = _SERIES_PATH.match(path)
            if match:
                return f"{self.base_url}/series/{match.group(1)}/{match.group(2)}"
            legacy = _LEGACY_SERIES_PATH.match(path)
            if legacy:
                slug = legacy.group(1)
                matches = {
                    m.url for m in self._search_series(slug.replace("-", " "))
                    if m.url.rsplit("/", 1)[-1] == slug
                }
                if len(matches) == 1:
                    return matches.pop()
                raise MangaBoltSourceError(
                    f"MangaBolt no longer serves {manga_url}, and its search lists "
                    f"{len(matches)} series with the slug {slug!r}")
        raise MangaBoltSourceError(f"Not a MangaBolt series URL: {manga_url}")

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters listed on the series page."""
        series_url = self._series_url(manga_url)
        soup = BeautifulSoup(self._get_html(series_url), "html.parser")

        chapters = []
        seen_urls = set()
        seen_numbers = set()
        for link in soup.find_all("a", href=True):
            path = self._site_path(link["href"])
            if not path or not _CHAPTER_PATH.match(path):
                continue
            match = _OWN_CHAPTER_TEXT.match(link.get_text(" ", strip=True))
            if not match:
                continue
            url = f"{self.base_url}{path.rstrip('/')}"
            number = match.group(1)
            if url in seen_urls or number in seen_numbers:
                continue
            seen_urls.add(url)
            seen_numbers.add(number)
            chapters.append(Chapter(
                number=number,
                title=None,
                url=url,
                date=None,
            ))

        if not chapters:
            raise MangaBoltSourceError(f"No chapter links found on {series_url}")
        return sorted(chapters)

    @staticmethod
    def _page_url(value, where: str) -> str:
        """``value`` if it is a reader page image URL, else raise."""
        if isinstance(value, str):
            target = urlparse(value)
            if (target.scheme == "https" and target.netloc.lower() == _PAGE_HOST
                    and not target.query and not target.fragment
                    and _PAGE_PATH.match(target.path)):
                return value
        raise MangaBoltSourceError(f"Unexpected page image URL {value!r} in {where}")

    @staticmethod
    def _check_count(pages: List[str], expected, what: str, chapter_url: str) -> None:
        if expected is not None and expected != len(pages):
            raise MangaBoltSourceError(
                f"{chapter_url} lists {len(pages)} pages but its {what} says {expected}")

    def _manifest_pages(self, script, chapter_url: str) -> List[str]:
        """The page URLs of a reader-manifest script, in position order."""
        try:
            manifest = json.loads(script.string or script.get_text())
        except ValueError:
            raise MangaBoltSourceError(f"Unreadable reader manifest on {chapter_url}") from None
        items = manifest.get("pages") if isinstance(manifest, dict) else None
        if not isinstance(items, list) or not items:
            raise MangaBoltSourceError(f"Reader manifest on {chapter_url} has no pages")

        by_position = {}
        for item in items:
            position = item.get("position") if isinstance(item, dict) else None
            if not isinstance(position, int) or isinstance(position, bool):
                raise MangaBoltSourceError(f"Reader manifest page without a position on {chapter_url}")
            if position in by_position:
                raise MangaBoltSourceError(f"Reader manifest repeats position {position} on {chapter_url}")
            by_position[position] = self._page_url(item.get("url"), f"the reader manifest of {chapter_url}")

        if sorted(by_position) != list(range(1, len(by_position) + 1)):
            raise MangaBoltSourceError(
                f"Reader manifest positions on {chapter_url} are not 1..{len(by_position)}")
        return [by_position[p] for p in sorted(by_position)]

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter.

        The chapter page carries a reader-manifest JSON script listing every
        page with its position; its count must agree with the page slots and
        the "Page 1 of N" counter. Only a page without a manifest falls back
        to the page slot images.
        """
        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")

        slots = soup.select("[data-page-slot]")
        counter = _PAGE_COUNTER.search(soup.get_text(" ", strip=True))
        expected = int(counter.group(1)) if counter else None

        scripts = soup.select("script#reader-manifest")
        if len(scripts) > 1:
            raise MangaBoltSourceError(f"{chapter_url} has {len(scripts)} reader manifests")
        if scripts:
            pages = self._manifest_pages(scripts[0], chapter_url)
            if slots:
                self._check_count(pages, len(slots), "page slots", chapter_url)
        else:
            pages = []
            for slot in slots:
                img = slot if slot.name == "img" else slot.find("img")
                pages.append(self._page_url(img.get("src") if img else None,
                                            f"the page slots of {chapter_url}"))
            if not pages:
                raise MangaBoltSourceError(f"No reader pages found on {chapter_url}")

        if len(set(pages)) != len(pages):
            raise MangaBoltSourceError(f"{chapter_url} lists the same page image twice")
        self._check_count(pages, expected, "page counter", chapter_url)
        return pages

    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header.

        A body that is not an image (a block page, an empty answer) is a
        failed page, and no older file is left behind at ``path``.
        """
        try:
            headers = {
                "User-Agent": BROWSER_USER_AGENT_SHORT,
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            content = response.content
            if not _identifies_as_image(content):
                Path(path).unlink(missing_ok=True)
                logger.debug("Failed to download %s: response body is not an image", url)
                return False
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False
