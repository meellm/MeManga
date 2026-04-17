"""
Example: REST API-based scraper.

Use this pattern for sites that:
- Expose a public or semi-public JSON API for search, chapters, and pages
- Don't require scraping HTML at all (or only minimally)
- May need authentication headers or API keys

Real examples: mangadex.org (public API), kagane.org (REST API + Playwright for images)

Tips:
- Use self._get_json(url) for GET requests returning JSON (rate-limited + retried).
- Use self._request(url).json() if you need custom params/headers.
- Set self._rate_limit to respect the API's rate limits (default: 1.0s between requests).
"""

from typing import List, Optional
from ..base import BaseScraper, Chapter, Manga


class ExampleAPIScraper(BaseScraper):
    """Scraper for a manga site with a REST API."""

    name = "example_api"
    base_url = "https://example-api-site.com"

    API_BASE = "https://api.example-api-site.com/v1"

    def __init__(self):
        super().__init__()
        self._rate_limit = 0.5  # Be polite: 0.5s between requests
        self.session.headers.update({
            "Accept": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            # "Authorization": "Bearer YOUR_API_KEY",  # If required
        })

    def search(self, query: str) -> List[Manga]:
        data = self._get_json(f"{self.API_BASE}/search", params={"q": query, "limit": 20})

        results = []
        for item in data.get("results", []):
            series_id = item.get("id")
            title = item.get("title", "")
            if not series_id or not title:
                continue
            results.append(Manga(
                title=title,
                url=f"{self.base_url}/series/{series_id}",
                cover_url=item.get("cover_url"),
            ))
        return results

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        # Extract series ID from URL: /series/<id>
        series_id = manga_url.rstrip("/").split("/")[-1]
        data = self._get_json(f"{self.API_BASE}/series/{series_id}/chapters")

        chapters = []
        for ch in data.get("chapters", []):
            chapters.append(Chapter(
                number=str(ch.get("number", 0)),
                title=ch.get("title") or None,
                url=f"{self.base_url}/read/{ch['id']}",
                date=ch.get("published_at"),
            ))
        return sorted(chapters)

    def get_pages(self, chapter_url: str) -> List[str]:
        chapter_id = chapter_url.rstrip("/").split("/")[-1]
        data = self._get_json(f"{self.API_BASE}/chapters/{chapter_id}/pages")

        return [page["url"] for page in data.get("pages", []) if page.get("url")]

    def _get_json(self, url: str, params: Optional[dict] = None) -> dict:
        """Rate-limited GET returning parsed JSON."""
        resp = self._request(url, params=params)
        resp.raise_for_status()
        return resp.json()
