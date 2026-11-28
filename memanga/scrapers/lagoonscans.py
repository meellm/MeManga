"""
Lagoon Scans: an English manhwa and manhua reader on the WordPress
"MangaThemesia" theme.

https://lagoonscans.com

It reads like the theme's other sites in ``mangathemesia_sites``: a search
page of ``.listupd .bs .bsx`` cards, a series page under ``/manga/`` whose
rows carry ``data-num`` and a "Chapter N" label, and a reader whose pages
are in its ``ts_reader.run({...})`` call, on the site's own upload path. The
reader must name the chapter asked for as its canonical address, and a
reader marked protected is not read.

A series page lists only the chapters the site keeps on it; when they do
not start at chapter 1 the listing says so in a warning, and older
chapters are not looked for elsewhere. A series whose own genres include an
adult genre, or whose type is a novel, is not read.
"""

import json
import logging
import re
from typing import List

from bs4 import BeautifulSoup

from .base import Chapter
from .mangathemesia_sites import MangaThemesiaSite, MangaThemesiaSourceError

logger = logging.getLogger(__name__)

_TS_READER = re.compile(r"ts_reader\.run\(\s*(?=\{)")
_ADULT_GENRES = frozenset({"adult", "mature", "hentai", "smut", "18+"})
_NOVEL_TYPES = frozenset({"novel", "light novel", "web novel"})


class LagoonScansScraper(MangaThemesiaSite):
    """lagoonscans.com: pages are in the reader's ``ts_reader.run`` call."""

    name = "lagoonscans"
    base_url = "https://lagoonscans.com"
    content_language = "en"
    # Series with an adult genre are refused; none was served.
    nsfw = False

    _site_hosts = frozenset({"lagoonscans.com"})
    _series_dirs = ("manga",)
    _trailing_slash = True
    _search_path = "/"
    _image_hosts = frozenset({"lagoonscans.com"})
    _image_path_prefix = "/wp-content/uploads/"
    _chapter_label = re.compile(r"chapter\s+(\d+(?:\.\d+)?)(?![\d.])", re.I)

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.2

    def _fetch(self, url: str, what: str):
        """The theme's fetch; a series page is also checked for the series'
        own adult genres and novel type before its chapters are read."""
        response = super()._fetch(url, what)
        if what == "series page":
            reason = self._refusal(BeautifulSoup(response.text, "html.parser"))
            if reason:
                raise MangaThemesiaSourceError(
                    f"{self.name} series {url} {reason}, which this source does not read")
        return response

    @staticmethod
    def _refusal(soup) -> str:
        genres = {" ".join(a.get_text(" ", strip=True).split()).casefold()
                  for a in soup.select("div.seriestugenre a[rel~=tag]")}
        if genres & _ADULT_GENRES:
            return "has an adult genre"
        for row in soup.select("table.infotable tr"):
            cells = [" ".join(td.get_text(" ", strip=True).split()) for td in row.find_all("td")]
            if (len(cells) == 2 and cells[0].casefold() == "type"
                    and cells[1].casefold() in _NOVEL_TYPES):
                return "is a novel"
        return ""

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """The theme's listing; a list that does not start at chapter 1
        is reported as the site's partial list."""
        chapters = super().get_chapters(manga_url)
        oldest = min(chapters, key=lambda c: c.numeric)
        if oldest.numeric > 1:
            logger.warning("%s: %s lists %d chapter(s), %s to %s; earlier chapters are not "
                           "on the site's series page and are not listed", self.name,
                           self._series_url(manga_url), len(chapters), oldest.number,
                           chapters[0].number)
        return chapters

    def _reader_images(self, html: str, chapter_url: str) -> list:
        def refused(why: str):
            return MangaThemesiaSourceError(f"{self.name} chapter {chapter_url} {why}")

        canonical = BeautifulSoup(html or "", "html.parser").select_one("link[rel=canonical]")
        if canonical is None or (canonical.get("href") or "").strip() != chapter_url:
            raise refused("is not the chapter asked for")
        calls = list(_TS_READER.finditer(html or ""))
        if len(calls) != 1:
            raise refused(f"has {len(calls)} reader page lists, not one")
        try:
            data, _ = json.JSONDecoder().raw_decode(html, calls[0].end())
        except ValueError:
            raise refused("has a reader page list that is not JSON") from None
        if not isinstance(data, dict) or data.get("protected") not in (None, False):
            raise refused("has a protected reader, which this source does not read")
        sources = data.get("sources")
        if not isinstance(sources, list) or not sources:
            raise refused("has a reader without image sources")
        if len(sources) == 1:
            source = sources[0]
        else:
            named = [s for s in sources if isinstance(s, dict)
                     and s.get("source") == data.get("defaultSource")]
            if len(named) != 1:
                raise refused("does not name one default image source")
            source = named[0]
        images = source.get("images") if isinstance(source, dict) else None
        if not isinstance(images, list):
            raise refused("has a reader source without images")
        return images
