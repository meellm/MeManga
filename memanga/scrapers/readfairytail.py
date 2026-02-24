"""
ReadFairyTail scraper (readfairytail.com / ww7.readfairytail.com) - Fairy Tail dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadFairyTailScraper(ReadMangaBaseScraper):
    """Scraper for readfairytail.com - Fairy Tail manga."""
    
    name = "readfairytail"
    base_url = "https://ww7.readfairytail.com"
    cdn_pattern = r"cdn\.readfairytail\.com"
