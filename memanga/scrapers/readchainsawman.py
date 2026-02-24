"""
ReadChainsawMan scraper (readchainsawman.com) - Chainsaw Man dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadChainsawManScraper(ReadMangaBaseScraper):
    """Scraper for readchainsawman.com - Chainsaw Man manga."""
    
    name = "readchainsawman"
    base_url = "https://readchainsawman.com"
    cdn_pattern = r"cdn\.readchainsawman\.com|AnimeRleases"
