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
- MangaPark (mangapark.io) - Vast collection (Playwright)
- Mangakakalot (mangakakalot.com) - Huge library
- Manganato (manganato.com) - Same network as Kakalot
- Mangago (mangago.me) - Large yaoi/shoujo collection
- MangaTaro (mangataro.org) - ComicK replacement, popular aggregator

Non-working (DRM protected):
- MangaFire (mangafire.to) - DRM with image scrambling + Cloudflare Turnstile
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
from .mangapark import MangaParkScraper
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
    
    # Asura Scans - Manhwa (Playwright)
    "asuracomic.net": AsuraScansScraper,
    "asurascans.com": AsuraScansScraper,
    "asuratoon.com": AsuraScansScraper,
    
    # Mangakatana - General (Playwright)
    "mangakatana.com": MangakatanataScraper,
    
    # MangaDex - Community (API)
    "mangadex.org": MangaDexScraper,
    "api.mangadex.org": MangaDexScraper,
    
    # Mangapill - Large library (no Cloudflare, simple requests)
    "mangapill.com": MangapillScraper,
    
    # NEW: MangaReader.to
    "mangareader.to": MangaReaderScraper,
    
    # NEW: MangaFire.to
    "mangafire.to": MangaFireScraper,
    
    # NEW: MangaSee123
    "mangasee123.com": MangaSeeScraper,
    
    # NEW: MangaBuddy
    "mangabuddy.com": MangaBuddyScraper,
    
    # NEW: Bato.to
    "bato.to": BatoToScraper,
    "batoto.to": BatoToScraper,
    
    # NEW: MangaPark (Playwright)
    "mangapark.io": MangaParkScraper,
    "mangapark.net": MangaParkScraper,
    
    # NEW: Mangakakalot
    "mangakakalot.com": MangakakalotScraper,
    "mangakakalot.to": MangakakalotScraper,
    
    # NEW: Manganato
    "manganato.com": ManganatoScraper,
    "chapmanganato.to": ManganatoScraper,
    "readmanganato.com": ManganatoScraper,
    
    # NEW: Mangago
    "mangago.me": MangagoScraper,
    "www.mangago.me": MangagoScraper,
    
    # NEW: MangaTaro (ComicK replacement)
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
        "mangasee123.com",
        "mangabuddy.com",
        "bato.to",
        "mangapark.io",
        "mangakakalot.com",
        "manganato.com",
        "mangago.me",
        "mangataro.org",  # ComicK replacement
        # "mangafire.to",  # DRM protected - doesn't work
    ]
