"""
ReadOnePiece scraper (ww8.readonepiece.com / ww12.readonepiece.com) - One Piece dedicated site.

Uses WordPress manga theme with CDN-hosted images.
"""

from .readmanga_base import ReadMangaBaseScraper


class ReadOnePieceScraper(ReadMangaBaseScraper):
    """Scraper for readonepiece.com - One Piece manga."""
    
    name = "readonepiece"
    base_url = "https://ww12.readonepiece.com"
    cdn_pattern = r"cdn\.readonepiece\.com"
