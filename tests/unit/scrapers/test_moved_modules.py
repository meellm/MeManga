"""Scraper modules folded into shared ones keep their import paths (#251).

A hand-written module that became a class in a shared module (or a
subclass of its identical twin) still imports under its old name, with
a DeprecationWarning, and gives back the very class the registry uses.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys

import pytest

import memanga.scrapers as pkg
from memanga.scrapers import SCRAPERS


# old module -> (class name, a domain it serves)
MOVED = {
    "beastarsmanga": ("BeastarsMangaScraper", "beastarsmanga.com"),
    "monstermanga": ("MonsterMangaScraper", "monstermanga.org"),
    "readichithewitch": ("ReadIchiTheWitchScraper", "readichithewitch.com"),
    "ajimenoippo": ("AjimeNoIppoScraper", "ajimenoippo.com"),
    "hajimenoippoonline": ("HajimeNoIppoOnlineScraper", "hajime-no-ippo-manga.online"),
    "hajimnoippo": ("HajimNoIppoScraper", "hajimnoippo.com"),
    "hajimenoippoblogger": ("HajimeNoIppoBloggerScraper", "hajime-noippo.com"),
    "bluelockreadonline": ("BlueLockReadOnlineScraper", "bluelockread.online"),
    "vagabondmanga": ("VagabondMangaScraper", "vagabondmanga.org"),
    "sousnofrierenga": ("SousouNoFrierenScraper", "sousou-no-frieren.com"),
    "spyxfamilymanga": ("SpyXFamilyMangaScraper", "spyxfamilymanga.org"),
    "tgmanga": ("TGMangaScraper", "tgmanga.com"),
    "blueexorcistmanga": ("BlueExorcistMangaScraper", "blueexorcistmanga.com"),
    "blamemanga": ("BlameMangaScraper", "blame-manga.com"),
    "homunculusmanga": ("HomunculusMangaScraper", "homunculusmanga.com"),
    "fireforcemangaorg": ("FireForceMangaOrgScraper", "fireforcemanga.org"),
    "tokyoghoulclub": ("TokyoGhoulClubScraper", "tokyoghoul.club"),
    "deathnotemanga": ("DeathNoteMangaScraper", "death-note-manga.com"),
    "bluelockmangaorg": ("BlueLockMangaNetScraper", "bluelockmanga.net"),
    "kaijuno8manga": ("KaijuNo8MangaScraper", "kaijuno8-manga.com"),
    "dragonballsuperonline": ("DragonBallSuperOnlineScraper", "thedragonballsuper.online"),
    "dragonballsuperorg": ("DragonBallSuperOrgScraper", "dragonballsuper.org"),
    "onepiecemanga1": ("OnePieceManga1Scraper", "1piecemanga.com"),
    "readslamdunkonline": ("ReadSlamDunkOnlineScraper", "read-slamdunk.online"),
    "readtokyorevengers": ("ReadTokyoRevengersScraper", "read-tokyorevengers.com"),
    "fairytailmangafree": ("FairyTailMangaFreeScraper", "fairytailmangafree.com"),
    "readkenganashura": ("ReadKenganAshuraScraper", "read-kengan-ashura.com"),
    "bocchitherockmanga": ("BocchiTheRockMangaScraper", "bocchitherockmanga.com"),
    "elusivesamurai": ("ElusiveSamuraiScraper", "elusive-samurai.com"),
    "readbluelockorg": ("ReadBlueLockOrgScraper", "readbluelock.org"),
    "drstonemanga": ("DrStoneMangaScraper", "drstonemanga.com"),
    "mangaclash": ("MangaClashScraper", "mangaclash.com"),
    "mangaeffect": ("MangaReadScraper", "mangaeffect.com"),
    "mangafoxfun": ("MangaFoxFunScraper", "mangafox.fun"),
}


def test_table_matches_the_package():
    assert set(MOVED) == set(pkg._MOVED_MODULES)


def test_moved_modules_are_gone_from_disk():
    on_disk = {name for _, name, _ in pkgutil.iter_modules(pkg.__path__)}
    assert not on_disk & set(MOVED)
    assert set(pkg._MOVED_MODULES.values()) <= on_disk


@pytest.mark.parametrize("old", sorted(MOVED))
def test_old_import_path_gives_the_registry_class(old, monkeypatch):
    cls_name, domain = MOVED[old]
    fullname = f"memanga.scrapers.{old}"
    monkeypatch.delitem(sys.modules, fullname, raising=False)
    with pytest.deprecated_call(match=fullname):
        module = importlib.import_module(fullname)
    assert getattr(module, cls_name) is SCRAPERS[domain]
    new = f"memanga.scrapers.{pkg._MOVED_MODULES[old]}"
    assert SCRAPERS[domain].__module__ == new


def test_from_import_form(monkeypatch):
    monkeypatch.delitem(sys.modules, "memanga.scrapers.tgmanga", raising=False)
    with pytest.deprecated_call():
        from memanga.scrapers.tgmanga import TGMangaScraper
    assert TGMangaScraper is SCRAPERS["tgmanga.com"]


def test_unknown_module_still_fails():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("memanga.scrapers.nosuchscraper")


# ──────────────────────────────────────────────────────────────────────
# Identical twins: one site's scraper is a subclass of the other's
# ──────────────────────────────────────────────────────────────────────


TWINS = [
    # (domain, class, name, base_url, twin domain)
    ("mangaclash.com", "MangaClashScraper", "mangaclash", "https://mangaclash.com",
     "kunmanga.com"),
    ("mangaeffect.com", "MangaReadScraper", "mangaread", "https://www.mangaread.org",
     "coffeemanga.io"),
    ("mangafox.fun", "MangaFoxFunScraper", "mangafoxfun", "https://mangafox.fun",
     "mangapanda.onl"),
]


@pytest.mark.parametrize("domain,cls_name,name,base_url,twin", TWINS,
                         ids=[t[0] for t in TWINS])
def test_twin_keeps_its_identity(domain, cls_name, name, base_url, twin):
    cls = SCRAPERS[domain]
    assert cls.__name__ == cls_name
    assert cls.__bases__ == (SCRAPERS[twin],)
    assert cls.name == name
    assert cls.base_url == base_url
    # Every method is inherited unchanged from the twin
    assert not any(inspect.isfunction(v) for v in vars(cls).values())


def test_playwright_twin_has_its_own_browser_worker():
    clash, kun = SCRAPERS["mangaclash.com"], SCRAPERS["kunmanga.com"]
    assert "_worker" in vars(clash)
    assert clash._worker is not kun._worker


@pytest.mark.parametrize("domain", [t[0] for t in TWINS])
def test_twins_keep_separate_catalog_rows(domain):
    from memanga.scrapers.catalog import source_catalog
    rows = {r.domain: r for r in source_catalog()}
    assert rows[domain].scraper == SCRAPERS[domain].__name__
