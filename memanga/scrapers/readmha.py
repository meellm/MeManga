"""
ReadMHA scraper (readmha.com / ww8.readmha.com) - My Hero Academia dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadMHAScraper(ReadMangaBaseScraper):
    """Scraper for readmha.com - My Hero Academia manga."""
    
    name = "readmha"
    base_url = "https://ww8.readmha.com"
    cdn_pattern = r"cdn\.readmha\.com"
