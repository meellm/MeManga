"""
Base scrapers for dedicated single-title sites.

These sites serve one series: every chapter is linked from one page and
chapter pages are plain <img> tags (or og:image tags) pointing at a CDN.
Subclasses set class attributes and, for a site-specific rule, override
one small hook; see single_title_sites.py.

They stay registered as individual scrapers rather than registry
templates, so the search sweep still includes them (their search() makes
no request).

Series attributes:
    manga_title: str             - Series title returned by search()
    manga_path: str              - Path of the series URL returned by search()
    chapter_list_path: str       - Path of the chapter list page (default: manga_path)
    cover_url: str               - Optional cover image URL

Chapter list (SingleTitleScraper):
    chapter_link_selector: str   - CSS selector for chapter links; when empty,
                                   links whose href matches chapter_href_pattern
    chapter_href_pattern: str    - Case-insensitive href regex (selector unset)
    chapter_number_pattern: str  - Regex whose group 1 is the chapter number
    chapter_number_lowercase     - Match the number pattern against the lowercased href
    chapter_number_dash_decimal  - Read "12-5" as chapter 12.5
    chapter_requires_number      - Skip links whose href has no chapter number
    absolute_chapter_urls        - Prefix relative hrefs with base_url
    untitled_links: str          - Title for a link without text: "" skips the link,
                                   "number" uses "Chapter <number>", "matched-number"
                                   does so only when the href has a number, and
                                   "integer" uses the digits after "chapter-"
    numeric_titles               - A title that is only digits becomes "Chapter <number>"

Pages:
    image_container_class: str   - Class of the element holding the pages (fallback: whole page)
    image_attrs: tuple           - <img> attributes to read, in order
    image_cdn_filters: tuple     - Accept an image URL containing any of these
"""

import logging
import re
from typing import Iterable, List, Optional, Tuple
from bs4 import BeautifulSoup
from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)


def _float_or_zero(number: str) -> float:
    try:
        return float(number)
    except ValueError:
        return 0


class SingleTitleScraper(BaseScraper):
    """Base scraper for dedicated single-title CDN sites."""

    name: str = "single_title_base"
    base_url: str = ""
    manga_title: str = ""
    manga_path: str = "/"
    chapter_list_path: Optional[str] = None
    cover_url: Optional[str] = None

    chapter_link_selector: str = ""
    chapter_href_pattern: str = r'chapter-\d+'
    chapter_number_pattern: str = r'chapter-(\d+(?:\.\d+)?)'
    chapter_number_lowercase: bool = True
    chapter_number_dash_decimal: bool = False
    chapter_requires_number: bool = False
    absolute_chapter_urls: bool = True
    untitled_links: str = ""
    numeric_titles: bool = False

    image_container_class: str = ""
    image_attrs: Tuple[str, ...] = ("src", "data-src")
    image_cdn_filters: Tuple[str, ...] = ()

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": self.base_url,
        })

    @property
    def _manga_url(self) -> str:
        return self.base_url + self.manga_path

    @property
    def _chapter_list_url(self) -> str:
        path = self.manga_path if self.chapter_list_path is None else self.chapter_list_path
        return self.base_url + path

    def search(self, query: str) -> List[Manga]:
        """Search for manga (single manga site)."""
        return [Manga(
            title=self.manga_title,
            url=self._manga_url,
            cover_url=self.cover_url,
        )]

    # ── Chapters ──────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters from the series page."""
        html = self._get_html(self._chapter_list_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()

        for link in self._chapter_links(soup):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            text = link.get_text(strip=True)

            if self.absolute_chapter_urls and not href.startswith("http"):
                href = self._absolute(href)

            number, matched = self._chapter_number(href)
            if not matched and self.chapter_requires_number:
                continue

            if not text:
                text = self._untitled_title(link, href, number, matched)
                if not text:
                    continue
            else:
                text = self._chapter_title(text, number)

            if self._skip_chapter(href):
                continue

            chapters.append(Chapter(
                number=number,
                title=text,
                url=href,
            ))

        # Sort by chapter number descending
        chapters.sort(key=lambda c: c.numeric, reverse=True)
        return chapters

    def _chapter_links(self, soup) -> list:
        if self.chapter_link_selector:
            return soup.select(self.chapter_link_selector)
        return soup.find_all("a", href=re.compile(self.chapter_href_pattern, re.I))

    def _absolute(self, href: str) -> str:
        return self.base_url + href

    def _chapter_number(self, href: str) -> Tuple[str, bool]:
        """Chapter number in ``href`` ("0" when there is none), and whether one was found."""
        source = href.lower() if self.chapter_number_lowercase else href
        match = re.search(self.chapter_number_pattern, source)
        if not match:
            return "0", False
        number = match.group(1)
        if self.chapter_number_dash_decimal:
            number = number.replace("-", ".")
        return number, True

    def _untitled_title(self, link, href: str, number: str, matched: bool) -> Optional[str]:
        """Title for a chapter link without text; None skips the link."""
        if self.untitled_links == "number":
            return f"Chapter {number}"
        if self.untitled_links == "matched-number":
            return f"Chapter {number}" if matched else None
        if self.untitled_links == "integer":
            match = re.search(r'chapter-(\d+)', href, re.I)
            return f"Chapter {match.group(1)}" if match else None
        return None

    def _chapter_title(self, text: str, number: str) -> str:
        if self.numeric_titles and text.isdigit():
            return f"Chapter {number}"
        return text

    def _skip_chapter(self, href: str) -> bool:
        return False

    # ── Pages ─────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs."""
        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        return self._page_urls(soup)

    def _page_urls(self, soup) -> List[str]:
        container = soup
        if self.image_container_class:
            container = soup.find(class_=self.image_container_class) or soup
        return self._pick(self._img_srcs(container.find_all("img")))

    def _img_srcs(self, imgs: Iterable, attrs: Optional[Tuple[str, ...]] = None) -> List[str]:
        """The first non-empty attribute of each <img>, from ``attrs`` in order."""
        attrs = attrs or self.image_attrs
        srcs = []
        for img in imgs:
            src = ""
            for attr in attrs:
                src = img.get(attr) or ""
                if src:
                    break
            srcs.append(src.strip())
        return srcs

    @staticmethod
    def _meta_srcs(soup, props: Tuple[str, ...] = ("og:image", "twitter:image")) -> List[str]:
        """Image URLs from <meta property=...> tags, one property after another."""
        return [meta.get("content", "").strip()
                for prop in props
                for meta in soup.select(f'meta[property="{prop}"]')]

    def _pick(self, urls: Iterable[str], accept=None) -> List[str]:
        """Accepted page URLs in order, without duplicates or placeholders."""
        accept = accept or self._is_page_image
        pages = []
        seen = set()
        for url in urls:
            # Skip placeholder images
            if not url or url.startswith("data:") or "data:image" in url:
                continue
            if url not in seen and accept(url):
                seen.add(url)
                pages.append(url)
        return pages

    def _is_page_image(self, url: str) -> bool:
        return any(f in url for f in self.image_cdn_filters)

    # ── Download ──────────────────────────────────────────────────────

    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "Referer": self.base_url,
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False


class NumberedChaptersScraper(SingleTitleScraper):
    """Sites whose chapter list is every link to a numbered chapter URL.

    Chapters are deduplicated by number, titled "Chapter <number>" and
    listed oldest first. Relative links are resolved against
    chapter_url_base (default: base_url).
    """

    chapter_href_markers: Tuple[str, ...] = ("/manga/",)
    chapter_url_base: Optional[str] = None

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for the manga."""
        html = self._get_html(self._chapter_list_url)
        soup = BeautifulSoup(html, "html.parser")
        base = self.chapter_url_base or self.base_url

        chapters = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if (not all(m in href for m in self.chapter_href_markers)
                    or "chapter" not in href.lower()):
                continue

            if not href.startswith("http"):
                if href.startswith("/"):
                    href = base + href
                else:
                    href = base + "/" + href

            match = re.search(self.chapter_number_pattern, href)
            if match:
                number = match.group(1)
                if number not in seen:
                    seen.add(number)
                    chapters.append(Chapter(
                        number=number,
                        title=f"Chapter {number}",
                        url=href,
                    ))

        chapters.sort(key=lambda c: _float_or_zero(c.number))
        return chapters
