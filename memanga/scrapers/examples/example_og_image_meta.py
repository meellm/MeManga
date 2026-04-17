"""
Example: Single-manga dedicated site using OGImageMetaScraper template.

Use this pattern for sites that:
- Host exactly one manga series
- Use WordPress with Comic Easel or similar plugin
- Serve chapter images via og:image / twitter:image meta tags
- Host images on an external CDN (Blogger, mangaclash, readkakegurui, etc.)

Just subclass OGImageMetaScraper and fill in the class attributes — no methods needed.

Real examples: beastarsmanga.com, vagabondmanga.org, demonslayermanga.com,
               readkakegurui.com, bocchitherockmanga.com
"""

from ..templates.og_image_meta import OGImageMetaScraper


class ExampleOGImageScraper(OGImageMetaScraper):
    """Single-manga site serving pages via og:image meta tags."""

    # Site URL (no trailing slash)
    base_url = "https://example-dedicated-manga.com"

    # Title shown in search results
    manga_title = "My Manga Title"

    # Regex that matches chapter page hrefs (used to find chapter links on homepage)
    chapter_link_pattern = r'chapter-\d+'

    # CDN hostname substrings — only img tags/meta tags matching these are accepted as pages.
    # Find this by inspecting a chapter page: look for <img> or og:image content URLs.
    image_cdn_filters = ["cdn.example-manga-cdn.com"]

    # Optional: cover image URL shown in search results
    cover_url = "https://example-dedicated-manga.com/wp-content/uploads/cover.jpg"

    # Set True if the site shows a Cloudflare challenge page
    uses_cloudscraper = False

    # Set True if images are served from Blogger CDN (auto-upgrades to /s1600/ resolution)
    normalize_blogger = False
