"""
Example: Simple requests-based multi-manga aggregator scraper.

Use this pattern for sites that:
- Have no Cloudflare or heavy bot protection
- Serve standard HTML with BeautifulSoup-parseable pages
- Host images on their own CDN (no special auth needed)

Real examples: mangapill.com, mangahere.cc, mangatown.com
"""

import re
from typing import List
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class ExampleRequestsScraper(BaseScraper):
    """Scraper for example-manga-site.com using plain requests."""

    name = "example"
    base_url = "https://example-manga-site.com"

    def search(self, query: str) -> List[Manga]:
        url = f"{self.base_url}/search?q={query.replace(' ', '+')}"
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        results = []
        for card in soup.select(".manga-card"):
            a = card.select_one("a[href]")
            img = card.select_one("img")
            if not a:
                continue
            results.append(Manga(
                title=a.get_text(strip=True),
                url=a["href"] if a["href"].startswith("http") else self.base_url + a["href"],
                cover_url=img.get("data-src") or img.get("src") if img else None,
            ))
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        soup = BeautifulSoup(self._get_html(manga_url), "html.parser")

        chapters = []
        for li in soup.select(".chapter-list li"):
            a = li.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = self.base_url + href

            match = re.search(r'chapter[/-](\d+(?:\.\d+)?)', href, re.IGNORECASE)
            number = match.group(1) if match else a.get_text(strip=True)

            chapters.append(Chapter(
                number=number,
                title=a.get_text(strip=True),
                url=href,
            ))

        return sorted(chapters, reverse=True)

    def get_pages(self, chapter_url: str) -> List[str]:
        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")

        pages = []
        for img in soup.select(".reading-content img"):
            src = img.get("data-src") or img.get("src") or ""
            if src and not src.startswith("data:"):
                pages.append(src.strip())
        return pages
