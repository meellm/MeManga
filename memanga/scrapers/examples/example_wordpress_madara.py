"""
Example: WordPress Madara theme scraper (multi-manga aggregator or single-manga site).

Use this pattern for sites that:
- Run on WordPress with the Madara manga theme
- Have URLs like /manga/<slug>/ and /manga/<slug>/<chapter>/
- Optionally use AJAX POST to load chapter images

Madara is one of the most common manga WordPress themes — used by hundreds of sites.
Spot it by: /wp-content/plugins/madara/ in page source, or chapter URLs ending in
/<chapter-number>/<style>/ with a "manga" post type.

Just fill in the class attributes.

Real examples: mangayy.org, isekaiscan.com (Playwright variant), zinmanga.com,
               kunmanga.com, mangaclash.com
"""

from ..templates.wordpress_madara import WordPressMadaraScraper


class ExampleMadaraScraper(WordPressMadaraScraper):
    """WordPress Madara theme — multi-manga aggregator."""

    base_url = "https://example-madara-site.com"

    # Leave empty for multi-manga aggregators; set for dedicated single-manga sites
    manga_title = ""
    manga_slug = ""
    is_single_manga = False

    # CDN substrings to accept as valid page images.
    # Check a chapter page's <img> tags to find the CDN hostname.
    image_cdn_filters = ["cdn.example-madara-cdn.com"]

    # True if the site has Cloudflare protection
    uses_cloudscraper = False

    # True if chapter pages are loaded via wp-admin/admin-ajax.php POST
    # (check Network tab: POST to /wp-admin/admin-ajax.php with action=manga_get_reading_style)
    uses_ajax = False


# ── Single-manga variant ──────────────────────────────────────────────────────

class ExampleMadaraSingleScraper(WordPressMadaraScraper):
    """WordPress Madara theme — dedicated single-manga site."""

    base_url = "https://my-manga-site.com"
    manga_title = "My Manga"
    manga_slug = "my-manga"         # The URL slug: /manga/my-manga/
    is_single_manga = True
    image_cdn_filters = ["img.spoilerhat.com"]
    uses_cloudscraper = True
