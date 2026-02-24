"""
ReadJujutsuKaisen scraper (readjujutsukaisen.com) - Jujutsu Kaisen dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadJujutsuKaisenScraper(ReadMangaBaseScraper):
    """Scraper for readjujutsukaisen.com - Jujutsu Kaisen manga."""
    
    name = "readjujutsukaisen"
    base_url = "https://readjujutsukaisen.com"
    cdn_pattern = r"cdn\.readjujutsukaisen\.com"
