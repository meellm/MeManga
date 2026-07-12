"""
MangaPark scraper
https://mangapark1.com

MangaPark's older domains are unreliable from normal requests, while
mangapark1.com currently serves the catalog without a browser challenge.
Chapter lists come from the site's JSON endpoint, and page images need a
Referer header when downloaded from the CDN.
"""

import re
import logging
from typing import List
from urllib.parse import quote_plus
from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class MangaParkScraper(BaseScraper):
    """Scraper for MangaPark (mangapark1.com)."""

    name = "mangapark"
    base_url = "https://mangapark1.com"

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title via /filter?keyword=..."""
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/filter?keyword={quote_plus(query)}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        seen = set()
        # Result cards are div.unit; each holds a poster link and a text
        # title link, both pointing at /manga/<slug>.
        for unit in soup.select("div.unit"):
            link = unit.select_one('a[href*="/manga/"]')
            if not link:
                continue
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"

            img = unit.find("img")
            # Poster link text is just a flag emoji; prefer the info-block
            # text link, then the cover's alt attribute.
            title = ""
            for a in unit.select('a[href*="/manga/"]'):
                text = a.get_text(strip=True)
                if text and not a.find("img") and len(text) > 2:
                    title = text
                    break
            if not title and img:
                title = img.get("alt", "")
            if not title:
                title = href.rstrip("/").split("/")[-1].replace("-", " ").title()

            cover_url = None
            if img:
                cover_url = img.get("data-src") or img.get("src")
                if cover_url and cover_url.startswith("/"):
                    cover_url = f"{self.base_url}{cover_url}"

            if title and len(title) > 2:
                results.append(Manga(
                    title=title,
                    url=manga_url,
                    cover_url=cover_url,
                ))

        return results[:10]

    def _slug_from_url(self, manga_url: str) -> str:
        """Extract the comic slug from a /manga/<slug> URL."""
        match = re.search(r"/manga/([^/?#]+)", manga_url)
        if not match:
            raise ValueError(f"Not a MangaPark manga URL: {manga_url}")
        return match.group(1)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters via the JSON chapter-list endpoint.

        The manga page HTML only embeds the latest ~20 chapters; the
        site's own "Load All Chapters" button calls this endpoint.
        """
        slug = self._slug_from_url(manga_url)
        try:
            data = self._get_json(
                f"{self.base_url}/get-chapter-list",
                params={"slug": slug},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            entries = data.get("data", []) if data.get("success") else []
        except Exception as e:
            logger.debug(f"Chapter-list endpoint failed for {slug}: {e}")
            entries = []

        chapters = []
        seen = set()
        for entry in entries:
            chapter_slug = entry.get("chapter_slug")
            if not chapter_slug or chapter_slug in seen:
                continue
            seen.add(chapter_slug)

            num = entry.get("chapter_num")
            if isinstance(num, float) and num.is_integer():
                num = int(num)
            number = str(num) if num is not None else ""
            if not number:
                match = re.search(r"(\d+\.?\d*)", chapter_slug)
                number = match.group(1) if match else chapter_slug

            chapters.append(Chapter(
                number=number,
                title=entry.get("chapter_name"),
                url=f"{self.base_url}/read/{slug}/{chapter_slug}",
                date=entry.get("updated_at"),
            ))

        if not chapters:
            chapters = self._chapters_from_html(manga_url, slug)

        return sorted(chapters)

    def _chapters_from_html(self, manga_url: str, slug: str) -> List[Chapter]:
        """Fallback: scrape /read/<slug>/... links off the manga page."""
        from bs4 import BeautifulSoup

        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()
        for link in soup.select(f'a[href*="/read/{slug}/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            text = link.get("title") or link.get_text(strip=True)
            match = re.search(r"chapter[_\s-]*(\d+\.?\d*)", text, re.I) \
                or re.search(r"(\d+\.?\d*)", text) \
                or re.search(r"chapter[_\s-]*(\d+)(?:-(\d+))?", href, re.I)
            if match and len(match.groups()) > 1 and match.group(2):
                number = f"{match.group(1)}.{match.group(2)}"
            else:
                number = match.group(1) if match else text

            chapters.append(Chapter(
                number=number,
                title=text or None,
                url=chapter_url,
            ))

        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs from the reader page.

        Pages are lazyload <img data-src> tags inside div.pages; the
        CDN URLs are server-rendered, no JS needed.
        """
        from bs4 import BeautifulSoup

        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()
        for img in soup.select("div.pages img"):
            src = img.get("data-src") or img.get("src")
            if not src or "/assets/" in src or src in seen:
                continue
            seen.add(src)
            pages.append(src)

        return pages

    def download_image(self, url: str, path) -> bool:
        """Download image with Referer — the CDN 403s without it."""
        from pathlib import Path

        try:
            response = self._request(url, headers={"Referer": f"{self.base_url}/"})
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False
