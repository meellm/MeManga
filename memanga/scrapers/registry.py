"""
Data-driven scraper registry.

Maps domains to template classes + config, dynamically creating scraper
classes at import time. Eliminates ~80 individual scraper files.
"""

from .templates import (
    NuxtSSRScraper,
    OGImageMetaScraper,
    WordPressMadaraScraper,
    LaiondCDNScraper,
    MangosmScraper,
)

# ═══════════════════════════════════════════════════════════════════
# Nuxt SSR configs
# ═══════════════════════════════════════════════════════════════════

_cfg_dddmanga = {
    "BASE_URL": "https://dddmanga.com",
    "ASSETS_URL": "https://assets.dddmanga.com/dandadan",
    "MANGA_TITLE": "Dandadan",
    "SEARCH_KEYWORDS": ["danda", "dan da dan"],
}

_cfg_chainsawdevil = {
    "BASE_URL": "https://chainsawdevil.com",
    "ASSETS_URL": "https://assets.chainsawdevil.com/chainsaw-man",
    "MANGA_TITLE": "Chainsaw Man",
    "SEARCH_KEYWORDS": ["chainsaw", "csm"],
}

_cfg_jjkaisen = {
    "BASE_URL": "https://jjkaisen.com",
    "ASSETS_URL": "https://assets.jjkaisen.com/jjkaisen",
    "MANGA_TITLE": "Jujutsu Kaisen",
    "SEARCH_KEYWORDS": ["jujutsu", "jjk", "kaisen"],
}

_cfg_oshinokoyo = {
    "BASE_URL": "https://oshinokoyo.com",
    "ASSETS_URL": "https://assets.oshinokoyo.com/oshinoko",
    "MANGA_TITLE": "Oshi no Ko",
    "SEARCH_KEYWORDS": ["oshi", "my star"],
}

_cfg_punpunmanga = {
    "BASE_URL": "https://punpunmanga.com",
    "ASSETS_URL": "https://assets.punpunmanga.com/punpun",
    "MANGA_TITLE": "Goodnight Punpun (Oyasumi Punpun)",
    "SEARCH_KEYWORDS": ["punpun", "oyasumi"],
}

_cfg_furieren = {
    "BASE_URL": "https://furieren.com",
    "ASSETS_URL": "https://assets.furieren.com/frieren",
    "MANGA_TITLE": "Frieren: Beyond Journey's End",
    "SEARCH_KEYWORDS": ["frieren", "journey's end"],
}

_cfg_kokounohito = {
    "BASE_URL": "https://kokounohito.com",
    "ASSETS_URL": "https://assets.kokounohito.com/kokounohito",
    "MANGA_TITLE": "The Climber (Kokou no Hito)",
    "SEARCH_KEYWORDS": ["climber", "kokou"],
}

_cfg_madeabyss = {
    "BASE_URL": "https://madeabyss.com",
    "ASSETS_URL": "https://assets.madeabyss.com/madeinabyss",
    "MANGA_TITLE": "Made in Abyss",
    "SEARCH_KEYWORDS": ["abyss", "made"],
}

_cfg_unopiece = {
    "BASE_URL": "https://unopiece.com",
    "ASSETS_URL": "https://assets.unopiece.com/onepiece",
    "MANGA_TITLE": "One Piece",
    "SEARCH_KEYWORDS": ["one piece"],
}

_cfg_onepunchmanofficial = {
    "BASE_URL": "https://onepunchmanofficial.com",
    "ASSETS_URL": "https://assets.onepunchmanofficial.com/onepunchmanofficial",
    "MANGA_TITLE": "One Punch Man",
    "SEARCH_KEYWORDS": ["one punch man"],
}

_cfg_blackclova = {
    "BASE_URL": "https://blackclova.com",
    "ASSETS_URL": "https://assets.blackclova.com/blackclover",
    "MANGA_TITLE": "Black Clover",
    "SEARCH_KEYWORDS": ["black clover"],
}

_cfg_kagurabachiread = {
    "BASE_URL": "https://kagurabachiread.com",
    "ASSETS_URL": "https://assets.kagurabachiread.com/kagurabachi",
    "MANGA_TITLE": "Kagurabachi",
    "SEARCH_KEYWORDS": ["kagurabachi"],
}

_cfg_centuriya = {
    "BASE_URL": "https://centuriya.com",
    "ASSETS_URL": "https://assets.centuriya.com/centuria",
    "MANGA_TITLE": "Centuria",
    "SEARCH_KEYWORDS": ["centuria"],
}

_cfg_grandbluemanga = {
    "BASE_URL": "https://grandbluemanga.com",
    "ASSETS_URL": "https://assets.grandbluemanga.com/grandblue",
    "MANGA_TITLE": "Grand Blue Dreaming",
    "SEARCH_KEYWORDS": ["grand blue"],
}

_cfg_gachiakutayo = {
    "BASE_URL": "https://gachiakutayo.com",
    "ASSETS_URL": "https://assets.gachiakutayo.com/gachiakuta",
    "MANGA_TITLE": "Gachiakuta",
    "SEARCH_KEYWORDS": ["gachiakuta"],
}

_cfg_galaxxias = {
    "BASE_URL": "https://galaxxias.com",
    "ASSETS_URL": "https://assets.galaxxias.com/galaxias",
    "MANGA_TITLE": "Galaxias",
    "SEARCH_KEYWORDS": ["galaxias"],
}

_cfg_ichithewitchread = {
    "BASE_URL": "https://ichithewitchread.com",
    "ASSETS_URL": "https://assets.ichithewitchread.com/ichithewitch",
    "MANGA_TITLE": "Ichi the Witch",
    "SEARCH_KEYWORDS": ["ichi"],
}

_cfg_jujutsumodulo_nuxt = {
    "BASE_URL": "https://jujutsumodulo.com",
    "ASSETS_URL": "https://assets.jujutsumodulo.com/jujutsumodulo",
    "MANGA_TITLE": "Jujutsu Kaisen Modulo",
    "SEARCH_KEYWORDS": ["jujutsu modulo"],
}

# ═══════════════════════════════════════════════════════════════════
# OG Image Meta configs
# ═══════════════════════════════════════════════════════════════════

_cfg_frierenmanga = {
    "base_url": "https://frieren-manga.com",
    "manga_title": "Frieren: Beyond Journey's End",
    "image_cdn_filters": ["img.spoilerhat.com", "mangafox"],
    "cover_url": "https://frieren-manga.com/wp-content/uploads/2024/10/Frieren-Beyond-Journeys-End-Manga-2.jpg",
}

_cfg_akiramanga = {
    "base_url": "https://akiramanga.com",
    "manga_title": "Akira",
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://akiramanga.com/wp-content/uploads/2022/02/Akira-Volume-1.webp",
}

_cfg_kaijimanga = {
    "base_url": "https://w9.kaijimanga.com",
    "manga_title": "Kaiji",
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://w9.kaijimanga.com/wp-content/uploads/2022/02/Volume-1.webp",
}

_cfg_berserkmanga = {
    "base_url": "https://w3.berserk-manga.com",
    "manga_title": "Berserk",
    "image_cdn_filters": ["mangaclash.com", "cdn"],
    "cover_url": "https://www.berserk-manga.com/wp-content/uploads/2025/04/Berserk-manga-715x1024.jpg",
}

_cfg_bleachread = {
    "base_url": "https://w38.bleach-read.com",
    "manga_title": "Bleach",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
}

_cfg_stoneocean = {
    "base_url": "https://stone-ocean-manga.com",
    "manga_title": "JoJo's Bizarre Adventure Part 6: Stone Ocean",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com", "bp.blogspot.com"],
}

_cfg_jojolands = {
    "base_url": "https://w9.jojolandsmanga.com",
    "manga_title": "JoJo's Bizarre Adventure Part 9: The JOJOLands",
    "image_cdn_filters": ["bp.blogspot.com", "blogger.googleusercontent.com"],
}

_cfg_steelballrun = {
    "base_url": "https://steel-ball-run.com",
    "manga_title": "Steel Ball Run",
    "image_cdn_filters": ["bp.blogspot.com", "blogger.googleusercontent.com"],
}

_cfg_recordofragnarok = {
    "base_url": "https://w1.record-of-ragnarok-manga.com",
    "manga_title": "Record of Ragnarok",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
}

_cfg_bluebox = {
    "base_url": "https://blue-box-manga.online",
    "manga_title": "Blue Box",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
}

_cfg_undeadunluck = {
    "base_url": "https://readundeadunluck.com",
    "manga_title": "Undead Unluck",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
}

_cfg_heavenlydelusion = {
    "base_url": "https://heavenly-delusion.com",
    "manga_title": "Tengoku Daimakyou (Heavenly Delusion)",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com", "bp.blogspot.com"],
}

_cfg_bananafish = {
    "base_url": "https://www.bananafishmanga.com",
    "manga_title": "Banana Fish",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["lowee.us"],
    "cover_url": "https://www.bananafishmanga.com/wp-content/uploads/2026/01/banana-fish-cover-1-1.webp",
}

_cfg_nanamanga = {
    "base_url": "https://w2.nanamanga.online",
    "manga_title": "Nana",
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://nanamanga.online/wp-content/uploads/2025/04/nana-manga-677x1024.webp",
}

_cfg_trigun = {
    "base_url": "https://trigunmanga.com",
    "manga_title": "Trigun",
    "image_cdn_filters": ["blogger.googleusercontent.com"],
}

_cfg_tomie = {
    "base_url": "https://w12.tomie-manga.com",
    "manga_title": "Tomie",
    "chapter_link_pattern": r'tomie-chapter-\d+',
    "image_cdn_filters": ["mangarchive.com"],
    "cover_url": "https://img.mangarchive.com/images/Tomie/zRmniOlt9ZA3OkOJvKZOISesleslGS1750519535.webp",
    "uses_cloudscraper": True,
}

_cfg_dorohedoro = {
    "base_url": "https://dorohedoro.online",
    "manga_title": "Dorohedoro",
    "chapter_link_pattern": r'dorohedoro-chapter-\d+',
    "image_cdn_filters": ["blogger.googleusercontent.com", "blogspot.com"],
    "cover_url": "https://dorohedoro.online/wp-content/uploads/2022/06/dorohedoro.jpg",
    "uses_cloudscraper": True,
}

_cfg_gantz = {
    "base_url": "https://www.gantzmangafree.com",
    "manga_title": "Gantz",
    "image_cdn_filters": ["bp.blogspot.com", "blogger.googleusercontent.com"],
    "uses_cloudscraper": True,
}

_cfg_parasyte = {
    "base_url": "https://w9.parasytemanga.com",
    "manga_title": "Parasyte",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "uses_cloudscraper": True,
}

_cfg_fma = {
    "base_url": "https://w9.full-metal-alchemist.online",
    "manga_title": "Fullmetal Alchemist",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "uses_cloudscraper": True,
}

_cfg_blame = {
    "base_url": "https://w9.blame-manga.com",
    "manga_title": "BLAME!",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://w9.blame-manga.com/wp-content/uploads/2022/03/Blame-Volume-1.webp",
}

_cfg_beck = {
    "base_url": "https://beckmanga.com",
    "manga_title": "Beck: Mongolian Chop Squad",
    "image_cdn_filters": ["blogger.googleusercontent.com", "bp.blogspot.com"],
    "cover_url": "https://beckmanga.com/wp-content/uploads/2024/10/Beck-Manga-Volume-1-685x1024.webp",
}

_cfg_claymore = {
    "base_url": "https://readclaymore.com",
    "manga_title": "Claymore",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://readclaymore.com/wp-content/uploads/2022/06/Claymore-Manga-Volume-1.webp",
}

_cfg_bakidou = {
    "base_url": "https://bakidou.com",
    "manga_title": "Baki (All Series)",
    "image_cdn_filters": ["wp-content/uploads"],
    "cover_url": "https://bakidou.com/wp-content/uploads/2020/01/hiya.jpg",
}

_cfg_worldtrigger = {
    "base_url": "https://world-trigger.online",
    "manga_title": "World Trigger",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["blogger.googleusercontent.com"],
    "cover_url": "https://world-trigger.online/wp-content/uploads/2022/06/World-Trigger-Manga.webp",
}

_cfg_hyouka = {
    "base_url": "https://hyoukamanga.com",
    "manga_title": "Hyouka",
    "image_cdn_filters": ["blogger.googleusercontent.com", "bp.blogspot.com"],
    "cover_url": "https://hyoukamanga.com/wp-content/uploads/2022/10/Hyouka-Manga-Header.webp",
}

_cfg_witchwatch = {
    "base_url": "https://witch-watch.com",
    "manga_title": "Witch Watch",
    "image_cdn_filters": ["blogger.googleusercontent.com", "bp.blogspot.com"],
    "cover_url": "https://witch-watch.com/wp-content/uploads/2024/01/witch-watch-manga.webp",
}

_cfg_onepiecemangaonline = {
    "base_url": "https://w58.onepiece-manga-online.net",
    "manga_title": "One Piece",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["nangca.com", "/wp-content/uploads/"],
    "uses_cloudscraper": True,
}

_cfg_kimetsuyaiba = {
    "base_url": "https://kimetsu-yaiba.online",
    "manga_title": "Demon Slayer: Kimetsu no Yaiba",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["/wp-content/uploads/"],
    "cover_url": "https://kimetsu-yaiba.online/wp-content/uploads/2025/08/Demon-Slayer_-Kimetsu-no-Yaiba.webp",
    "uses_cloudscraper": True,
}

_cfg_deathnotefree = {
    "base_url": "https://www.deathnotemangafree.com",
    "manga_title": "Death Note",
    "chapter_link_pattern": r'chapter-(\d+(?:\.\d+)?)',
    "image_cdn_filters": ["wp-content/uploads"],
}

# ═══════════════════════════════════════════════════════════════════
# WordPress Madara configs
# ═══════════════════════════════════════════════════════════════════

_cfg_azmanga = {
    "base_url": "https://azmanga.com",
    "uses_ajax": True,
}

_cfg_mangaforfree = {
    "base_url": "https://mangaforfree.net",
    "uses_ajax": True,
}

_cfg_sxfmanga = {
    "base_url": "https://ww2.sxfmanga.net",
    "manga_title": "Spy x Family",
    "manga_slug": "spy-x-family",
    "is_single_manga": True,
    "image_cdn_filters": ["img.spoilerhat.com", "mangafox"],
}

_cfg_mashlemanga = {
    "base_url": "https://www.mashlemanga.net",
    "manga_title": "Mashle: Magic and Muscles",
    "manga_slug": "mashle",
    "is_single_manga": True,
    "image_cdn_filters": ["img.spoilerhat.com", "wasabisys.com"],
}

_cfg_gutsberserk = {
    "base_url": "https://www.gutsberserk.com",
    "manga_title": "Berserk",
    "manga_slug": "berserk",
    "is_single_manga": True,
    "image_cdn_filters": ["img.spoilerhat.com", "mangafox"],
    "uses_cloudscraper": True,
}

_cfg_vinlandsaga = {
    "base_url": "https://ww3.vinlandsagamanga.net",
    "manga_title": "Vinland Saga",
    "manga_slug": "vinland-saga",
    "is_single_manga": True,
    "image_cdn_filters": ["img.spoilerhat.com", "zjcdn.mangafox.me"],
}

_cfg_dandadannet = {
    "base_url": "https://ww2.dandadanmanga.net",
    "manga_title": "Dandadan",
    "manga_slug": "dandadan",
    "is_single_manga": True,
    "image_cdn_filters": ["img.spoilerhat.com", "mangafox"],
}

_cfg_hiperdex = {
    "base_url": "https://hiperdex.com",
    "uses_ajax": True,
}

_cfg_mangaread = {
    "base_url": "https://www.mangaread.org",
    "uses_ajax": True,
}

_cfg_s2manga = {
    "base_url": "https://s2manga.com",
    "uses_ajax": True,
}

_cfg_manhwatop = {
    "base_url": "https://manhwatop.com",
    "uses_ajax": True,
}

_cfg_mangadistrict = {
    "base_url": "https://mangadistrict.com",
    "uses_ajax": True,
}

_cfg_manga18fx = {
    "base_url": "https://manga18fx.com",
    "uses_ajax": True,
    "image_cdn_filters": ["manga18fx"],
}

_cfg_aquamanga = {
    "base_url": "https://aquareader.net",
    "uses_ajax": True,
    "image_cdn_filters": ["aquareader.net"],
}

# ── Haruneko Madara additions ──

_cfg_apollcomics = {
    "base_url": "https://apollcomics.es",
    "uses_ajax": True,
}

_cfg_bokugents = {
    "base_url": "https://bokugents.com",
    "uses_ajax": True,
}

_cfg_dragontranslation = {
    "base_url": "https://dragontranslation.org",
    "uses_ajax": True,
}

_cfg_hipercool = {
    "base_url": "https://hipercool.net",
    "uses_ajax": True,
}

_cfg_mangasehri = {
    "base_url": "https://mangasehri.com",
    "uses_ajax": True,
}

_cfg_mangawow = {
    "base_url": "https://mangawow.com",
    "uses_ajax": True,
    "image_cdn_filters": ["mangawow.com"],
}

_cfg_pawmanga = {
    "base_url": "https://pawmanga.com",
    "uses_ajax": True,
    "image_cdn_filters": ["pawmanga.com"],
}

_cfg_rawxz = {
    "base_url": "https://rawjx.net",
    "uses_ajax": True,
    "image_cdn_filters": ["rawxz.xyz"],
}

_cfg_resetscans = {
    "base_url": "https://reset-scans.org",
    "uses_ajax": True,
}

_cfg_ruyamanga = {
    "base_url": "https://www.ruyamanga2.com",
    "uses_ajax": True,
    "image_cdn_filters": ["cdnformanga.xyz"],
}

_cfg_shinobiscans = {
    "base_url": "https://shinobiscans.com",
    "uses_ajax": True,
}

_cfg_tortugaceviri = {
    "base_url": "https://tortugaceviri.com",
    "uses_ajax": True,
    "image_cdn_filters": ["mangawow.com"],
}

_cfg_vermanhwa = {
    "base_url": "https://vermanhwa.com",
    "uses_ajax": True,
    "image_cdn_filters": ["vermanhwa.com"],
}

_cfg_yakshascans = {
    "base_url": "https://yakshascans.com",
    "uses_ajax": True,
    "image_cdn_filters": ["yakshascans.com"],
}

_cfg_zinmanga = {
    "base_url": "https://mangazin.org",
    "uses_ajax": True,
    "image_cdn_filters": ["mangazin.org"],
}

# ═══════════════════════════════════════════════════════════════════
# Laiond CDN configs
# ═══════════════════════════════════════════════════════════════════

_cfg_overlord = {
    "base_url": "https://overlord-manga.online",
    "manga_title": "Overlord",
}

_cfg_rezero = {
    "base_url": "https://rezero-manga.online",
    "manga_title": "Re:ZERO -Starting Life in Another World-",
}

_cfg_goblinslayer = {
    "base_url": "https://goblin-slayer-manga.online",
    "manga_title": "Goblin Slayer",
}

_cfg_mushokutensei = {
    "base_url": "https://mushoku-tensei-manga.online",
    "manga_title": "Mushoku Tensei: Isekai Ittara Honki Dasu",
}

_cfg_skipbeat_laiond = {
    "base_url": "https://skip-beat-manga.online",
    "manga_title": "Skip Beat!",
}

_cfg_conan_laiond = {
    "base_url": "https://detective-conan-manga.online",
    "manga_title": "Detective Conan (Case Closed)",
    "uses_cloudscraper": True,
}

_cfg_caseclosed = {
    "base_url": "https://case-closed.online",
    "manga_title": "Case Closed (Detective Conan)",
    "uses_cloudscraper": True,
}

_cfg_witchhat = {
    "base_url": "https://witch-hat-atelier.online",
    "manga_title": "Witch Hat Atelier (Tongari Boushi no Atelier)",
    "cdn_domains": ["laiond.com", "loinew.com"],
}

_cfg_callofthenight = {
    "base_url": "https://w2.call-of-the-night.online",
    "manga_title": "Call of the Night (Yofukashi no Uta)",
}

_cfg_aoashi = {
    "base_url": "https://ao-ashi-manga.com",
    "manga_title": "Ao Ashi",
}

_cfg_dgrayman = {
    "base_url": "https://d-grayman.online",
    "manga_title": "D.Gray-man",
    "uses_cloudscraper": True,
}

_cfg_blueexorcist_laiond = {
    "base_url": "https://blue-exorcist.online",
    "manga_title": "Blue Exorcist",
    "uses_cloudscraper": True,
}

_cfg_real = {
    "base_url": "https://real-manga.online",
    "manga_title": "Real",
    "uses_cloudscraper": True,
}

_cfg_conan2 = {
    "base_url": "https://detective-conan.online",
    "manga_title": "Detective Conan",
    "uses_cloudscraper": True,
}

_cfg_skipbeat2 = {
    "base_url": "https://skip-beat.online",
    "manga_title": "Skip Beat!",
    "cdn_domains": ["loinew.com"],
    "uses_cloudscraper": True,
}

# ═══════════════════════════════════════════════════════════════════
# Mangosm configs
# ═══════════════════════════════════════════════════════════════════

_cfg_blacklagoon = {
    "base_url": "https://readblacklagoon.com",
    "manga_title": "Black Lagoon",
    "manga_slug": "black-lagoon",
    "cdn_domains": ["img.mangarchive.com", "mangarchive.com/images"],
}

_cfg_hxh = {
    "base_url": "https://hxhmanga.com",
    "manga_title": "Hunter x Hunter",
    "manga_slug": "hunter-x-hunter",
    "cdn_domains": ["images.mangafreak.me"],
    "cdn_referer": "https://mangafreak.me/",
}

_cfg_jjkmodulo = {
    "base_url": "https://jujutsukaisenmodulo.org",
    "manga_title": "Jujutsu Kaisen Modulo",
    "manga_slug": "jujutsu-kaisen-modulo",
    "cdn_domains": ["planeptune.us", "wp-content/uploads"],
}

_cfg_readjjkfree = {
    "base_url": "https://readjujutsukaisenfree.com",
    "manga_title": "Jujutsu Kaisen",
    "manga_slug": "jujutsu-kaisen",
    "cdn_domains": ["planeptune.us", "wp-content/uploads"],
}

_cfg_bleachorg = {
    "base_url": "https://www.bleachmanga.org",
    "manga_title": "Bleach",
    "manga_slug": "bleach",
    "cdn_domains": ["cdn.mangaclash.com"],
}

_cfg_kagurabachimnew = {
    "base_url": "https://kagurabachi-manga.com",
    "manga_title": "Kagurabachi",
    "manga_slug": "kagurabachi",
    "cdn_domains": ["saidvps.xyz"],
}

# ═══════════════════════════════════════════════════════════════════
# Domain → (template_class, config) mapping
# ═══════════════════════════════════════════════════════════════════

TEMPLATE_SCRAPERS = {
    # ── Nuxt SSR ──
    "dddmanga.com": (NuxtSSRScraper, _cfg_dddmanga),
    "chainsawdevil.com": (NuxtSSRScraper, _cfg_chainsawdevil),
    "jjkaisen.com": (NuxtSSRScraper, _cfg_jjkaisen),
    "oshinokoyo.com": (NuxtSSRScraper, _cfg_oshinokoyo),
    "punpunmanga.com": (NuxtSSRScraper, _cfg_punpunmanga),
    "furieren.com": (NuxtSSRScraper, _cfg_furieren),
    "kokounohito.com": (NuxtSSRScraper, _cfg_kokounohito),
    "madeabyss.com": (NuxtSSRScraper, _cfg_madeabyss),
    "unopiece.com": (NuxtSSRScraper, _cfg_unopiece),
    "onepunchmanofficial.com": (NuxtSSRScraper, _cfg_onepunchmanofficial),
    "blackclova.com": (NuxtSSRScraper, _cfg_blackclova),
    "kagurabachiread.com": (NuxtSSRScraper, _cfg_kagurabachiread),
    "centuriya.com": (NuxtSSRScraper, _cfg_centuriya),
    "grandbluemanga.com": (NuxtSSRScraper, _cfg_grandbluemanga),
    "gachiakutayo.com": (NuxtSSRScraper, _cfg_gachiakutayo),
    "galaxxias.com": (NuxtSSRScraper, _cfg_galaxxias),
    "ichithewitchread.com": (NuxtSSRScraper, _cfg_ichithewitchread),
    "jujutsumodulo.com": (NuxtSSRScraper, _cfg_jujutsumodulo_nuxt),

    # ── OG Image Meta ──
    "frieren-manga.com": (OGImageMetaScraper, _cfg_frierenmanga),
    "akiramanga.com": (OGImageMetaScraper, _cfg_akiramanga),
    "kaijimanga.com": (OGImageMetaScraper, _cfg_kaijimanga),
    "w9.kaijimanga.com": (OGImageMetaScraper, _cfg_kaijimanga),
    "berserk-manga.com": (OGImageMetaScraper, _cfg_berserkmanga),
    "w3.berserk-manga.com": (OGImageMetaScraper, _cfg_berserkmanga),
    "w4.berserk-manga.com": (OGImageMetaScraper, _cfg_berserkmanga),
    "bleach-read.com": (OGImageMetaScraper, _cfg_bleachread),
    "w38.bleach-read.com": (OGImageMetaScraper, _cfg_bleachread),
    "stone-ocean-manga.com": (OGImageMetaScraper, _cfg_stoneocean),
    "jojolandsmanga.com": (OGImageMetaScraper, _cfg_jojolands),
    "w9.jojolandsmanga.com": (OGImageMetaScraper, _cfg_jojolands),
    "steel-ball-run.com": (OGImageMetaScraper, _cfg_steelballrun),
    "record-of-ragnarok-manga.com": (OGImageMetaScraper, _cfg_recordofragnarok),
    "w1.record-of-ragnarok-manga.com": (OGImageMetaScraper, _cfg_recordofragnarok),
    "blue-box-manga.online": (OGImageMetaScraper, _cfg_bluebox),
    "readundeadunluck.com": (OGImageMetaScraper, _cfg_undeadunluck),
    "heavenly-delusion.com": (OGImageMetaScraper, _cfg_heavenlydelusion),
    "bananafishmanga.com": (OGImageMetaScraper, _cfg_bananafish),
    "www.bananafishmanga.com": (OGImageMetaScraper, _cfg_bananafish),
    "nanamanga.online": (OGImageMetaScraper, _cfg_nanamanga),
    "w2.nanamanga.online": (OGImageMetaScraper, _cfg_nanamanga),
    "trigunmanga.com": (OGImageMetaScraper, _cfg_trigun),
    "tomie-manga.com": (OGImageMetaScraper, _cfg_tomie),
    "w12.tomie-manga.com": (OGImageMetaScraper, _cfg_tomie),
    "dorohedoro.online": (OGImageMetaScraper, _cfg_dorohedoro),
    "gantzmangafree.com": (OGImageMetaScraper, _cfg_gantz),
    "www.gantzmangafree.com": (OGImageMetaScraper, _cfg_gantz),
    "parasytemanga.com": (OGImageMetaScraper, _cfg_parasyte),
    "w9.parasytemanga.com": (OGImageMetaScraper, _cfg_parasyte),
    "full-metal-alchemist.online": (OGImageMetaScraper, _cfg_fma),
    "w9.full-metal-alchemist.online": (OGImageMetaScraper, _cfg_fma),
    "blame-manga.com": (OGImageMetaScraper, _cfg_blame),
    "w9.blame-manga.com": (OGImageMetaScraper, _cfg_blame),
    "beckmanga.com": (OGImageMetaScraper, _cfg_beck),
    "readclaymore.com": (OGImageMetaScraper, _cfg_claymore),
    "bakidou.com": (OGImageMetaScraper, _cfg_bakidou),
    "world-trigger.online": (OGImageMetaScraper, _cfg_worldtrigger),
    "hyoukamanga.com": (OGImageMetaScraper, _cfg_hyouka),
    "witch-watch.com": (OGImageMetaScraper, _cfg_witchwatch),
    "onepiece-manga-online.net": (OGImageMetaScraper, _cfg_onepiecemangaonline),
    "w57.onepiece-manga-online.net": (OGImageMetaScraper, _cfg_onepiecemangaonline),
    "w58.onepiece-manga-online.net": (OGImageMetaScraper, _cfg_onepiecemangaonline),
    "kimetsu-yaiba.online": (OGImageMetaScraper, _cfg_kimetsuyaiba),
    "deathnotemangafree.com": (OGImageMetaScraper, _cfg_deathnotefree),
    "www.deathnotemangafree.com": (OGImageMetaScraper, _cfg_deathnotefree),

    # ── WordPress Madara ──
    "azmanga.com": (WordPressMadaraScraper, _cfg_azmanga),
    "mangaforfree.net": (WordPressMadaraScraper, _cfg_mangaforfree),
    "sxfmanga.net": (WordPressMadaraScraper, _cfg_sxfmanga),
    "ww2.sxfmanga.net": (WordPressMadaraScraper, _cfg_sxfmanga),
    "www.sxfmanga.net": (WordPressMadaraScraper, _cfg_sxfmanga),
    "mashlemanga.net": (WordPressMadaraScraper, _cfg_mashlemanga),
    "www.mashlemanga.net": (WordPressMadaraScraper, _cfg_mashlemanga),
    "gutsberserk.com": (WordPressMadaraScraper, _cfg_gutsberserk),
    "www.gutsberserk.com": (WordPressMadaraScraper, _cfg_gutsberserk),
    "vinlandsagamanga.net": (WordPressMadaraScraper, _cfg_vinlandsaga),
    "ww3.vinlandsagamanga.net": (WordPressMadaraScraper, _cfg_vinlandsaga),
    "w3.vinlandsagamanga.net": (WordPressMadaraScraper, _cfg_vinlandsaga),
    "dandadanmanga.net": (WordPressMadaraScraper, _cfg_dandadannet),
    "ww2.dandadanmanga.net": (WordPressMadaraScraper, _cfg_dandadannet),
    "w2.dandadanmanga.net": (WordPressMadaraScraper, _cfg_dandadannet),
    "hiperdex.com": (WordPressMadaraScraper, _cfg_hiperdex),
    "mangaread.org": (WordPressMadaraScraper, _cfg_mangaread),
    "www.mangaread.org": (WordPressMadaraScraper, _cfg_mangaread),
    "s2manga.com": (WordPressMadaraScraper, _cfg_s2manga),
    "s2manga.io": (WordPressMadaraScraper, _cfg_s2manga),
    "manhwatop.com": (WordPressMadaraScraper, _cfg_manhwatop),
    "mangadistrict.com": (WordPressMadaraScraper, _cfg_mangadistrict),
    "manga18fx.com": (WordPressMadaraScraper, _cfg_manga18fx),
    "aquareader.net": (WordPressMadaraScraper, _cfg_aquamanga),
    
    # ── Haruneko Madara additions ──
    "apollcomics.es": (WordPressMadaraScraper, _cfg_apollcomics),
    "bokugents.com": (WordPressMadaraScraper, _cfg_bokugents),
    "dragontranslation.org": (WordPressMadaraScraper, _cfg_dragontranslation),
    "hipercool.net": (WordPressMadaraScraper, _cfg_hipercool),
    "mangasehri.com": (WordPressMadaraScraper, _cfg_mangasehri),
    "mangawow.com": (WordPressMadaraScraper, _cfg_mangawow),
    "pawmanga.com": (WordPressMadaraScraper, _cfg_pawmanga),
    "rawjx.net": (WordPressMadaraScraper, _cfg_rawxz),
    "reset-scans.org": (WordPressMadaraScraper, _cfg_resetscans),
    "ruyamanga2.com": (WordPressMadaraScraper, _cfg_ruyamanga),
    "www.ruyamanga2.com": (WordPressMadaraScraper, _cfg_ruyamanga),
    "shinobiscans.com": (WordPressMadaraScraper, _cfg_shinobiscans),
    "tortugaceviri.com": (WordPressMadaraScraper, _cfg_tortugaceviri),
    "vermanhwa.com": (WordPressMadaraScraper, _cfg_vermanhwa),
    "yakshascans.com": (WordPressMadaraScraper, _cfg_yakshascans),
    "mangazin.org": (WordPressMadaraScraper, _cfg_zinmanga),

    # ── Laiond CDN ──
    "overlord-manga.online": (LaiondCDNScraper, _cfg_overlord),
    "rezero-manga.online": (LaiondCDNScraper, _cfg_rezero),
    "re-zero-manga.online": (LaiondCDNScraper, _cfg_rezero),
    "goblin-slayer-manga.online": (LaiondCDNScraper, _cfg_goblinslayer),
    "mushoku-tensei-manga.online": (LaiondCDNScraper, _cfg_mushokutensei),
    "skip-beat-manga.online": (LaiondCDNScraper, _cfg_skipbeat_laiond),
    "detective-conan-manga.online": (LaiondCDNScraper, _cfg_conan_laiond),
    "case-closed.online": (LaiondCDNScraper, _cfg_caseclosed),
    "witch-hat-atelier.online": (LaiondCDNScraper, _cfg_witchhat),
    "call-of-the-night.online": (LaiondCDNScraper, _cfg_callofthenight),
    "w2.call-of-the-night.online": (LaiondCDNScraper, _cfg_callofthenight),
    "ao-ashi-manga.com": (LaiondCDNScraper, _cfg_aoashi),
    "d-grayman.online": (LaiondCDNScraper, _cfg_dgrayman),
    "blue-exorcist.online": (LaiondCDNScraper, _cfg_blueexorcist_laiond),
    "real-manga.online": (LaiondCDNScraper, _cfg_real),
    "detective-conan.online": (LaiondCDNScraper, _cfg_conan2),
    "skip-beat.online": (LaiondCDNScraper, _cfg_skipbeat2),

    # ── Mangosm ──
    "readblacklagoon.com": (MangosmScraper, _cfg_blacklagoon),
    "hxhmanga.com": (MangosmScraper, _cfg_hxh),
    "jujutsukaisenmodulo.org": (MangosmScraper, _cfg_jjkmodulo),
    "readjujutsukaisenfree.com": (MangosmScraper, _cfg_readjjkfree),
    "bleachmanga.org": (MangosmScraper, _cfg_bleachorg),
    "www.bleachmanga.org": (MangosmScraper, _cfg_bleachorg),
    "kagurabachi-manga.com": (MangosmScraper, _cfg_kagurabachimnew),
}


_class_cache = {}


def get_template_scrapers():
    """Create scraper classes from template+config registry.

    Returns dict of {domain: scraper_class}.
    """
    result = {}

    for domain, (template, config) in TEMPLATE_SCRAPERS.items():
        config_id = id(config)
        if config_id not in _class_cache:
            cls_name = f"Registry_{domain.replace('.', '_').replace('-', '_')}"
            _class_cache[config_id] = type(cls_name, (template,), dict(config))
        result[domain] = _class_cache[config_id]

    return result
