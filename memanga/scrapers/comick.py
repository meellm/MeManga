"""
ComicK scraper - Popular manga aggregator (comick.io / comick.dev)
Uses the site's own JSON API (api.comick.dev) - no HTML scraping needed.

The comick.io / comick.dev web pages sit behind Cloudflare's headless
verification, but the API the SPA calls answers plain requests:

- search:         /v1.0/search?type=comic&q=...
- comic by slug:  /comic/{slug}/          -> {"comic": {"hid": ...}}
- chapter list:   /v1.0/comic/{hid}/chapters?lang=en&limit=&page=
- chapter detail: /chapter/{chapter_hid}  -> {"chapter": {"md_images": [...]}}

Hosted pages are served from meo.comick.pictures/{b2key}. Chapters that
only link to an external/official site have no md_images and yield [].
"""

import re
from typing import List, Optional

from .base import BaseScraper, Chapter, Manga


class ComickScraper(BaseScraper):
    """Scraper for ComicK using its public JSON API."""

    name = "comick"
    base_url = "https://comick.io"  # Redirects to comick.dev
    api_url = "https://api.comick.dev"
    image_cdn = "https://meo.comick.pictures"

    _CHAPTERS_PAGE_SIZE = 300
    _MAX_CHAPTER_PAGES = 50

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://comick.io/",
            "Origin": "https://comick.io",
        })

    def _extract_slug(self, url: str) -> Optional[str]:
        """Extract comic slug from a ComicK URL."""
        match = re.search(r'/comic/([^/?#]+)', url)
        return match.group(1) if match else None

    def _extract_chapter_hid(self, url: str) -> Optional[str]:
        """Extract chapter hid from a ComicK chapter URL.

        URL formats:
        https://comick.io/comic/{slug}/{hid}-chapter-{chap}-{lang}
        https://comick.io/comic/{slug}/{hid}
        """
        match = re.search(r'/comic/[^/?#]+/([^/?#]+)', url)
        if not match:
            return None
        segment = match.group(1)
        return segment.split('-chapter-', 1)[0] or None

    def _cover_url(self, item: dict) -> Optional[str]:
        """Build a cover URL from an API comic record."""
        for cover in item.get("md_covers") or []:
            b2key = cover.get("b2key") if isinstance(cover, dict) else None
            if b2key:
                return f"{self.image_cdn}/{b2key}"
        return item.get("cover_url") or None

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        data = self._get_json(
            f"{self.api_url}/v1.0/search",
            params={"type": "comic", "page": 1, "limit": 20, "q": query},
        )
        if not isinstance(data, list):
            return []

        results = []
        seen = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            title = (item.get("title") or "").strip()
            if not slug or not title or slug in seen:
                continue
            seen.add(slug)

            results.append(Manga(
                title=title,
                url=f"{self.base_url}/comic/{slug}",
                cover_url=self._cover_url(item),
                description=item.get("desc") or None,
            ))

        return results

    def _get_comic(self, slug: str) -> dict:
        """Fetch the API comic record for a slug."""
        data = self._get_json(f"{self.api_url}/comic/{slug}/")
        comic = data.get("comic") if isinstance(data, dict) else None
        return comic if isinstance(comic, dict) else {}

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get cover image URL from the API (web pages are Cloudflare-gated)."""
        slug = self._extract_slug(manga_url)
        if not slug:
            return None
        try:
            return self._cover_url(self._get_comic(slug))
        except Exception:
            return None

    def _fetch_chapter_list(self, hid: str, lang: Optional[str]) -> List[dict]:
        """Fetch every chapter record for a comic, following pagination."""
        records: List[dict] = []
        for page in range(1, self._MAX_CHAPTER_PAGES + 1):
            params = {"limit": self._CHAPTERS_PAGE_SIZE, "page": page}
            if lang:
                params["lang"] = lang
            data = self._get_json(
                f"{self.api_url}/v1.0/comic/{hid}/chapters", params=params,
            )
            if not isinstance(data, dict):
                break
            batch = data.get("chapters") or []
            if not batch:
                break
            records.extend(batch)
            total = data.get("total") or 0
            if len(records) >= total or len(batch) < self._CHAPTERS_PAGE_SIZE:
                break
        return records

    _OFFICIAL_GROUPS = {"mangaplus", "manga plus", "official"}

    def _is_official(self, ch: dict) -> bool:
        """True for official/external uploads (MangaPlus etc.), which
        usually link out to the publisher and have no hosted images."""
        for link in ch.get("md_chapters_groups") or []:
            group = link.get("md_groups") if isinstance(link, dict) else None
            if isinstance(group, dict) and group.get("official"):
                return True
        names = ch.get("group_name") or []
        return any(
            isinstance(name, str) and name.strip().lower() in self._OFFICIAL_GROUPS
            for name in names
        )

    def _upload_rank(self, ch: dict) -> tuple:
        """Sort key for duplicate uploads: scan groups before official
        ones, then by votes."""
        return (not self._is_official(ch), ch.get("up_count") or 0)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga, preferring English releases."""
        slug = self._extract_slug(manga_url)
        if not slug:
            raise ValueError(f"Could not extract comic slug from: {manga_url}")

        hid = self._get_comic(slug).get("hid")
        if not hid:
            return []

        records = self._fetch_chapter_list(hid, "en")
        if not records:
            # Non-English-only titles: fall back to every language.
            records = self._fetch_chapter_list(hid, None)

        # Several groups often upload the same chapter; keep the best
        # upload per chapter number. Records without a chapter number
        # (volume-only/oneshot extras) are skipped rather than collapsed
        # into one fake "Chapter 0".
        best = {}
        for ch in records:
            chapter_hid = ch.get("hid")
            number = str(ch.get("chap") or "").strip()
            if not chapter_hid or not number:
                continue
            current = best.get(number)
            if current is None or self._upload_rank(ch) > self._upload_rank(current):
                best[number] = ch

        chapters = []
        for number, ch in best.items():
            lang = ch.get("lang") or "en"
            title = (ch.get("title") or "").strip() or f"Chapter {number}"
            date = ch.get("publish_at") or ch.get("created_at")
            chapters.append(Chapter(
                number=number,
                title=title,
                url=f"{self.base_url}/comic/{slug}/{ch['hid']}-chapter-{number}-{lang}",
                date=date[:10] if date else None,
            ))

        return sorted(chapters, key=lambda x: x.numeric)

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        chapter_hid = self._extract_chapter_hid(chapter_url)
        if not chapter_hid:
            raise ValueError(f"Could not extract chapter id from: {chapter_url}")

        data = self._get_json(f"{self.api_url}/chapter/{chapter_hid}")
        chapter = data.get("chapter") if isinstance(data, dict) else None
        images = (chapter or {}).get("md_images") or []

        pages = []
        for img in images:
            url = ""
            if isinstance(img, dict):
                key = img.get("b2key") or img.get("url") or ""
                if key:
                    url = key if key.startswith("http") else f"{self.image_cdn}/{key}"
            elif isinstance(img, str):
                url = img if img.startswith("http") else f"{self.image_cdn}/{img}"
            if url and url not in pages:
                pages.append(url)

        return pages
