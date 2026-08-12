"""
VyManga scraper
https://mangavyvy.net (formerly vymanga.net / vyvymanga.net)

General manga aggregator. Search and detail pages live on the main site,
but each chapter link routes through an encrypted ad-redirect chain
(aovheroes.com -> aov-news.com / summonersky.com; the exact ad domains
rotate per request) that resolves to a reader page. The reader page's
images are served from Blogger/Google storage and need no Referer.
requests follows the redirect chain automatically, so get_pages just
parses the reader HTML the chain lands on -- taking care to keep only the
carousel slide images and drop the "same author" recommendation cover
thumbnails the reader embeds inside that same carousel.
"""

import re
from typing import List
from urllib.parse import quote, urlparse, urlunparse
from .base import BaseScraper, Chapter, Manga

# Old hosts still handed to us by the registry / saved libraries. Their
# /manga/ pages now 403; the identical path resolves on the canonical host.
_LEGACY_HOSTS = {"vymanga.net", "vyvymanga.net"}


class VyMangaScraper(BaseScraper):
    """Scraper for VyManga (mangavyvy.net)."""

    name = "vymanga"
    base_url = "https://mangavyvy.net"
    _canonical_host = "mangavyvy.net"

    def _canonical_url(self, url: str) -> str:
        """Rewrite legacy vymanga.net / vyvymanga.net hosts to the canonical
        host so direct old-domain manga URLs don't 403."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host in _LEGACY_HOSTS:
            return urlunparse(parsed._replace(netloc=self._canonical_host))
        return url

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

        soup = BeautifulSoup(self._get_html(self._canonical_url(manga_url)), "html.parser")

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

        # The chapter link routes through an ad-redirect chain (rotating ad
        # domains such as aovheroes.com -> aov-news.com / summonersky.com) that
        # requests follows automatically to the reader page holding the images.
        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")

        # Page images are the reader carousel slides: a single <img> directly
        # inside each .carousel-item. The reader also embeds a "same author"
        # recommendation table *inside* the same carousel whose cover thumbnails
        # (<img class="img-recommend">, served from the site's own cover CDN)
        # would otherwise be scraped as pages, so take only the direct slide
        # images and skip anything flagged as a recommendation thumbnail.
        images = soup.select(".carousel-item > img")
        if not images:
            container = soup.select_one("#carousel, .vview, .carousel-inner")
            images = container.select("img") if container else []

        pages = []
        seen = set()
        for img in images:
            if "img-recommend" in (img.get("class") or []):
                continue
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src or src in seen:
                continue
            # Skip the lazy-load placeholder (loading.gif / blank.gif). Test the
            # filename only, never the whole URL: reader page IDs are opaque
            # base64 blobs that can coincidentally contain "icon"/"logo"/etc.,
            # so a substring scan over the full URL would silently drop pages.
            name = urlparse(src).path.rsplit("/", 1)[-1].lower()
            if src.startswith("data:") or name.endswith(".gif"):
                continue
            seen.add(src)
            pages.append(src)

        return pages
