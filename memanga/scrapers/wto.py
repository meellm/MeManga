"""
WTO scraper - Bato mirror
https://wto.to

wto.to serves the same Bato-style HTML as bato.to, so all parsing is
inherited from BatoToScraper. The difference is transport: wto.to sits
behind a Cloudflare managed challenge that 403s plain requests and
cloudscraper, so HTML fetches go through Playwright instead.

The challenge does not always auto-resolve for headless browsers.
When that happens we return the challenge page as-is and the inherited
parsers yield empty results instead of crashing; live health checks
classify the domain as PROTECTED.
"""

import logging

from .batoto import BatoToScraper
from .playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)


def _is_cf_challenge(html: str) -> bool:
    """True if the HTML is a Cloudflare interstitial, not real content."""
    head = html[:3000].lower()
    return any(
        marker in head
        for marker in (
            "just a moment",
            "cf-chl",
            "performing security verification",
            "cf-turnstile",
            "ray id",
        )
    )


class WTOScraper(BatoToScraper, PlaywrightScraper):
    """Scraper for wto.to (Bato mirror behind Cloudflare)."""

    name = "wto"
    base_url = "https://wto.to"

    def _get_html(self, url: str) -> str:
        """Fetch HTML via Playwright so the Cloudflare challenge can run."""
        html = self._get_page_content(url, wait_time=6000)
        if _is_cf_challenge(html):
            # Give the managed challenge one longer chance to auto-resolve.
            html = self._get_page_content(url, wait_time=15000)
        if _is_cf_challenge(html):
            logger.warning(
                "wto.to Cloudflare challenge did not clear for %s - "
                "returning challenge page (parsers will find no content)",
                url,
            )
        return html
