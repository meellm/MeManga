"""
Source metadata catalog — the one place source facts are declared.

Facts that belong to a scraper class (how it talks to the site, the
language it serves, adult content) are class attributes on the scraper
itself: ``engine``, ``content_language``, ``nsfw`` (see BaseScraper).
Facts that differ between domains served by the same class (search
skips, curation order, short notes) live here, keyed by domain.

Everything else derives from these declarations: the search sweep's
skip set (memanga.search.BROKEN_SEARCH_SOURCES), source ranking, the
GUI's first-launch defaults, `memanga sources`, and the generated
docs (python -m memanga.source_docs).

Nothing here claims a source works right now. Reachability changes
without notice; the live probes under tests/scrapers/live/ and the
Sources page health check are the place to find that out.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────
# Search skips — registered sources the multi-source sweep never
# probes, so a worker slot doesn't wait out the full timeout. They stay
# registered so saved library entries and pasted URLs still resolve.
# Re-run tests/scrapers/live/ against a candidate domain before
# removing its entry here; that is the supported way to re-enable it.
# ─────────────────────────────────────────────────────────────────────


class SkipReason(str, Enum):
    """Why the search sweep skips a domain."""

    SHUTDOWN = "shutdown"
    UNREACHABLE = "unreachable"
    REPLACED = "replaced"
    UNRELIABLE = "unreliable"
    REGION_BLOCKED = "region-blocked"
    NEEDS_JS = "needs-js"
    CHALLENGE = "challenge"
    ALIAS = "alias"

    @property
    def description(self) -> str:
        return _SKIP_REASON_DESCRIPTIONS[self]


_SKIP_REASON_DESCRIPTIONS = {
    SkipReason.SHUTDOWN: "The site shows a shutdown page.",
    SkipReason.UNREACHABLE: (
        "The domain doesn't resolve, fails TLS, or every request times out."),
    SkipReason.REPLACED: "The domain now forwards to an unrelated site.",
    SkipReason.UNRELIABLE: (
        "Replaced, regionally blocked, or chronically timing out."),
    SkipReason.REGION_BLOCKED: (
        "Blocked on some networks, where requests stall; it may work elsewhere."),
    SkipReason.NEEDS_JS: (
        "Search runs client-side; the plain HTML returns no results."),
    SkipReason.CHALLENGE: (
        "An interactive Cloudflare challenge blocks plain requests."),
    SkipReason.ALIAS: (
        "A retired or redirecting domain of a source that is searched under "
        "its current domain."),
}


@dataclass(frozen=True)
class SearchSkip:
    """Why one domain is left out of the search sweep."""

    reason: SkipReason
    note: str = ""
    issue: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"reason": self.reason.value, "note": self.note,
                "issue": self.issue}


def _skips(reason: SkipReason, note: str, *domains: str,
           issue: Optional[int] = None) -> Dict[str, SearchSkip]:
    skip = SearchSkip(reason, note, issue)
    return {domain: skip for domain in domains}


SEARCH_SKIPS: Dict[str, SearchSkip] = {
    **_skips(SkipReason.SHUTDOWN, "Serves a shutdown image.",
             "mangasee123.com"),
    **_skips(SkipReason.UNREACHABLE, "",
             "mangareader.to", "chapmanganato.to", "readmanganato.com",
             "manganato.com", "mangakakalot.to"),
    **_skips(SkipReason.UNREACHABLE, "Former MangaSee mirror.",
             "manga4life.com", "mangalife.us"),
    **_skips(SkipReason.REPLACED, "Forwards to a gambling page.",
             "mangakakalot.com"),
    **_skips(SkipReason.UNREACHABLE,
             "Fails TLS verification and plain HTTP no longer serves "
             "MangaClash; www. has no DNS. No verified replacement domain.",
             "mangaclash.com", issue=179),
    **_skips(SkipReason.UNRELIABLE, "",
             "mangatown.com", "www.mangatown.com",
             "manhwa18.cc",
             "mangafreak.me", "mangafreak.ws", "ww2.mangafreak.me",
             "bato.to", "batoto.to"),
    **_skips(SkipReason.REGION_BLOCKED,
             "Self-signed certificate and a regional access-block page from "
             "the audit network. No verified replacement domain.",
             "hiperdex.com", issue=180),
    **_skips(SkipReason.REGION_BLOCKED,
             "DNS poisoning and SNI filtering on some networks stall the "
             "sweep. Usable by direct URL where reachable.",
             "mangago.me", "www.mangago.me", issue=151),
    **_skips(SkipReason.ALIAS, "Retired Asura Scans domain.",
             "asuracomic.net", "asuratoon.com", issue=177),
    **_skips(SkipReason.ALIAS, "Redirects to lector-mangas.lat.",
             "lectormangass.net", issue=186),
    **_skips(SkipReason.NEEDS_JS, "",
             "mangabolt.com",
             "truemanga.com", "mangamonk.com",
             "mangahub.us",
             "hivetoons.org", "hivetoon.com",
             "isekaiscan.com",
             "zinmanga.com",
             "kunmanga.com",
             "flamecomics.xyz"),
    **_skips(SkipReason.CHALLENGE, "Even cloudscraper gets a 403.",
             "manhuafast.com", "manhuaus.org"),
    **_skips(SkipReason.CHALLENGE,
             "Its browser scraper times out waiting out the challenge.",
             "manganato.gg"),
    **_skips(SkipReason.CHALLENGE,
             "The site and its search API challenge plain requests, "
             "cloudscraper and headless Firefox; images need a per-session "
             "token.",
             "kagane.org", "www.kagane.org", "kagane.to", issue=182),
}


# ─────────────────────────────────────────────────────────────────────
# Curated ranking. Order is popularity: the search worker submits
# sources in this order so MangaDex, MangaPill etc. start first, and
# results from earlier sources are listed first. Only canonical domains
# belong here; retired aliases stay out so the sweep doesn't probe the
# same scraper twice. Re-order or trim when a live probe says a site
# went stale.
#
# The first DEFAULT_ENABLED_COUNT are ticked on the Sources page of a
# fresh install, so a new user gets results in seconds instead of
# probing 100+ smaller sources. Everything else stays available.
# ─────────────────────────────────────────────────────────────────────


POPULAR_SOURCES: List[str] = [
    "mangadex.org",
    "mangapill.com",
    "mangapark1.com",
    "mangafire.to",
    "mangabuddy.com",
    "weebcentral.com",
    "mangakatana.com",
    "asurascans.com",
    "comix.to",
    "comick.io",
    "mangahub.io",
    "mangahere.cc",
    "mangapanda.onl",
    "mangahere.onl",
    "mangataro.org",
    "luminousscans.com",
    "tcbonepiecechapters.com",
    "fanfox.net",
    "1manga.co",
    "coffeemanga.io",
    "manhuaplus.org",
    "mangaeffect.com",
    "mangafox.fun",
    "mangayy.org",
]

DEFAULT_ENABLED_COUNT = 15
DEFAULT_ENABLED_SOURCES: List[str] = POPULAR_SOURCES[:DEFAULT_ENABLED_COUNT]


# ─────────────────────────────────────────────────────────────────────
# Short descriptions for the docs and `memanga sources`. Template sites
# fall back to the series title in their registry config.
# ─────────────────────────────────────────────────────────────────────


SOURCE_NOTES: Dict[str, str] = {
    # Aggregators
    "mangadex.org": "Largest fan-translation library",
    "mangapill.com": "Fast, no Cloudflare",
    "mangapark1.com": "Large library (Chromium, Cloudflare)",
    "mangafire.to": "VRF-signed API + image descrambling",
    "mangabuddy.com": "Popular aggregator",
    "weebcentral.com": "1000+ series",
    "mangakatana.com": "General library",
    "comix.to": "React SPA aggregator",
    "comick.io": "Clean API",
    "mangahub.io": "Huge library",
    "mangahere.cc": "Large library",
    "mangapanda.onl": "MangaHub network",
    "mangahere.onl": "Alternate mirror",
    "mangataro.org": "ComicK replacement",
    "mangafox.fun": "MangaHub network",
    "mangahub.us": "MangaHub network",
    "1manga.co": "Large library (MangaHub CDN)",
    "bato.to": "Community-driven",
    "mangareader.to": "Clean UI",
    "mangago.me": "Yaoi/Shoujo collection",
    "mangadot.net": "Multi-language aggregator",
    "mangaball.net": "Multi-language",
    "readcomiconline.li": "Western comics",
    "zazamanga.com": "Also serves several redirected series sites",
    "kagane.org": "Token-protected pages",
    # Scan groups and regional sites
    "tcbonepiecechapters.com": "Jump manga (One Piece, JJK)",
    "asurascans.com": "Manhwa specialist",
    "omegascans.org": "Manhwa translations",
    "flamecomics.xyz": "Manhwa translations",
    "luminousscans.com": "Manhwa translations",
    "hivetoons.org": "Void Scans network",
    "olympusxyz.com": "Spanish manhwa scans (Olympus Scanlation)",
    "zonatmo.org": "Spanish manga/manhwa library",
    "lector-mangas.lat": "Spanish manga/manhwa reader",
    "en-thunderscans.com": "English manhwa scans",
    "wurmz.net": "Indonesian manga/manhwa/manhua reader",
    # Focus
    "manytoon.com": "Adult manhwa",
    "toonily.me": "Manhwa focused",
    "isekaiscan.com": "Isekai focused",
    "manhuaplus.org": "Manhua focused",
    "manhuaus.org": "Manhua focused",
    "manhuafast.com": "Manhua focused",
    "manhwatop.com": "Manhwa focused",
    # Adult
    "nhentai.net": "Doujinshi",
    "e-hentai.org": "Galleries",
    "hentaifox.com": "Doujinshi",
    "imhentai.xxx": "Doujinshi",
    "hentairead.com": "Doujinshi",
    "pururin.to": "Doujinshi",
    "manga18fx.com": "Adult manga",
    "manhwa18.cc": "Adult manhwa",
    "hentai20.io": "Adult content",
    # Single-series sites with their own scraper
    "readsnk.com": "Attack on Titan",
    "readsnkmanga.com": "Attack on Titan",
    "readberserk.com": "Berserk",
    "read-berserk-manga.com": "Berserk",
    "berserkmang.org": "Berserk",
    "readhaikyuu.com": "Haikyuu!!",
    "readjujutsukaisen.com": "Jujutsu Kaisen",
    "readjujutsukaisenmanga.com": "Jujutsu Kaisen + Modulo",
    "read-jjk.com": "Jujutsu Kaisen",
    "jjkmanga.net": "Jujutsu Kaisen",
    "readchainsawman.com": "Chainsaw Man",
    "readonepiece.com": "One Piece",
    "onepieceread.com": "One Piece",
    "1piecemanga.com": "One Piece",
    "readnaruto.com": "Naruto",
    "readmha.com": "My Hero Academia",
    "readfairytail.com": "Fairy Tail",
    "fairytailmangafree.com": "Fairy Tail: 100 Years Quest",
    "readblackclover.com": "Black Clover",
    "beastarsmanga.com": "Beastars",
    "vagabondmanga.org": "Vagabond",
    "monstermanga.org": "Monster",
    "death-note-manga.com": "Death Note",
    "tgmanga.com": "Tokyo Ghoul",
    "tokyoghoul.club": "Tokyo Ghoul",
    "readichithewitch.com": "Ichi the Witch",
    "demonslayermanga.com": "Demon Slayer",
    "demon-slayer.online": "Demon Slayer",
    "drstonemanga.com": "Dr. Stone",
    "sakamotomanga.com": "Sakamoto Days",
    "sakamoto-days.online": "Sakamoto Days",
    "elusive-samurai.com": "The Elusive Samurai",
    "readbluelock.org": "Blue Lock",
    "bluelockread.online": "Blue Lock",
    "bluelockmanga.net": "Blue Lock",
    "bluelock-read.com": "Blue Lock",
    "bluelockread.com": "Blue Lock",
    "bocchitherockmanga.com": "Bocchi the Rock!",
    "spyxfamilymanga.org": "Spy x Family",
    "blueexorcistmanga.com": "Blue Exorcist",
    "ajimenoippo.com": "Hajime no Ippo",
    "hajime-no-ippo-manga.online": "Hajime no Ippo",
    "hajimnoippo.com": "Hajime no Ippo",
    "hajime-noippo.com": "Hajime no Ippo",
    "read-slamdunk.online": "Slam Dunk",
    "read-tokyorevengers.com": "Tokyo Revengers",
    "thedragonballsuper.online": "Dragon Ball Super",
    "dragonballsuper.org": "Dragon Ball Super",
    "jojolionmanga.com": "JoJo Part 8: JoJolion",
    "homunculusmanga.com": "Homunculus",
    "sousou-no-frieren.com": "Frieren",
    "readkingdomfree.com": "Kingdom",
    "kaijuno8-manga.com": "Kaiju No. 8",
    "fireforcemanga.org": "Fire Force",
    "read-kengan-ashura.com": "Kengan Ashura",
    "kenganashura.com": "Kengan Ashura / Omega",
    "readoshinoko.com": "Oshi no Ko",
    "oyasumipunpun.com": "Goodnight Punpun",
    "onepunchmanmangaa.com": "One Punch Man",
    "readopm.com": "One Punch Man",
    "onepunchmanread.com": "One Punch Man",
    "one-punch.online": "One Punch Man",
    "mashle-manga.online": "Mashle",
    "bakirahen.com": "Baki Rahen",
    "blame-manga.com": "BLAME!",
}


# ─────────────────────────────────────────────────────────────────────
# Derived catalog
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceInfo:
    """Everything the catalog knows about one scraper's source.

    One row per scraper: ``domain`` is the canonical domain and
    ``aliases`` the other domains the same scraper serves.
    """

    domain: str
    aliases: Tuple[str, ...]
    scraper: str
    engine: str
    template: Optional[str]
    language: Optional[str]
    nsfw: bool
    note: str
    popularity: Optional[int]
    default_enabled: bool
    search_skip: Optional[SearchSkip]

    @property
    def searchable(self) -> bool:
        """Whether the default search sweep probes this source.

        Template sites are never swept (their search() only matches
        their own series), and a skipped source is left out unless one
        of its domains is still searchable.
        """
        return self.template is None and self.search_skip is None

    @staticmethod
    def _status_label(template: Optional[str], skip: Optional[SearchSkip]) -> str:
        if template:
            return "Not searched (template)"
        if skip:
            return f"Not searched ({skip.reason.value})"
        return "Included in search"

    @property
    def search_status(self) -> str:
        """Human-readable search status shared by CLI and generated docs."""
        return self._status_label(self.template, self.search_skip)

    @property
    def domain_search_skips(self) -> Dict[str, SearchSkip]:
        """Structured skip data for each registered domain, including aliases."""
        return {
            candidate: SEARCH_SKIPS[candidate]
            for domain in (self.domain,) + self.aliases
            for candidate in (domain, "www." + domain)
            if candidate in SEARCH_SKIPS
        }

    def search_status_for(self, domain: str) -> str:
        """Status of a canonical domain or alias in the default sweep."""
        if domain == self.domain:
            return self.search_status
        if domain not in self.aliases:
            raise ValueError(f"Domain is not part of this source: {domain}")
        return self._status_label(self.template,
                                  self.domain_search_skips.get(domain))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "aliases": list(self.aliases),
            "scraper": self.scraper,
            "engine": self.engine,
            "template": self.template,
            "language": self.language,
            "nsfw": self.nsfw,
            "note": self.note,
            "popularity": self.popularity,
            "default_enabled": self.default_enabled,
            "searchable": self.searchable,
            "search_status": self.search_status,
            "search_skip": (self.search_skip.to_dict()
                            if self.search_skip else None),
            "domain_search_skips": {
                domain: skip.to_dict()
                for domain, skip in self.domain_search_skips.items()
            },
        }


def _base(domain: str) -> str:
    return domain[4:] if domain.startswith("www.") else domain


def _series_title(cls) -> str:
    return (getattr(cls, "MANGA_TITLE", "")
            or getattr(cls, "manga_title", "") or "")


def source_catalog() -> List[SourceInfo]:
    """Build one SourceInfo per registered scraper.

    Derived from the live ``SCRAPERS`` mapping, so it always matches
    what get_scraper() resolves. Sorted like the search sweep: curated
    sources in popularity order, then alphabetical.
    """
    from . import SCRAPERS
    from .registry import TEMPLATE_SCRAPERS

    rank = {d: i for i, d in enumerate(POPULAR_SOURCES)}
    default_enabled = set(DEFAULT_ENABLED_SOURCES)

    # Group domains by the class get_scraper() resolves them to. A bare
    # domain wins over its www. form, as in get_scraper().
    raw_by_class: Dict[type, List[str]] = {}
    bases_by_class: Dict[type, List[str]] = {}
    seen = set()
    for raw, cls in SCRAPERS.items():
        raw_by_class.setdefault(cls, []).append(raw)
        base = _base(raw)
        if base in seen:
            continue
        seen.add(base)
        owner = SCRAPERS.get(base, cls)
        bases_by_class.setdefault(owner, []).append(base)

    rows = []
    for cls, bases in bases_by_class.items():
        ranked = [d for d in bases if d in rank]
        canonical = min(ranked, key=rank.__getitem__) if ranked else bases[0]
        aliases = tuple(d for d in bases if d != canonical)

        raws = raw_by_class.get(cls, [])
        if any(d not in SEARCH_SKIPS for d in raws):
            skip = None
        else:
            skip = (SEARCH_SKIPS.get(canonical)
                    or SEARCH_SKIPS.get("www." + canonical)
                    or SEARCH_SKIPS[raws[0]])

        template = None
        if canonical in TEMPLATE_SCRAPERS or "www." + canonical in TEMPLATE_SCRAPERS:
            entry = (TEMPLATE_SCRAPERS.get(canonical)
                     or TEMPLATE_SCRAPERS["www." + canonical])
            template = entry[0].__name__

        note = next((SOURCE_NOTES[d] for d in (canonical,) + aliases
                     if d in SOURCE_NOTES), "") or _series_title(cls)

        rows.append(SourceInfo(
            domain=canonical,
            aliases=aliases,
            scraper=cls.__name__,
            engine=getattr(cls, "engine", "http"),
            template=template,
            language=getattr(cls, "content_language", None),
            nsfw=bool(getattr(cls, "nsfw", False)),
            note=note,
            popularity=rank.get(canonical),
            default_enabled=canonical in default_enabled,
            search_skip=skip,
        ))

    rows.sort(key=lambda r: (999 if r.popularity is None else r.popularity,
                             r.domain))
    return rows
