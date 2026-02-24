"""
ReadBerserk scraper (readberserk.com) - Berserk dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadBerserkScraper(ReadMangaBaseScraper):
    """Scraper for readberserk.com - Berserk manga."""
    
    name = "readberserk"
    base_url = "https://readberserk.com"
    cdn_pattern = r"cdn\.readberserk\.com"
