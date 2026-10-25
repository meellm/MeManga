"""Source metadata contracts shared by search, CLI, GUI and docs."""

from memanga.scrapers import (DEFAULT_ENABLED_SOURCES, POPULAR_SOURCES,
                              SCRAPERS, list_supported_sources)
from memanga.scrapers.catalog import SEARCH_SKIPS, source_catalog
from memanga.search import BROKEN_SEARCH_SOURCES


def test_search_skips_preserve_legacy_set_and_registered_domains():
    legacy = {
        "mangasee123.com", "mangareader.to", "chapmanganato.to",
        "readmanganato.com", "manganato.com", "mangakakalot.com",
        "mangakakalot.to", "manga4life.com", "mangalife.us",
        "mangaclash.com", "mangatown.com", "www.mangatown.com",
        "manhwa18.cc", "mangafreak.me", "mangafreak.ws",
        "ww2.mangafreak.me", "bato.to", "batoto.to", "hiperdex.com",
        "mangago.me", "www.mangago.me", "asuracomic.net",
        "asuratoon.com", "lectormangass.net", "mangabolt.com",
        "truemanga.com", "mangamonk.com", "mangahub.us",
        "hivetoons.org", "hivetoon.com", "isekaiscan.com",
        "zinmanga.com", "kunmanga.com", "flamecomics.xyz",
        "manhuafast.com", "manhuaus.org", "manganato.gg",
        "kagane.org", "www.kagane.org", "kagane.to",
    }
    assert BROKEN_SEARCH_SOURCES == set(SEARCH_SKIPS)
    assert BROKEN_SEARCH_SOURCES == legacy
    assert BROKEN_SEARCH_SOURCES <= set(SCRAPERS)
    assert SEARCH_SKIPS["asuracomic.net"].reason.value == "alias"
    assert SEARCH_SKIPS["mangago.me"].reason.value == "region-blocked"


def test_popularity_and_defaults_are_registered_and_ordered():
    assert len(POPULAR_SOURCES) == len(set(POPULAR_SOURCES))
    assert set(POPULAR_SOURCES) <= set(SCRAPERS)
    assert DEFAULT_ENABLED_SOURCES == POPULAR_SOURCES[:15]
    assert not set(POPULAR_SOURCES) & set(SEARCH_SKIPS)


def test_catalog_covers_supported_domains_once():
    rows = source_catalog()
    domains = [domain for row in rows for domain in (row.domain, *row.aliases)]
    assert len(domains) == len(set(domains))
    assert set(domains) == set(list_supported_sources())
    assert rows[0].domain == "mangadex.org"


def test_declared_metadata_is_exposed():
    rows = {row.domain: row for row in source_catalog()}
    assert rows["mangadex.org"].engine == "api"
    assert rows["nhentai.net"].nsfw
    assert rows["mangadex.org"].default_enabled
    assert not rows["mangadex.org"].search_skip
    assert (rows["asurascans.com"].to_dict()["domain_search_skips"]
            ["asuracomic.net"]["reason"] == "alias")
