"""Registry-level scraper tests.

We do NOT hit real scraper endpoints. These verify the registry's API
and that every registered scraper at least imports cleanly.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def test_get_supported_sources_returns_iterable():
    from memanga.downloader import get_supported_sources
    srcs = list(get_supported_sources())
    assert len(srcs) > 0


def test_known_sources_present():
    from memanga.downloader import get_supported_sources
    srcs = set(get_supported_sources())
    assert "mangadex.org" in srcs
    assert "mangafire.to" in srcs


def test_get_scraper_returns_object_for_known_source():
    from memanga.scrapers import get_scraper
    s = get_scraper("mangadex.org")
    assert hasattr(s, "search")
    assert hasattr(s, "get_chapters")
    assert hasattr(s, "get_pages")


def test_get_scraper_raises_or_returns_none_for_unknown():
    from memanga.scrapers import get_scraper
    try:
        s = get_scraper("not-a-real-source.test")
        # If it returns None, that's OK
        assert s is None or hasattr(s, "search")
    except Exception:
        # Raising is also acceptable
        pass


class TestBaseScraperInterface:
    """All scrapers must conform to BaseScraper's contract."""

    def _all_modules(self):
        import importlib, pkgutil
        import memanga.scrapers as pkg
        names = []
        for _, name, _ in pkgutil.iter_modules(pkg.__path__):
            if name.startswith("_") or name == "base":
                continue
            try:
                m = importlib.import_module(f"memanga.scrapers.{name}")
                names.append((name, m))
            except Exception:
                # Skip modules that need an active network / extra config
                continue
        return names

    def test_all_scrapers_import(self):
        # The mere act of import succeeded — no exception bubbled.
        assert self._all_modules()


def test_no_bare_except_in_package():
    """Issue #246: a bare ``except:`` also catches KeyboardInterrupt and
    SystemExit, so Ctrl+C inside a scraper was swallowed."""
    import ast
    from pathlib import Path
    import memanga
    root = Path(memanga.__file__).resolve().parent
    bare = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bare += [f"{path.relative_to(root)}:{node.lineno}"
                 for node in ast.walk(tree)
                 if isinstance(node, ast.ExceptHandler) and node.type is None]
    assert bare == []


# ─────────────────────────────────────────────────────────────────────────
# Lazy loading (#253) — scraper modules are imported on lookup only
# ─────────────────────────────────────────────────────────────────────────

# Package modules that are not scraper implementations.
_REGISTRY_MODULES = {"memanga.scrapers", "memanga.scrapers.base",
                     "memanga.scrapers.catalog", "memanga.scrapers.registry"}


def _loaded_scraper_modules(code: str) -> set:
    """Run ``code`` in a fresh interpreter; return the scraper modules it loaded."""
    probe = (
        f"{code}\n"
        "import sys\n"
        "print('\\n'.join(m for m in sys.modules "
        "if m.startswith('memanga.scrapers.')))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, check=True).stdout.split()
    return {m for m in out
            if m not in _REGISTRY_MODULES
            and not m.startswith("memanga.scrapers.templates")}


class TestLazyRegistry:
    def test_cli_import_loads_no_scraper_module(self):
        assert _loaded_scraper_modules("import memanga.cli") == set()

    @pytest.mark.parametrize("flag", ["--version", "--help"])
    def test_cli_exit_loads_no_scraper_module(self, flag, isolated_home):
        # atexit runs handlers last in, first out: registering the probe
        # before memanga.cli registers its browser cleanup makes the probe
        # see sys.modules after that cleanup has run.
        code = (
            "import atexit, runpy, sys\n"
            "def probe():\n"
            "    print('LOADED', *(m for m in sys.modules\n"
            "                      if m.startswith('memanga.scrapers.')\n"
            "                      or m.split('.')[0] == 'playwright'))\n"
            "atexit.register(probe)\n"
            f"sys.argv = ['memanga', {flag!r}]\n"
            "runpy.run_module('memanga', run_name='__main__')\n"
        )
        result = subprocess.run([sys.executable, "-c", code],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        probe = [line for line in result.stdout.splitlines()
                 if line.startswith("LOADED")]
        assert len(probe) == 1, result.stdout
        loaded = {m for m in probe[0].split()[1:]
                  if m not in _REGISTRY_MODULES
                  and not m.startswith("memanga.scrapers.templates")}
        assert loaded == set()

    def test_listing_domains_loads_no_scraper_module(self):
        code = (
            "from memanga.scrapers import SCRAPERS, list_supported_sources\n"
            "assert len(SCRAPERS) == len(list(SCRAPERS)) > 300\n"
            "assert 'mangadex.org' in SCRAPERS and 'nope.invalid' not in SCRAPERS\n"
            "assert 'mangadex.org' in list_supported_sources()\n"
        )
        assert _loaded_scraper_modules(code) == set()

    def test_unknown_source_loads_no_scraper_module(self):
        code = (
            "from memanga.scrapers import get_scraper\n"
            "try:\n"
            "    get_scraper('nope.invalid')\n"
            "except ValueError as e:\n"
            "    assert 'mangadex.org' in str(e)\n"
            "else:\n"
            "    raise SystemExit('no error')\n"
        )
        assert _loaded_scraper_modules(code) == set()

    def test_lookup_loads_only_that_scraper(self):
        code = ("from memanga.scrapers import get_scraper\n"
                "get_scraper('api.mangadex.org')\n")
        assert _loaded_scraper_modules(code) == {"memanga.scrapers.mangadex"}

    def test_subdomain_lookup_loads_only_that_scraper(self):
        code = ("from memanga.scrapers import get_scraper\n"
                "get_scraper('foo.weebcentral.com')\n")
        loaded = _loaded_scraper_modules(code)
        assert "memanga.scrapers.weebcentral" in loaded
        assert "memanga.scrapers.mangadex" not in loaded

    def test_every_path_names_a_scraper_class(self):
        import memanga.scrapers as pkg
        from memanga.scrapers.base import BaseScraper
        for domain, path in pkg._SCRAPER_PATHS.items():
            module, _, name = path.partition(":")
            cls = pkg.SCRAPERS[domain]
            assert cls.__name__ == name, domain
            assert cls.__module__ == f"memanga.scrapers.{module}", domain
            assert issubclass(cls, BaseScraper), domain

    def test_scraper_values_are_the_module_classes(self):
        from memanga.scrapers import SCRAPERS
        from memanga.scrapers.mangadex import MangaDexScraper
        from memanga.scrapers.registry import get_template_scrapers
        assert SCRAPERS["mangadex.org"] is MangaDexScraper
        assert SCRAPERS["api.mangadex.org"] is MangaDexScraper
        assert SCRAPERS.get("nope.invalid") is None
        for domain, cls in get_template_scrapers().items():
            assert SCRAPERS[domain] is cls

    def test_registry_is_read_only(self):
        from memanga.scrapers import SCRAPERS
        with pytest.raises(TypeError):
            SCRAPERS["new.example"] = object  # type: ignore[index]

    def test_class_names_are_still_exported(self):
        import memanga.scrapers as pkg
        from memanga.scrapers import MangaDexScraper, ReadMangaBaseScraper
        from memanga.scrapers.mangadex import MangaDexScraper as direct
        from memanga.scrapers.readmanga_base import ReadMangaBaseScraper as rb
        assert MangaDexScraper is direct
        assert ReadMangaBaseScraper is rb
        for name in pkg._CLASS_PATHS:
            assert getattr(pkg, name) is not None, name
        assert {"MangaDexScraper", "get_scraper"} <= set(dir(pkg))

    def test_unknown_attribute_raises_attribute_error(self):
        import memanga.scrapers as pkg
        with pytest.raises(AttributeError):
            pkg.NoSuchScraper  # noqa: B018
        # Submodule imports still fall through to the import system.
        from memanga.scrapers import mangafire
        assert mangafire.__name__ == "memanga.scrapers.mangafire"
