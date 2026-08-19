"""
Atsumaru scraper - Manga aggregator
Site: atsu.moe

Atsumaru is a React SPA backed by a Typesense search endpoint and REST APIs.
This scraper uses the APIs directly:

* search   -> GET /collections/manga/documents/search?q=...
* chapters -> GET /api/manga/allChapters?mangaId=...
* pages    -> GET /api/read/chapter?mangaId=...&chapterId=...
"""

import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urlencode

from .base import BaseScraper, Chapter, Manga


class AtsumaruScraper(BaseScraper):
    """Scraper for Atsumaru (atsu.moe)."""

    name = "atsumaru"
    base_url = "https://atsu.moe"

    # IDs are short randomly-generated identifiers whose alphabet can include
    # "-" and "_" (e.g. "9L82jefe"), so match those too. The class stops at
    # "/", "?" or "#", so a trailing path or query is still excluded.
    _MANGA_ID_RE = re.compile(r"/manga/([A-Za-z0-9_-]+)")
    _READ_RE = re.compile(r"/read/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)")

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": self.base_url + "/",
        })

    def _abs_static_url(self, path: str) -> str:
        """Absolutize a static/CDN path, using cdn.atsu.moe directly."""
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return "https://cdn.atsu.moe" + path

    @classmethod
    def _extract_manga_id(cls, url: str) -> Optional[str]:
        """Extract manga ID from a manga URL like /manga/<id>."""
        match = cls._MANGA_ID_RE.search(url or "")
        return match.group(1) if match else None

    @classmethod
    def _extract_read_ids(cls, url: str) -> tuple:
        """Extract (manga_id, chapter_id) from a read URL like /read/<manga>/<chapter>."""
        match = cls._READ_RE.search(url or "")
        if match:
            return match.group(1), match.group(2)
        return None, None

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title via Typesense endpoint."""
        params = urlencode({
            "q": query,
            "query_by": "title,otherNames",
            "per_page": "20",
        })
        url = f"{self.base_url}/collections/manga/documents/search?{params}"
        try:
            data = self._get_json(url)
        except Exception:
            return []
        return self._parse_search(data)

    def _parse_search(self, data: dict) -> List[Manga]:
        """Parse Typesense search response into Manga objects."""
        results = []
        seen = set()
        for hit in (data or {}).get("hits") or []:
            doc = hit.get("document") or {}
            manga_id = doc.get("id")
            title = (doc.get("title") or "").strip()
            if not manga_id or not title:
                continue
            if manga_id in seen:
                continue
            seen.add(manga_id)

            cover = doc.get("posterMedium") or doc.get("poster") or doc.get("posterSmall")
            cover_url = self._abs_static_url(cover) if cover else None

            results.append(Manga(
                title=title,
                url=f"{self.base_url}/manga/{manga_id}",
                cover_url=cover_url,
                description=doc.get("synopsis"),
            ))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga via the allChapters API."""
        manga_id = self._extract_manga_id(manga_url)
        if not manga_id:
            return []

        url = f"{self.base_url}/api/manga/allChapters?mangaId={manga_id}"
        try:
            data = self._get_json(url)
        except Exception:
            return []
        return self._parse_chapters(data, manga_id)

    def _parse_chapters(self, data: dict, manga_id: str) -> List[Chapter]:
        """Parse allChapters response into Chapter objects, sorted ascending."""
        chapters = []
        seen = set()

        for entry in (data or {}).get("chapters") or []:
            chapter_id = entry.get("id")
            if not chapter_id or chapter_id in seen:
                continue
            seen.add(chapter_id)

            number = self._chapter_number(entry)
            title = (entry.get("title") or "").strip() or f"Chapter {number}"

            date = None
            ts = entry.get("createdAt")
            if ts:
                try:
                    date = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
                except Exception:
                    pass

            chapters.append(Chapter(
                number=number,
                title=title,
                url=f"{self.base_url}/read/{manga_id}/{chapter_id}",
                date=date,
            ))

        return sorted(chapters, key=lambda ch: ch.numeric)

    @staticmethod
    def _chapter_number(entry: dict) -> str:
        """Extract clean chapter number from an allChapters entry."""
        raw = entry.get("number")
        if raw is not None:
            try:
                num = float(raw)
                return str(int(num)) if num.is_integer() else str(num)
            except (TypeError, ValueError):
                pass

        index = entry.get("index")
        if index is not None:
            try:
                return str(int(index) + 1)
            except (TypeError, ValueError):
                pass

        title = entry.get("title") or ""
        match = re.search(r"(\d+(?:\.\d+)?)", title)
        return match.group(1) if match else "0"

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter via the read API."""
        manga_id, chapter_id = self._extract_read_ids(chapter_url)

        if not manga_id or not chapter_id:
            parsed = urlparse(chapter_url)
            qs = parse_qs(parsed.query)
            manga_id = manga_id or (qs.get("mangaId") or [None])[0]
            chapter_id = chapter_id or (qs.get("chapterId") or [None])[0]

        if not manga_id or not chapter_id:
            return []

        url = f"{self.base_url}/api/read/chapter?mangaId={manga_id}&chapterId={chapter_id}"
        try:
            data = self._get_json(url)
        except Exception:
            return []
        return self._parse_pages(data)

    def _parse_pages(self, data: dict) -> List[str]:
        """Parse read/chapter response into ordered page URLs."""
        pages_list = ((data or {}).get("readChapter") or {}).get("pages") or []

        pages = []
        for page in sorted(pages_list, key=lambda p: p.get("number", 0)):
            img = page.get("image")
            if img:
                pages.append(self._abs_static_url(img))

        return pages
