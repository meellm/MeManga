"""
Example: Dedicated single-manga site subclassing ReadMangaBaseScraper.

Use this pattern for sites in the read[manga].com family:
- readsnk.com, readberserk.com, readhaikyuu.com, readjujutsukaisen.com, etc.
- WordPress manga theme with CDN-hosted images
- Images require a Referer header to download

To add a new site in this family, subclass ReadMangaBaseScraper and set
the two required attributes. Override search() if the manga title/keywords differ.

Real examples: readsnk.com (Attack on Titan), readberserk.com (Berserk),
               readhaikyuu.com (Haikyuu!!), readjujutsukaisen.com (JJK)
"""

from ..readmanga_base import ReadMangaBaseScraper
from ..base import Manga
from typing import List


class ExampleReadMangaScraper(ReadMangaBaseScraper):
    """Dedicated single-manga read[x].com style site."""

    name = "examplemanga"
    base_url = "https://readexamplemanga.com"

    # Regex to identify CDN image URLs on chapter pages.
    # Inspect a chapter page's <img> src attributes to find the CDN hostname.
    cdn_pattern = r'cdn\.readexamplemanga\.com'

    def search(self, query: str) -> List[Manga]:
        query_lower = query.lower()
        # Return this manga if any relevant keyword appears in the query
        if any(kw in query_lower for kw in ["example manga", "example", "author name"]):
            return [Manga(
                title="Example Manga",
                url=f"{self.base_url}/manga/example-manga/",
                cover_url=f"{self.base_url}/wp-content/uploads/cover.jpg",
            )]
        return []
