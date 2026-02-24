"""
ReadNaruto scraper (ww8.readnaruto.com) - Naruto dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadNarutoScraper(ReadMangaBaseScraper):
    """Scraper for readnaruto.com - Naruto manga."""
    
    name = "readnaruto"
    base_url = "https://ww8.readnaruto.com"
    cdn_pattern = r"cdn\.readnaruto\.com"
