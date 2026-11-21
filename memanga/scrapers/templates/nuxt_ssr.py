"""
Template for Nuxt SSR single-manga sites with assets CDN.

Sites like dddmanga.com, chainsawdevil.com, jjkaisen.com, etc.
All share: sequential chapters, assets CDN for images, single manga per site.

Subclass config attributes:
    BASE_URL: str        - Site URL (e.g., "https://dddmanga.com")
    ASSETS_URL: str      - CDN base (e.g., "https://assets.dddmanga.com/dandadan")
    MANGA_TITLE: str     - Display title (e.g., "Dandadan")
    SEARCH_KEYWORDS: list - Strings that trigger search match
    CHAPTERS_FROM_LINKS: bool - List the chapters the site links (including
                           decimal ones such as /chapter/16-5/) instead of
                           numbering 1..N; off by default
"""

import logging
import re
from typing import List
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


class NuxtSSRSourceError(RuntimeError):
    """The site answered, but with no chapter information to list."""


class NuxtSSRScraper(BaseScraper):
    """Template for Nuxt SSR single-manga sites with sequential chapters."""

    BASE_URL: str = ""
    ASSETS_URL: str = ""
    MANGA_TITLE: str = ""
    SEARCH_KEYWORDS: list = []
    CHAPTERS_FROM_LINKS: bool = False

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.BASE_URL,
        })

    def search(self, query: str) -> List[Manga]:
        """Search returns the single manga if query matches keywords."""
        q = query.lower()
        for kw in self.SEARCH_KEYWORDS:
            if kw.lower() in q or q in kw.lower():
                return [Manga(
                    title=self.MANGA_TITLE,
                    url=self.BASE_URL,
                )]
        return []

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters by detecting max chapter from homepage."""
        if self.CHAPTERS_FROM_LINKS:
            return self._chapters_from_links()
        # A failed fetch raises; there is no list to guess.
        resp = self._request(self.BASE_URL)

        # Try "Read Latest Chapter (N)" pattern
        match = re.search(r'Read Latest Chapter \((\d+)\)', resp.text)
        if match:
            max_chapter = int(match.group(1))
        else:
            # Fallback: find highest chapter number in links
            chapter_matches = re.findall(r'/chapter/(\d+)/', resp.text)
            max_chapter = max((int(c) for c in chapter_matches), default=0)
        if max_chapter < 1:
            raise NuxtSSRSourceError(
                f"No chapter count or chapter links found on {self.BASE_URL}")

        return [
            Chapter(
                number=str(i),
                title=f"Chapter {i}",
                url=f"{self.BASE_URL}/chapter/{i}/",
            )
            for i in range(1, max_chapter + 1)
        ]

    # A released chapter link on the series page: /chapter/12/ or the
    # decimal form /chapter/12-5/ (chapter 12.5).
    _CHAPTER_LINK_RE = r'chapter/(\d+)(?:-(\d+))?/?'

    def _chapters_from_links(self) -> List[Chapter]:
        """List the chapters the series page links to.

        The series page is BASE_URL after any redirect. Only links under
        that page's own host and path count, links the site marks as
        unreleased are skipped, and each chapter keeps the site's own
        path (``/chapter/16-5/`` is chapter 16.5). A failed fetch or a
        page without chapter links raises instead of guessing a list.
        """
        resp = self._request(self.BASE_URL)
        page_url = getattr(resp, "url", None) or self.BASE_URL
        final = urlparse(page_url)
        series_path = final.path if final.path.endswith("/") else final.path + "/"
        link_re = re.compile(re.escape(series_path) + self._CHAPTER_LINK_RE)

        found = {}
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            # The site marks a listed-but-unreleased chapter's row (the
            # link or an element around it) with the "unreleased" class.
            if any("unreleased" in (el.get("class") or [])
                   for el in (a, *a.parents)):
                continue
            target = urlparse(urljoin(page_url, a["href"]))
            if target.netloc != final.netloc:
                continue
            match = link_re.fullmatch(target.path)
            if not match:
                continue
            whole, part = match.groups()
            chapter_id = f"{whole}-{part}" if part else whole
            found.setdefault(chapter_id, f"{whole}.{part}" if part else whole)

        if not found:
            raise NuxtSSRSourceError(f"No chapter links found on {self.BASE_URL}")

        chapters = [
            Chapter(
                number=number,
                title=f"Chapter {number}",
                url=f"{self.BASE_URL}/chapter/{chapter_id}/",
            )
            for chapter_id, number in found.items()
        ]
        return sorted(chapters, key=lambda c: c.numeric)

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images from assets CDN (or the Mangayi CDN after redirect)."""
        try:
            resp = self._request(chapter_url)
        except Exception:
            return []

        # Extract chapter number from URL (link-listed chapters may be
        # decimal: /chapter/16-5/)
        chapter_re = (r'/chapter/(\d+(?:-\d+)?)/' if self.CHAPTERS_FROM_LINKS
                      else r'/chapter/(\d+)/')
        match = re.search(chapter_re, chapter_url)
        if not match:
            return []
        chapter_num = match.group(1)

        # Find images from assets CDN: assets.{domain}/{manga}/chapter-N/X.ext
        assets_escaped = re.escape(self.ASSETS_URL)
        img_matches = re.findall(
            rf'src="({assets_escaped}/chapter-{chapter_num}/\d+\.(?:jpeg|jpg|png|webp))"',
            resp.text
        )

        if img_matches:
            return list(dict.fromkeys(img_matches))

        # Sites now redirect to mangayi.com, which serves pages from a different
        # CDN host and manga slug: {cdn}/image/{slug}/chapter-N/X.ext
        img_matches = re.findall(
            rf'src="(https?://[^/"]+/image/[^/"]+/chapter-{chapter_num}/\d+\.(?:jpeg|jpg|png|webp))"',
            resp.text
        )
        if img_matches:
            return list(dict.fromkeys(img_matches))

        # Fallback: any image from the assets domain (filter to image extensions)
        all_imgs = re.findall(
            rf'src="({assets_escaped}/[^"]+\.(?:jpeg|jpg|png|webp|gif))"',
            resp.text
        )
        return list(dict.fromkeys(all_imgs))

    def download_image(self, url: str, path: Path) -> bool:
        """Download image with Referer header."""
        try:
            response = self._request(url, headers={
                "Referer": self.BASE_URL,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            })

            if len(response.content) < 1000:
                return False

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False
