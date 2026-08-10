"""
VyManga scraper
https://mangavyvy.net (formerly vymanga.net / vyvymanga.net)

General manga aggregator. Search and detail pages live on the main site,
but each chapter link routes through an encrypted ad-redirect chain
(aovheroes.com -> summonersky.com) that resolves to a reader page. The
reader page's images are served from Blogger/Google storage. requests
follows the redirect chain automatically, so get_pages just parses the
reader HTML the chain lands on.
"""

import re
from typing import List
from urllib.parse import quote
from .base import BaseScraper, Chapter, Manga


class VyMangaScraper(BaseScraper):
    """Scraper for VyManga (mangavyvy.net)."""

    name = "vymanga"
    base_url = "https://mangavyvy.net"

    def search(self, query: str) -> List[Manga]:
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/search?q={quote(query)}"
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        results = []
        seen = set()

        for item in soup.select("div.comic-item"):
            link = item.select_one('a[href*="/manga/"]')
            if not link:
                continue
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            img = item.select_one("img")

            title_el = item.select_one(".comic-title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title and img:
                title = img.get("title") or img.get("alt") or ""
            title = title.strip()
            if not title:
                continue

            cover_url = None
            if img:
                cover_url = img.get("data-src") or img.get("src")

            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))

        return results[:20]

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(self._get_html(manga_url), "html.parser")

        chapters = []
        seen = set()

        for link in soup.select("a.list-chapter"):
            href = link.get("href", "")
            if not href or href in seen:
                continue

            span = link.select_one("span")
            label = span.get_text(strip=True) if span else ""

            # Chapter number lives in id="chapter-<num>"; fall back to label.
            match = re.search(r"chapter-([\d.]+)", link.get("id", ""), re.I)
            if not match:
                match = re.search(r"chapter\s*([\d.]+)", label, re.I)
            number = match.group(1).rstrip(".") if match else label

            seen.add(href)
            chapters.append(Chapter(
                number=number,
                title=label or f"Chapter {number}",
                url=href,
            ))

        return sorted(chapters, key=lambda c: c.numeric)

    def get_pages(self, chapter_url: str) -> List[str]:
        from bs4 import BeautifulSoup

        # The chapter link routes through an ad-redirect chain that requests
        # follows automatically to the reader page holding the images.
        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")

        container = soup.select_one("#carousel, .vview, .carousel-inner")
        images = container.select("img") if container else soup.select(".carousel-item img")

        pages = []
        seen = set()
        for img in images:
            src = img.get("data-src") or img.get("src") or ""
            src = src.strip()
            if not src or src in seen:
                continue
            low = src.lower()
            if low.endswith(".gif") or any(x in low for x in ("loading", "blank", "logo", "icon")):
                continue
            seen.add(src)
            pages.append(src)

        return pages
