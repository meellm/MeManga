"""HTML tests for SingleTitleScraper and the dedicated sites built on it.

These sites used to be one hand-written module each; the expectations
below pin the behavior each module had, so the shared base can't drift
from it.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import SCRAPERS, get_scraper
from memanga.scrapers.single_title_base import (
    NumberedChaptersScraper,
    SingleTitleScraper,
)


# domain -> (class name, name, base_url, search title, search url, cover url)
SITES = {
    "beastarsmanga.com": (
        "BeastarsMangaScraper", "beastarsmanga", "https://beastarsmanga.com",
        "Beastars", "https://beastarsmanga.com/home/",
        "https://beastarsmanga.com/wp-content/uploads/2023/12/beastars.jpeg"),
    "monstermanga.org": (
        "MonsterMangaScraper", "monstermanga", "https://www.monstermanga.org",
        "Monster", "https://www.monstermanga.org/",
        "https://www.monstermanga.org/wp-content/uploads/2025/07/monster-cover-1.webp"),
    "readichithewitch.com": (
        "ReadIchiTheWitchScraper", "readichithewitch",
        "https://ww1.readichithewitch.com", "Ichi the Witch",
        "https://ww1.readichithewitch.com/manga/ichi-the-witch/", None),
    "vagabondmanga.org": (
        "VagabondMangaScraper", "vagabondmanga", "https://www.vagabondmanga.org",
        "Vagabond", "https://www.vagabondmanga.org/", None),
    "sousou-no-frieren.com": (
        "SousouNoFrierenScraper", "sousounofrieren", "https://sousou-no-frieren.com",
        "Sousou no Frieren (Frieren: Beyond Journey's End)",
        "https://sousou-no-frieren.com/", None),
    "spyxfamilymanga.org": (
        "SpyXFamilyMangaScraper", "spyxfamilymanga", "https://spyxfamilymanga.org",
        "Spy x Family", "https://spyxfamilymanga.org/",
        "https://spyxfamilymanga.org/wp-content/uploads/2025/05/cropped-spy-x-family-"
        "acrylic-coaster-act-1-osk-40769758363879-removebg-preview-192x192.png"),
    "tgmanga.com": (
        "TGMangaScraper", "tgmanga", "https://tgmanga.com",
        "Tokyo Ghoul", "https://tgmanga.com/", None),
    "blueexorcistmanga.com": (
        "BlueExorcistMangaScraper", "blueexorcistmanga", "https://blueexorcistmanga.com",
        "Blue Exorcist (Ao no Exorcist)", "https://blueexorcistmanga.com/home/",
        "https://blueexorcistmanga.com/wp-content/uploads/2023/10/Blue-Exorcist-cover.webp"),
    "fireforcemanga.org": (
        "FireForceMangaOrgScraper", "fireforcemangaorg", "https://w1.fireforcemanga.org",
        "Fire Force (Enen no Shouboutai)", "https://w1.fireforcemanga.org/",
        "https://w2.fireforcemanga.org/wp-content/uploads/2025/08/enen-no-shouboutai-cover-1.webp"),
    "tokyoghoul.club": (
        "TokyoGhoulClubScraper", "tokyoghoulclub", "https://tokyoghoul.club",
        "Tokyo Ghoul", "https://tokyoghoul.club/",
        "https://tokyoghoul.club/wp-content/uploads/2025/07/tokyo-ghoul-cover-1.webp"),
    "death-note-manga.com": (
        "DeathNoteMangaScraper", "deathnotemanga", "https://w13.death-note-manga.com",
        "Death Note", "https://w13.death-note-manga.com/", None),
    "blame-manga.com": (
        "BlameMangaScraper", "blamemanga", "https://w9.blame-manga.com",
        "BLAME!", "https://w9.blame-manga.com/",
        "https://w9.blame-manga.com/wp-content/uploads/2025/01/Blame-Manga-OpenGraph.webp"),
    "homunculusmanga.com": (
        "HomunculusMangaScraper", "homunculusmanga", "https://www.homunculusmanga.com",
        "Homunculus", "https://www.homunculusmanga.com/", None),
    "read-kengan-ashura.com": (
        "ReadKenganAshuraScraper", "readkenganashura", "https://read-kengan-ashura.com",
        "Kengan Ashura", "https://read-kengan-ashura.com/manga/kengan-ashura/",
        "https://read-kengan-ashura.com/wp-content/uploads/2022/06/kengan-ashura-1.jpg"),
    "ajimenoippo.com": (
        "AjimeNoIppoScraper", "ajimenoippo", "https://www.ajimenoippo.com",
        "Hajime no Ippo", "https://www.ajimenoippo.com/", None),
    "hajime-no-ippo-manga.online": (
        "HajimeNoIppoOnlineScraper", "hajimenoippoonline",
        "https://hajime-no-ippo-manga.online", "Hajime no Ippo",
        "https://hajime-no-ippo-manga.online/", None),
    "hajimnoippo.com": (
        "HajimNoIppoScraper", "hajimnoippo", "https://hajimnoippo.com",
        "Hajime no Ippo", "https://hajimnoippo.com/", None),
    "hajime-noippo.com": (
        "HajimeNoIppoBloggerScraper", "hajimenoippoblogger",
        "https://w22.hajime-noippo.com", "Hajime no Ippo",
        "https://w22.hajime-noippo.com/", None),
    "bluelockread.online": (
        "BlueLockReadOnlineScraper", "bluelockreadonline",
        "https://bluelockread.online", "Blue Lock",
        "https://bluelockread.online/", None),
    "bluelockmanga.net": (
        "BlueLockMangaNetScraper", "bluelockmanganet", "https://bluelockmanga.net",
        "Blue Lock", "https://bluelockmanga.net/",
        "https://bluelockmanga.net/wp-content/uploads/2024/05/81Z85oL1xvL._SL1500_-2.jpg"),
    "kaijuno8-manga.com": (
        "KaijuNo8MangaScraper", "kaijuno8manga", "https://kaijuno8-manga.com",
        "Kaiju No. 8", "https://kaijuno8-manga.com/",
        "https://kaijuno8-manga.com/wp-content/uploads/2025/09/Read-Kaiju-No.-8-Manga-Online.webp"),
    "thedragonballsuper.online": (
        "DragonBallSuperOnlineScraper", "dragonballsuperonline",
        "https://thedragonballsuper.online", "Dragon Ball Super",
        "https://thedragonballsuper.online/",
        "https://thedragonballsuper.online/wp-content/uploads/2024/08/thumb-350-330775.webp"),
    "dragonballsuper.org": (
        "DragonBallSuperOrgScraper", "dragonballsuperorg", "https://www.dragonballsuper.org",
        "Dragon Ball Super", "https://www.dragonballsuper.org/", ""),
    "1piecemanga.com": (
        "OnePieceManga1Scraper", "onepiecemanga1", "https://w064.1piecemanga.com",
        "One Piece", "https://w064.1piecemanga.com/",
        "https://w064.1piecemanga.com/wp-content/uploads/2024/08/One_Piece_Chapter_1.png"),
    "read-tokyorevengers.com": (
        "ReadTokyoRevengersScraper", "readtokyorevengers", "https://read-tokyorevengers.com",
        "Tokyo Revengers", "https://read-tokyorevengers.com/",
        "https://w5.read-tokyorevengers.com/wp-content/uploads/2023/07/TOKYO-REVENGERS-manga.webp"),
    "fairytailmangafree.com": (
        "FairyTailMangaFreeScraper", "fairytailmangafree", "https://www.fairytailmangafree.com",
        "Fairy Tail: 100 Years Quest", "https://www.fairytailmangafree.com/",
        "https://fairytailmangafree.com/wp-content/uploads/2025/09/fairy-tail-cover-1.webp"),
    "read-slamdunk.online": (
        "ReadSlamDunkOnlineScraper", "readslamdunkonline", "https://read-slamdunk.online",
        "Slam Dunk", "https://read-slamdunk.online/",
        "https://read-slamdunk.online/wp-content/uploads/2023/03/cropped-339-3392153_"
        "sakuragi-hanamichi-slam-dunk-removebg-preview-192x192.png"),
    "bocchitherockmanga.com": (
        "BocchiTheRockMangaScraper", "bocchitherockmanga", "https://bocchitherockmanga.com",
        "Bocchi the Rock!", "https://bocchitherockmanga.com/", None),
    "elusive-samurai.com": (
        "ElusiveSamuraiScraper", "elusivesamurai", "https://elusive-samurai.com",
        "The Elusive Samurai", "https://elusive-samurai.com/", None),
    "readbluelock.org": (
        "ReadBlueLockOrgScraper", "readbluelockorg", "https://readbluelock.org",
        "Blue Lock", "https://readbluelock.org/", None),
    "drstonemanga.com": (
        "DrStoneMangaScraper", "drstonemanga", "https://drstonemanga.com",
        "Dr. Stone", "https://drstonemanga.com/", None),
}

ALIASES = {
    "www.vagabondmanga.org": "vagabondmanga.org",
    "www.monstermanga.org": "monstermanga.org",
    "ww1.readichithewitch.com": "readichithewitch.com",
    "w13.death-note-manga.com": "death-note-manga.com",
    "w1.fireforcemanga.org": "fireforcemanga.org",
    "w9.blame-manga.com": "blame-manga.com",
    "www.homunculusmanga.com": "homunculusmanga.com",
    "www.ajimenoippo.com": "ajimenoippo.com",
    "w22.hajime-noippo.com": "hajime-noippo.com",
    "www.dragonballsuper.org": "dragonballsuper.org",
    "w064.1piecemanga.com": "1piecemanga.com",
    "w20.read-tokyorevengers.com": "read-tokyorevengers.com",
    "w23.read-tokyorevengers.com": "read-tokyorevengers.com",
    "www.fairytailmangafree.com": "fairytailmangafree.com",
    "w5.bocchitherockmanga.com": "bocchitherockmanga.com",
    "w4.elusive-samurai.com": "elusive-samurai.com",
}


# ──────────────────────────────────────────────────────────────────────
# Registry wiring
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain", sorted(SITES) + sorted(ALIASES))
def test_domain_keeps_its_scraper_class(domain):
    cls_name, name, base_url, *_ = SITES[ALIASES.get(domain, domain)]
    s = get_scraper(domain)
    assert isinstance(s, SingleTitleScraper)
    assert type(s).__name__ == cls_name
    assert type(s).__module__ == "memanga.scrapers.single_title_sites"
    assert s.name == name
    assert s.base_url == base_url
    assert s.session.headers["Referer"] == base_url


def test_every_single_title_class_is_covered():
    covered = {SCRAPERS[d] for d in SITES}
    registered = {cls for d, cls in ((d, SCRAPERS[d]) for d in SCRAPERS)
                  if cls.__module__ == "memanga.scrapers.single_title_sites"}
    assert registered == covered
    assert len(covered) == len(SITES)


@pytest.mark.parametrize("domain", sorted(ALIASES))
def test_alias_shares_class_with_canonical_domain(domain):
    assert SCRAPERS[domain] is SCRAPERS[ALIASES[domain]]


def test_class_names_are_still_exported():
    import memanga.scrapers as pkg
    for cls_name, *_ in SITES.values():
        assert getattr(pkg, cls_name).__name__ == cls_name


@pytest.mark.parametrize("domain", sorted(SITES))
def test_search_returns_the_series_offline(domain):
    _, _, _, title, url, cover = SITES[domain]
    results = get_scraper(domain).search("anything")
    assert [(r.title, r.url, r.cover_url) for r in results] == [(title, url, cover)]


@pytest.mark.parametrize("domain", sorted(SITES))
def test_sites_stay_in_the_search_sweep(domain):
    """Registry templates are left out of the sweep; these sites are not."""
    from memanga.scrapers.catalog import source_catalog
    from memanga.scrapers.registry import TEMPLATE_SCRAPERS
    assert domain not in TEMPLATE_SCRAPERS
    row = next(r for r in source_catalog() if r.domain == domain)
    assert row.template is None
    assert row.scraper == SITES[domain][0]


def _chapters(s, patch_html, html, fetched=None):
    def fake(url):
        if fetched is not None:
            fetched.append(url)
        return html

    patch_html(s, fake)
    return [(c.number, c.title, c.url) for c in s.get_chapters("ignored")]


# ──────────────────────────────────────────────────────────────────────
# Selector layout (beastarsmanga, monstermanga, readichithewitch, ...)
# ──────────────────────────────────────────────────────────────────────


BEASTARS_HOME = """
<html><body>
  <a href="https://beastarsmanga.com/manga/59241-beastars-chapter-196/">Chapter 196</a>
  <a href="/manga/59241-beastars-chapter-10.5/">Chapter 10.5</a>
  <a href="https://beastarsmanga.com/manga/59241-beastars-chapter-196/">dup</a>
  <a href="https://beastarsmanga.com/manga/59241-beastars-chapter-1/"></a>
  <a href="https://beastarsmanga.com/about/">About</a>
</body></html>
"""


class TestSelectorLayoutChapters:
    def test_reads_series_page_and_parses_links(self, patch_html):
        fetched = []
        chapters = _chapters(get_scraper("beastarsmanga.com"), patch_html,
                             BEASTARS_HOME, fetched)
        assert fetched == ["https://beastarsmanga.com/home/"]
        assert chapters == [
            ("196", "Chapter 196",
             "https://beastarsmanga.com/manga/59241-beastars-chapter-196/"),
            ("10.5", "Chapter 10.5",
             "https://beastarsmanga.com/manga/59241-beastars-chapter-10.5/"),
        ]

    def test_series_specific_number_pattern(self, patch_html):
        s = get_scraper("monstermanga.org")
        assert [c[0] for c in _chapters(s, patch_html,
                '<a href="https://www.monstermanga.org/manga/'
                'monster-chapter-162-0/">Chapter 162</a>')] == ["162"]

    def test_ichi_reads_manga_page(self, patch_html):
        s = get_scraper("readichithewitch.com")
        patch_html(s, {"/manga/ichi-the-witch/":
                       '<a href="/chapter/ichi-the-witch-chapter-42/">Ch 42</a>'})
        chapters = s.get_chapters("ignored")
        assert [(c.number, c.url) for c in chapters] == [
            ("42", "https://ww1.readichithewitch.com/chapter/ichi-the-witch-chapter-42/")]

    def test_no_chapters(self, patch_html):
        s = get_scraper("beastarsmanga.com")
        patch_html(s, "<html><body></body></html>")
        assert s.get_chapters("ignored") == []

    def test_vagabond_titles_untitled_links_from_slug(self, patch_html):
        s = get_scraper("vagabondmanga.org")
        assert _chapters(s, patch_html, '<a href="/manga/chapter-12-5/"></a>') == [
            ("12", "Chapter 12-5", "https://www.vagabondmanga.org/manga/chapter-12-5/")]

    def test_frieren_titles_untitled_links_by_integer(self, patch_html):
        s = get_scraper("sousou-no-frieren.com")
        html = ('<a href="/manga/253-sousou-no-frieren-chapter-140/"></a>'
                '<a href="/manga/253-sousou-no-frieren-chapter-x/"></a>')
        assert _chapters(s, patch_html, html) == [
            ("140", "Chapter 140",
             "https://sousou-no-frieren.com/manga/253-sousou-no-frieren-chapter-140/")]

    def test_spyxfamily_span_titles_and_dash_decimals(self, patch_html):
        s = get_scraper("spyxfamilymanga.org")
        html = ('<a href="/manga/spyxfamily-chapter-110-5/">'
                '<span class="chapter-name">Chapter 110.5</span></a>'
                '<a href="/manga/spyxfamily-chapter-9/"><img src="x.jpg"></a>')
        assert _chapters(s, patch_html, html) == [
            ("110.5", "Chapter 110.5",
             "https://spyxfamilymanga.org/manga/spyxfamily-chapter-110-5/")]

    def test_blue_exorcist_reads_home_with_dash_decimals(self, patch_html):
        fetched = []
        s = get_scraper("blueexorcistmanga.com")
        chapters = _chapters(s, patch_html,
                             '<a href="/manga/ao-no-exorcist-chapter-150-5/">Ch</a>',
                             fetched)
        assert fetched == ["https://blueexorcistmanga.com/home/"]
        assert [c[0] for c in chapters] == ["150.5"]

    def test_homunculus_skips_non_manga_links(self, patch_html):
        s = get_scraper("homunculusmanga.com")
        html = ('<a href="/manga/homunculus-chapter-166/"></a>'
                '<a href="/manga/homunculus-extra/">chapter list</a>'
                '<a href="/tag/chapter-2/">Chapter 2</a>')
        assert _chapters(s, patch_html, html) == [
            ("166", "Chapter 166",
             "https://www.homunculusmanga.com/manga/homunculus-chapter-166/")]

    def test_kengan_reads_homepage_with_dash_decimals(self, patch_html):
        fetched = []
        s = get_scraper("read-kengan-ashura.com")
        html = ('<a href="/comic/kengan-ashura-chapter-12-5/"></a>'
                '<a href="/comic/kengan-ashura-chapter-3/">Chapter 3</a>'
                '<a href="/comic/kengan-ashura-chapter-4/oembed">x</a>'
                '<a href="/comic/kengan-ashura-special-chapter/"></a>')
        assert _chapters(s, patch_html, html, fetched) == [
            ("12.5", "Chapter 12.5",
             "https://read-kengan-ashura.com/comic/kengan-ashura-chapter-12-5/"),
            ("3", "Chapter 3", "https://read-kengan-ashura.com/comic/kengan-ashura-chapter-3/"),
            ("0", "Chapter 0", "https://read-kengan-ashura.com/comic/kengan-ashura-special-chapter/"),
        ]
        assert fetched == ["https://read-kengan-ashura.com"]


class TestSelectorLayoutPages:
    def test_cdn_images_anywhere_src_first(self, patch_html):
        s = get_scraper("beastarsmanga.com")
        patch_html(s, """
          <img src="https://beastarsmanga.com/wp-content/uploads/logo.png">
          <div><img src="https://cdn.readkakegurui.com/b/1.jpg"
                    data-src="https://cdn.readkakegurui.com/b/other.jpg"></div>
          <img data-src="https://cdn.readkakegurui.com/b/2.jpg">
          <img src=" https://cdn.readkakegurui.com/b/3.jpg ">
          <img src="https://cdn.readkakegurui.com/b/1.jpg">
        """)
        assert s.get_pages("https://beastarsmanga.com/manga/x-chapter-1/") == [
            "https://cdn.readkakegurui.com/b/1.jpg",
            "https://cdn.readkakegurui.com/b/2.jpg",
            "https://cdn.readkakegurui.com/b/3.jpg",
        ]

    def test_tgmanga_accepts_only_upload_jpegs(self, patch_html):
        s = get_scraper("tgmanga.com")
        patch_html(s, '<img src="https://tgmanga.com/wp-content/uploads/1.JPEG">'
                      '<img src="https://tgmanga.com/wp-content/uploads/logo.png">'
                      '<img src="https://cdn.example/2.jpeg">')
        assert s.get_pages("x") == ["https://tgmanga.com/wp-content/uploads/1.JPEG"]

    def test_blue_exorcist_prefers_separator_images(self, patch_html):
        s = get_scraper("blueexorcistmanga.com")
        patch_html(s, '<img src="https://cdn.readkakegurui.com/cover.jpg">'
                      '<div class="separator"><img src="https://cdn.readkakegurui.com/1.jpg"></div>')
        assert s.get_pages("x") == ["https://cdn.readkakegurui.com/1.jpg"]
        patch_html(s, '<img src="https://cdn.readkakegurui.com/2.jpg">')
        assert s.get_pages("x") == ["https://cdn.readkakegurui.com/2.jpg"]

    def test_fire_force_meta_then_image_fallback(self, patch_html):
        s = get_scraper("fireforcemanga.org")
        patch_html(s, '<meta property="og:image" content="https://cdn.mangaclash.com/1.jpg">'
                      '<meta property="twitter:image" content="https://cdn.mangaclash.com/2.jpg">'
                      '<meta property="og:image" content="https://cdn.mangaclash.com/1.jpg">'
                      '<img src="https://cdn.mangaclash.com/3.jpg">')
        assert s.get_pages("x") == ["https://cdn.mangaclash.com/1.jpg",
                                    "https://cdn.mangaclash.com/2.jpg"]
        patch_html(s, '<img src="data:image/gif;base64,R0lG" '
                      'data-src="https://cdn.mangaclash.com/3.jpg">')
        assert s.get_pages("x") == ["https://cdn.mangaclash.com/3.jpg"]

    def test_death_note_prefers_full_size_links(self, patch_html):
        s = get_scraper("death-note-manga.com")
        patch_html(s, """
          <div class="separator"><a href="https://blogger.googleusercontent.com/full/1.jpg">
            <img src="https://blogger.googleusercontent.com/s320/1.jpg"></a></div>
          <div class="separator"><a href="https://example.org/">
            <img src="https://blogger.googleusercontent.com/s320/2.jpg"></a></div>
        """)
        assert s.get_pages("x") == ["https://blogger.googleusercontent.com/full/1.jpg",
                                    "https://blogger.googleusercontent.com/s320/2.jpg"]

    def test_blame_reads_only_meta_images(self, patch_html):
        s = get_scraper("blame-manga.com")
        patch_html(s, '<img src="https://blogger.googleusercontent.com/0.jpg">'
                      '<meta property="og:image" content="https://blogger.googleusercontent.com/1.jpg">')
        assert s.get_pages("x") == ["https://blogger.googleusercontent.com/1.jpg"]


# ──────────────────────────────────────────────────────────────────────
# .entry-content layout (Hajime no Ippo sites, bluelockread.online)
# ──────────────────────────────────────────────────────────────────────


IPPO_HOME = """
<html><body>
  <a href="https://www.ajimenoippo.com/manga/hajime-no-ippo-chapter-1470/">Chapter 1470</a>
  <a href="/manga/HAJIME-NO-IPPO-CHAPTER-12/"></a>
  <a href="https://www.ajimenoippo.com/manga/hajime-no-ippo-chapter-5.5/">Chapter 5.5</a>
  <a href="https://www.ajimenoippo.com/contact/">Contact</a>
</body></html>
"""


class TestEntryContentLayoutChapters:
    def test_any_chapter_link_and_untitled_links_get_a_title(self, patch_html):
        fetched = []
        chapters = _chapters(get_scraper("ajimenoippo.com"), patch_html,
                             IPPO_HOME, fetched)
        assert fetched == ["https://www.ajimenoippo.com/"]
        assert chapters == [
            ("1470", "Chapter 1470",
             "https://www.ajimenoippo.com/manga/hajime-no-ippo-chapter-1470/"),
            ("12", "Chapter 12",
             "https://www.ajimenoippo.com/manga/HAJIME-NO-IPPO-CHAPTER-12/"),
            ("5.5", "Chapter 5.5",
             "https://www.ajimenoippo.com/manga/hajime-no-ippo-chapter-5.5/"),
        ]


class TestEntryContentLayoutPages:
    def test_lazy_images_inside_entry_content(self, patch_html):
        s = get_scraper("ajimenoippo.com")
        patch_html(s, """
          <img src="https://cdn.mangaclash.com/outside.jpg">
          <div class="entry-content">
            <img src="data:image/svg+xml;base64,AAAA"
                 data-src="https://cdn.mangaclash.com/ippo/1.jpg">
            <img src="data:image/gif;base64,R0lG">
            <img src="https://cdn.mangaclash.com/ippo/2.jpg">
            <img data-src="https://elsewhere.example/3.jpg">
          </div>
        """)
        assert s.get_pages("https://www.ajimenoippo.com/manga/x-chapter-1/") == [
            "https://cdn.mangaclash.com/ippo/1.jpg",
            "https://cdn.mangaclash.com/ippo/2.jpg",
        ]

    def test_whole_page_when_no_entry_content(self, patch_html):
        s = get_scraper("bluelockread.online")
        patch_html(s, '<img data-src="https://bluelockread.online/wp-content/'
                      'uploads/2024/01/01.jpg">')
        assert s.get_pages("https://bluelockread.online/blue-lock-chapter-1/") == [
            "https://bluelockread.online/wp-content/uploads/2024/01/01.jpg"]


# ──────────────────────────────────────────────────────────────────────
# Plain-link layout: hrefs kept as written, digit titles become "Chapter N"
# ──────────────────────────────────────────────────────────────────────


class TestPlainLinkLayout:
    def test_relative_links_kept_and_number_required(self, patch_html):
        s = get_scraper("bluelockmanga.net")
        html = ('<a href="/blue-lock-chapter-300/"></a>'
                '<a href="https://bluelockmanga.net/blue-lock-chapter-299/">299</a>'
                '<a href="https://bluelockmanga.net/blue-lock-chapter-298/">Ch. 298</a>'
                '<a href="/blue-lock-chapter-extra/">Extra</a>')
        assert _chapters(s, patch_html, html) == [
            ("300", "Chapter 300", "/blue-lock-chapter-300/"),
            ("299", "Chapter 299", "https://bluelockmanga.net/blue-lock-chapter-299/"),
            ("298", "Ch. 298", "https://bluelockmanga.net/blue-lock-chapter-298/"),
        ]

    def test_text_less_links_skipped_where_number_optional(self, patch_html):
        s = get_scraper("thedragonballsuper.online")
        html = ('<a href="/dragon-ball-super-manga-chapter-100/"></a>'
                '<a href="/dragon-ball-super-manga-chapter-99/">99</a>'
                '<a href="/dragon-ball-super-manga-chapter-x/">7</a>')
        assert _chapters(s, patch_html, html) == [
            ("99", "Chapter 99", "/dragon-ball-super-manga-chapter-99/"),
            ("0", "Chapter 0", "/dragon-ball-super-manga-chapter-x/"),
        ]

    def test_case_sensitive_numbers(self, patch_html):
        s = get_scraper("read-tokyorevengers.com")
        html = '<a href="/manga/tokyo-manji-revengers-chapter-278/Chapter-1">Last</a>'
        assert [c[0] for c in _chapters(s, patch_html, html)] == ["278"]

    def test_dragon_ball_org_dash_decimals(self, patch_html):
        s = get_scraper("dragonballsuper.org")
        html = '<a href="/manga/dragon-ball-chou-super-chapter-67-5/">67</a>'
        assert _chapters(s, patch_html, html) == [
            ("67.5", "Chapter 67.5", "/manga/dragon-ball-chou-super-chapter-67-5/")]

    def test_kaiju_pages_skip_logos(self, patch_html):
        s = get_scraper("kaijuno8-manga.com")
        patch_html(s, '<div class="entry-content">'
                      '<img src="https://kaijuno8-manga.com/wp-content/uploads/logo.png">'
                      '<img data-src="https://cdn.example/1.WEBP"></div>')
        assert s.get_pages("x") == ["https://cdn.example/1.WEBP"]

    def test_one_piece_pages_skip_emoji(self, patch_html):
        s = get_scraper("1piecemanga.com")
        patch_html(s, '<p><img src="https://w064.1piecemanga.com/wp-includes/x.png">'
                      '<img src="https://s.w.org/Emoji/72x72/1.png">'
                      '<img src="https://eu2.contabostorage.com/op/1"></p>')
        assert s.get_pages("x") == ["https://eu2.contabostorage.com/op/1"]

    def test_tokyo_revengers_falls_back_to_reader_images(self, patch_html):
        s = get_scraper("read-tokyorevengers.com")
        patch_html(s, '<div class="reading-content"><img src="https://x.example/p1"></div>')
        assert s.get_pages("x") == ["https://x.example/p1"]

    def test_fairy_tail_skips_covers_then_falls_back(self, patch_html):
        s = get_scraper("fairytailmangafree.com")
        patch_html(s, '<img data-src="https://cdn.mangaclash.com/Cover.jpg">'
                      '<img data-src="https://cdn.mangaclash.com/1.jpg">')
        assert s.get_pages("x") == ["https://cdn.mangaclash.com/1.jpg"]
        patch_html(s, '<div class="entry-content"><img src="https://x.example/1.png"></div>')
        assert s.get_pages("x") == ["https://x.example/1.png"]


class TestSlamDunk:
    def test_titles_and_bare_relative_links(self, patch_html):
        s = get_scraper("read-slamdunk.online")
        html = ('<a href="read/manga/slam-dunk-chapter-276/">Final</a>'
                '<a href="/manga/slam-dunk-chapter-275/">Chapter 275</a>'
                '<a href="https://read-slamdunk.online/about/">Chapter list</a>')
        # A bare relative href gets a "/"; a title without "Chapter" is replaced
        assert _chapters(s, patch_html, html) == [
            ("276", "Chapter 276",
             "https://read-slamdunk.online/read/manga/slam-dunk-chapter-276/"),
            ("275", "Chapter 275", "https://read-slamdunk.online/manga/slam-dunk-chapter-275/"),
        ]

    def test_pages_fall_back_to_og_image(self, patch_html):
        s = get_scraper("read-slamdunk.online")
        patch_html(s, '<meta property="twitter:image" content="https://cdn.mangaclash.com/0.jpg">'
                      '<meta property="og:image" content="https://cdn.mangaclash.com/1.jpg">')
        assert s.get_pages("x") == ["https://cdn.mangaclash.com/1.jpg"]


# ──────────────────────────────────────────────────────────────────────
# Numbered-link layout (oldest first, one chapter per number)
# ──────────────────────────────────────────────────────────────────────


class TestNumberedLayout:
    def test_resolves_against_chapter_base_and_dedups_by_number(self, patch_html):
        s = get_scraper("bocchitherockmanga.com")
        assert isinstance(s, NumberedChaptersScraper)
        html = ('<a href="/manga/bocchi-chapter-10/">x</a>'
                '<a href="read/manga/bocchi-chapter-2/"></a>'
                '<a href="https://w5.bocchitherockmanga.com/manga/bocchi-chapter-10/">y</a>'
                '<a href="/news/chapter-3/">z</a>')
        assert _chapters(s, patch_html, html) == [
            ("2", "Chapter 2", "https://w5.bocchitherockmanga.com/read/manga/bocchi-chapter-2/"),
            ("10", "Chapter 10", "https://w5.bocchitherockmanga.com/manga/bocchi-chapter-10/"),
        ]

    def test_dr_stone_chapter_paths(self, patch_html):
        s = get_scraper("drstonemanga.com")
        html = '<a href="/chapter/232">x</a><a href="/chapter/2">y</a><a href="/manga/z">z</a>'
        assert _chapters(s, patch_html, html) == [
            ("2", "Chapter 2", "https://drstonemanga.com/chapter/2"),
            ("232", "Chapter 232", "https://drstonemanga.com/chapter/232"),
        ]

    def test_read_blue_lock_lazy_images(self, patch_html):
        s = get_scraper("readbluelock.org")
        patch_html(s, '<img src="https://readbluelock.org/logo.png" '
                      'data-src="https://images.asuratoon.top/1.jpg">')
        assert s.get_pages("x") == ["https://images.asuratoon.top/1.jpg"]


# ──────────────────────────────────────────────────────────────────────
# Image download
# ──────────────────────────────────────────────────────────────────────


class TestDownloadImage:
    def test_sends_referer_and_writes_body(self, monkeypatch, tmp_path, fake_response):
        s = get_scraper("hajime-noippo.com")
        seen = {}

        def fake_get(url, headers=None, timeout=None):
            seen.update(url=url, headers=headers, timeout=timeout)
            return fake_response(content=b"\xff\xd8\xff" + b"x" * 10)

        monkeypatch.setattr(s.session, "get", fake_get)
        path = tmp_path / "ch" / "001.jpg"
        assert s.download_image("https://1.bp.blogspot.com/p.jpg", path) is True
        assert path.read_bytes() == b"\xff\xd8\xff" + b"x" * 10
        assert seen["headers"]["Referer"] == "https://w22.hajime-noippo.com"
        assert seen["headers"]["Accept"].startswith("image/")
        assert seen["timeout"] == 30

    def test_http_error_is_a_failed_page(self, monkeypatch, tmp_path, fake_response):
        s = get_scraper("beastarsmanga.com")
        monkeypatch.setattr(s.session, "get",
                            lambda *a, **k: fake_response(status=404))
        path = tmp_path / "001.jpg"
        assert s.download_image("https://cdn.readkakegurui.com/x.jpg", path) is False
        assert not path.exists()
