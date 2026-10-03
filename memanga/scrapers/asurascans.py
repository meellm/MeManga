"""
Asura Scans scraper - Popular for manhwa/webtoons
https://asurascans.com

The site is an Astro frontend backed by a public JSON API served from
its own host, api.asurascans.com - not same-origin with the site - so
no headless browser is needed. Against that host:

    GET /api/series?search=<query>         -> series search
    GET /api/series/<slug>                 -> series detail (cover, title)
    GET /api/series/<slug>/chapters        -> chapter list
    GET /api/series/<slug>/chapters/<num>  -> chapter detail incl. page URLs

Issue #177: the old scraper drove Playwright at
asuracomic.net/series?name=<query>. That domain now redirects to the
asurascans.com homepage and drops the query string, so every search
parsed the homepage and came back empty. The API above is what the
site's own frontend calls.

Legacy URLs keep working. Public series paths append a short routing
suffix to the slug (/comics/nano-machine-05c7df14); entries saved from
the retired domains may or may not carry one (/series/nano-machine-...,
/manga/nano-machine). The API canonicalises whatever slug segment it is
given, so we pass the one in the URL through untouched.
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class AsuraScansScraper(BaseScraper):
    """Scraper for Asura Scans."""

    name = "asurascans"
    base_url = "https://asurascans.com"
    api_url = "https://api.asurascans.com/api"

    # Series slug segment: /comics/<slug> today, /series/<slug> or the
    # older Madara-style /manga/<slug>/ on the retired asuracomic.net /
    # asuratoon.com domains.
    _SERIES_RE = re.compile(r"/(?:comics|series|manga)/([^/?#]+)")
    # Chapter number segment: /chapter/330, /chapter/100.5
    _CHAPTER_RE = re.compile(r"/chapter/([^/?#]+)")
    # Reader images, for the HTML fallback in get_pages().
    _PAGE_IMG_RE = re.compile(
        r"https://cdn\.asurascans\.com/asura-images/chapters/[^\"\\\s]+"
    )

    # -- URL helpers --------------------------------------------------

    def _series_slug(self, url: str) -> Optional[str]:
        """Pull the series slug out of a series or chapter URL."""
        match = self._SERIES_RE.search(url or "")
        if not match:
            logger.debug(f"[Asura] Not an Asura series URL: {url!r}")
            return None
        return match.group(1)

    def _series_url(self, series: dict) -> str:
        """Public series URL for an API series object."""
        public = series.get("public_url") or ""
        if public.startswith("/"):
            return self.base_url + public
        return f"{self.base_url}/comics/{series.get('slug') or ''}"

    @staticmethod
    def _format_number(raw) -> Optional[str]:
        """Chapter number the way the site spells it: 330, or 100.5."""
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return str(int(value)) if value.is_integer() else str(value)

    # -- Parsers: split out so tests can feed them canned payloads -----

    def _parse_search(self, payload: dict, query: str) -> List[Manga]:
        # `data` is null - not [] - when the API matched nothing.
        series = (payload or {}).get("data") or []

        # The API matches alt titles and descriptions too, so a query
        # like "solo" buries "Solo Leveling" under loosely related hits.
        # Float title matches to the front (stable sort keeps the API's
        # own ranking within each group) so they survive the cap below.
        needle = (query or "").lower().strip()
        series = sorted(
            series,
            key=lambda s: 0 if needle and needle in (s.get("title") or "").lower() else 1,
        )

        results = []
        for item in series:
            title = (item.get("title") or "").strip()
            if not title or not (item.get("public_url") or item.get("slug")):
                continue
            results.append(Manga(
                title=title,
                url=self._series_url(item),
                cover_url=item.get("cover") or None,
            ))
            if len(results) >= 10:
                break

        return results

    # Chapter rows flagged premium are early access: the site lists
    # them, but the chapter detail comes back `is_locked` with zero
    # pages until the window closes (issue #177 - Nano Machine 331 was
    # listed and undownloadable). Keys the API has used for that expiry:
    _EARLY_ACCESS_KEYS = ("early_access_until", "unlock_time", "available_at")

    @staticmethod
    def _parse_timestamp(raw) -> Optional[datetime]:
        """Parse an API timestamp. Tolerates the trailing "Z" (which
        `fromisoformat` only accepts from 3.11) and a missing offset."""
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            return None
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    @classmethod
    def _is_early_access(cls, row: dict) -> bool:
        """True while a premium chapter row is still paywalled."""
        if not row.get("is_premium"):
            return False
        for key in cls._EARLY_ACCESS_KEYS:
            until = cls._parse_timestamp(row.get(key))
            if until is not None:
                return until > datetime.now(timezone.utc)
        # Premium with no unlock time published - assume still locked.
        return True

    def _parse_chapters(self, payload: dict, series_url: str) -> List[Chapter]:
        rows = (payload or {}).get("data") or []

        chapters = []
        seen = set()
        for row in rows:
            if self._is_early_access(row):
                logger.debug(f"[Asura] Skipping early-access chapter "
                             f"{row.get('number')!r}")
                continue
            number = self._format_number(row.get("number"))
            if number is None or number in seen:
                continue
            seen.add(number)
            chapters.append(Chapter(
                number=number,
                title=row.get("title") or None,
                url=f"{series_url}/chapter/{number}",
                date=(row.get("published_at") or "")[:10] or None,
            ))

        return sorted(chapters)

    def _parse_pages(self, payload: dict) -> List[str]:
        data = (payload or {}).get("data") or {}

        # Early-access chapters are listed but paywalled: the detail
        # response carries the metadata with an empty `pages` array.
        if data.get("is_locked"):
            logger.debug("[Asura] Chapter is locked (early access)")
            return []

        pages = []
        for page in (data.get("chapter") or {}).get("pages") or []:
            url = page.get("url") if isinstance(page, dict) else page
            if url:
                pages.append(url)
        return pages

    def _parse_pages_html(self, html: str) -> List[str]:
        """Fallback: reader image URLs embedded in the chapter page.

        The Astro island payload holds the same CDN URLs the API
        returns, HTML-escaped and each listed twice (preload + reader).
        """
        import html as html_module

        pages = []
        seen = set()
        for url in self._PAGE_IMG_RE.findall(html_module.unescape(html or "")):
            if url not in seen:
                seen.add(url)
                pages.append(url)
        return pages

    # -- Public API ---------------------------------------------------

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        # NOTE: the endpoint also accepts ?name=, but silently ignores
        # it and returns the whole catalogue. ?search= is the filter
        # the site's own browse UI uses.
        payload = self._get_json(f"{self.api_url}/series",
                                 params={"search": query})
        return self._parse_search(payload, query)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        slug = self._series_slug(manga_url)
        if not slug:
            return []

        payload = self._get_json(f"{self.api_url}/series/{slug}/chapters")
        # Rebuild chapter URLs on the live domain so library entries
        # saved against asuracomic.net still link somewhere that loads.
        return self._parse_chapters(payload, f"{self.base_url}/comics/{slug}")

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        slug = self._series_slug(chapter_url)
        match = self._CHAPTER_RE.search(chapter_url or "")
        if not slug or not match:
            logger.debug(f"[Asura] Not an Asura chapter URL: {chapter_url!r}")
            return []

        payload = self._get_json(
            f"{self.api_url}/series/{slug}/chapters/{match.group(1)}")
        pages = self._parse_pages(payload)
        if pages or ((payload or {}).get("data") or {}).get("is_locked"):
            return pages

        # API shape changed? Fall back to the reader page's own markup,
        # rebuilt on the live domain - the caller's URL may be a retired
        # alias that now redirects to the homepage (issue #177).
        reader_url = f"{self.base_url}/comics/{slug}/chapter/{match.group(1)}"
        logger.debug(f"[Asura] No pages from API for {chapter_url}, "
                     f"falling back to chapter HTML at {reader_url}")
        try:
            return self._parse_pages_html(self._get_html(reader_url))
        except Exception as e:
            logger.debug(f"[Asura] HTML page fallback failed: {e}")
            return []

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get cover image URL from the series API."""
        slug = self._series_slug(manga_url)
        if not slug:
            return None
        try:
            payload = self._get_json(f"{self.api_url}/series/{slug}")
            return ((payload or {}).get("series") or {}).get("cover") or None
        except Exception as e:
            logger.debug(f"[Asura] Cover lookup failed for {manga_url}: {e}")
            return None
