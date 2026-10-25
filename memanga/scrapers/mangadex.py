"""
MangaDex scraper - Uses official API (no HTML scraping needed)
https://api.mangadex.org/docs/
"""

import logging
import threading
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests
from memanga import __version__
from .base import BaseScraper, Chapter, Manga, _retry


USER_AGENT = f"MeManga/{__version__} (+https://github.com/meellm/MeManga)"
_REPORT_URL = "https://api.mangadex.network/report"
logger = logging.getLogger(__name__)

# MangaDex group IDs whose active leaders asked MeManga to stop offering their
# chapters. Users can add more with `config --mangadex-remove-group`.
REMOVED_GROUP_IDS = frozenset()


def removed_group_ids(config=None) -> set:
    """Built-in removal requests plus any the user has configured."""
    configured = config.get("mangadex.removed_group_ids", []) if config else []
    return set(REMOVED_GROUP_IDS) | set(configured or [])


class MangaDexScraper(BaseScraper):
    """Scraper for MangaDex using official API."""
    
    name = "mangadex"
    base_url = "https://api.mangadex.org"
    engine = "api"
    content_language = "en"  # the feed requests translatedLanguage "en"
    
    def __init__(self):
        super().__init__()
        self._rate_limit = 0.5  # MangaDex is generous with rate limits

        # MangaDex requires an honest client User-Agent, not browser identity
        # or browser-only Fetch Metadata: https://api.mangadex.org/docs/2-limitations/
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        self.data_saver = False
        self.removed_group_ids = removed_group_ids()
        # MangaDex@Home node per chapter hash, so a failed image can be
        # retried on a freshly assigned node.
        self._at_home = {}
        self._at_home_lock = threading.Lock()

    @staticmethod
    def _groups(item):
        return [rel for rel in item.get("relationships", [])
                if rel.get("type") == "scanlation_group"]
    
    def _extract_manga_id(self, url: str) -> Optional[str]:
        """Extract manga ID from MangaDex URL."""
        # URL formats:
        # https://mangadex.org/title/abc123
        # https://mangadex.org/title/abc123/manga-name
        import re
        match = re.search(r'/title/([a-f0-9-]+)', url)
        return match.group(1) if match else None
    
    def _extract_chapter_id(self, url: str) -> Optional[str]:
        """Extract chapter ID from MangaDex URL."""
        import re
        match = re.search(r'/chapter/([a-f0-9-]+)', url)
        return match.group(1) if match else None
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        url = f"{self.base_url}/manga"
        params = {
            "title": query,
            "limit": 10,
            "includes[]": ["cover_art"],
            "order[relevance]": "desc",
        }
        
        data = self._get_json(url, params=params)
        results = []
        
        for item in data.get("data", []):
            manga_id = item["id"]
            attrs = item["attributes"]
            
            # Get title (prefer English)
            titles = attrs.get("title", {})
            title = titles.get("en") or titles.get("ja-ro") or list(titles.values())[0]
            
            # Get cover
            cover_url = None
            for rel in item.get("relationships", []):
                if rel["type"] == "cover_art":
                    cover_filename = rel.get("attributes", {}).get("fileName")
                    if cover_filename:
                        cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}.256.jpg"
            
            results.append(Manga(
                title=title,
                url=f"https://mangadex.org/title/{manga_id}",
                cover_url=cover_url,
                description=attrs.get("description", {}).get("en", ""),
            ))
        
        return results
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all English chapters for a manga."""
        manga_id = self._extract_manga_id(manga_url)
        if not manga_id:
            raise ValueError(f"Could not extract manga ID from: {manga_url}")
        
        chapters = []
        offset = 0
        limit = 100
        
        while True:
            url = f"{self.base_url}/manga/{manga_id}/feed"
            params = {
                "translatedLanguage[]": ["en"],
                "order[chapter]": "asc",
                "limit": limit,
                "offset": offset,
                "includes[]": ["scanlation_group"],
            }
            
            data = self._get_json(url, params=params)
            items = data.get("data", [])
            
            if not items:
                break
            
            for item in items:
                attrs = item["attributes"]
                chapter_num = attrs.get("chapter") or "0"
                groups = self._groups(item)
                if any(group.get("id") in self.removed_group_ids for group in groups):
                    continue
                
                # Skip external chapters (no pages hosted on MangaDex)
                if attrs.get("externalUrl") or attrs.get("pages", 0) == 0:
                    continue
                
                chapter = Chapter(
                    number=chapter_num,
                    title=attrs.get("title"),
                    url=f"https://mangadex.org/chapter/{item['id']}",
                    date=attrs.get("publishAt"),
                )
                chapter.group_ids = [g.get("id") for g in groups if g.get("id")]
                chapter.group_names = [g.get("attributes", {}).get("name") for g in groups
                                       if g.get("attributes", {}).get("name")]
                chapters.append(chapter)
            
            offset += limit
            if len(items) < limit:
                break
        
        # Sort and deduplicate. MangaDex can have multiple English uploads for
        # the same chapter, and API tie ordering is not stable enough to trust.
        # Prefer the earliest upload so repeated checks pick the same scanlation
        # instead of flipping between duplicates.
        seen = set()
        unique_chapters = []
        for ch in sorted(chapters, key=lambda ch: (ch.numeric, ch.date or "")):
            if ch.number not in seen:
                seen.add(ch.number)
                unique_chapters.append(ch)
        
        return unique_chapters
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        chapter_id = self._extract_chapter_id(chapter_url)
        if not chapter_id:
            raise ValueError(f"Could not extract chapter ID from: {chapter_url}")

        # Recheck the group at download time, including older cached chapters.
        if self.removed_group_ids:
            chapter = self._get_json(
                f"{self.base_url}/chapter/{chapter_id}",
                params={"includes[]": ["scanlation_group"]},
            )["data"]
            if any(g.get("id") in self.removed_group_ids for g in self._groups(chapter)):
                raise ValueError("Chapter is unavailable at the scanlation group's request")
        
        url = f"{self.base_url}/at-home/server/{chapter_id}"
        data = self._get_json(url)
        
        base = data["baseUrl"]
        chapter_hash = data["chapter"]["hash"]
        quality = "dataSaver" if self.data_saver else "data"
        pages = data["chapter"][quality]
        with self._at_home_lock:
            self._at_home[chapter_hash] = {"chapter_id": chapter_id, "base": base}
        
        path = "data-saver" if self.data_saver else "data"
        return [f"{base}/{path}/{chapter_hash}/{page}" for page in pages]

    def _refresh_node(self, chapter_hash: str, failed_base: str):
        """Ask for a new MangaDex@Home node after a failed image."""
        with self._at_home_lock:
            node = self._at_home.get(chapter_hash)
            if not node or node["base"] != failed_base:
                return  # Unknown chapter, or another page already refreshed it.
            try:
                data = self._get_json(
                    f"{self.base_url}/at-home/server/{node['chapter_id']}")
                node["base"] = data["baseUrl"]
            except Exception as exc:
                logger.debug("Could not refresh MangaDex@Home node: %s", exc)

    def download_image(self, url: str, path: Path) -> bool:
        """Fetch a chapter image and report MangaDex@Home results.

        https://api.mangadex.org/docs/04-chapter/retrieving-chapter/ asks for
        one report per image from a node outside mangadex.org, success or not.
        """
        base, sep, rest = url.partition("/data/")
        if not sep:
            base, sep, rest = url.partition("/data-saver/")
        if (not sep or not base.startswith("https://")
                or "mangadex.org" in urlparse(base).netloc):
            return super().download_image(url, path)

        chapter_hash = rest.split("/", 1)[0]
        with self._at_home_lock:
            node = self._at_home.get(chapter_hash)
            if node:
                base = node["base"]
        url = f"{base}{sep}{rest}"

        def _attempt():
            # Same spacing and retry budget as BaseScraper._request, but each
            # attempt is reported on its own.
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            start = time.monotonic()
            response = None
            content = b""
            retrieved = False
            try:
                response = self.session.get(url, timeout=30)
                content = response.content
                response.raise_for_status()
                retrieved = True
                return content
            finally:
                self._report(url, retrieved, response, content, start)

        try:
            content = _retry(
                _attempt,
                max_attempts=3,
                base_delay=1.0,
                exceptions=(requests.RequestException,),
            )
        except Exception as exc:
            logger.debug("Failed to retrieve %s: %s", url, exc)
            self._refresh_node(chapter_hash, base)
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except OSError as exc:
            logger.debug("Failed to save %s: %s", url, exc)
            return False

    @staticmethod
    def _report(url, success, response, content, start):
        """Send one MangaDex@Home report; never affects the image result."""
        try:
            report = {
                "url": url,
                "success": success,
                "cached": bool(response is not None and
                               response.headers.get("X-Cache", "").startswith("HIT")),
                "bytes": len(content),
                "duration": max(0, round((time.monotonic() - start) * 1000)),
            }
            requests.post(_REPORT_URL, json=report,
                          headers={"User-Agent": USER_AGENT}, timeout=5)
        except Exception as exc:
            logger.debug("MangaDex@Home report failed: %s", exc)
