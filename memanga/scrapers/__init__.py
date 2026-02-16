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
from .flamecomics import FlameComicsScraper
from .luminousscans import LuminousScansScraper
from .mangahere import MangaHereScraper
from .hentai20 import Hentai20Scraper
from .readcomiconline import ReadComicOnlineScraper
from .coffeemanga import CoffeeMangaScraper
from .mgeko import MGekoScraper
from .manhuafast import ManhuaFastScraper
from .mangaeffect import MangaReadScraper
from .manhuaplus import ManhuaPlusScraper
from .manhwa18 import Manhwa18Scraper
from .mangahub import MangaHubScraper
from .mangatown import MangaTownScraper
from .hiperdex import HiperDexScraper
from .mangaread import MangaReadOrgScraper
from .s2manga import S2MangaScraper
from .manhwatop import ManhwaTopScraper
from .manhuaus import ManhuaUsScraper
from .truemanga import TrueMangaScraper
from .mangadistrict import MangaDistrictScraper
from .manga18fx import Manga18fxScraper
from .nhentai import NHentaiScraper
from .hentaifox import HentaiFoxScraper
from .imhentai import IMHentaiScraper
from .ehentai import EHentaiScraper
from .readmanga_base import ReadMangaBaseScraper
from .readsnk import ReadSNKScraper
from .readberserk import ReadBerserkScraper
from .readhaikyuu import ReadHaikyuuScraper
from .readjujutsukaisen import ReadJujutsuKaisenScraper
from .readchainsawman import ReadChainsawManScraper
from .azmanga import AZMangaScraper
from .readonepiece import ReadOnePieceScraper
from .readnaruto import ReadNarutoScraper
from .readmha import ReadMHAScraper
from .readfairytail import ReadFairyTailScraper
from .readblackclover import ReadBlackCloverScraper
from .mangapanda import MangaPandaScraper
from .mangabolt import MangaBoltScraper
from .mangaforfree import MangaForFreeScraper
from .mangafoxfun import MangaFoxFunScraper
from .mangahubus import MangaHubUsScraper
from .onemanga import OneMangaScraper
from .mangafreak import MangaFreakScraper
from .comick import ComickScraper
from .fanfox import FanFoxScraper
from .toonily import ToonilyScraper
from .omegascans import OmegaScansScraper
from .hivetoons import HivetoonsScraper
from .mangayy import MangaYYScraper
from .manga4life import Manga4LifeScraper
from .isekaiscan import IsekaiScanScraper
from .zinmanga import ZinMangaScraper
from .mangaclash import MangaClashScraper
from .kunmanga import KunMangaScraper
from .manytoon import ManyToonScraper
from .pururin import PururinScraper
from .hentairead import HentaiReadScraper
from .manganato_gg import ManganatoGGScraper
from .mangahereonl import MangaHereOnlScraper
from .trigunmanga import TrigunMangaScraper
from .beastarsmanga import BeastarsMangaScraper
from .vagabondmanga import VagabondMangaScraper
from .monstermanga import MonsterMangaScraper
from .bleachread import BleachReadScraper
from .deathnotemanga import DeathNoteMangaScraper
from .tgmanga import TGMangaScraper
from .readichithewitch import ReadIchiTheWitchScraper
from .demonslayermanga import DemonSlayerMangaScraper
from .drstonemanga import DrStoneMangaScraper
from .sakamotomanga import SakamotoMangaScraper
from .elusivesamurai import ElusiveSamuraiScraper
from .readbluelockorg import ReadBlueLockOrgScraper
from .bocchitherockmanga import BocchiTheRockMangaScraper
from .sxfmanga import SXFMangaScraper
from .spyxfamilymanga import SpyXFamilyMangaScraper
from .mashlemanga import MashleMangaScraper
from .blueexorcistmanga import BlueExorcistMangaScraper
from .frierenmanga import FrierenMangaScraper
from .punpunmanga import PunpunMangaScraper
from .furierenmanga import FurierenMangaScraper
from .kokounohitomanga import KokouNoHitoMangaScraper
from .madeabyssmanga import MadeAbyssMangaScraper
from .ajimenoippo import AjimeNoIppoScraper
from .hajimenoippoonline import HajimeNoIppoOnlineScraper
from .hajimnoippo import HajimNoIppoScraper
from .hajimenoippoblogger import HajimeNoIppoBloggerScraper
from .bluelockreadonline import BlueLockReadOnlineScraper

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
    
    # FlameComics
    "flamecomics.xyz": FlameComicsScraper,
    
    # LuminousScans
    "luminousscans.com": LuminousScansScraper,
    
    # MangaHere
    "mangahere.cc": MangaHereScraper,
    
    # Hentai20 (NSFW)
    "hentai20.io": Hentai20Scraper,
    
    # ReadComicOnline (Comics)
    "readcomiconline.li": ReadComicOnlineScraper,
    
    # CoffeeManga
    "coffeemanga.io": CoffeeMangaScraper,
    
    # MGeko
    "mgeko.cc": MGekoScraper,
    
    # ManhuaFast
    "manhuafast.com": ManhuaFastScraper,
    
    # MangaRead/MangaEffect
    "mangaeffect.com": MangaReadScraper,
    
    # ManhuaPlus
    "manhuaplus.org": ManhuaPlusScraper,
    
    # Manhwa18
    "manhwa18.cc": Manhwa18Scraper,
    
    # MangaHub
    "mangahub.io": MangaHubScraper,
    
    # MangaTown
    "mangatown.com": MangaTownScraper,
    "www.mangatown.com": MangaTownScraper,
    
    # HiperDex
    "hiperdex.com": HiperDexScraper,
    
    # MangaRead.org
    "mangaread.org": MangaReadOrgScraper,
    "www.mangaread.org": MangaReadOrgScraper,
    
    # S2Manga
    "s2manga.com": S2MangaScraper,
    "s2manga.io": S2MangaScraper,
    
    # ManhwaTop
    "manhwatop.com": ManhwaTopScraper,
    
    # ManhuaUs
    "manhuaus.org": ManhuaUsScraper,
    
    # TrueManga / MangaMonk
    "truemanga.com": TrueMangaScraper,
    "mangamonk.com": TrueMangaScraper,
    
    # MangaDistrict
    "mangadistrict.com": MangaDistrictScraper,
    
    # Manga18fx (WordPress Madara - NSFW)
    "manga18fx.com": Manga18fxScraper,
    
    # NHentai (Doujin gallery)
    "nhentai.net": NHentaiScraper,
    
    # HentaiFox (Doujin gallery)
    "hentaifox.com": HentaiFoxScraper,
    
    # IMHentai (Doujin gallery)
    "imhentai.xxx": IMHentaiScraper,
    
    # E-Hentai (Doujin gallery)
    "e-hentai.org": EHentaiScraper,
    "exhentai.org": EHentaiScraper,
    
    # ReadSNK - Attack on Titan dedicated (WordPress + CDN)
    "readsnk.com": ReadSNKScraper,
    
    # ReadBerserk - Berserk dedicated (WordPress + CDN)
    "readberserk.com": ReadBerserkScraper,
    
    # ReadHaikyuu - Haikyuu!! dedicated (WordPress + CDN)
    "readhaikyuu.com": ReadHaikyuuScraper,
    
    # ReadJujutsuKaisen - JJK dedicated (WordPress + CDN)
    "readjujutsukaisen.com": ReadJujutsuKaisenScraper,
    
    # ReadChainsawMan - Chainsaw Man dedicated (WordPress + CDN)
    "readchainsawman.com": ReadChainsawManScraper,
    
    # AZManga - Manga/manhwa aggregator (WordPress Madara)
    "azmanga.com": AZMangaScraper,
    
    # ReadOnePiece - One Piece dedicated (WordPress + CDN)
    "readonepiece.com": ReadOnePieceScraper,
    "ww8.readonepiece.com": ReadOnePieceScraper,
    "ww12.readonepiece.com": ReadOnePieceScraper,
    
    # ReadNaruto - Naruto dedicated (WordPress + CDN)
    "readnaruto.com": ReadNarutoScraper,
    "ww8.readnaruto.com": ReadNarutoScraper,
    "ww10.readnaruto.com": ReadNarutoScraper,
    "ww11.readnaruto.com": ReadNarutoScraper,
    
    # ReadMHA - My Hero Academia dedicated (WordPress + CDN)
    "readmha.com": ReadMHAScraper,
    "ww8.readmha.com": ReadMHAScraper,
    "ww10.readmha.com": ReadMHAScraper,
    
    # ReadFairyTail - Fairy Tail dedicated (WordPress + CDN)
    "readfairytail.com": ReadFairyTailScraper,
    "ww7.readfairytail.com": ReadFairyTailScraper,
    
    # ReadBlackClover - Black Clover dedicated (WordPress + CDN)
    "readblackclover.com": ReadBlackCloverScraper,
    "ww7.readblackclover.com": ReadBlackCloverScraper,
    
    # MangaPanda - MangaHub network (cloudscraper)
    "mangapanda.onl": MangaPandaScraper,
    
    # MangaBolt - Jump manga aggregator
    "mangabolt.com": MangaBoltScraper,
    
    # MangaForFree - WordPress Madara
    "mangaforfree.net": MangaForFreeScraper,
    
    # MangaFox.fun - MangaHub network (cloudscraper)
    "mangafox.fun": MangaFoxFunScraper,
    
    # MangaHub.us - MangaHub network (cloudscraper)
    "mangahub.us": MangaHubUsScraper,
    
    # 1Manga.co - Large library (MangaHub CDN)
    "1manga.co": OneMangaScraper,
    
    # MangaFreak.ws - Large manga library
    "mangafreak.ws": MangaFreakScraper,
    "mangafreak.me": MangaFreakScraper,
    "ww2.mangafreak.me": MangaFreakScraper,
    
    # ComicK - Popular manga aggregator (Playwright + Cloudflare bypass)
    "comick.io": ComickScraper,
    "comick.dev": ComickScraper,
    
    # FanFox (MangaFox) - Large manga library (Playwright)
    "fanfox.net": FanFoxScraper,
    "mangafox.me": FanFoxScraper,
    
    # Toonily - Korean manhwa/webtoon (Playwright)
    "toonily.me": ToonilyScraper,
    
    # Omega Scans - Manhwa/webtoon (Playwright)
    "omegascans.org": OmegaScansScraper,
    # Hivetoons - Void Scans network (Playwright)
    "hivetoons.org": HivetoonsScraper,
    "hivetoon.com": HivetoonsScraper,  # Redirects to hivetoons.org
    # MangaYY - WordPress Madara (Playwright)
    "mangayy.org": MangaYYScraper,
    "likemanga.io": MangaYYScraper,  # Redirects to mangayy.org
    
    # Manga4Life / MangaLife - Large library (Playwright + JS)
    "manga4life.com": Manga4LifeScraper,
    "mangalife.us": Manga4LifeScraper,
    
    # IsekaiScan - Isekai manga/manhwa (Playwright + Madara)
    "isekaiscan.com": IsekaiScanScraper,
    
    # ZinManga - Manga aggregator (Playwright + Madara)
    "zinmanga.com": ZinMangaScraper,
    
    # MangaClash - Manga aggregator (Playwright + Madara + CF)
    "mangaclash.com": MangaClashScraper,
    
    # KunManga - Manga aggregator (Playwright + Madara + CF)
    "kunmanga.com": KunMangaScraper,
    
    # ManyToon - Adult manhwa (Playwright + JS chapters)
    "manytoon.com": ManyToonScraper,
    
    # Pururin - Doujin gallery (Playwright + JS)
    "pururin.to": PururinScraper,
    
    # HentaiRead - Hentai manga (Playwright)
    "hentairead.com": HentaiReadScraper,
    
    # Manganato.gg - New domain with Cloudflare (Playwright)
    "manganato.gg": ManganatoGGScraper,
    
    # MangaHere.onl - Images from mghcdn.com (Playwright)
    "mangahere.onl": MangaHereOnlScraper,
    
    # TrigunManga - Trigun dedicated (WordPress + Blogger CDN)
    "trigunmanga.com": TrigunMangaScraper,
    
    # BeastarsManga - Beastars dedicated (WordPress + cdn.readkakegurui.com)
    "beastarsmanga.com": BeastarsMangaScraper,
    
    # VagabondManga - Vagabond dedicated (WordPress + cdn.mangaclash.com)
    "vagabondmanga.org": VagabondMangaScraper,
    "www.vagabondmanga.org": VagabondMangaScraper,
    
    # MonsterManga - Monster (Naoki Urasawa) dedicated (WordPress + official.lowee.us)
    "monstermanga.org": MonsterMangaScraper,
    "www.monstermanga.org": MonsterMangaScraper,
    
    # BleachRead - Bleach dedicated (WordPress + Blogger CDN)
    "bleach-read.com": BleachReadScraper,
    "w38.bleach-read.com": BleachReadScraper,
    
    # DeathNoteManga - Death Note dedicated (WordPress + Blogger CDN)
    "death-note-manga.com": DeathNoteMangaScraper,
    "w13.death-note-manga.com": DeathNoteMangaScraper,
    
    # TGManga - Tokyo Ghoul dedicated (WordPress + wp-content)
    "tgmanga.com": TGMangaScraper,
    
    # ReadIchiTheWitch - Ichi the Witch dedicated (cdn.readichithewitch.com)
    "readichithewitch.com": ReadIchiTheWitchScraper,
    "ww1.readichithewitch.com": ReadIchiTheWitchScraper,
    
    # DemonSlayerManga - Demon Slayer / Kimetsu no Yaiba dedicated (cdn.demonslayermanga.com)
    "demonslayermanga.com": DemonSlayerMangaScraper,
    "ww9.demonslayermanga.com": DemonSlayerMangaScraper,
    
    # DrStoneManga - Dr. Stone dedicated (assets.drstonemanga.com)
    "drstonemanga.com": DrStoneMangaScraper,
    
    # SakamotoManga - Sakamoto Days dedicated (cdn3.mangaclash.com)
    "sakamotomanga.com": SakamotoMangaScraper,
    
    # ElusiveSamurai - The Elusive Samurai dedicated (pic.readkakegurui.com)
    "elusive-samurai.com": ElusiveSamuraiScraper,
    "w4.elusive-samurai.com": ElusiveSamuraiScraper,
    
    # ReadBlueLockOrg - Blue Lock dedicated (images.asuratoon.top)
    "readbluelock.org": ReadBlueLockOrgScraper,
    
    # BocchiTheRockManga - Bocchi the Rock! dedicated (cdn.black-clover.org)
    "bocchitherockmanga.com": BocchiTheRockMangaScraper,
    "w5.bocchitherockmanga.com": BocchiTheRockMangaScraper,
    
    # SXFManga - Spy x Family dedicated (WordPress Madara + img.spoilerhat.com proxy)
    "sxfmanga.net": SXFMangaScraper,
    "ww2.sxfmanga.net": SXFMangaScraper,
    "www.sxfmanga.net": SXFMangaScraper,
    
    # SpyXFamilyManga - Spy x Family dedicated (cdn3.mangaclash.com)
    "spyxfamilymanga.org": SpyXFamilyMangaScraper,
    
    # MashleManga - Mashle dedicated (WordPress Madara + img.spoilerhat.com proxy)
    "mashlemanga.net": MashleMangaScraper,
    "www.mashlemanga.net": MashleMangaScraper,
    
    # BlueExorcistManga - Blue Exorcist / Ao no Exorcist dedicated (cdn.readkakegurui.com)
    "blueexorcistmanga.com": BlueExorcistMangaScraper,
    
    # FrierenManga - Frieren: Beyond Journey's End dedicated (WordPress Comic Easel + img.spoilerhat.com proxy)
    "frieren-manga.com": FrierenMangaScraper,
    
    # PunpunManga - Goodnight Punpun dedicated (Nuxt SSR + assets.punpunmanga.com)
    "punpunmanga.com": PunpunMangaScraper,
    
    # FurierenManga - Frieren: Beyond Journey's End dedicated (Nuxt SSR + assets.furieren.com)
    "furieren.com": FurierenMangaScraper,
    
    # KokouNoHitoManga - The Climber dedicated (Nuxt SSR + assets.kokounohito.com)
    "kokounohito.com": KokouNoHitoMangaScraper,
    
    # MadeAbyssManga - Made in Abyss dedicated (Nuxt SSR + assets.madeabyss.com)
    "madeabyss.com": MadeAbyssMangaScraper,
    
    # AjimeNoIppo - Hajime no Ippo dedicated (WordPress + cdn.mangaclash.com)
    "ajimenoippo.com": AjimeNoIppoScraper,
    "www.ajimenoippo.com": AjimeNoIppoScraper,
    
    # HajimeNoIppoOnline - Hajime no Ippo dedicated (WordPress + laiond.com)
    "hajime-no-ippo-manga.online": HajimeNoIppoOnlineScraper,
    
    # HajimNoIppo - Hajime no Ippo dedicated (WordPress + planeptune.us)
    "hajimnoippo.com": HajimNoIppoScraper,
    
    # HajimeNoIppoBlogger - Hajime no Ippo dedicated (WordPress + Blogger CDN)
    "hajime-noippo.com": HajimeNoIppoBloggerScraper,
    "w22.hajime-noippo.com": HajimeNoIppoBloggerScraper,
    
    # BlueLockReadOnline - Blue Lock dedicated (WordPress + wp-content)
    "bluelockread.online": BlueLockReadOnlineScraper,
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
    # Return unique main domains from SCRAPERS
    seen = set()
    sources = []
    for domain in SCRAPERS.keys():
        # Get base domain without www
        base = domain.replace("www.", "")
        if base not in seen:
            seen.add(base)
            sources.append(base)
    return sorted(sources)
