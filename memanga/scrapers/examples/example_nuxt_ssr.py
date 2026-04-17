"""
Example: Single-manga Nuxt SSR site using NuxtSSRScraper template.

Use this pattern for sites that:
- Host exactly one manga series
- Are built with Nuxt.js (server-side rendered)
- Serve images from an assets CDN with sequential paths like:
    https://assets.example.com/manga-slug/chapter-1/page-001.jpg

Chapters are detected from the homepage HTML (e.g., "Read Latest Chapter (42)").
Images are constructed from ASSETS_URL + chapter number + page index — no scraping needed.

Just fill in the class attributes.

Real examples: dddmanga.com (Dandadan), chainsawdevil.com (Chainsaw Man),
               jjkaisen.com (JJK), vinlandmanga.com (Vinland Saga)
"""

from ..templates.nuxt_ssr import NuxtSSRScraper


class ExampleNuxtScraper(NuxtSSRScraper):
    """Single-manga Nuxt SSR site with assets CDN."""

    # Main site URL
    BASE_URL = "https://example-nuxt-manga.com"

    # CDN base URL where images are stored.
    # Images follow the pattern: {ASSETS_URL}/chapter-{N}/{page:03d}.jpg
    ASSETS_URL = "https://assets.example-nuxt-manga.com/my-manga-slug"

    # Display title
    MANGA_TITLE = "My Manga Title"

    # Search keywords — if any of these appear in the query, return this manga
    SEARCH_KEYWORDS = ["my manga", "manga title", "author name"]

    # Fallback max chapter count if the homepage doesn't advertise the latest chapter
    FALLBACK_MAX = 150
