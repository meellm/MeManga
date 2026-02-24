"""
ReadSNK scraper (readsnk.com) - Attack on Titan/Shingeki no Kyojin dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadSNKScraper(ReadMangaBaseScraper):
    """Scraper for readsnk.com - Attack on Titan manga."""
    
    name = "readsnk"
    base_url = "https://readsnk.com"
    cdn_pattern = r"cdn\.readsnk\.com"
