"""
ZonaTMO scraper - Spanish manga/manhwa/manhua library
Site: zonatmo.org

ZonaTMO is a server-rendered Laravel site, so plain HTTP + HTML parsing
covers the whole pipeline:

* search   -> GET /biblioteca?title=<query> lists result cards linking to
              /library/<type>/<id>/<slug>.
* chapters -> the series page renders one ``li.upload-link`` row per
              chapter, carrying ``data-chapter-number`` and one or more
              uploads (one per scan group) that link to /view_uploads/<id>.
              Older chapters sit in a hidden ``#chapters-hidden`` list but
              are still in the HTML.
* pages    -> GET /view_uploads/<id> renders every page as a reader
              ``<img>`` (``storage.zonatmo.org/chapters/<id>/<n>.webp``);
              the first few are also preloaded via ``<link rel=preload>``.

The library mixes comics and text-only novels (``/library/novel/...``).
MeManga downloads page images, so novels are left out of search results
and novel URLs resolve to no chapters.

Image downloads send the site Referer and reject non-image bodies so a
CDN block page can never end up saved as a page.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .base import BaseScraper, Chapter, Manga, looks_like_image

logger = logging.getLogger(__name__)


class ZonaTMOScraper(BaseScraper):
    """Scraper for ZonaTMO (zonatmo.org)."""

    name = "zonatmo"
    base_url = "https://zonatmo.org"

    # Series pages are /library/<type>/<id>/<slug>; reader pages are
    # /view_uploads/<upload_id>.
    _SERIES_RE = re.compile(r"/library/([a-z_-]+)/(\d+)(?:/([^/?#]+))?")
    _UPLOAD_RE = re.compile(r"/view_uploads/(\d+)")
    _NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
    _DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
    _BG_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
    _PAGE_NUM_RE = re.compile(r"/(\d+)\.[a-z0-9]+(?:\?.*)?$", re.IGNORECASE)
    _IMG_ATTRS = ("data-src", "data-lazy-src", "data-original", "src")
    # Text-only entries: nothing to download as images.
    _NOVEL_TYPES = {"novel", "novela"}

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            "Referer": self.base_url + "/",
        })

    # URL helpers

    @classmethod
    def _parse_series_url(cls, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Return (type, id, slug) from a series URL, e.g. ("manhwa", "6426", "solo-leveling")."""
        match = cls._SERIES_RE.search(url or "")
        if match:
            return match.group(1), match.group(2), match.group(3)
        return None, None, None

    @classmethod
    def _parse_upload_url(cls, url: str) -> Optional[str]:
        """Return the upload id from a /view_uploads/<id> reader URL."""
        match = cls._UPLOAD_RE.search(url or "")
        return match.group(1) if match else None

    @classmethod
    def _is_novel(cls, kind: Optional[str]) -> bool:
        return (kind or "").strip().lower() in cls._NOVEL_TYPES

    def _absolute(self, url: str) -> str:
        url = (url or "").strip()
        if url.startswith("//"):
            return "https:" + url
        return urljoin(self.base_url + "/", url)

    @staticmethod
    def _is_zonatmo_host(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "zonatmo.org" or host.endswith(".zonatmo.org")

    @classmethod
    def _img_src(cls, img) -> str:
        """Return an <img>'s real source, preferring lazy-load attributes."""
        for attr in cls._IMG_ATTRS:
            src = (img.get(attr) or "").strip()
            if src and not src.startswith("data:"):
                return src
        return ""

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search the /biblioteca listing by title."""
        query = (query or "").strip()
        if not query:
            return []
        response = self._request(f"{self.base_url}/biblioteca", params={"title": query})
        return self._parse_search(response.text)

    def _parse_search(self, html: str) -> List[Manga]:
        """Parse /biblioteca result cards into Manga objects, skipping novels."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        results = []
        seen = set()
        for link in soup.find_all("a", href=True):
            url = self._absolute(link["href"]).split("#")[0].split("?")[0]
            if not self._is_zonatmo_host(url):
                continue
            kind, series_id, _ = self._parse_series_url(url)
            if not series_id or series_id in seen:
                continue
            # Novels are text-only; there are no page images to download.
            if self._is_novel(kind) or self._card_is_novel(link):
                continue

            title = self._card_title(link)
            if not title:
                continue
            seen.add(series_id)
            results.append(Manga(
                title=title,
                url=url,
                cover_url=self._card_cover(link),
            ))
        return results[:20]

    @classmethod
    def _card_is_novel(cls, link) -> bool:
        """True when the card's type badge says the entry is a novel."""
        for badge in link.select(".book-type"):
            if cls._is_novel(badge.get_text(" ", strip=True)):
                return True
        return False

    @staticmethod
    def _card_title(link) -> str:
        for tag in link.find_all(["h4", "h5", "h3"]):
            text = (tag.get("title") or tag.get_text(" ", strip=True)).strip()
            if text:
                return text
        title = (link.get("title") or "").strip()
        if title:
            return title
        img = link.find("img")
        if img and (img.get("alt") or "").strip():
            return img["alt"].strip()
        return ""

    def _card_cover(self, link) -> Optional[str]:
        img = link.find("img")
        src = self._img_src(img) if img else ""
        if src:
            return self._absolute(src)
        for tag in [link] + link.find_all(True):
            bg = (tag.get("data-bg") or "").strip()
            if bg:
                return self._absolute(bg)
            match = self._BG_URL_RE.search(tag.get("style") or "")
            if match:
                return self._absolute(match.group(1))
        return None

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters listed on a series page."""
        url = self._absolute(manga_url)
        if not self._is_zonatmo_host(url):
            # Only fetch series pages from ZonaTMO itself.
            return []
        kind, series_id, _ = self._parse_series_url(url)
        if not series_id or self._is_novel(kind):
            # Novels have no image pages, so there is nothing to download.
            return []
        return self._parse_chapters(self._get_html(url))

    def _parse_chapters(self, html: str) -> List[Chapter]:
        """Parse chapter rows into Chapter objects, sorted ascending.

        Rows in the hidden older-chapters list are included. A chapter can
        have several uploads (one per scan group); keep the first one listed
        so the downloader gets one row per chapter.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        rows = soup.select("li.upload-link") or soup.select("li[data-chapter-number]")

        chapters = []
        seen = set()
        for row in rows:
            link = next(
                (a for a in row.find_all("a", href=True)
                 if self._parse_upload_url(a["href"])),
                None,
            )
            if link is None:
                continue

            number = self._chapter_number(row.get("data-chapter-number"))
            if number is None:
                label = row.select_one(".chapter-number") or row.find("h4")
                if label is not None:
                    number = self._chapter_number(
                        label.get("data-number") or label.get_text(" ", strip=True)
                    )
            if number is None or number in seen:
                continue
            seen.add(number)

            date_match = self._DATE_RE.search(link.parent.get_text(" ", strip=True)
                                              if link.parent else "")
            chapters.append(Chapter(
                number=number,
                title=f"Chapter {number}",
                url=self._absolute(link["href"]),
                date=(f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
                      if date_match else None),
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @classmethod
    def _chapter_number(cls, raw) -> Optional[str]:
        """Normalise "201", "200.50" or "Capítulo 12.0" to a number string."""
        match = cls._NUMBER_RE.search(str(raw if raw is not None else ""))
        if not match:
            return None
        value = match.group(0)
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return value or "0"

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get ordered page image URLs for a chapter."""
        upload_id = self._parse_upload_url(chapter_url)
        if not upload_id:
            return []
        try:
            html = self._get_html(f"{self.base_url}/view_uploads/{upload_id}")
        except Exception as e:
            logger.debug(f"Failed to fetch pages for {chapter_url}: {e}")
            return []
        return self._parse_pages(html, upload_id)

    def _parse_pages(self, html: str, upload_id: str) -> List[str]:
        """Extract this chapter's page images from the reader HTML.

        Image preloads and reader <img> tags (including lazy-load attributes)
        are merged, since the preloads only cover the first few pages. Images
        whose path carries the upload id (``/chapters/<id>/``) are kept, which
        skips covers and site chrome; if none do, the reader's own
        ``.reader-img-wrap`` images are used instead.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        candidates = []
        for link in soup.find_all("link", href=True):
            rel = [r.lower() for r in (link.get("rel") or [])]
            if "preload" in rel and (link.get("as") or "").lower() == "image":
                candidates.append(link["href"])
        reader_imgs = []
        for img in soup.find_all("img"):
            src = self._img_src(img)
            if not src:
                continue
            candidates.append(src)
            if img.find_parent(class_="reader-img-wrap"):
                reader_imgs.append(src)

        marker = f"/{upload_id}/"
        pages = self._dedupe(
            url for url in map(self._absolute, candidates) if marker in url
        )
        if not pages:
            pages = self._dedupe(map(self._absolute, reader_imgs))
        return self._sort_pages(pages)

    @staticmethod
    def _dedupe(urls) -> List[str]:
        seen = set()
        result = []
        for url in urls:
            if url.startswith("http") and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    @classmethod
    def _sort_pages(cls, pages: List[str]) -> List[str]:
        """Order pages by their numeric file name when every page has one.

        Preloads and reader images are merged, so numbered files like
        ``.../969671/12.webp`` are sorted by number rather than by where
        they first appeared in the HTML.
        """
        numbers = []
        for url in pages:
            match = cls._PAGE_NUM_RE.search(url)
            if not match:
                return pages
            numbers.append(int(match.group(1)))
        return [url for _, url in sorted(zip(numbers, pages), key=lambda item: item[0])]

    # Images

    def download_image(self, url: str, path: Path) -> bool:
        """Download a page with the site Referer, refusing non-image bodies."""
        try:
            response = self._request(url, headers={
                "Referer": self.base_url + "/",
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            })
            if not looks_like_image(response.content,
                                    response.headers.get("Content-Type", "")):
                return False
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False
