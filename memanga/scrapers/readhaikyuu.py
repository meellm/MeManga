"""
ReadHaikyuu scraper (readhaikyuu.com) - Haikyuu!! dedicated site.

Uses WordPress manga theme with CDN-hosted images.
Note: Uses cdn.readneverland.com for images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadHaikyuuScraper(ReadMangaBaseScraper):
    """Scraper for readhaikyuu.com - Haikyuu!! manga."""
    
    name = "readhaikyuu"
    base_url = "https://readhaikyuu.com"
    cdn_pattern = r"cdn\.read(haikyuu|neverland)\.com"
