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
- Plus ~80 template-based scrapers via registry (Nuxt SSR, OG Image Meta, Madara, Laiond CDN, Mangosm)
"""

from .base import BaseScraper, Chapter, Manga
from .registry import get_template_scrapers

# ── Core aggregator scrapers ──
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
from .manhuaus import ManhuaUsScraper
from .truemanga import TrueMangaScraper
from .nhentai import NHentaiScraper
from .hentaifox import HentaiFoxScraper
from .imhentai import IMHentaiScraper
from .ehentai import EHentaiScraper
from .mangapanda import MangaPandaScraper
from .mangabolt import MangaBoltScraper
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
from .zazamanga import ZazaMangaScraper
from .mangaball import MangaBallScraper
from .manytoon import ManyToonScraper
from .pururin import PururinScraper
from .hentairead import HentaiReadScraper
from .manganato_gg import ManganatoGGScraper
from .mangahereonl import MangaHereOnlScraper

# ── Playwright-based Madara scrapers (not templatable) ──
from .isekaiscan import IsekaiScanScraper
from .zinmanga import ZinMangaScraper
from .mangaclash import MangaClashScraper
from .kunmanga import KunMangaScraper

# ── ReadManga base + subclasses ──
from .readmanga_base import ReadMangaBaseScraper
from .readsnk import ReadSNKScraper
from .readberserk import ReadBerserkScraper
from .readhaikyuu import ReadHaikyuuScraper
from .readjujutsukaisen import ReadJujutsuKaisenScraper
from .readchainsawman import ReadChainsawManScraper
from .readonepiece import ReadOnePieceScraper
from .readnaruto import ReadNarutoScraper
from .readmha import ReadMHAScraper
from .readfairytail import ReadFairyTailScraper
from .readblackclover import ReadBlackCloverScraper

# ── Unique/complex scrapers kept as individual files ──
from .beastarsmanga import BeastarsMangaScraper
from .vagabondmanga import VagabondMangaScraper
from .monstermanga import MonsterMangaScraper
from .deathnotemanga import DeathNoteMangaScraper
from .tgmanga import TGMangaScraper
from .readichithewitch import ReadIchiTheWitchScraper
from .demonslayermanga import DemonSlayerMangaScraper
from .drstonemanga import DrStoneMangaScraper
from .sakamotomanga import SakamotoMangaScraper
from .elusivesamurai import ElusiveSamuraiScraper
from .readbluelockorg import ReadBlueLockOrgScraper
from .bocchitherockmanga import BocchiTheRockMangaScraper
from .spyxfamilymanga import SpyXFamilyMangaScraper
from .blueexorcistmanga import BlueExorcistMangaScraper
from .ajimenoippo import AjimeNoIppoScraper
from .hajimenoippoonline import HajimeNoIppoOnlineScraper
from .hajimnoippo import HajimNoIppoScraper
from .hajimenoippoblogger import HajimeNoIppoBloggerScraper
from .bluelockreadonline import BlueLockReadOnlineScraper
from .readslamdunkonline import ReadSlamDunkOnlineScraper
from .readtokyorevengers import ReadTokyoRevengersScraper
from .dragonballsuperonline import DragonBallSuperOnlineScraper
from .dragonballsuperorg import DragonBallSuperOrgScraper
from .fairytailmangafree import FairyTailMangaFreeScraper
from .jojolionmanga import JoJolionMangaScraper
from .homunculusmanga import HomunculusMangaScraper
from .sousnofrierenga import SousouNoFrierenScraper
from .demonslayeronline import DemonSlayerOnlineScraper
from .mangoasis import MangOasisScraper
from .readkingdomfree import ReadKingdomFreeScraper
from .sakamotodaysonline import SakamotoDaysOnlineScraper
from .onepiecemanga1 import OnePieceManga1Scraper
from .kaijuno8manga import KaijuNo8MangaScraper
from .bluelockmangaorg import BlueLockMangaNetScraper
from .tokyoghoulclub import TokyoGhoulClubScraper
from .fireforcemangaorg import FireForceMangaOrgScraper
from .readkenganashura import ReadKenganAshuraScraper
from .bluelockreadcom import BlueLockReadComScraper
from .onepieceread import OnePieceReadScraper
from .mangadna import MangaDNAScraper
from .readjjkmanga import ReadJJKMangaScraper
from .readoshinoko import ReadOshiNoKoScraper
from .readberserkmanga import ReadBerserkMangaScraper
from .monstermangaonline import MonsterMangaOnlineScraper
from .kenganashuramanga import KenganAshuraMangaScraper
from .oyasumipunpunmanga import OyasumiPunpunMangaScraper
from .readsnkmanga import ReadSNKMangaScraper
from .onepunchmanmangaa import OnePunchManMangaaScraper
from .readopm import ReadOPMScraper
from .readjjkcom import ReadJJKComScraper
from .onepunchmanread import OnePunchManReadScraper
from .berserkmangorg import BerserkMangOrgScraper
from .bluelockreadww2 import BlueLockReadWW2Scraper
from .mashlemangaonline import MashleMangaOnlineScraper
from .readonepunchonline import ReadOnePunchOnlineScraper
from .bakirahen import BakiRahenScraper
from .blamemanga import BlameMangaScraper
from .jjkmanga import JJKMangaScraper
from .kagane import KaganeScraper

# ── Scrapers kept as individual files (unique domain mappings) ──

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

    # ManhuaUs
    "manhuaus.org": ManhuaUsScraper,

    # TrueManga / MangaMonk
    "truemanga.com": TrueMangaScraper,
    "mangamonk.com": TrueMangaScraper,

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
    "hivetoon.com": HivetoonsScraper,

    # MangaYY - WordPress Madara (Playwright)
    "mangayy.org": MangaYYScraper,
    "likemanga.io": MangaYYScraper,

    # Manga4Life / MangaLife - Large library (Playwright + JS)
    "manga4life.com": Manga4LifeScraper,
    "mangalife.us": Manga4LifeScraper,

    # IsekaiScan - Isekai manga/manhwa (Playwright + Madara)
    "isekaiscan.com": IsekaiScanScraper,

    # ZinManga - Manga aggregator (Playwright + Madara)
    "zinmanga.com": ZinMangaScraper,

    # ZazaManga - Manga aggregator (Playwright, redirected series sites)
    "zazamanga.com": ZazaMangaScraper,
    "www.zazamanga.com": ZazaMangaScraper,
    "deathnotemanga.com": ZazaMangaScraper,
    "death-note-online.com": ZazaMangaScraper,
    "fairytail100yearsquest.com": ZazaMangaScraper,
    "gintama.site": ZazaMangaScraper,
    "initialdmanga.com": ZazaMangaScraper,
    "inuyasha.net": ZazaMangaScraper,
    "onepunchmanmanga.org": ZazaMangaScraper,
    "readhellsing.com": ZazaMangaScraper,
    "readoverlord.com": ZazaMangaScraper,

    # MangaBall - Multi-language aggregator (Playwright, limited search)
    "mangaball.net": MangaBallScraper,

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

    # BeastarsManga - Beastars dedicated (WordPress + cdn.readkakegurui.com)
    "beastarsmanga.com": BeastarsMangaScraper,

    # VagabondManga - Vagabond dedicated (WordPress + cdn.mangaclash.com)
    "vagabondmanga.org": VagabondMangaScraper,
    "www.vagabondmanga.org": VagabondMangaScraper,

    # MonsterManga - Monster (Naoki Urasawa) dedicated (WordPress + official.lowee.us)
    "monstermanga.org": MonsterMangaScraper,
    "www.monstermanga.org": MonsterMangaScraper,

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

    # SpyXFamilyManga - Spy x Family dedicated (cdn3.mangaclash.com)
    "spyxfamilymanga.org": SpyXFamilyMangaScraper,

    # BlueExorcistManga - Blue Exorcist / Ao no Exorcist dedicated (cdn.readkakegurui.com)
    "blueexorcistmanga.com": BlueExorcistMangaScraper,

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

    # ReadSlamDunkOnline - Slam Dunk dedicated (WordPress + cdn.mangaclash.com)
    "read-slamdunk.online": ReadSlamDunkOnlineScraper,

    # ReadTokyoRevengers - Tokyo Revengers dedicated (WordPress + wp-content/mangaread.org)
    "read-tokyorevengers.com": ReadTokyoRevengersScraper,
    "w20.read-tokyorevengers.com": ReadTokyoRevengersScraper,
    "w23.read-tokyorevengers.com": ReadTokyoRevengersScraper,

    # DragonBallSuperOnline - Dragon Ball Super dedicated (WordPress + wp-content/uploads)
    "thedragonballsuper.online": DragonBallSuperOnlineScraper,

    # DragonBallSuperOrg - Dragon Ball Super dedicated (WordPress + mangaread.org CDN)
    "dragonballsuper.org": DragonBallSuperOrgScraper,
    "www.dragonballsuper.org": DragonBallSuperOrgScraper,

    # FairyTailMangaFree - Fairy Tail 100 Years Quest dedicated (WordPress + cdn.mangaclash.com)
    "fairytailmangafree.com": FairyTailMangaFreeScraper,
    "www.fairytailmangafree.com": FairyTailMangaFreeScraper,

    # JoJolionManga - JoJo Part 8: JoJolion dedicated (WordPress + Blogger CDN)
    "jojolionmanga.com": JoJolionMangaScraper,

    # HomunculusManga - Homunculus dedicated (WordPress + mangaread.org CDN)
    "homunculusmanga.com": HomunculusMangaScraper,
    "www.homunculusmanga.com": HomunculusMangaScraper,

    # SousouNoFrieren - Frieren dedicated (WordPress + cdn.mangaclash.com)
    "sousou-no-frieren.com": SousouNoFrierenScraper,

    # DemonSlayerOnline - Demon Slayer dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "demon-slayer.online": DemonSlayerOnlineScraper,
    "w4.demon-slayer.online": DemonSlayerOnlineScraper,

    # MangOasis - Multilingual manga aggregator (WordPress MangaVerse + cdn.mangoasis.com)
    "mangoasis.com": MangOasisScraper,
    "www.mangoasis.com": MangOasisScraper,

    # ReadKingdomFree - Kingdom dedicated (WordPress + planeptune.us CDN)
    "readkingdomfree.com": ReadKingdomFreeScraper,
    "www.readkingdomfree.com": ReadKingdomFreeScraper,

    # SakamotoDaysOnline - Sakamoto Days dedicated (PHP + attachment CDN)
    "sakamoto-days.online": SakamotoDaysOnlineScraper,

    # OnePieceManga1 - One Piece dedicated (WordPress + Contabo storage CDN)
    "1piecemanga.com": OnePieceManga1Scraper,
    "w064.1piecemanga.com": OnePieceManga1Scraper,

    # KaijuNo8Manga - Kaiju No. 8 dedicated (WordPress + wp-content CDN)
    "kaijuno8-manga.com": KaijuNo8MangaScraper,

    # BlueLockMangaNet - Blue Lock dedicated (WordPress + Blogger CDN)
    "bluelockmanga.net": BlueLockMangaNetScraper,

    # TokyoGhoulClub - Tokyo Ghoul dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "tokyoghoul.club": TokyoGhoulClubScraper,

    # FireForceMangaOrg - Fire Force dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "fireforcemanga.org": FireForceMangaOrgScraper,
    "w1.fireforcemanga.org": FireForceMangaOrgScraper,

    # ReadKenganAshura - Kengan Ashura dedicated (WordPress Comic Easel + Blogger CDN)
    "read-kengan-ashura.com": ReadKenganAshuraScraper,

    # BlueLockReadCom - Blue Lock dedicated (custom site + attachment CDN)
    "bluelock-read.com": BlueLockReadComScraper,

    # OnePieceRead - One Piece dedicated (Next.js SSR + cdn.onepiecechapters.com)
    "onepieceread.com": OnePieceReadScraper,

    # MangaDNA - General manga/manhwa aggregator (img.mangadna.com CDN)
    "mangadna.com": MangaDNAScraper,

    # ReadJJKManga - JJK + Modulo dedicated (WordPress + wp-content CDN)
    "readjujutsukaisenmanga.com": ReadJJKMangaScraper,

    # ReadOshiNoKo - Oshi no Ko dedicated (WordPress + mangaread.org CDN)
    "readoshinoko.com": ReadOshiNoKoScraper,
    "w13.readoshinoko.com": ReadOshiNoKoScraper,

    # ReadBerserkManga - Berserk dedicated (WordPress + hot.planeptune.us CDN)
    "read-berserk-manga.com": ReadBerserkMangaScraper,

    # MonsterMangaOnline - Aggregator (WordPress MangaVerse + cdn.monster-manga.online)
    "monster-manga.online": MonsterMangaOnlineScraper,
    "www.monster-manga.online": MonsterMangaOnlineScraper,

    # KenganAshuraManga - Kengan Ashura/Omega dedicated (WordPress + wp-content CDN)
    "kenganashura.com": KenganAshuraMangaScraper,

    # OyasumiPunpunManga - Goodnight Punpun dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "oyasumipunpun.com": OyasumiPunpunMangaScraper,

    # ReadSNKManga - Attack on Titan dedicated (WordPress + Blogger CDN)
    "readsnkmanga.com": ReadSNKMangaScraper,

    # OnePunchManMangaa - One Punch Man dedicated (WordPress + wp-content/uploads CDN)
    "onepunchmanmangaa.com": OnePunchManMangaaScraper,

    # ReadOPM - Manga aggregator with One Punch Man focus (cdn.readopm.com CDN)
    "readopm.com": ReadOPMScraper,
    "ww6.readopm.com": ReadOPMScraper,

    # ReadJJK.com - Jujutsu Kaisen dedicated (WordPress Kadence + img.read-jjk.com CDN)
    "read-jjk.com": ReadJJKComScraper,

    # OnePunchManRead - One Punch Man dedicated (WordPress Elementor + cdn.mangadistrict.com CDN)
    "onepunchmanread.com": OnePunchManReadScraper,

    # BerserkMangOrg - Berserk dedicated (WordPress + mangaread.org CDN)
    "berserkmang.org": BerserkMangOrgScraper,
    "www.berserkmang.org": BerserkMangOrgScraper,

    # BlueLockReadWW2 - Blue Lock dedicated (custom theme + cdn.bluelockread.com CDN)
    "bluelockread.com": BlueLockReadWW2Scraper,
    "ww2.bluelockread.com": BlueLockReadWW2Scraper,

    # MashleMangaOnline - Mashle dedicated (WordPress + wp-content/uploads CDN)
    "mashle-manga.online": MashleMangaOnlineScraper,

    # ReadOnePunchOnline - One Punch Man (WordPress + cache.imagemanga.online CDN)
    "one-punch.online": ReadOnePunchOnlineScraper,
    "read.one-punch.online": ReadOnePunchOnlineScraper,

    # BakiRahen - Baki Rahen dedicated (WordPress Ifenzi v2 + cdn.readkakegurui.com CDN)
    "bakirahen.com": BakiRahenScraper,

    # BlameManga - BLAME! dedicated (WordPress Comic Easel + Blogger CDN)
    "blame-manga.com": BlameMangaScraper,
    "w9.blame-manga.com": BlameMangaScraper,

    # JJKManga - Jujutsu Kaisen dedicated (cloudscraper + pic.readkakegurui.com CDN)
    "jjkmanga.net": JJKMangaScraper,

    # Kagane - Multi-manga REST API + Playwright for DRM-protected images
    "kagane.org": KaganeScraper,
    "www.kagane.org": KaganeScraper,
}

# Merge template-based scrapers into SCRAPERS dict
# Template scrapers override any duplicate domains (fixes dead code duplicates)
SCRAPERS.update(get_template_scrapers())


def get_scraper(source: str) -> BaseScraper:
    """Get scraper instance for a source domain."""
    source = source.lower()
    if source.startswith("www."):
        source = source[4:]

    # Exact match first
    if source in SCRAPERS:
        return SCRAPERS[source]()

    # Match by domain suffix (e.g., "ww3.mangafreak.me" matches "mangafreak.me")
    for domain, scraper_class in SCRAPERS.items():
        if source == domain or source.endswith("." + domain):
            return scraper_class()

    supported = list_supported_sources()
    raise ValueError(f"No scraper available for: {source}\nSupported: {', '.join(supported)}")


def list_supported_sources():
    """List all supported source domains."""
    seen = set()
    sources = []
    for domain in SCRAPERS.keys():
        base = domain[4:] if domain.startswith("www.") else domain
        if base not in seen:
            seen.add(base)
            sources.append(base)
    return sorted(sources)
