"""
Mangadot scraper - Multi-language manga aggregator
Site: mangadot.net

Mangadot is a React-Router SSR app behind Cloudflare, but the data that
matters is reachable over plain HTTP without a browser:

* search   -> GET /search?search=<query> renders manga cards server-side.
* chapters -> GET /api/manga/<id>/chapters/list returns a JSON array with one
              entry per language/scanlation group.
* pages    -> the reader loads page images from /api/uploads/<id>/images for
              user uploads and /api/chapters/<id>/images for everything else;
              both return an ordered ``images`` list of site-relative URLs.

Page images are served directly (no Referer/token needed), so the base-class
``download_image`` handles the actual downloads.
"""

import re
import time
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _retry


class MangadotScraper(BaseScraper):
    """Scraper for Mangadot (mangadot.net)."""

    name = "mangadot"
    base_url = "https://mangadot.net"

    # URL helpers

    def _abs_url(self, href: str) -> str:
        """Absolutize a site-relative URL against the base host."""
        return urljoin(self.base_url + "/", href or "")

    @staticmethod
    def _manga_id(url: str) -> Optional[str]:
        match = re.search(r"/manga/(\d+)", url or "")
        return match.group(1) if match else None

    @staticmethod
    def _chapter_id(url: str) -> Optional[str]:
        match = re.search(r"/chapter/(\d+)", url or "")
        return match.group(1) if match else None

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        html = self._get_html(f"{self.base_url}/search?search={quote_plus(query)}")
        return self._parse_search(html)

    def _parse_search(self, html: str) -> List[Manga]:
        """Parse the search page into Manga results.

        Each result card is an ``<a href="/manga/<id>">`` wrapping a cover
        ``<img>`` plus a ``div.line-clamp-2`` holding the clean title (the
        anchor's raw text also carries the "Manga" type badge and a star
        rating, so the title div is used instead).
        """
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()
        for anchor in soup.select('a[href^="/manga/"]'):
            manga_id = self._manga_id(anchor.get("href", ""))
            if not manga_id or manga_id in seen:
                continue

            title_el = anchor.select_one("div.line-clamp-2")
            title = (title_el.get_text(strip=True) if title_el else "").strip()
            if not title:
                continue
            seen.add(manga_id)

            cover_url = None
            img = anchor.find("img")
            if img:
                src = img.get("src") or img.get("data-src")
                cover_url = self._abs_url(src) if src else None

            results.append(Manga(
                title=title,
                url=f"{self.base_url}/manga/{manga_id}",
                cover_url=cover_url,
            ))

        return results[:20]

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga via the chapters-list API."""
        manga_id = self._manga_id(manga_url)
        if not manga_id:
            return []
        data = self._get_json(f"{self.base_url}/api/manga/{manga_id}/chapters/list")
        return self._parse_chapters(data)

    def _parse_chapters(self, data) -> List[Chapter]:
        """Parse the chapters-list JSON into Chapter objects.

        A chapter number can appear once per language and scanlation group;
        keep a single readable release per number, preferring English so the
        downloader gets one clean list instead of duplicate rows.
        """
        if not isinstance(data, list):
            return []

        best = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if entry.get("id") is None or entry.get("chapter_number") is None:
                continue
            key = self._chapter_number(entry)
            current = best.get(key)
            if current is None or (
                self._is_english(entry) and not self._is_english(current)
            ):
                best[key] = entry

        chapters = []
        for entry in best.values():
            number = self._chapter_number(entry)
            title = (entry.get("chapter_title") or "").strip() or f"Chapter {number}"
            chapters.append(Chapter(
                number=number,
                title=title,
                url=f"{self.base_url}/chapter/{entry['id']}",
                date=self._clean_date(entry.get("date_added")),
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _is_english(entry: dict) -> bool:
        return (entry.get("language") or "").lower().startswith("en")

    @staticmethod
    def _chapter_number(entry: dict) -> str:
        """Derive a clean chapter-number string from a listing entry."""
        raw = entry.get("chapter_number")
        try:
            num = float(raw)
            return str(int(num)) if num.is_integer() else str(num)
        except (TypeError, ValueError):
            match = re.search(r"(\d+(?:\.\d+)?)", str(raw or ""))
            return match.group(1) if match else "0"

    @staticmethod
    def _clean_date(raw) -> Optional[str]:
        """Reduce ``2026-08-10 14:31:28.120232+00`` to a plain ``YYYY-MM-DD``.

        The downloader's ComicInfo date parser reads ``%Y-%m-%d`` cleanly,
        whereas the raw ``+00`` offset is not a valid ISO offset.
        """
        if not raw:
            return None
        return str(raw).split(" ", 1)[0].strip() or None

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        chapter_id = self._chapter_id(chapter_url)
        if not chapter_id:
            return []
        payload = self._get_images_payload(chapter_id)
        return self._parse_pages(payload)

    def _get_images_payload(self, chapter_id: str) -> Optional[dict]:
        """Fetch a chapter's page-image payload from whichever endpoint applies.

        The reader serves user uploads from ``/api/uploads/<id>/images`` and
        other chapters from ``/api/chapters/<id>/images``; the wrong endpoint
        returns 404, so try the upload endpoint first (the common case) and
        fall back to the other.
        """
        for path in (
            f"/api/uploads/{chapter_id}/images",
            f"/api/chapters/{chapter_id}/images",
        ):
            payload = self._get_json_optional(self.base_url + path)
            if payload and payload.get("images"):
                return payload
        return None

    def _get_json_optional(self, url: str) -> Optional[dict]:
        """Rate-limited JSON GET that tolerates a 404.

        Returns ``None`` (instead of raising) when the endpoint does not apply
        to this chapter, so ``_get_images_payload`` can try the alternate one
        without paying the retry back-off a real error would trigger. Transient
        failures still retry via ``_retry``.
        """
        def _do_get():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            resp = self.session.get(
                url,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

        return _retry(
            _do_get,
            max_attempts=3,
            base_delay=1.0,
            exceptions=(requests.RequestException,),
        )

    def _parse_pages(self, payload: Optional[dict]) -> List[str]:
        """Extract ordered, absolute page image URLs from an images payload."""
        images = (payload or {}).get("images") or []
        pages = []
        for image in images:
            url = image.get("url") if isinstance(image, dict) else image
            if not isinstance(url, str) or not url.strip():
                continue
            pages.append(self._abs_url(url.strip()))
        return pages
