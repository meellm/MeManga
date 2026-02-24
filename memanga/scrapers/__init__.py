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
from .zazamanga import ZazaMangaScraper
from .mangaball import MangaBallScraper
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
from .akiramanga import AkiraMangaScraper
from .tomiemanga import TomieMangaScraper
from .kaijimanga import KaijiMangaScraper
from .berserkmanga import BerserkMangaScraper
from .readblacklagoon import ReadBlackLagoonScraper
from .hxhmanga import HxHMangaScraper
from .dddmanga import DDDMangaScraper
from .chainsawdevil import ChainsawDevilScraper
from .jjkaisen import JJKaisenScraper
from .oshinokoyo import OshiNoKoYoScraper
from .unopiece import UnoPieceScraper
from .onepunchmanofficial import OnePunchManOfficialScraper
from .blackclova import BlackClovaScraper
from .kagurabachiread import KagurabachiReadScraper
from .centuriya import CenturiyaScraper
from .grandbluemanga import GrandBlueMangaScraper
from .gachiakutayo import GachiakutaYoScraper
from .galaxxias import GalaxxiasScraper
from .ichithewitchread import IchiTheWitchReadScraper
from .jujutsumodulo import JujutsuModuloScraper
from .readslamdunkonline import ReadSlamDunkOnlineScraper
from .readtokyorevengers import ReadTokyoRevengersScraper
from .dragonballsuperonline import DragonBallSuperOnlineScraper
from .dragonballsuperorg import DragonBallSuperOrgScraper
from .fairytailmangafree import FairyTailMangaFreeScraper
from .aoashimanga import AoAshiMangaScraper
from .recordofragnarokmanga import RecordOfRagnarokMangaScraper
from .blueboxmangaonline import BlueBoxMangaOnlineScraper
from .bleachmangaorg import BleachMangaOrgScraper
from .readundeadunluck import ReadUndeadUnluckScraper
from .steelballrun import SteelBallRunScraper
from .jojolandsmanga import JoJoLandsMangaScraper
from .jojolionmanga import JoJolionMangaScraper
from .gantzmangafree import GantzMangaFreeScraper
from .homunculusmanga import HomunculusMangaScraper
from .dandadanmanganet import DandadanMangaNetScraper
from .sousnofrierenga import SousouNoFrierenScraper
from .stoneoceanmanga import StoneOceanMangaScraper
from .heavenlydelusion import HeavenlyDelusionScraper
from .bananafishmanga import BananaFishMangaScraper
from .demonslayeronline import DemonSlayerOnlineScraper
from .nanamangaonline import NanaMangaOnlineScraper
from .mangoasis import MangOasisScraper
from .readkingdomfree import ReadKingdomFreeScraper
from .sakamotodaysonline import SakamotoDaysOnlineScraper
from .dorohedroonline import DorohedoroOnlineScraper
from .onepiecemanga1 import OnePieceManga1Scraper
from .vinlandsagamanga import VinlandSagaMangaScraper
from .kaijuno8manga import KaijuNo8MangaScraper
from .bluelockmangaorg import BlueLockMangaNetScraper
from .tokyoghoulclub import TokyoGhoulClubScraper
from .fireforcemangaorg import FireForceMangaOrgScraper
from .readkenganashura import ReadKenganAshuraScraper
from .overlordmangaonline import OverlordMangaOnlineScraper
from .rezeromangaonline import ReZeroMangaOnlineScraper
from .goblinslayermangaonline import GoblinSlayerMangaOnlineScraper
from .mushokutenseimangaonline import MushokuTenseiMangaOnlineScraper
from .bluelockreadcom import BlueLockReadComScraper
from .onepieceread import OnePieceReadScraper
from .mangadna import MangaDNAScraper
from .readjjkmanga import ReadJJKMangaScraper
from .jjkmodulo import JJKModuloScraper
from .readjjkfree import ReadJJKFreeScraper
from .readclaymore import ReadClaymoreScraper
from .readoshinoko import ReadOshiNoKoScraper
from .readberserkmanga import ReadBerserkMangaScraper
from .blamamanga import BlameMangaScraper
from .monstermangaonline import MonsterMangaOnlineScraper
from .kenganashuramanga import KenganAshuraMangaScraper
from .skipbeatmangaonline import SkipBeatMangaOnlineScraper
from .oyasumipunpunmanga import OyasumiPunpunMangaScraper
from .readsnkmanga import ReadSNKMangaScraper
from .onepunchmanmangaa import OnePunchManMangaaScraper
from .readopm import ReadOPMScraper
from .readjjkcom import ReadJJKComScraper
from .detectiveconanmangaonline import DetectiveConanMangaOnlineScraper
from .onepunchmanread import OnePunchManReadScraper
from .caseclosedonline import CaseClosedOnlineScraper
from .hyoukamanga import HyoukaMangaScraper
from .witchwatch import WitchWatchScraper
from .witchhatatelier import WitchHatAtelierScraper
from .beckmanga import BeckMangaScraper
from .kagurabachimanganew import KagurabachiMangaNewScraper
from .worldtrigger import WorldTriggerOnlineScraper
from .callofthenight import CallOfTheNightScraper
from .realmanga import RealMangaScraper
from .detectiveconan import DetectiveConanScraper
from .dorohedoro import DorohedoroScraper
from .tomie import TomieScraper
from .gutsberserk import GutsBerserkScraper
from .berserkmangorg import BerserkMangOrgScraper
from .onepiecemangaonline import OnePieceMangaOnlineScraper
from .kimetsuyaibaonline import KimetsuYaibaOnlineScraper
from .bluelockreadww2 import BlueLockReadWW2Scraper
from .dgraymanonline import DGraymanOnlineScraper
from .skipbeatonline import SkipBeatOnlineScraper
from .mashlemangaonline import MashleMangaOnlineScraper
from .readonepunchonline import ReadOnePunchOnlineScraper
from .blueexorcistonline import BlueExorcistOnlineScraper
from .bakirahen import BakiRahenScraper
from .bakidou import BakidouScraper
from .fullmetalalchemistonline import FullmetalAlchemistOnlineScraper
from .parasytemanga import ParasyteMangaScraper
from .deathnotemangafree import DeathNoteMangaFreeScraper

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
    
    # AkiraManga - Akira dedicated (WordPress Comic Easel + Blogger CDN)
    "akiramanga.com": AkiraMangaScraper,
    
    # TomieManga - Tomie (Junji Ito) dedicated (WordPress Comic Easel + img.mangarchive.com)
    "tomie-manga.com": TomieMangaScraper,
    "w12.tomie-manga.com": TomieMangaScraper,
    
    # KaijiManga - Kaiji dedicated (WordPress Comic Easel + Blogger CDN)
    "kaijimanga.com": KaijiMangaScraper,
    "w9.kaijimanga.com": KaijiMangaScraper,
    
    # BerserkManga - Berserk dedicated (WordPress Comic Easel + cdn3.mangaclash.com)
    "berserk-manga.com": BerserkMangaScraper,
    "w3.berserk-manga.com": BerserkMangaScraper,
    "w4.berserk-manga.com": BerserkMangaScraper,
    
    # ReadBlackLagoon - Black Lagoon dedicated (WordPress Mangosm + img.mangarchive.com)
    "readblacklagoon.com": ReadBlackLagoonScraper,
    
    # HxHManga - Hunter x Hunter dedicated (WordPress Mangosm + mangafreak.me CDN)
    "hxhmanga.com": HxHMangaScraper,
    
    # DDDManga - Dandadan dedicated (Nuxt SSR + assets.dddmanga.com CDN)
    "dddmanga.com": DDDMangaScraper,
    
    # ChainsawDevil - Chainsaw Man dedicated (Nuxt SSR + assets.chainsawdevil.com CDN)
    "chainsawdevil.com": ChainsawDevilScraper,
    
    # JJKaisen - Jujutsu Kaisen dedicated (Nuxt SSR + assets.jjkaisen.com CDN)
    "jjkaisen.com": JJKaisenScraper,
    
    # OshiNoKoYo - Oshi no Ko dedicated (Nuxt SSR + assets.oshinokoyo.com CDN)
    "oshinokoyo.com": OshiNoKoYoScraper,
    
    # UnoPiece - One Piece dedicated (Nuxt SSR + assets.unopiece.com CDN)
    "unopiece.com": UnoPieceScraper,
    
    # OnePunchManOfficial - One Punch Man dedicated (Nuxt SSR + assets.onepunchmanofficial.com CDN)
    "onepunchmanofficial.com": OnePunchManOfficialScraper,
    
    # BlackClova - Black Clover dedicated (Nuxt SSR + assets.blackclova.com CDN)
    "blackclova.com": BlackClovaScraper,
    
    # KagurabachiRead - Kagurabachi dedicated (Nuxt SSR + assets.kagurabachiread.com CDN)
    "kagurabachiread.com": KagurabachiReadScraper,
    
    # Centuriya - Centuria dedicated (Nuxt SSR + assets.centuriya.com CDN)
    "centuriya.com": CenturiyaScraper,
    
    # GrandBlueManga - Grand Blue Dreaming dedicated (Nuxt SSR + assets.grandbluemanga.com CDN)
    "grandbluemanga.com": GrandBlueMangaScraper,
    
    # GachiakutaYo - Gachiakuta dedicated (Nuxt SSR + assets.gachiakutayo.com CDN)
    "gachiakutayo.com": GachiakutaYoScraper,
    
    # Galaxxias - Galaxias dedicated (Nuxt SSR + assets.galaxxias.com CDN)
    "galaxxias.com": GalaxxiasScraper,
    
    # IchiTheWitchRead - Ichi the Witch dedicated (Nuxt SSR + assets.ichithewitchread.com CDN)
    "ichithewitchread.com": IchiTheWitchReadScraper,
    
    # JujutsuModulo - Jujutsu Kaisen Modulo dedicated (Nuxt SSR + assets.jujutsumodulo.com CDN)
    "jujutsumodulo.com": JujutsuModuloScraper,
    
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
    
    # AoAshiManga - Ao Ashi dedicated (WordPress + laiond.com CDN)
    "ao-ashi-manga.com": AoAshiMangaScraper,
    
    # RecordOfRagnarokManga - Record of Ragnarok dedicated (WordPress + Blogger CDN)
    "record-of-ragnarok-manga.com": RecordOfRagnarokMangaScraper,
    "w1.record-of-ragnarok-manga.com": RecordOfRagnarokMangaScraper,
    
    # BlueBoxMangaOnline - Blue Box / Ao no Hako dedicated (WordPress + Blogger CDN)
    "blue-box-manga.online": BlueBoxMangaOnlineScraper,
    
    # BleachMangaOrg - Bleach dedicated (WordPress Mangosm + cdn.mangaclash.com)
    "bleachmanga.org": BleachMangaOrgScraper,
    "www.bleachmanga.org": BleachMangaOrgScraper,
    
    # ReadUndeadUnluck - Undead Unluck dedicated (WordPress + Blogger CDN)
    "readundeadunluck.com": ReadUndeadUnluckScraper,
    
    # SteelBallRun - JoJo Part 7: Steel Ball Run dedicated (WordPress + Blogger CDN)
    "steel-ball-run.com": SteelBallRunScraper,
    
    # JoJoLandsManga - JoJo Part 9: The JOJOLands dedicated (WordPress + Blogger CDN)
    "jojolandsmanga.com": JoJoLandsMangaScraper,
    "w9.jojolandsmanga.com": JoJoLandsMangaScraper,
    
    # JoJolionManga - JoJo Part 8: JoJolion dedicated (WordPress + Blogger CDN)
    "jojolionmanga.com": JoJolionMangaScraper,
    
    # GantzMangaFree - Gantz dedicated (WordPress + Blogger CDN, cloudscraper)
    "gantzmangafree.com": GantzMangaFreeScraper,
    "www.gantzmangafree.com": GantzMangaFreeScraper,
    
    # HomunculusManga - Homunculus dedicated (WordPress + mangaread.org CDN)
    "homunculusmanga.com": HomunculusMangaScraper,
    "www.homunculusmanga.com": HomunculusMangaScraper,
    
    # DandadanMangaNet - Dandadan dedicated (WordPress Madara + img.spoilerhat.com)
    "dandadanmanga.net": DandadanMangaNetScraper,
    "ww2.dandadanmanga.net": DandadanMangaNetScraper,
    "w2.dandadanmanga.net": DandadanMangaNetScraper,
    
    # SousouNoFrieren - Frieren dedicated (WordPress + cdn.mangaclash.com)
    "sousou-no-frieren.com": SousouNoFrierenScraper,
    
    # StoneOceanManga - JoJo Part 6 dedicated (WordPress + Blogger CDN)
    "stone-ocean-manga.com": StoneOceanMangaScraper,
    
    # HeavenlyDelusion - Tengoku Daimakyou dedicated (WordPress + Blogger CDN)
    "heavenly-delusion.com": HeavenlyDelusionScraper,
    
    # BananaFishManga - Banana Fish dedicated (WordPress + official.lowee.us CDN)
    "bananafishmanga.com": BananaFishMangaScraper,
    "www.bananafishmanga.com": BananaFishMangaScraper,
    
    # DemonSlayerOnline - Demon Slayer / Kimetsu no Yaiba dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "demon-slayer.online": DemonSlayerOnlineScraper,
    "w4.demon-slayer.online": DemonSlayerOnlineScraper,
    
    # NanaMangaOnline - Nana by Ai Yazawa dedicated (WordPress Comic Easel + Blogger CDN)
    "nanamanga.online": NanaMangaOnlineScraper,
    "w2.nanamanga.online": NanaMangaOnlineScraper,
    
    # MangOasis - Multilingual manga aggregator (WordPress MangaVerse + cdn.mangoasis.com)
    "mangoasis.com": MangOasisScraper,
    "www.mangoasis.com": MangOasisScraper,
    
    # ReadKingdomFree - Kingdom dedicated (WordPress + planeptune.us CDN)
    "readkingdomfree.com": ReadKingdomFreeScraper,
    "www.readkingdomfree.com": ReadKingdomFreeScraper,
    
    # SakamotoDaysOnline - Sakamoto Days dedicated (PHP + attachment CDN)
    "sakamoto-days.online": SakamotoDaysOnlineScraper,
    
    # DorohedoroOnline - Dorohedoro dedicated (WordPress + Blogger CDN)
    "dorohedoro.online": DorohedoroOnlineScraper,
    
    # OnePieceManga1 - One Piece dedicated (WordPress + Contabo storage CDN)
    "1piecemanga.com": OnePieceManga1Scraper,
    "w064.1piecemanga.com": OnePieceManga1Scraper,
    
    # VinlandSagaManga - Vinland Saga dedicated (WordPress Madara + img.spoilerhat.com proxy)
    "vinlandsagamanga.net": VinlandSagaMangaScraper,
    "ww3.vinlandsagamanga.net": VinlandSagaMangaScraper,
    "w3.vinlandsagamanga.net": VinlandSagaMangaScraper,
    
    # KaijuNo8Manga - Kaiju No. 8 dedicated (WordPress + wp-content CDN)
    "kaijuno8-manga.com": KaijuNo8MangaScraper,
    
    # BlueLockMangaNet - Blue Lock dedicated (WordPress + Blogger CDN)
    "bluelockmanga.net": BlueLockMangaNetScraper,
    
    # TokyoGhoulClub - Tokyo Ghoul dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "tokyoghoul.club": TokyoGhoulClubScraper,
    
    # FireForceMangaOrg - Fire Force / Enen no Shouboutai dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "fireforcemanga.org": FireForceMangaOrgScraper,
    "w1.fireforcemanga.org": FireForceMangaOrgScraper,
    
    # ReadKenganAshura - Kengan Ashura dedicated (WordPress Comic Easel + Blogger CDN)
    "read-kengan-ashura.com": ReadKenganAshuraScraper,
    
    # OverlordMangaOnline - Overlord dedicated (WordPress Zazm + laiond.com CDN)
    "overlord-manga.online": OverlordMangaOnlineScraper,
    
    # ReZeroMangaOnline - Re:ZERO dedicated (WordPress Zazm + laiond.com CDN)
    "rezero-manga.online": ReZeroMangaOnlineScraper,
    
    # GoblinSlayerMangaOnline - Goblin Slayer dedicated (WordPress Zazm + laiond.com CDN)
    "goblin-slayer-manga.online": GoblinSlayerMangaOnlineScraper,
    
    # MushokuTenseiMangaOnline - Mushoku Tensei dedicated (WordPress Zazm + laiond.com CDN)
    "mushoku-tensei-manga.online": MushokuTenseiMangaOnlineScraper,
    
    # BlueLockReadCom - Blue Lock dedicated (custom site + attachment CDN)
    "bluelock-read.com": BlueLockReadComScraper,
    
    # OnePieceRead - One Piece dedicated (Next.js SSR + cdn.onepiecechapters.com)
    "onepieceread.com": OnePieceReadScraper,
    
    # MangaDNA - General manga/manhwa aggregator (img.mangadna.com CDN)
    "mangadna.com": MangaDNAScraper,
    
    # ReadJJKManga - JJK + Modulo dedicated (WordPress + wp-content CDN)
    "readjujutsukaisenmanga.com": ReadJJKMangaScraper,
    
    # JJKModulo - JJK Modulo dedicated (WordPress Mangosm + planeptune.us CDN)
    "jujutsukaisenmodulo.org": JJKModuloScraper,
    
    # ReadJJKFree - JJK main series dedicated (WordPress Mangosm + planeptune.us CDN)
    "readjujutsukaisenfree.com": ReadJJKFreeScraper,
    
    # ReadClaymore - Claymore dedicated (WordPress + Blogger CDN)
    "readclaymore.com": ReadClaymoreScraper,
    
    # ReadOshiNoKo - Oshi no Ko dedicated (WordPress + mangaread.org CDN)
    "readoshinoko.com": ReadOshiNoKoScraper,
    "w13.readoshinoko.com": ReadOshiNoKoScraper,
    
    # ReadBerserkManga - Berserk dedicated (WordPress + hot.planeptune.us CDN)
    "read-berserk-manga.com": ReadBerserkMangaScraper,
    
    # MonsterMangaOnline - Aggregator (WordPress MangaVerse + cdn.monster-manga.online)
    "monster-manga.online": MonsterMangaOnlineScraper,
    "www.monster-manga.online": MonsterMangaOnlineScraper,
    
    # BlameManga - BLAME! by Tsutomu Nihei dedicated (WordPress + Blogger CDN)
    "blame-manga.com": BlameMangaScraper,
    "w9.blame-manga.com": BlameMangaScraper,
    
    # KenganAshuraManga - Kengan Ashura/Omega dedicated (WordPress + wp-content CDN)
    "kenganashura.com": KenganAshuraMangaScraper,
    
    # SkipBeatMangaOnline - Skip Beat dedicated (WordPress Zazm + laiond.com CDN)
    "skip-beat-manga.online": SkipBeatMangaOnlineScraper,
    
    # OyasumiPunpunManga - Goodnight Punpun dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "oyasumipunpun.com": OyasumiPunpunMangaScraper,
    
    # ReadSNKManga - Attack on Titan dedicated (WordPress + Blogger CDN) - different from readsnk.com
    "readsnkmanga.com": ReadSNKMangaScraper,
    
    # OnePunchManMangaa - One Punch Man dedicated (WordPress + wp-content/uploads CDN)
    "onepunchmanmangaa.com": OnePunchManMangaaScraper,
    
    # ReadOPM - Manga aggregator with One Punch Man focus (cdn.readopm.com CDN)
    "readopm.com": ReadOPMScraper,
    "ww6.readopm.com": ReadOPMScraper,
    
    # ReadJJK.com - Jujutsu Kaisen dedicated (WordPress Kadence + img.read-jjk.com CDN)
    "read-jjk.com": ReadJJKComScraper,
    
    # DetectiveConanMangaOnline - Detective Conan / Case Closed dedicated (WordPress Zazm + laiond.com CDN)
    "detective-conan-manga.online": DetectiveConanMangaOnlineScraper,
    
    # OnePunchManRead - One Punch Man dedicated (WordPress Elementor + cdn.mangadistrict.com CDN)
    "onepunchmanread.com": OnePunchManReadScraper,
    
    # CaseClosedOnline - Case Closed / Detective Conan dedicated (WordPress Zazm + laiond.com CDN)
    "case-closed.online": CaseClosedOnlineScraper,
    
    # HyoukaManga - Hyouka dedicated (WordPress Toivo Lite + Blogger CDN)
    "hyoukamanga.com": HyoukaMangaScraper,
    
    # WitchWatch - Witch Watch by Kenta Shinohara dedicated (WordPress Toivo Lite + Blogger CDN)
    "witch-watch.com": WitchWatchScraper,
    
    # WitchHatAtelier - Tongari Boushi no Atelier dedicated (WordPress Zazm + laiond.com CDN)
    "witch-hat-atelier.online": WitchHatAtelierScraper,
    
    # BeckManga - Beck: Mongolian Chop Squad dedicated (WordPress + Blogger CDN)
    "beckmanga.com": BeckMangaScraper,
    
    # KagurabachiMangaNew - Kagurabachi dedicated (WordPress Mangosm + saidvps.xyz CDN)
    "kagurabachi-manga.com": KagurabachiMangaNewScraper,
    
    # WorldTriggerOnline - World Trigger dedicated (WordPress Toivo Lite + Blogger CDN via og:image)
    "world-trigger.online": WorldTriggerOnlineScraper,
    
    # CallOfTheNight - Call of the Night / Yofukashi no Uta dedicated (WordPress Zazm + laiond.com CDN)
    "call-of-the-night.online": CallOfTheNightScraper,
    "w2.call-of-the-night.online": CallOfTheNightScraper,
    
    # RealManga - Real by Takehiko Inoue (wheelchair basketball manga, WordPress + laiond.com CDN)
    "real-manga.online": RealMangaScraper,
    
    # Detective Conan (Case Closed) - 1100+ chapters, WordPress + laiond.com CDN
    "detective-conan.online": DetectiveConanScraper,
    
    # Dorohedoro - Dark fantasy, 167 chapters, Blogger CDN
    "dorohedoro.online": DorohedoroScraper,
    
    # Tomie (Junji Ito) - Horror, 20 chapters, mangarchive.com CDN
    "tomie-manga.com": TomieScraper,
    "w12.tomie-manga.com": TomieScraper,
    
    # GutsBerserk - Berserk dedicated (WordPress Madara + img.spoilerhat.com proxy)
    "gutsberserk.com": GutsBerserkScraper,
    "www.gutsberserk.com": GutsBerserkScraper,
    
    # BerserkMangOrg - Berserk dedicated (WordPress + mangaread.org CDN)
    "berserkmang.org": BerserkMangOrgScraper,
    "www.berserkmang.org": BerserkMangOrgScraper,
    
    # OnePieceMangaOnline - One Piece dedicated (WordPress Comic Easel + nangca.com CDN)
    "onepiece-manga-online.net": OnePieceMangaOnlineScraper,
    "w57.onepiece-manga-online.net": OnePieceMangaOnlineScraper,
    "w58.onepiece-manga-online.net": OnePieceMangaOnlineScraper,
    
    # KimetsuYaibaOnline - Demon Slayer / Kimetsu no Yaiba dedicated (WordPress Comic Easel + wp-content CDN)
    "kimetsu-yaiba.online": KimetsuYaibaOnlineScraper,
    
    # BlueLockReadWW2 - Blue Lock dedicated (custom theme + cdn.bluelockread.com CDN)
    "bluelockread.com": BlueLockReadWW2Scraper,
    "ww2.bluelockread.com": BlueLockReadWW2Scraper,
    
    # DGraymanOnline - D.Gray-man dedicated (WordPress + laiond.com CDN)
    "d-grayman.online": DGraymanOnlineScraper,
    
    # SkipBeatOnline - Skip Beat dedicated (WordPress + loinew.com CDN)
    "skip-beat.online": SkipBeatOnlineScraper,
    
    # MashleMangaOnline - Mashle dedicated (WordPress + wp-content/uploads CDN)
    "mashle-manga.online": MashleMangaOnlineScraper,
    
    # ReadOnePunchOnline - One Punch Man (WordPress + cache.imagemanga.online CDN)
    "one-punch.online": ReadOnePunchOnlineScraper,
    "read.one-punch.online": ReadOnePunchOnlineScraper,
    
    # BlueExorcistOnline - Blue Exorcist / Ao no Exorcist (WordPress + laiond.com CDN)
    "blue-exorcist.online": BlueExorcistOnlineScraper,
    
    # BakiRahen - Baki Rahen dedicated (WordPress Ifenzi v2 + cdn.readkakegurui.com CDN)
    "bakirahen.com": BakiRahenScraper,
    
    # Bakidou - Multi-Baki series (WordPress Comic Easel + wp-content/uploads CDN)
    "bakidou.com": BakidouScraper,
    
    # FullmetalAlchemistOnline - FMA dedicated (WordPress + Blogger CDN)
    "full-metal-alchemist.online": FullmetalAlchemistOnlineScraper,
    "w9.full-metal-alchemist.online": FullmetalAlchemistOnlineScraper,
    
    # ParasyteManga - Parasyte dedicated (WordPress + Blogger CDN)
    "parasytemanga.com": ParasyteMangaScraper,
    "w9.parasytemanga.com": ParasyteMangaScraper,
    
    # DeathNoteMangaFree - Death Note dedicated (Static HTML + wp-content CDN)
    "deathnotemangafree.com": DeathNoteMangaFreeScraper,
    "www.deathnotemangafree.com": DeathNoteMangaFreeScraper,
    
    # Re-Zero-Manga.Online - Re:ZERO dedicated (WordPress + laiond.com CDN, alternate domain)
    "re-zero-manga.online": ReZeroMangaOnlineScraper,
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
