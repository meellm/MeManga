"""
Dedicated single-title sites built on SingleTitleScraper.

Each class keeps the name it had as a hand-written module. Most differ
only in data; a site-specific chapter or page rule is a small override
of one SingleTitleScraper hook.
"""

from .single_title_base import NumberedChaptersScraper, SingleTitleScraper


_ENTRY_IMAGES = "div.entry-content img, article img, p img"
_IMAGE_EXTENSIONS = (".jpg", ".png", ".webp")


# ── Chapter links picked by a series-specific selector ──────────────


class BeastarsMangaScraper(SingleTitleScraper):
    """Scraper for beastarsmanga.com - Beastars (images on cdn.readkakegurui.com)."""

    name = "beastarsmanga"
    base_url = "https://beastarsmanga.com"
    manga_title = "Beastars"
    manga_path = "/home/"
    cover_url = "https://beastarsmanga.com/wp-content/uploads/2023/12/beastars.jpeg"
    # Format: /manga/59241-beastars-chapter-X/
    chapter_link_selector = "a[href*='beastars-chapter']"
    chapter_number_pattern = r'chapter[- ]?(\d+(?:\.\d+)?)'
    image_cdn_filters = ("cdn.readkakegurui.com",)


class MonsterMangaScraper(SingleTitleScraper):
    """Scraper for monstermanga.org - Monster by Naoki Urasawa (images on official.lowee.us)."""

    name = "monstermanga"
    base_url = "https://www.monstermanga.org"
    manga_title = "Monster"
    cover_url = "https://www.monstermanga.org/wp-content/uploads/2025/07/monster-cover-1.webp"
    # Format: /manga/monster-chapter-162-0/
    chapter_link_selector = "a[href*='monster-chapter-']"
    chapter_number_pattern = r'monster-chapter-(\d+(?:\.\d+)?)'
    image_cdn_filters = ("official.lowee.us",)


class ReadIchiTheWitchScraper(SingleTitleScraper):
    """Scraper for readichithewitch.com - Ichi the Witch (images on cdn.readichithewitch.com)."""

    name = "readichithewitch"
    base_url = "https://ww1.readichithewitch.com"
    manga_title = "Ichi the Witch"
    manga_path = "/manga/ichi-the-witch/"
    # Format: /chapter/ichi-the-witch-chapter-X/
    chapter_link_selector = "a[href*='ichi-the-witch-chapter-']"
    image_cdn_filters = ("cdn.readichithewitch.com",)


class VagabondMangaScraper(SingleTitleScraper):
    """Scraper for vagabondmanga.org - Vagabond (images on cdn.mangaclash.com)."""

    name = "vagabondmanga"
    base_url = "https://www.vagabondmanga.org"
    manga_title = "Vagabond"
    # Format: /manga/chapter-X/
    chapter_link_selector = "a[href*='/manga/chapter-']"
    image_cdn_filters = ("cdn.mangaclash.com",)

    def _untitled_title(self, link, href, number, matched):
        return f"Chapter {href.split('chapter-')[-1].rstrip('/')}"


class SousouNoFrierenScraper(SingleTitleScraper):
    """Scraper for sousou-no-frieren.com - Frieren: Beyond Journey's End (images on cdn.mangaclash.com)."""

    name = "sousounofrieren"
    base_url = "https://sousou-no-frieren.com"
    manga_title = "Sousou no Frieren (Frieren: Beyond Journey's End)"
    # Format: /manga/253-sousou-no-frieren-chapter-X/
    chapter_link_selector = "a[href*='sousou-no-frieren-chapter-']"
    untitled_links = "integer"
    image_cdn_filters = ("mangaclash",)


class SpyXFamilyMangaScraper(SingleTitleScraper):
    """Scraper for spyxfamilymanga.org - Spy x Family (images on cdn3.mangaclash.com)."""

    name = "spyxfamilymanga"
    base_url = "https://spyxfamilymanga.org"
    manga_title = "Spy x Family"
    cover_url = ("https://spyxfamilymanga.org/wp-content/uploads/2025/05/cropped-spy-x-family-"
                 "acrylic-coaster-act-1-osk-40769758363879-removebg-preview-192x192.png")
    # Format: /manga/spyxfamily-chapter-X/
    chapter_link_selector = "a[href*='spyxfamily-chapter-']"
    chapter_number_pattern = r'chapter-(\d+(?:[.-]\d+)?)'
    chapter_number_dash_decimal = True
    image_attrs = ("data-src", "src")
    image_cdn_filters = ("mangaclash.com",)

    def _untitled_title(self, link, href, number, matched):
        # Text-less links carry the title in a child span
        span = link.select_one(".chapter-name")
        return span.get_text(strip=True) if span else None


class TGMangaScraper(SingleTitleScraper):
    """Scraper for tgmanga.com - Tokyo Ghoul (images in wp-content/uploads)."""

    name = "tgmanga"
    base_url = "https://tgmanga.com"
    manga_title = "Tokyo Ghoul"
    # Format: /manga/tokyo-ghoul-chapter-X/
    chapter_link_selector = "a[href*='tokyo-ghoul-chapter-']"

    def _is_page_image(self, url):
        # Only wp-content/uploads JPEGs are chapter pages
        return "wp-content/uploads" in url and ".jpeg" in url.lower()


class BlueExorcistMangaScraper(SingleTitleScraper):
    """Scraper for blueexorcistmanga.com - Blue Exorcist (images on cdn.readkakegurui.com)."""

    name = "blueexorcistmanga"
    base_url = "https://blueexorcistmanga.com"
    manga_title = "Blue Exorcist (Ao no Exorcist)"
    manga_path = "/home/"
    cover_url = "https://blueexorcistmanga.com/wp-content/uploads/2023/10/Blue-Exorcist-cover.webp"
    # Format: /manga/ao-no-exorcist-chapter-X/
    chapter_link_selector = "a[href*='ao-no-exorcist-chapter']"
    chapter_number_pattern = r'chapter-(\d+(?:[.-]\d+)?)'
    chapter_number_dash_decimal = True
    image_cdn_filters = ("cdn.readkakegurui.com",)

    def _page_urls(self, soup):
        # Pages sit in separator divs; fall back to every image
        imgs = [div.find("img") for div in soup.select("div.separator")]
        return (self._pick(self._img_srcs(img for img in imgs if img))
                or self._pick(self._img_srcs(soup.find_all("img"))))


class FireForceMangaOrgScraper(SingleTitleScraper):
    """Scraper for fireforcemanga.org - Fire Force (og:image pages on cdn.mangaclash.com)."""

    name = "fireforcemangaorg"
    base_url = "https://w1.fireforcemanga.org"
    manga_title = "Fire Force (Enen no Shouboutai)"
    cover_url = "https://w2.fireforcemanga.org/wp-content/uploads/2025/08/enen-no-shouboutai-cover-1.webp"
    chapter_link_selector = "a[href*='enen-no-shouboutai-chapter']"
    image_cdn_filters = ("mangaclash.com",)

    def _page_urls(self, soup):
        return (self._pick(self._meta_srcs(soup))
                or self._pick(self._img_srcs(soup.find_all("img"), ("data-src", "src"))))


class TokyoGhoulClubScraper(FireForceMangaOrgScraper):
    """Scraper for tokyoghoul.club - Tokyo Ghoul (og:image pages on cdn.mangaclash.com)."""

    name = "tokyoghoulclub"
    base_url = "https://tokyoghoul.club"
    manga_title = "Tokyo Ghoul"
    cover_url = "https://tokyoghoul.club/wp-content/uploads/2025/07/tokyo-ghoul-cover-1.webp"
    chapter_link_selector = "a[href*='tokyo-ghoul-chapter']"


class DeathNoteMangaScraper(SingleTitleScraper):
    """Scraper for death-note-manga.com - Death Note (images on Blogger CDN)."""

    name = "deathnotemanga"
    base_url = "https://w13.death-note-manga.com"
    manga_title = "Death Note"
    chapter_link_selector = "a[href*='death-note-chapter-']"
    image_cdn_filters = ("blogger.googleusercontent.com",)

    def _page_urls(self, soup):
        # Each separator div links the full-size image or holds the <img>
        urls = []
        for div in soup.select("div.separator"):
            a = div.find("a")
            if a and self._is_page_image(a.get("href", "")):
                urls.append(a.get("href", ""))
                continue
            img = div.find("img")
            if img:
                urls.extend(self._img_srcs([img]))
        return self._pick(urls) or self._pick(self._img_srcs(soup.find_all("img")))


class BlameMangaScraper(SingleTitleScraper):
    """Scraper for blame-manga.com - BLAME! (og:image pages on Blogger CDN)."""

    name = "blamemanga"
    base_url = "https://w9.blame-manga.com"
    manga_title = "BLAME!"
    cover_url = "https://w9.blame-manga.com/wp-content/uploads/2025/01/Blame-Manga-OpenGraph.webp"
    chapter_link_selector = "a[href*='/manga/blame-chapter']"
    chapter_number_pattern = r'chapter[- ]?(\d+(?:\.\d+)?)'
    image_cdn_filters = ("blogger.googleusercontent.com",)

    def _page_urls(self, soup):
        return self._pick(self._meta_srcs(soup))


class HomunculusMangaScraper(SingleTitleScraper):
    """Scraper for homunculusmanga.com - Homunculus (og:image pages on mangaread.org CDN)."""

    name = "homunculusmanga"
    base_url = "https://www.homunculusmanga.com"
    manga_title = "Homunculus"
    chapter_link_selector = "a[href*='chapter']"
    chapter_number_pattern = r'chapter[- ]?(\d+(?:\.\d+)?)'
    untitled_links = "matched-number"
    image_cdn_filters = ("mangaread.org", "mangaclash.com", "blogspot.com")

    def _skip_chapter(self, href):
        return "/manga/" not in href or "chapter" not in href

    def _page_urls(self, soup):
        return self._pick(self._meta_srcs(soup))


class ReadKenganAshuraScraper(SingleTitleScraper):
    """Scraper for read-kengan-ashura.com - Kengan Ashura (images on Blogger CDN)."""

    name = "readkenganashura"
    base_url = "https://read-kengan-ashura.com"
    manga_title = "Kengan Ashura"
    manga_path = "/manga/kengan-ashura/"
    chapter_list_path = ""
    cover_url = "https://read-kengan-ashura.com/wp-content/uploads/2022/06/kengan-ashura-1.jpg"
    chapter_href_pattern = r'comic/kengan-ashura.*chapter'
    chapter_number_pattern = r'chapter-(\d+(?:-\d+)?)'
    chapter_number_dash_decimal = True
    untitled_links = "number"
    image_attrs = ("src",)
    image_cdn_filters = ("blogspot.com",)

    def _skip_chapter(self, href):
        return "oembed" in href or "tag/" in href


# ── Lazy-loaded pages inside .entry-content ─────────────────────────


class _EntryContentScraper(SingleTitleScraper):
    """Any "chapter-N" link; pages are lazy-loaded images inside .entry-content."""

    untitled_links = "integer"
    image_container_class = "entry-content"
    image_attrs = ("data-src", "src")


class AjimeNoIppoScraper(_EntryContentScraper):
    """Scraper for ajimenoippo.com - Hajime no Ippo (images on cdn.mangaclash.com)."""

    name = "ajimenoippo"
    base_url = "https://www.ajimenoippo.com"
    manga_title = "Hajime no Ippo"
    image_cdn_filters = ("cdn.mangaclash.com",)


class HajimeNoIppoOnlineScraper(_EntryContentScraper):
    """Scraper for hajime-no-ippo-manga.online - Hajime no Ippo (images on laiond.com)."""

    name = "hajimenoippoonline"
    base_url = "https://hajime-no-ippo-manga.online"
    manga_title = "Hajime no Ippo"
    image_cdn_filters = ("laiond.com",)


class HajimNoIppoScraper(_EntryContentScraper):
    """Scraper for hajimnoippo.com - Hajime no Ippo (images on planeptune.us)."""

    name = "hajimnoippo"
    base_url = "https://hajimnoippo.com"
    manga_title = "Hajime no Ippo"
    image_cdn_filters = ("planeptune.us",)


class HajimeNoIppoBloggerScraper(_EntryContentScraper):
    """Scraper for hajime-noippo.com - Hajime no Ippo (images on Blogger CDN)."""

    name = "hajimenoippoblogger"
    base_url = "https://w22.hajime-noippo.com"
    manga_title = "Hajime no Ippo"
    image_cdn_filters = ("bp.blogspot.com",)


class BlueLockReadOnlineScraper(_EntryContentScraper):
    """Scraper for bluelockread.online - Blue Lock (images in wp-content/uploads)."""

    name = "bluelockreadonline"
    base_url = "https://bluelockread.online"
    manga_title = "Blue Lock"
    image_cdn_filters = ("wp-content/uploads",)


# ── Relative chapter links, digit-only titles become "Chapter N" ────


class _PlainLinksScraper(SingleTitleScraper):
    """Chapter hrefs are kept as written and numbered case-sensitively."""

    absolute_chapter_urls = False
    chapter_number_lowercase = False
    numeric_titles = True


class BlueLockMangaNetScraper(_PlainLinksScraper):
    """Scraper for bluelockmanga.net - Blue Lock (images on Blogger CDN / wp-content)."""

    name = "bluelockmanganet"
    base_url = "https://bluelockmanga.net"
    manga_title = "Blue Lock"
    cover_url = "https://bluelockmanga.net/wp-content/uploads/2024/05/81Z85oL1xvL._SL1500_-2.jpg"
    chapter_link_selector = "a[href*='blue-lock-chapter-']"
    chapter_requires_number = True
    untitled_links = "number"
    image_cdn_filters = ("blogger", "blogspot", "wp-content")

    def _page_urls(self, soup):
        return self._pick(self._img_srcs(soup.select(_ENTRY_IMAGES), ("data-src", "src")))


class KaijuNo8MangaScraper(_PlainLinksScraper):
    """Scraper for kaijuno8-manga.com - Kaiju No. 8 (images in wp-content)."""

    name = "kaijuno8manga"
    base_url = "https://kaijuno8-manga.com"
    manga_title = "Kaiju No. 8"
    cover_url = "https://kaijuno8-manga.com/wp-content/uploads/2025/09/Read-Kaiju-No.-8-Manga-Online.webp"
    # Format: /comic/kaiju-no-8-monster-8-chapter-N/
    chapter_link_selector = "a[href*='chapter-']"
    chapter_requires_number = True
    untitled_links = "number"

    def _page_urls(self, soup):
        return self._pick(self._img_srcs(soup.select(_ENTRY_IMAGES), ("data-src", "src")))

    def _is_page_image(self, url):
        lower = url.lower()
        if "logo" in lower or "icon" in lower:
            return False
        return "wp-content" in url or any(ext in lower for ext in _IMAGE_EXTENSIONS)


class DragonBallSuperOnlineScraper(_PlainLinksScraper):
    """Scraper for thedragonballsuper.online - Dragon Ball Super (images in wp-content/uploads)."""

    name = "dragonballsuperonline"
    base_url = "https://thedragonballsuper.online"
    manga_title = "Dragon Ball Super"
    cover_url = "https://thedragonballsuper.online/wp-content/uploads/2024/08/thumb-350-330775.webp"
    chapter_link_selector = "a[href*='dragon-ball-super-manga-chapter-']"

    def _page_urls(self, soup):
        imgs = soup.select("div.reading-content img, div.page-break img, div.entry-content img")
        return self._pick(self._img_srcs(imgs, ("data-src", "data-lazy-src", "src")))

    def _is_page_image(self, url):
        # Skip thumbnail/cover images
        if "thumb" in url.lower():
            return False
        return "wp-content" in url or any(ext in url for ext in _IMAGE_EXTENSIONS)


class DragonBallSuperOrgScraper(_PlainLinksScraper):
    """Scraper for dragonballsuper.org - Dragon Ball Super (images on mangaread.org CDN)."""

    name = "dragonballsuperorg"
    base_url = "https://www.dragonballsuper.org"
    manga_title = "Dragon Ball Super"
    cover_url = ""  # Uses inline images
    chapter_link_selector = "a[href*='dragon-ball-chou-super-chapter-']"
    chapter_number_pattern = r'chapter-(\d+(?:\.\d+|-\d+)?)'
    chapter_number_dash_decimal = True

    def _page_urls(self, soup):
        imgs = soup.select("div.reading-content img, div.page-break img, img.wp-manga-chapter-img")
        return self._pick(self._img_srcs(imgs, ("data-src", "data-lazy-src", "src")))

    def _is_page_image(self, url):
        return ("mangaread.org" in url or "wp-content" in url
                or any(ext in url for ext in _IMAGE_EXTENSIONS))


class OnePieceManga1Scraper(_PlainLinksScraper):
    """Scraper for 1piecemanga.com - One Piece (images on Contabo storage)."""

    name = "onepiecemanga1"
    base_url = "https://w064.1piecemanga.com"
    manga_title = "One Piece"
    cover_url = "https://w064.1piecemanga.com/wp-content/uploads/2024/08/One_Piece_Chapter_1.png"
    chapter_link_selector = "a[href*='one-piece-chapter-']"
    chapter_requires_number = True

    def _page_urls(self, soup):
        return self._pick(self._img_srcs(soup.select(_ENTRY_IMAGES), ("src",)))

    def _is_page_image(self, url):
        lower = url.lower()
        if not ("contabostorage.com" in url or any(ext in lower for ext in _IMAGE_EXTENSIONS)):
            return False
        return not ("wp-includes" in url or "emoji" in lower)


class ReadTokyoRevengersScraper(_PlainLinksScraper):
    """Scraper for read-tokyorevengers.com - Tokyo Revengers (images in wp-content / mangaread.org)."""

    name = "readtokyorevengers"
    base_url = "https://read-tokyorevengers.com"
    manga_title = "Tokyo Revengers"
    cover_url = "https://w5.read-tokyorevengers.com/wp-content/uploads/2023/07/TOKYO-REVENGERS-manga.webp"
    chapter_link_selector = "a[href*='/manga/tokyo-manji-revengers-chapter-']"

    def _page_urls(self, soup):
        attrs = ("src", "data-src", "data-lazy-src")
        return (self._pick(self._img_srcs(soup.select("img.wp-manga-chapter-img"), attrs),
                           lambda url: ("wp-content" in url or "cdn" in url
                                        or any(ext in url for ext in _IMAGE_EXTENSIONS)))
                or self._pick(self._img_srcs(
                    soup.select("div.page-break img, div.reading-content img"), attrs),
                    lambda url: True))


class FairyTailMangaFreeScraper(_PlainLinksScraper):
    """Scraper for fairytailmangafree.com - Fairy Tail: 100 Years Quest (images on cdn.mangaclash.com)."""

    name = "fairytailmangafree"
    base_url = "https://www.fairytailmangafree.com"
    manga_title = "Fairy Tail: 100 Years Quest"
    cover_url = "https://fairytailmangafree.com/wp-content/uploads/2025/09/fairy-tail-cover-1.webp"
    chapter_link_selector = "a[href*='fairy-tail-100-years-quest-chapter-']"

    def _page_urls(self, soup):
        return (self._pick(self._img_srcs(soup.select("img[data-src]"), ("data-src",)),
                           lambda url: "mangaclash" in url and "cover" not in url.lower())
                or self._pick(self._img_srcs(soup.select("div.entry-content img"), ("data-src", "src")),
                              lambda url: any(ext in url for ext in _IMAGE_EXTENSIONS)))


class ReadSlamDunkOnlineScraper(SingleTitleScraper):
    """Scraper for read-slamdunk.online - Slam Dunk (images on cdn.mangaclash.com)."""

    name = "readslamdunkonline"
    base_url = "https://read-slamdunk.online"
    manga_title = "Slam Dunk"
    cover_url = ("https://read-slamdunk.online/wp-content/uploads/2023/03/cropped-339-3392153_"
                 "sakuragi-hanamichi-slam-dunk-removebg-preview-192x192.png")
    # Format: /manga/slam-dunk-chapter-N/
    chapter_link_selector = "a[href*='/manga/slam-dunk-chapter-']"
    chapter_number_lowercase = False

    def _absolute(self, href):
        return self.base_url + href if href.startswith("/") else self.base_url + "/" + href

    def _chapter_title(self, text, number):
        return text if "Chapter" in text else f"Chapter {number}"

    def _page_urls(self, soup):
        imgs = soup.select("img.wp-manga-chapter-img")
        return (self._pick(self._img_srcs(imgs, ("src", "data-src", "data-lazy-src")),
                           lambda url: "mangaclash.com" in url or "cdn." in url)
                or self._pick(self._meta_srcs(soup, ("og:image",)),
                              lambda url: "mangaclash.com" in url))


# ── Every link to a numbered chapter URL, oldest first ──────────────


class BocchiTheRockMangaScraper(NumberedChaptersScraper):
    """Scraper for bocchitherockmanga.com - Bocchi the Rock! (images on cdn.black-clover.org)."""

    name = "bocchitherockmanga"
    base_url = "https://bocchitherockmanga.com"
    chapter_url_base = "https://w5.bocchitherockmanga.com"
    manga_title = "Bocchi the Rock!"
    chapter_href_markers = ("/manga",)
    image_cdn_filters = ("black-clover.org",)


class ElusiveSamuraiScraper(NumberedChaptersScraper):
    """Scraper for elusive-samurai.com - The Elusive Samurai (images on pic.readkakegurui.com)."""

    name = "elusivesamurai"
    base_url = "https://elusive-samurai.com"
    chapter_url_base = "https://w4.elusive-samurai.com"
    manga_title = "The Elusive Samurai"
    image_cdn_filters = ("readkakegurui.com",)


class ReadBlueLockOrgScraper(NumberedChaptersScraper):
    """Scraper for readbluelock.org - Blue Lock (images on images.asuratoon.top)."""

    name = "readbluelockorg"
    base_url = "https://readbluelock.org"
    manga_title = "Blue Lock"
    image_attrs = ("data-src", "src")
    image_cdn_filters = ("asuratoon.top",)


class DrStoneMangaScraper(NumberedChaptersScraper):
    """Scraper for drstonemanga.com - Dr. Stone (images on assets.drstonemanga.com)."""

    name = "drstonemanga"
    base_url = "https://drstonemanga.com"
    manga_title = "Dr. Stone"
    chapter_href_markers = ("/chapter/",)
    chapter_number_pattern = r'/chapter/(\d+)'
    image_cdn_filters = ("assets.drstonemanga.com",)
