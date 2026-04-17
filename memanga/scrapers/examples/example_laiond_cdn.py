"""
Example: WordPress site using laiond.com / loinew.com CDN (LaiondCDNScraper template).

Use this pattern for sites that:
- Are single-manga WordPress sites
- Serve chapter images from laiond.com, loinew.com, or a similar CDN
- Use /comic/<slug>/ or /manga/<slug>/ URL structure

Spot it by inspecting chapter page <img> tags — if src contains "laiond.com" or
"loinew.com", this template fits.

Real examples: hajime-no-ippo-manga.online, readkingdomfree.com
"""

from ..templates.laiond_cdn import LaiondCDNScraper


class ExampleLaiondScraper(LaiondCDNScraper):
    """Single-manga WordPress site with laiond.com CDN images."""

    # Site URL
    base_url = "https://read-my-manga.online"

    # Display title
    manga_title = "My Manga"

    # Regex matching chapter link hrefs on the homepage
    chapter_link_pattern = r'chapter-\d+'

    # CDN domains to accept as page images (default includes laiond.com)
    cdn_domains = ["laiond.com", "loinew.com"]

    # True if site has Cloudflare
    uses_cloudscraper = False

    # "comic" or "manga" — matches the URL path: /comic/<slug>/chapter-1/
    url_path_prefix = "comic"
