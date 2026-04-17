"""
Example: WordPress Mangosm theme site (MangosmScraper template).

Use this pattern for sites that:
- Are single-manga WordPress sites using the Mangosm theme
- Serve images from CDNs like mangafreak.me, mangarchive.com, planeptune.us,
  cdn.mangaclash.com, or saidvps.xyz

Spot it by: /wp-content/themes/mangosm/ in page source, or chapter URLs like
/my-manga-chapter-12/.

Real examples: hajimnoippo.com, readkingdomfree.com (planeptune CDN),
               homunculusmanga.com (mangaread.org CDN)
"""

from ..templates.mangosm import MangosmScraper


class ExampleMangosmScraper(MangosmScraper):
    """Single-manga WordPress Mangosm theme site."""

    # Site URL
    base_url = "https://example-mangosm-site.com"

    # Display title
    manga_title = "My Manga"

    # URL slug used in chapter links: /my-manga-chapter-12/
    manga_slug = "my-manga"

    # CDN domain substrings to accept as valid page images
    cdn_domains = ["planeptune.us"]

    # Override CDN Referer if it differs from base_url (leave empty to use base_url)
    cdn_referer = ""

    # Regex matching chapter href pattern (auto-set from manga_slug if left empty)
    chapter_link_pattern = ""
