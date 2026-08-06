"""
MangaBall scraper - Multi-language manga aggregator
Site: mangaball.net

MangaBall is an API-driven SPA (Laravel backend). The homepage and title
pages ship only skeleton placeholders and pull their real data from JSON
``/api/v1/`` endpoints guarded by a per-session CSRF token, while reader
pages embed the page-image list as a JSON blob. This scraper talks to those
endpoints directly over HTTP instead of rendering the SPA in a browser:

* search  -> POST /api/v1/smart-search/search/
* chapters -> POST /api/v1/chapter/chapter-listing-by-title-id/
* pages   -> the ``chapterImages`` JSON array embedded in the reader page
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _retry


class MangaBallScraper(BaseScraper):
    """Scraper for MangaBall."""

    name = "mangaball"
    base_url = "https://mangaball.net"

    # Every /title-detail/<slug>-<id>/ URL ends in a 24-hex-char title id,
    # which the chapter-listing API keys off. Anchor to the trailing
    # "-<id>" segment so a hex-looking run earlier in the slug is ignored;
    # allow an optional trailing slash, query, or fragment after it.
    _TITLE_ID_RE = re.compile(r"-([0-9a-f]{24})(?:[/?#]|$)")

    # Reader pages inline the ordered page list as `chapterImages = JSON.parse(`...`)`.
    _CHAPTER_IMAGES_RE = re.compile(
        r"chapterImages\s*=\s*JSON\.parse\(\s*`(.*?)`\s*\)", re.S
    )

    def __init__(self):
        super().__init__()
        self._csrf_token: Optional[str] = None

    # CSRF / POST helpers

    def _get_csrf_token(self, force: bool = False) -> Optional[str]:
        """Fetch and cache the per-session CSRF token.

        The /api/v1 endpoints validate an ``X-CSRF-TOKEN`` header against the
        session cookie, so both are primed by loading a normal page once and
        reading ``<meta name="csrf-token">``. The token is stable for the life
        of the session cookie, so it is cached and only refreshed on demand.
        """
        if self._csrf_token and not force:
            return self._csrf_token
        html = self._get_html(self.base_url + "/")
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        self._csrf_token = meta.get("content") if meta else None
        return self._csrf_token

    def _api_post(self, path: str, data: dict) -> dict:
        """Rate-limited form POST to an /api/v1 endpoint, returning JSON.

        A stale session makes Laravel answer HTTP 419; on that we refresh the
        CSRF token so the retry (driven by ``_retry``) posts a valid one.
        """
        url = urljoin(self.base_url, path)

        def _do_post():
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            resp = self.session.post(
                url,
                data=data,
                headers={
                    "X-CSRF-TOKEN": self._get_csrf_token() or "",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.base_url + "/",
                },
                timeout=30,
            )
            if resp.status_code == 419:
                # CSRF/session expired - refresh so the retry sends a fresh one.
                self._get_csrf_token(force=True)
            resp.raise_for_status()
            return resp.json()

        return _retry(
            _do_post,
            max_attempts=3,
            base_delay=1.0,
            exceptions=(requests.RequestException,),
        )

    # URL helpers

    def _abs_url(self, href: str) -> str:
        """Absolutize a site-relative URL and force https.

        The chapter API returns ``http://`` links even though the site serves
        https, so normalise the scheme to avoid a needless redirect per page.
        """
        url = urljoin(self.base_url + "/", href or "")
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        return url

    @classmethod
    def _extract_title_id(cls, url: str) -> Optional[str]:
        match = cls._TITLE_ID_RE.search(url or "")
        return match.group(1) if match else None

    # Search

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title via the smart-search API."""
        payload = self._api_post(
            "/api/v1/smart-search/search/", {"search_input": query}
        )
        return self._parse_search(payload)

    def _parse_search(self, payload: dict) -> List[Manga]:
        """Parse a smart-search JSON response into Manga results."""
        if (payload or {}).get("code") != 200:
            return []

        results = []
        seen = set()
        for item in (payload.get("data") or {}).get("manga") or []:
            href = item.get("url") or ""
            title = (item.get("title") or "").strip()
            if not href or not title:
                continue

            url = self._abs_url(href)
            if url in seen:
                continue
            seen.add(url)

            results.append(Manga(
                title=title,
                url=url,
                cover_url=item.get("img") or None,
            ))

        return results[:20]

    # Chapters

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga via the chapter-listing API."""
        title_id = self._extract_title_id(manga_url)
        if not title_id:
            return []

        payload = self._api_post(
            "/api/v1/chapter/chapter-listing-by-title-id/",
            {"title_id": title_id, "userSettingsEnabled": "false"},
        )
        return self._parse_chapters(payload)

    def _parse_chapters(self, payload: dict) -> List[Chapter]:
        """Parse a chapter-listing JSON response into Chapter objects.

        Each entry groups the same chapter number across translation groups and
        languages; pick one readable translation per chapter (English first).
        """
        if (payload or {}).get("code") != 200:
            return []

        chapters = []
        seen = set()
        for entry in payload.get("ALL_CHAPTERS") or []:
            translation = self._pick_translation(entry.get("translations") or [])
            if not translation:
                continue

            url = self._abs_url(translation.get("url") or "")
            if not translation.get("url") or url in seen:
                continue
            seen.add(url)

            number = self._chapter_number(entry)
            title = (entry.get("title") or "").strip() or f"Chapter {number}"
            chapters.append(Chapter(
                number=number,
                title=title,
                url=url,
                date=translation.get("date"),
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _pick_translation(translations: list) -> Optional[dict]:
        """Choose one readable translation per chapter, preferring English."""
        usable = [t for t in translations if t.get("url")]
        if not usable:
            return None
        for t in usable:
            if (t.get("language") or "").lower().startswith("en"):
                return t
        return usable[0]

    @staticmethod
    def _chapter_number(entry: dict) -> str:
        """Derive a clean chapter-number string from a listing entry."""
        raw = entry.get("number_float")
        try:
            num = float(raw)
            return str(int(num)) if num.is_integer() else str(num)
        except (TypeError, ValueError):
            pass
        text = str(entry.get("number") or entry.get("title") or "")
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        return match.group(1) if match else "0"

    # Pages

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_html(self._abs_url(chapter_url))
        return self._parse_pages(html)

    def _parse_pages(self, html: str) -> List[str]:
        """Extract ordered page image URLs from a reader page.

        The reader embeds the list as ``chapterImages = JSON.parse(`[...]`)``;
        fall back to scraping CDN ``<img>`` tags if that shape ever changes.
        """
        match = self._CHAPTER_IMAGES_RE.search(html)
        if match:
            try:
                urls = json.loads(match.group(1))
                pages = [self._abs_url(u.strip()) for u in urls
                         if isinstance(u, str) and u.strip()]
                if pages:
                    return pages
            except (ValueError, TypeError):
                pass

        soup = BeautifulSoup(html, "html.parser")
        pages = []
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            if "poke-black-and-white.net" in src or re.search(r"-\d{3}\.(webp|jpg|png)", src):
                src = src.strip()
                if src not in pages:
                    pages.append(src)
        return pages
