"""
MeManga Scrapers

``SCRAPERS`` maps every supported domain to its scraper class: the
individual scrapers registered below plus the template-based ones from
``registry.TEMPLATE_SCRAPERS``. Source metadata (search skips, curated
ranking, notes, and the class-level ``engine`` / ``content_language`` /
``nsfw`` attributes) is collected by ``catalog.source_catalog()``; see
docs/SUPPORTED_SOURCES.md for the generated list.

Scraper modules are imported on first lookup, not with this package, so
commands that never talk to a site don't load every scraper and its
dependencies. Listing or testing domains imports no scraper module;
``SCRAPERS[domain]`` and ``get_scraper()`` import only the one needed.

``get_scraper()`` hands each thread one instance per scraper class, so
repeated calls for a source share its session. It never gives one
instance to two threads (scraper state and sessions are not guaranteed
thread-safe); code that hands a scraper's work to threads of its own
gives each a ``BaseScraper.worker_copy()``, as chapter page downloads
do. Request spacing is shared by the whole class in every thread (see
``base.BaseScraper._rate_lock``).
"""

import threading
from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import Dict, Optional, Type, Union

from .base import BaseScraper, Chapter, Manga

# Individual scrapers: domain -> "module:ClassName" within this package.
_SCRAPER_PATHS: Dict[str, str] = {
    # TCB Scans - Jump manga (no Cloudflare, simple requests)
    "tcbonepiecechapters.com": "tcbscans:TCBScansScraper",
    "tcbscans.com": "tcbscans:TCBScansScraper",
    "tcbscans.me": "tcbscans:TCBScansScraper",

    # WeebCentral - Large library (hybrid: cloudscraper + Playwright)
    "weebcentral.com": "weebcentral:WeebCentralScraper",

    # Asura Scans - Manhwa (api.asurascans.com JSON API).
    # asuracomic.net / asuratoon.com are retired aliases kept so
    # library entries saved against them still resolve.
    "asurascans.com": "asurascans:AsuraScansScraper",
    "asuracomic.net": "asurascans:AsuraScansScraper",
    "asuratoon.com": "asurascans:AsuraScansScraper",

    # Mangakatana - General (Playwright/Firefox)
    "mangakatana.com": "mangakatana:MangakatanataScraper",

    # MangaDex - Community (API)
    "mangadex.org": "mangadex:MangaDexScraper",
    "api.mangadex.org": "mangadex:MangaDexScraper",

    # Mangapill - Large library (no Cloudflare, simple requests)
    "mangapill.com": "mangapill:MangapillScraper",

    # MangaPark - current working domain
    "mangapark1.com": "mangapark:MangaParkScraper",

    # MangaReader.to
    "mangareader.to": "mangareader:MangaReaderScraper",

    # MangaFire.to (Firefox + VRF bypass + descrambling)
    "mangafire.to": "mangafire:MangaFireScraper",

    # MangaSee123
    "mangasee123.com": "mangasee:MangaSeeScraper",

    # MangaBuddy
    "mangabuddy.com": "mangabuddy:MangaBuddyScraper",

    # Bato.to
    "bato.to": "batoto:BatoToScraper",
    "batoto.to": "batoto:BatoToScraper",

    # Mangakakalot
    "mangakakalot.com": "mangakakalot:MangakakalotScraper",
    "mangakakalot.to": "mangakakalot:MangakakalotScraper",

    # Manganato
    "manganato.com": "manganato:ManganatoScraper",
    "chapmanganato.to": "manganato:ManganatoScraper",
    "readmanganato.com": "manganato:ManganatoScraper",

    # Mangago
    "mangago.me": "mangago:MangagoScraper",
    "www.mangago.me": "mangago:MangagoScraper",

    # MangaTaro (ComicK replacement)
    "mangataro.org": "mangataro:MangaTaroScraper",

    # Mangadot - Multi-language aggregator (React Router SSR + JSON API)
    "mangadot.net": "mangadot:MangadotScraper",

    # Olympus Scanlation - Spanish manhwa scans (Nuxt JSON API + panel chapter list)
    "olympusxyz.com": "olympus:OlympusScraper",

    # ZonaTMO - Spanish manga/manhwa library (Laravel SSR HTML)
    "zonatmo.org": "zonatmo:ZonaTMOScraper",

    # Lector Manga - Spanish manga/manhwa reader (static Astro HTML).
    # lectormangass.net 301-redirects to lector-mangas.lat and is kept
    # so URLs saved or discovered on the old host still resolve.
    "lector-mangas.lat": "lectormanga:LectorMangaScraper",
    "lectormangass.net": "lectormanga:LectorMangaScraper",

    # Thunder Scans EN - English manhwa scans (MangaThemesia WordPress theme)
    "en-thunderscans.com": "thunderscans:ThunderScansScraper",

    # Wurmz - Indonesian manga/manhwa/manhua reader (Next.js SSR HTML)
    "wurmz.net": "wurmz:WurmzScraper",

    # FlameComics
    "flamecomics.xyz": "flamecomics:FlameComicsScraper",

    # LuminousScans
    "luminousscans.com": "luminousscans:LuminousScansScraper",

    # MangaHere
    "mangahere.cc": "mangahere:MangaHereScraper",

    # Hentai20 (NSFW)
    "hentai20.io": "hentai20:Hentai20Scraper",

    # ReadComicOnline (Comics)
    "readcomiconline.li": "readcomiconline:ReadComicOnlineScraper",

    # CoffeeManga
    "coffeemanga.io": "coffeemanga:CoffeeMangaScraper",

    # MGeko
    "mgeko.cc": "mgeko:MGekoScraper",

    # ManhuaFast
    "manhuafast.com": "manhuafast:ManhuaFastScraper",

    # MangaRead/MangaEffect
    "mangaeffect.com": "mangaeffect:MangaReadScraper",

    # ManhuaPlus
    "manhuaplus.org": "manhuaplus:ManhuaPlusScraper",

    # Manhwa18
    "manhwa18.cc": "manhwa18:Manhwa18Scraper",

    # MangaHub
    "mangahub.io": "mangahub:MangaHubScraper",

    # MangaTown
    "mangatown.com": "mangatown:MangaTownScraper",
    "www.mangatown.com": "mangatown:MangaTownScraper",

    # ManhuaUs
    "manhuaus.org": "manhuaus:ManhuaUsScraper",

    # TrueManga / MangaMonk
    "truemanga.com": "truemanga:TrueMangaScraper",
    "mangamonk.com": "truemanga:TrueMangaScraper",

    # NHentai (Doujin gallery)
    "nhentai.net": "nhentai:NHentaiScraper",

    # HentaiFox (Doujin gallery)
    "hentaifox.com": "hentaifox:HentaiFoxScraper",

    # IMHentai (Doujin gallery)
    "imhentai.xxx": "imhentai:IMHentaiScraper",

    # E-Hentai (Doujin gallery)
    "e-hentai.org": "ehentai:EHentaiScraper",
    "exhentai.org": "ehentai:EHentaiScraper",

    # ReadSNK - Attack on Titan dedicated (WordPress + CDN)
    "readsnk.com": "readsnk:ReadSNKScraper",

    # ReadBerserk - Berserk dedicated (WordPress + CDN)
    "readberserk.com": "readberserk:ReadBerserkScraper",

    # ReadHaikyuu - Haikyuu!! dedicated (WordPress + CDN)
    "readhaikyuu.com": "readhaikyuu:ReadHaikyuuScraper",

    # ReadJujutsuKaisen - JJK dedicated (WordPress + CDN)
    "readjujutsukaisen.com": "readjujutsukaisen:ReadJujutsuKaisenScraper",

    # ReadChainsawMan - Chainsaw Man dedicated (WordPress + CDN)
    "readchainsawman.com": "readchainsawman:ReadChainsawManScraper",

    # ReadOnePiece - One Piece dedicated (WordPress + CDN)
    "readonepiece.com": "readonepiece:ReadOnePieceScraper",
    "ww8.readonepiece.com": "readonepiece:ReadOnePieceScraper",
    "ww12.readonepiece.com": "readonepiece:ReadOnePieceScraper",

    # ReadNaruto - Naruto dedicated (WordPress + CDN)
    "readnaruto.com": "readnaruto:ReadNarutoScraper",
    "ww8.readnaruto.com": "readnaruto:ReadNarutoScraper",
    "ww10.readnaruto.com": "readnaruto:ReadNarutoScraper",
    "ww11.readnaruto.com": "readnaruto:ReadNarutoScraper",

    # ReadMHA - My Hero Academia dedicated (WordPress + CDN)
    "readmha.com": "readmha:ReadMHAScraper",
    "ww8.readmha.com": "readmha:ReadMHAScraper",
    "ww10.readmha.com": "readmha:ReadMHAScraper",

    # ReadFairyTail - Fairy Tail dedicated (WordPress + CDN)
    "readfairytail.com": "readfairytail:ReadFairyTailScraper",
    "ww7.readfairytail.com": "readfairytail:ReadFairyTailScraper",

    # ReadBlackClover - Black Clover dedicated (WordPress + CDN)
    "readblackclover.com": "readblackclover:ReadBlackCloverScraper",
    "ww7.readblackclover.com": "readblackclover:ReadBlackCloverScraper",

    # MangaPanda - MangaHub network (cloudscraper)
    "mangapanda.onl": "mangapanda:MangaPandaScraper",

    # MangaBolt - Jump manga aggregator
    "mangabolt.com": "mangabolt:MangaBoltScraper",

    # MangaFox.fun - MangaHub network (cloudscraper)
    "mangafox.fun": "mangafoxfun:MangaFoxFunScraper",

    # MangaHub.us - MangaHub network (cloudscraper)
    "mangahub.us": "mangahubus:MangaHubUsScraper",

    # 1Manga.co - Large library (MangaHub CDN)
    "1manga.co": "onemanga:OneMangaScraper",

    # MangaFreak.ws - Large manga library
    "mangafreak.ws": "mangafreak:MangaFreakScraper",
    "mangafreak.me": "mangafreak:MangaFreakScraper",
    "ww2.mangafreak.me": "mangafreak:MangaFreakScraper",

    # ComicK - Popular manga aggregator (public JSON API)
    "comick.io": "comick:ComickScraper",
    "comick.dev": "comick:ComickScraper",

    # Comix - Popular manga/manhwa aggregator (Playwright)
    "comix.to": "comix:ComixScraper",

    # FanFox (MangaFox) - Large manga library (Playwright)
    "fanfox.net": "fanfox:FanFoxScraper",
    "mangafox.me": "fanfox:FanFoxScraper",

    # Toonily - Korean manhwa/webtoon (Playwright)
    "toonily.me": "toonily:ToonilyScraper",

    # Omega Scans - Manhwa/webtoon (Playwright)
    "omegascans.org": "omegascans:OmegaScansScraper",

    # Hivetoons - Void Scans network (Playwright)
    "hivetoons.org": "hivetoons:HivetoonsScraper",
    "hivetoon.com": "hivetoons:HivetoonsScraper",

    # MangaYY - WordPress Madara (Playwright)
    "mangayy.org": "mangayy:MangaYYScraper",
    "likemanga.io": "mangayy:MangaYYScraper",

    # Manga4Life / MangaLife - Large library (Playwright + JS)
    "manga4life.com": "manga4life:Manga4LifeScraper",
    "mangalife.us": "manga4life:Manga4LifeScraper",

    # IsekaiScan - Isekai manga/manhwa (Playwright + Madara)
    "isekaiscan.com": "isekaiscan:IsekaiScanScraper",

    # ZinManga - Manga aggregator (Playwright + Madara)
    "zinmanga.com": "zinmanga:ZinMangaScraper",

    # ZazaManga - Manga aggregator (Playwright, redirected series sites)
    "zazamanga.com": "zazamanga:ZazaMangaScraper",
    "www.zazamanga.com": "zazamanga:ZazaMangaScraper",
    "deathnotemanga.com": "zazamanga:ZazaMangaScraper",
    "death-note-online.com": "zazamanga:ZazaMangaScraper",
    "fairytail100yearsquest.com": "zazamanga:ZazaMangaScraper",
    "gintama.site": "zazamanga:ZazaMangaScraper",
    "initialdmanga.com": "zazamanga:ZazaMangaScraper",
    "inuyasha.net": "zazamanga:ZazaMangaScraper",
    "onepunchmanmanga.org": "zazamanga:ZazaMangaScraper",
    "readhellsing.com": "zazamanga:ZazaMangaScraper",
    "readoverlord.com": "zazamanga:ZazaMangaScraper",

    # MangaBall - Multi-language aggregator (HTTP JSON API)
    "mangaball.net": "mangaball:MangaBallScraper",

    # Atsumaru - Manga aggregator (Typesense search + REST API)
    "atsu.moe": "atsumaru:AtsumaruScraper",

    # MangaClash - Manga aggregator (Playwright + Madara + CF).
    # Site unreachable (#179); kept so saved library entries still
    # resolve, but skipped by the search sweep.
    "mangaclash.com": "mangaclash:MangaClashScraper",

    # KunManga - Manga aggregator (Playwright + Madara + CF)
    "kunmanga.com": "kunmanga:KunMangaScraper",

    # ManyToon - Adult manhwa (Playwright + JS chapters)
    "manytoon.com": "manytoon:ManyToonScraper",

    # Pururin - Doujin gallery (Playwright + JS)
    "pururin.to": "pururin:PururinScraper",

    # HentaiRead - Hentai manga (Playwright)
    "hentairead.com": "hentairead:HentaiReadScraper",

    # Manganato.gg - New domain with Cloudflare (Playwright)
    "manganato.gg": "manganato_gg:ManganatoGGScraper",

    # MangaHere.onl - Images from mghcdn.com (Playwright)
    "mangahere.onl": "mangahereonl:MangaHereOnlScraper",

    # BeastarsManga - Beastars dedicated (WordPress + cdn.readkakegurui.com)
    "beastarsmanga.com": "beastarsmanga:BeastarsMangaScraper",

    # VagabondManga - Vagabond dedicated (WordPress + cdn.mangaclash.com)
    "vagabondmanga.org": "vagabondmanga:VagabondMangaScraper",
    "www.vagabondmanga.org": "vagabondmanga:VagabondMangaScraper",

    # MonsterManga - Monster (Naoki Urasawa) dedicated (WordPress + official.lowee.us)
    "monstermanga.org": "monstermanga:MonsterMangaScraper",
    "www.monstermanga.org": "monstermanga:MonsterMangaScraper",

    # DeathNoteManga - Death Note dedicated (WordPress + Blogger CDN)
    "death-note-manga.com": "deathnotemanga:DeathNoteMangaScraper",
    "w13.death-note-manga.com": "deathnotemanga:DeathNoteMangaScraper",

    # TGManga - Tokyo Ghoul dedicated (WordPress + wp-content)
    "tgmanga.com": "tgmanga:TGMangaScraper",

    # ReadIchiTheWitch - Ichi the Witch dedicated (cdn.readichithewitch.com)
    "readichithewitch.com": "readichithewitch:ReadIchiTheWitchScraper",
    "ww1.readichithewitch.com": "readichithewitch:ReadIchiTheWitchScraper",

    # DemonSlayerManga - Demon Slayer / Kimetsu no Yaiba dedicated (cdn.demonslayermanga.com)
    "demonslayermanga.com": "demonslayermanga:DemonSlayerMangaScraper",
    "ww9.demonslayermanga.com": "demonslayermanga:DemonSlayerMangaScraper",

    # DrStoneManga - Dr. Stone dedicated (assets.drstonemanga.com)
    "drstonemanga.com": "drstonemanga:DrStoneMangaScraper",

    # SakamotoManga - Sakamoto Days dedicated (cdn3.mangaclash.com)
    "sakamotomanga.com": "sakamotomanga:SakamotoMangaScraper",

    # ElusiveSamurai - The Elusive Samurai dedicated (pic.readkakegurui.com)
    "elusive-samurai.com": "elusivesamurai:ElusiveSamuraiScraper",
    "w4.elusive-samurai.com": "elusivesamurai:ElusiveSamuraiScraper",

    # ReadBlueLockOrg - Blue Lock dedicated (images.asuratoon.top)
    "readbluelock.org": "readbluelockorg:ReadBlueLockOrgScraper",

    # BocchiTheRockManga - Bocchi the Rock! dedicated (cdn.black-clover.org)
    "bocchitherockmanga.com": "bocchitherockmanga:BocchiTheRockMangaScraper",
    "w5.bocchitherockmanga.com": "bocchitherockmanga:BocchiTheRockMangaScraper",

    # SpyXFamilyManga - Spy x Family dedicated (cdn3.mangaclash.com)
    "spyxfamilymanga.org": "spyxfamilymanga:SpyXFamilyMangaScraper",

    # BlueExorcistManga - Blue Exorcist / Ao no Exorcist dedicated (cdn.readkakegurui.com)
    "blueexorcistmanga.com": "blueexorcistmanga:BlueExorcistMangaScraper",

    # AjimeNoIppo - Hajime no Ippo dedicated (WordPress + cdn.mangaclash.com)
    "ajimenoippo.com": "ajimenoippo:AjimeNoIppoScraper",
    "www.ajimenoippo.com": "ajimenoippo:AjimeNoIppoScraper",

    # HajimeNoIppoOnline - Hajime no Ippo dedicated (WordPress + laiond.com)
    "hajime-no-ippo-manga.online": "hajimenoippoonline:HajimeNoIppoOnlineScraper",

    # HajimNoIppo - Hajime no Ippo dedicated (WordPress + planeptune.us)
    "hajimnoippo.com": "hajimnoippo:HajimNoIppoScraper",

    # HajimeNoIppoBlogger - Hajime no Ippo dedicated (WordPress + Blogger CDN)
    "hajime-noippo.com": "hajimenoippoblogger:HajimeNoIppoBloggerScraper",
    "w22.hajime-noippo.com": "hajimenoippoblogger:HajimeNoIppoBloggerScraper",

    # BlueLockReadOnline - Blue Lock dedicated (WordPress + wp-content)
    "bluelockread.online": "bluelockreadonline:BlueLockReadOnlineScraper",

    # ReadSlamDunkOnline - Slam Dunk dedicated (WordPress + cdn.mangaclash.com)
    "read-slamdunk.online": "readslamdunkonline:ReadSlamDunkOnlineScraper",

    # ReadTokyoRevengers - Tokyo Revengers dedicated (WordPress + wp-content/mangaread.org)
    "read-tokyorevengers.com": "readtokyorevengers:ReadTokyoRevengersScraper",
    "w20.read-tokyorevengers.com": "readtokyorevengers:ReadTokyoRevengersScraper",
    "w23.read-tokyorevengers.com": "readtokyorevengers:ReadTokyoRevengersScraper",

    # DragonBallSuperOnline - Dragon Ball Super dedicated (WordPress + wp-content/uploads)
    "thedragonballsuper.online": "dragonballsuperonline:DragonBallSuperOnlineScraper",

    # DragonBallSuperOrg - Dragon Ball Super dedicated (WordPress + mangaread.org CDN)
    "dragonballsuper.org": "dragonballsuperorg:DragonBallSuperOrgScraper",
    "www.dragonballsuper.org": "dragonballsuperorg:DragonBallSuperOrgScraper",

    # FairyTailMangaFree - Fairy Tail 100 Years Quest dedicated (WordPress + cdn.mangaclash.com)
    "fairytailmangafree.com": "fairytailmangafree:FairyTailMangaFreeScraper",
    "www.fairytailmangafree.com": "fairytailmangafree:FairyTailMangaFreeScraper",

    # JoJolionManga - JoJo Part 8: JoJolion dedicated (WordPress + Blogger CDN)
    "jojolionmanga.com": "jojolionmanga:JoJolionMangaScraper",

    # HomunculusManga - Homunculus dedicated (WordPress + mangaread.org CDN)
    "homunculusmanga.com": "homunculusmanga:HomunculusMangaScraper",
    "www.homunculusmanga.com": "homunculusmanga:HomunculusMangaScraper",

    # SousouNoFrieren - Frieren dedicated (WordPress + cdn.mangaclash.com)
    "sousou-no-frieren.com": "sousnofrierenga:SousouNoFrierenScraper",

    # DemonSlayerOnline - Demon Slayer dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "demon-slayer.online": "demonslayeronline:DemonSlayerOnlineScraper",
    "w4.demon-slayer.online": "demonslayeronline:DemonSlayerOnlineScraper",

    # MangOasis - Multilingual manga aggregator (WordPress MangaVerse + cdn.mangoasis.com)
    "mangoasis.com": "mangoasis:MangOasisScraper",
    "www.mangoasis.com": "mangoasis:MangOasisScraper",

    # ReadKingdomFree - Kingdom dedicated (WordPress + planeptune.us CDN)
    "readkingdomfree.com": "readkingdomfree:ReadKingdomFreeScraper",
    "www.readkingdomfree.com": "readkingdomfree:ReadKingdomFreeScraper",

    # SakamotoDaysOnline - Sakamoto Days dedicated (PHP + attachment CDN)
    "sakamoto-days.online": "sakamotodaysonline:SakamotoDaysOnlineScraper",

    # OnePieceManga1 - One Piece dedicated (WordPress + Contabo storage CDN)
    "1piecemanga.com": "onepiecemanga1:OnePieceManga1Scraper",
    "w064.1piecemanga.com": "onepiecemanga1:OnePieceManga1Scraper",

    # KaijuNo8Manga - Kaiju No. 8 dedicated (WordPress + wp-content CDN)
    "kaijuno8-manga.com": "kaijuno8manga:KaijuNo8MangaScraper",

    # BlueLockMangaNet - Blue Lock dedicated (WordPress + Blogger CDN)
    "bluelockmanga.net": "bluelockmangaorg:BlueLockMangaNetScraper",

    # TokyoGhoulClub - Tokyo Ghoul dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "tokyoghoul.club": "tokyoghoulclub:TokyoGhoulClubScraper",

    # FireForceMangaOrg - Fire Force dedicated (WordPress Toivo Lite + cdn.mangaclash.com)
    "fireforcemanga.org": "fireforcemangaorg:FireForceMangaOrgScraper",
    "w1.fireforcemanga.org": "fireforcemangaorg:FireForceMangaOrgScraper",

    # ReadKenganAshura - Kengan Ashura dedicated (WordPress Comic Easel + Blogger CDN)
    "read-kengan-ashura.com": "readkenganashura:ReadKenganAshuraScraper",

    # BlueLockReadCom - Blue Lock dedicated (custom site + attachment CDN)
    "bluelock-read.com": "bluelockreadcom:BlueLockReadComScraper",

    # OnePieceRead - One Piece dedicated (Next.js SSR + cdn.onepiecechapters.com)
    "onepieceread.com": "onepieceread:OnePieceReadScraper",

    # MangaDNA - General manga/manhwa aggregator (img.mangadna.com CDN)
    "mangadna.com": "mangadna:MangaDNAScraper",

    # ReadJJKManga - JJK + Modulo dedicated (WordPress + wp-content CDN)
    "readjujutsukaisenmanga.com": "readjjkmanga:ReadJJKMangaScraper",

    # ReadOshiNoKo - Oshi no Ko dedicated (WordPress + mangaread.org CDN)
    "readoshinoko.com": "readoshinoko:ReadOshiNoKoScraper",
    "w13.readoshinoko.com": "readoshinoko:ReadOshiNoKoScraper",

    # ReadBerserkManga - Berserk dedicated (WordPress + hot.planeptune.us CDN)
    "read-berserk-manga.com": "readberserkmanga:ReadBerserkMangaScraper",

    # MonsterMangaOnline - Aggregator (WordPress MangaVerse + cdn.monster-manga.online)
    "monster-manga.online": "monstermangaonline:MonsterMangaOnlineScraper",
    "www.monster-manga.online": "monstermangaonline:MonsterMangaOnlineScraper",

    # KenganAshuraManga - Kengan Ashura/Omega dedicated (WordPress + wp-content CDN)
    "kenganashura.com": "kenganashuramanga:KenganAshuraMangaScraper",

    # OyasumiPunpunManga - Goodnight Punpun dedicated (WordPress Ifenzi + cdn.readkakegurui.com)
    "oyasumipunpun.com": "oyasumipunpunmanga:OyasumiPunpunMangaScraper",

    # ReadSNKManga - Attack on Titan dedicated (WordPress + Blogger CDN)
    "readsnkmanga.com": "readsnkmanga:ReadSNKMangaScraper",

    # OnePunchManMangaa - One Punch Man dedicated (WordPress + wp-content/uploads CDN)
    "onepunchmanmangaa.com": "onepunchmanmangaa:OnePunchManMangaaScraper",

    # ReadOPM - Manga aggregator with One Punch Man focus (cdn.readopm.com CDN)
    "readopm.com": "readopm:ReadOPMScraper",
    "ww6.readopm.com": "readopm:ReadOPMScraper",

    # ReadJJK.com - Jujutsu Kaisen dedicated (WordPress Kadence + img.read-jjk.com CDN)
    "read-jjk.com": "readjjkcom:ReadJJKComScraper",

    # OnePunchManRead - One Punch Man dedicated (WordPress Elementor + cdn.mangadistrict.com CDN)
    "onepunchmanread.com": "onepunchmanread:OnePunchManReadScraper",

    # BerserkMangOrg - Berserk dedicated (WordPress + mangaread.org CDN)
    "berserkmang.org": "berserkmangorg:BerserkMangOrgScraper",
    "www.berserkmang.org": "berserkmangorg:BerserkMangOrgScraper",

    # BlueLockReadWW2 - Blue Lock dedicated (custom theme + cdn.bluelockread.com CDN)
    "bluelockread.com": "bluelockreadww2:BlueLockReadWW2Scraper",
    "ww2.bluelockread.com": "bluelockreadww2:BlueLockReadWW2Scraper",

    # MashleMangaOnline - Mashle dedicated (WordPress + wp-content/uploads CDN)
    "mashle-manga.online": "mashlemangaonline:MashleMangaOnlineScraper",

    # ReadOnePunchOnline - One Punch Man (WordPress + cache.imagemanga.online CDN)
    "one-punch.online": "readonepunchonline:ReadOnePunchOnlineScraper",
    "read.one-punch.online": "readonepunchonline:ReadOnePunchOnlineScraper",

    # BakiRahen - Baki Rahen dedicated (WordPress Ifenzi v2 + cdn.readkakegurui.com CDN)
    "bakirahen.com": "bakirahen:BakiRahenScraper",

    # BlameManga - BLAME! dedicated (WordPress Comic Easel + Blogger CDN)
    "blame-manga.com": "blamemanga:BlameMangaScraper",
    "w9.blame-manga.com": "blamemanga:BlameMangaScraper",

    # JJKManga - Jujutsu Kaisen dedicated (cloudscraper + pic.readkakegurui.com CDN)
    "jjkmanga.net": "jjkmanga:JJKMangaScraper",

    # Kagane - Multi-manga REST API + Playwright for DRM-protected images.
    # kagane.org now redirects to kagane.to; both sit behind a Cloudflare
    # challenge, so Kagane is skipped by search (see BROKEN_SEARCH_SOURCES).
    "kagane.org": "kagane:KaganeScraper",
    "www.kagane.org": "kagane:KaganeScraper",
    "kagane.to": "kagane:KaganeScraper",

    # VyManga - General aggregator (chapter links via ad-redirect -> Blogger CDN)
    # Legacy hosts (vymanga.net / vyvymanga.net) 403 on their own /manga/ pages
    # but the scraper canonicalises them to mangavyvy.net; register them so
    # saved/manual entries resolve to a scraper before canonicalisation runs.
    "mangavyvy.net": "vymanga:VyMangaScraper",
    "vymanga.net": "vymanga:VyMangaScraper",
    "vyvymanga.net": "vymanga:VyMangaScraper",
}

# Exported by name for callers that import a scraper class from this
# package; resolved lazily by __getattr__ below.
_CLASS_PATHS: Dict[str, str] = {
    path.partition(":")[2]: path for path in _SCRAPER_PATHS.values()
}
_CLASS_PATHS["ReadMangaBaseScraper"] = "readmanga_base:ReadMangaBaseScraper"
_CLASS_PATHS["get_template_scrapers"] = "registry:get_template_scrapers"


# A "module:ClassName" path, or a class built from a template config.
_Entry = Union[str, Type[BaseScraper]]


def _load(path: str):
    """Import ``"module:name"`` from this package and return the object."""
    module, _, name = path.partition(":")
    return getattr(import_module(f".{module}", __name__), name)


class _LazyScrapers(Mapping[str, Type[BaseScraper]]):
    """Read-only domain -> scraper class mapping that imports on lookup.

    Iterating, ``len()`` and ``in`` only need the domain names, so they
    never import a scraper module; reading a value imports just the
    module that defines it.
    """

    def __init__(self, paths: Dict[str, str]):
        self._paths = paths
        self._entries: Optional[Dict[str, _Entry]] = None

    def _domains(self) -> Dict[str, _Entry]:
        if self._entries is None:
            from .registry import get_template_scrapers
            entries: Dict[str, _Entry] = dict(self._paths)
            # Template scrapers override any duplicate domains (fixes dead code duplicates)
            entries.update(get_template_scrapers())
            self._entries = entries
        return self._entries

    def __getitem__(self, domain: str) -> Type[BaseScraper]:
        entry = self._domains()[domain]
        return _load(entry) if isinstance(entry, str) else entry

    def __contains__(self, domain: object) -> bool:
        return domain in self._domains()

    def __iter__(self) -> Iterator[str]:
        return iter(self._domains())

    def __len__(self) -> int:
        return len(self._domains())

    def __repr__(self) -> str:
        return f"<scraper registry: {len(self)} domains>"


SCRAPERS: Mapping[str, Type[BaseScraper]] = _LazyScrapers(_SCRAPER_PATHS)


def __getattr__(name: str):
    path = _CLASS_PATHS.get(name)
    if path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return _load(path)


def __dir__():
    return sorted(set(globals()) | set(_CLASS_PATHS))


# Per-thread scraper instances, keyed by scraper class.
_instances = threading.local()


def _resolve_class(source: str) -> Optional[Type[BaseScraper]]:
    """Scraper class for ``source``: an exact domain, else its closest
    registered parent domain (``ww3.mangafreak.me`` -> ``mangafreak.me``).

    Each parent is a single registry lookup, so a miss checks only the
    host's own labels and imports nothing.
    """
    if source in SCRAPERS:
        return SCRAPERS[source]
    dot = source.find(".")
    while dot != -1:
        parent = source[dot + 1:]
        if parent in SCRAPERS:
            return SCRAPERS[parent]
        dot = source.find(".", dot + 1)
    return None


def get_scraper(source: str) -> BaseScraper:
    """Get the scraper instance for a source domain.

    Repeated calls from one thread return the same instance for every
    domain of a scraper class; other threads get their own.
    """
    source = source.lower()
    if source.startswith("www."):
        source = source[4:]

    cls = _resolve_class(source)
    if cls is None:
        supported = list_supported_sources()
        raise ValueError(f"No scraper available for: {source}\nSupported: {', '.join(supported)}")

    local = _instances  # read once: clear_scraper_cache() may swap it
    instances = getattr(local, "by_class", None)
    if instances is None:
        instances = local.by_class = {}
    scraper = instances.get(cls)
    if scraper is None:
        scraper = instances[cls] = cls()
    return scraper


def clear_scraper_cache() -> None:
    """Drop the cached scraper instances of every thread."""
    global _instances
    _instances = threading.local()


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


# Curated ranking and first-launch defaults live in the source catalog;
# re-exported here because the search engine and GUI import them from
# this package.
from .catalog import DEFAULT_ENABLED_SOURCES, POPULAR_SOURCES  # noqa: E402
