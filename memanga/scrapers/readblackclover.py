"""
ReadBlackClover scraper (readblackclover.com / ww7.readblackclover.com) - Black Clover dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadBlackCloverScraper(ReadMangaBaseScraper):
    """Scraper for readblackclover.com - Black Clover manga."""
    
    name = "readblackclover"
    base_url = "https://ww7.readblackclover.com"
    cdn_pattern = r"cdn\.readblackclover\.com"
