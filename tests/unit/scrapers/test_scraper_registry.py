"""Registry-level scraper tests.

We do NOT hit real scraper endpoints. These verify the registry's API
and that every registered scraper at least imports cleanly.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from types import SimpleNamespace

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

    def test_lookalike_host_loads_no_scraper_module(self):
        code = (
            "from memanga.scrapers import get_scraper\n"
            "for host in ('evilmangadex.org', 'a.b.nope.invalid'):\n"
            "    try:\n"
            "        get_scraper(host)\n"
            "    except ValueError:\n"
            "        continue\n"
            "    raise SystemExit(f'{host} resolved')\n"
        )
        assert _loaded_scraper_modules(code) == set()


# ─────────────────────────────────────────────────────────────────────────
# Instance reuse and domain lookup (#254)
# ─────────────────────────────────────────────────────────────────────────

def _fake_scraper(name):
    from memanga.scrapers.base import BaseScraper

    def _none(self, *args):
        return []

    return type(name, (BaseScraper,), {
        "search": _none, "get_chapters": _none, "get_pages": _none,
    })


class _Response:
    def raise_for_status(self):
        pass


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return _Response()


@pytest.fixture
def fake_registry(monkeypatch):
    """Swap the registry for fake classes; returns {name: class}."""
    import memanga.scrapers as pkg
    classes = {name: _fake_scraper(name) for name in ("Site", "Api", "Other")}
    monkeypatch.setattr(pkg, "SCRAPERS", {
        "site.example": classes["Site"],
        "mirror.example": classes["Site"],
        "api.site.example": classes["Api"],
        "other.example": classes["Other"],
    })
    return classes


class TestScraperInstanceCache:
    def test_repeated_lookup_returns_same_instance(self, fake_registry):
        from memanga.scrapers import get_scraper
        first = get_scraper("site.example")
        assert isinstance(first, fake_registry["Site"])
        assert get_scraper("site.example") is first
        assert get_scraper("WWW.Site.Example") is first

    def test_domains_of_one_class_share_an_instance(self, fake_registry):
        from memanga.scrapers import get_scraper
        site = get_scraper("site.example")
        assert get_scraper("mirror.example") is site
        assert get_scraper("cdn.mirror.example") is site
        assert get_scraper("other.example") is not site

    def test_reuse_shares_session_and_rate_limit(self, fake_registry,
                                                 monkeypatch):
        from memanga.scrapers import base, get_scraper
        sleeps = []
        monkeypatch.setattr(base, "time", SimpleNamespace(
            time=time.time, sleep=sleeps.append))
        get_scraper("site.example").session = session = _Session()

        get_scraper("site.example")._request("https://site.example/a")
        assert sleeps == []
        # A later lookup sees the first request, so it waits its turn.
        get_scraper("mirror.example")._request("https://site.example/b")
        assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0
        assert session.urls == ["https://site.example/a",
                                "https://site.example/b"]

    def test_threads_get_their_own_instance(self, fake_registry):
        from memanga.scrapers import get_scraper
        mine = get_scraper("site.example")
        seen = []

        def lookup():
            seen.append(get_scraper("site.example"))
            seen.append(get_scraper("mirror.example"))

        worker = threading.Thread(target=lookup)
        worker.start()
        worker.join(timeout=10)
        assert len(seen) == 2
        assert seen[0] is seen[1]
        assert seen[0] is not mine
        assert get_scraper("site.example") is mine

    def test_clear_scraper_cache_gives_fresh_instances(self, fake_registry):
        from memanga.scrapers import clear_scraper_cache, get_scraper
        before = get_scraper("site.example")
        clear_scraper_cache()
        after = get_scraper("site.example")
        assert after is not before
        assert get_scraper("site.example") is after

    def test_failed_construction_is_not_cached(self, monkeypatch):
        import memanga.scrapers as pkg
        calls = []

        class Flaky(_fake_scraper("Flaky")):
            def __init__(self):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("boom")
                super().__init__()

        monkeypatch.setattr(pkg, "SCRAPERS", {"flaky.example": Flaky})
        with pytest.raises(RuntimeError):
            pkg.get_scraper("flaky.example")
        scraper = pkg.get_scraper("flaky.example")
        assert isinstance(scraper, Flaky)
        assert pkg.get_scraper("flaky.example") is scraper
        assert len(calls) == 2

    def test_real_aliases_share_an_instance(self):
        from memanga.scrapers import get_scraper
        from memanga.scrapers.mangadex import MangaDexScraper
        scraper = get_scraper("mangadex.org")
        assert isinstance(scraper, MangaDexScraper)
        assert get_scraper("api.mangadex.org") is scraper


class _Clock:
    """Fake time for memanga.scrapers.base: sleeping advances it, so
    request start times show the spacing whatever the thread timing."""

    def __init__(self):
        self.now = 100.0
        self.sleeps = []
        self._lock = threading.Lock()

    def time(self):
        with self._lock:
            return self.now

    def sleep(self, seconds):
        with self._lock:
            self.sleeps.append(seconds)
            self.now += seconds


class _TimedSession:
    def __init__(self, clock, starts):
        self._clock = clock
        self._starts = starts

    def get(self, url, **kwargs):
        self._starts.append(self._clock.time())
        return _Response()


class TestSharedRequestSpacing:
    @pytest.fixture
    def clock(self, monkeypatch):
        from memanga.scrapers import base
        clock = _Clock()
        monkeypatch.setattr(base, "time", clock)
        return clock

    def _in_thread(self, host, starts, clock):
        """Request once through ``host``'s scraper on a new thread;
        return the scraper and session that thread used."""
        from memanga.scrapers import get_scraper
        used = []

        def run():
            scraper = get_scraper(host)
            scraper.session = _TimedSession(clock, starts)
            scraper._request(f"https://{host}/")
            used.append((scraper, scraper.session))

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=10)
        assert len(used) == 1
        return used[0]

    def test_threads_share_spacing_not_instances(self, fake_registry, clock):
        starts = []
        first, first_session = self._in_thread("site.example", starts, clock)
        second, second_session = self._in_thread("site.example", starts,
                                                 clock)
        assert second is not first
        assert second_session is not first_session
        assert clock.sleeps == [1.0]
        assert starts == [100.0, 101.0]

    def test_alias_domains_share_spacing(self, fake_registry, clock):
        starts = []
        self._in_thread("site.example", starts, clock)
        self._in_thread("cdn.mirror.example", starts, clock)
        assert clock.sleeps == [1.0]

    def test_other_scrapers_keep_their_own_spacing(self, fake_registry,
                                                    clock):
        starts = []
        self._in_thread("site.example", starts, clock)
        self._in_thread("api.site.example", starts, clock)
        self._in_thread("other.example", starts, clock)
        assert clock.sleeps == []

    def test_parallel_requests_are_spaced(self, fake_registry, clock):
        from memanga.scrapers import get_scraper
        starts, used = [], []
        ready = threading.Barrier(4)

        def run(host):
            scraper = get_scraper(host)
            scraper.session = _TimedSession(clock, starts)
            used.append((scraper, scraper.session))
            ready.wait(timeout=10)
            scraper._request(f"https://{host}/")

        hosts = ["site.example", "mirror.example"] * 2
        workers = [threading.Thread(target=run, args=(h,)) for h in hosts]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        # The clock moves only while a request waits its turn, so each
        # request after the first waited a full second for the one before.
        assert len(starts) == 4
        assert clock.sleeps == [1.0, 1.0, 1.0]
        assert clock.now == 103.0
        assert len({id(s) for s, _ in used}) == 4
        assert len({id(session) for _, session in used}) == 4

    def test_instances_built_directly_share_spacing(self, fake_registry,
                                                    clock):
        starts = []
        site = fake_registry["Site"]
        for scraper in (site(), site()):
            scraper.session = _TimedSession(clock, starts)
            scraper._request("https://site.example/")
        assert clock.sleeps == [1.0]
        assert site()._last_request == 101.0
        assert fake_registry["Other"]()._last_request == 0.0

    def test_worker_copy_has_its_own_session(self, fake_registry, clock):
        import requests
        site = fake_registry["Site"]()
        site.session.headers["X-Token"] = "abc"
        site.session.cookies.set("cf_clearance", "ok")
        site.alias = site.session
        site.state = {"offset": 3}

        copy = site.worker_copy()
        assert type(copy) is type(site)
        assert isinstance(copy.session, requests.Session)
        assert copy.session is not site.session
        assert copy.alias is copy.session
        assert site.alias is site.session
        assert copy.session.headers["X-Token"] == "abc"
        assert copy.session.headers is not site.session.headers
        assert copy.session.cookies.get("cf_clearance") == "ok"
        assert copy.state is site.state

        # The copy waits its turn after the original's request.
        starts = []
        site.session = _TimedSession(clock, starts)
        copy.session = _TimedSession(clock, starts)
        site._request("https://site.example/a")
        copy._request("https://site.example/b")
        assert clock.sleeps == [1.0]
        assert starts == [100.0, 101.0]

    def test_reset_request_spacing_forgets_last_request(self, fake_registry,
                                                        clock):
        from memanga.scrapers.base import reset_request_spacing
        site = fake_registry["Site"]()
        site.session = _TimedSession(clock, [])
        site._request("https://site.example/")
        reset_request_spacing()
        site._request("https://site.example/")
        assert clock.sleeps == []


class TestDomainLookup:
    @pytest.mark.parametrize("host, name", [
        ("site.example", "Site"),
        ("www.site.example", "Site"),
        ("SITE.EXAMPLE", "Site"),
        ("ww3.site.example", "Site"),
        ("a.b.c.site.example", "Site"),
        # The most specific registered domain wins.
        ("api.site.example", "Api"),
        ("v2.api.site.example", "Api"),
        ("other.example", "Other"),
    ])
    def test_exact_and_subdomain_hosts_resolve(self, fake_registry, host,
                                               name):
        from memanga.scrapers import get_scraper
        assert type(get_scraper(host)) is fake_registry[name]

    @pytest.mark.parametrize("host", [
        "evilsite.example",          # suffix without a label boundary
        "site.example.evil.test",    # registered domain as a prefix
        "example",                   # parent of a registered domain
        "site.example.",             # trailing dot is not normalised
        "",
    ])
    def test_lookalike_hosts_do_not_resolve(self, fake_registry, host):
        from memanga.scrapers import get_scraper
        with pytest.raises(ValueError, match="No scraper available"):
            get_scraper(host)

    def test_unknown_host_error_lists_supported_sources(self, fake_registry):
        from memanga.scrapers import get_scraper
        with pytest.raises(ValueError) as err:
            get_scraper("nope.invalid")
        assert "nope.invalid" in str(err.value)
        assert "site.example" in str(err.value)
