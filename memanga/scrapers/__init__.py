"""
MeManga Scrapers

Working sources:
- TCBScans (tcbonepiecechapters.com) - Jump manga: One Piece, JJK, MHA
- WeebCentral (weebcentral.com) - Large library, 1000+ manga
- Asura Scans (asuracomic.net) - Manhwa specialist
- Mangakatana (mangakatana.com) - General library
- MangaDex (mangadex.org) - Community uploads (skip Shueisha)
- Mangapill (mangapill.com) - Large library, no Cloudflare
- MangaReader (mangareader.to) - Large library, clean UI
- MangaSee (mangasee123.com) - High quality scans
- MangaBuddy (mangabuddy.com) - Popular aggregator
- Bato.to (bato.to) - Community-driven
- Mangakakalot (mangakakalot.com) - Huge library
- Manganato (manganato.com) - Same network as Kakalot
- Mangago (mangago.me) - Large yaoi/shoujo collection
- MangaTaro (mangataro.org) - ComicK replacement, popular aggregator
- MangaFire (mangafire.to) - VRF bypass + image descrambling (Playwright)
"""

from .base import BaseScraper, Chapter, Manga
from .tcbscans import TCBScansScraper
from .weebcentral import WeebCentralScraper
from .asurascans import AsuraScansScraper
from .mangakatana import MangakatanataScraper
from .mangadex import MangaDexScraper
from .mangapill import MangapillScraper
from .mangareader import MangaReaderScraper
from .mangafire import MangaFireScraper
from .mangasee import MangaSeeScraper
from .mangabuddy import MangaBuddyScraper
from .batoto import BatoToScraper
from .mangakakalot import MangakakalotScraper
from .manganato import ManganatoScraper
from .mangago import MangagoScraper
from .mangataro import MangaTaroScraper

SCRAPERS = {
    # TCB Scans - Jump manga (no Cloudflare, simple requests)
    "tcbonepiecechapters.com": TCBScansScraper,
    "tcbscans.com": TCBScansScraper,
    "tcbscans.me": TCBScansScraper,
    
    # WeebCentral - Large library (hybrid: cloudscraper + Playwright)
    "weebcentral.com": WeebCentralScraper,
    
    # Asura Scans - Manhwa (Playwright/Firefox)
    "asuracomic.net": AsuraScansScraper,
    "asurascans.com": AsuraScansScraper,
    "asuratoon.com": AsuraScansScraper,
    
    # Mangakatana - General (Playwright/Firefox)
    "mangakatana.com": MangakatanataScraper,
    
    # MangaDex - Community (API)
    "mangadex.org": MangaDexScraper,
    "api.mangadex.org": MangaDexScraper,
    
    # Mangapill - Large library (no Cloudflare, simple requests)
    "mangapill.com": MangapillScraper,
    
    # MangaReader.to
    "mangareader.to": MangaReaderScraper,
    
    # MangaFire.to (Firefox + VRF bypass + descrambling)
    "mangafire.to": MangaFireScraper,
    
    # MangaSee123
    "mangasee123.com": MangaSeeScraper,
    
    # MangaBuddy
    "mangabuddy.com": MangaBuddyScraper,
    
    # Bato.to
    "bato.to": BatoToScraper,
    "batoto.to": BatoToScraper,
    
    # Mangakakalot
    "mangakakalot.com": MangakakalotScraper,
    "mangakakalot.to": MangakakalotScraper,
    
    # Manganato
    "manganato.com": ManganatoScraper,
    "chapmanganato.to": ManganatoScraper,
    "readmanganato.com": ManganatoScraper,
    
    # Mangago
    "mangago.me": MangagoScraper,
    "www.mangago.me": MangagoScraper,
    
    # MangaTaro (ComicK replacement)
    "mangataro.org": MangaTaroScraper,
}


def get_scraper(source: str) -> BaseScraper:
    """Get scraper instance for a source domain."""
    source = source.lower().replace("www.", "")
    
    for domain, scraper_class in SCRAPERS.items():
        if domain in source:
            return scraper_class()
    
    supported = list_supported_sources()
    raise ValueError(f"No scraper available for: {source}\nSupported: {', '.join(supported)}")


def list_supported_sources():
    """List all supported source domains."""
    return [
        "tcbonepiecechapters.com",
        "weebcentral.com",
        "asuracomic.net",
        "mangakatana.com",
        "mangadex.org",
        "mangapill.com",
        "mangareader.to",
        "mangafire.to",
        "mangasee123.com",
        "mangabuddy.com",
        "bato.to",
        "mangakakalot.com",
        "manganato.com",
        "mangago.me",
        "mangataro.org",
    ]
