"""
Scraper template classes for common site architectures.

These templates reduce duplication across 90+ scrapers that share identical logic
with only configuration differences (domain, CDN, selectors).
"""

from .nuxt_ssr import NuxtSSRScraper
from .og_image_meta import OGImageMetaScraper
from .laiond_cdn import LaiondCDNScraper
from .mangosm import MangosmScraper
from .wordpress_madara import WordPressMadaraScraper

__all__ = [
    "NuxtSSRScraper",
    "OGImageMetaScraper",
    "LaiondCDNScraper",
    "MangosmScraper",
    "WordPressMadaraScraper",
]
