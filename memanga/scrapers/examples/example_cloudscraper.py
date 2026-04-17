"""
Example: Cloudflare-protected site using cloudscraper.

Use this pattern for sites that:
- Return a Cloudflare challenge page to plain requests
- Work fine once the JS challenge is solved (no heavy interactivity needed)
- Don't require a real browser for page rendering

Real examples: jjkmanga.net, coffeemanga.io, mgeko.cc, manhuafast.com
"""

import re
import cloudscraper
from typing import List
from bs4 import BeautifulSoup
from ..base import BaseScraper, Chapter, Manga


class ExampleCloudscraperScraper(BaseScraper):
    """Scraper for a Cloudflare-protected manga site."""

    name = "example_cf"
    base_url = "https://example-cf-site.com"

    def __init__(self):
        super().__init__()
        # Replace the default requests.Session with a cloudscraper session
        self.session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.session.headers.update({
            "Referer": f"{self.base_url}/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def search(self, query: str) -> List[Manga]:
        url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=manga"
        soup = BeautifulSoup(self._get_html(url), "html.parser")

        results = []
        for item in soup.select(".post-title a"):
            href = item.get("href", "")
            title = item.get_text(strip=True)
            if href and title:
                results.append(Manga(title=title, url=href))
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        soup = BeautifulSoup(self._get_html(manga_url), "html.parser")

        chapters = []
        for li in soup.select("ul.version-chap li.wp-manga-chapter"):
            a = li.select_one("a")
            if not a:
                continue
            href = a["href"]
            match = re.search(r'chapter-(\d+(?:\.\d+)?)', href, re.IGNORECASE)
            number = match.group(1) if match else a.get_text(strip=True)
            chapters.append(Chapter(number=number, title=a.get_text(strip=True), url=href))

        return sorted(chapters, reverse=True)

    def get_pages(self, chapter_url: str) -> List[str]:
        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")

        pages = []
        for img in soup.select(".reading-content img"):
            src = img.get("data-src") or img.get("src") or ""
            src = src.strip()
            if src and not src.startswith("data:"):
                pages.append(src)
        return pages
