"""Issue #337 — the MangaDex cover lookup contacts MangaDex, so it must
respect the user's choice: never while mangadex.org is turned off in
Sources, and never with ``gui.mangadex_cover_fallback`` off. Covers
every entry point: startup backfill, broken-cover repair, Add Manga and
the Detail refresh after a rename.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest


_FALLBACK_URL = "https://uploads.mangadex.org/covers/abc/def.512.jpg"
_SOURCE_COVER = "https://cdn.mangapill.test/cover.jpg"
_DEAD_URL = "https://cover-host.invalid/broken.jpg"


def _block_mangadex(config, how):
    if how == "source_disabled":
        config.set("sources.disabled", ["mangadex.org", "other.test"])
    else:
        config.set("gui.mangadex_cover_fallback", False)


@pytest.fixture
def lookups(monkeypatch):
    """Record MangaDex lookups instead of making them."""
    import memanga.gui.cover_fallback as cf
    calls = []
    monkeypatch.setattr(cf, "fetch_mangadex_cover",
                        lambda title: calls.append(title) or _FALLBACK_URL)
    return calls


@pytest.fixture
def scraper(monkeypatch):
    """A source scraper whose cover lookup returns ``cover``."""
    stub = SimpleNamespace(cover=None, calls=[])

    def get_cover_url(url):
        stub.calls.append(url)
        return stub.cover

    monkeypatch.setattr("memanga.scrapers.get_scraper",
                        lambda domain: SimpleNamespace(get_cover_url=get_cover_url))
    return stub


class _SyncThread:
    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self):
        self._target()


# ─────────────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────────────


class TestFallbackAllowed:
    def test_default_allows(self, config):
        from memanga.gui.cover_fallback import mangadex_fallback_allowed
        assert mangadex_fallback_allowed(config) is True

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_blocked(self, config, how):
        from memanga.gui.cover_fallback import mangadex_fallback_allowed
        _block_mangadex(config, how)
        assert mangadex_fallback_allowed(config) is False

    def test_other_disabled_sources_do_not_block(self, config):
        from memanga.gui.cover_fallback import mangadex_fallback_allowed
        config.set("sources.disabled", ["mangapill.com"])
        assert mangadex_fallback_allowed(config) is True

    def test_no_config_blocks(self):
        from memanga.gui.cover_fallback import mangadex_fallback_allowed
        assert mangadex_fallback_allowed(None) is False


class TestFindCover:
    def test_source_cover_wins(self, config, scraper, lookups):
        from memanga.gui.cover_fallback import find_cover
        scraper.cover = _SOURCE_COVER
        assert find_cover(config, "mangapill.com", "https://u", "T") == _SOURCE_COVER
        assert lookups == []

    def test_falls_back_when_allowed(self, config, scraper, lookups):
        from memanga.gui.cover_fallback import find_cover
        assert find_cover(config, "mangapill.com", "https://u", "T") == _FALLBACK_URL
        assert lookups == ["T"]

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_no_fallback_when_blocked(self, config, scraper, lookups, how):
        from memanga.gui.cover_fallback import find_cover
        _block_mangadex(config, how)
        assert find_cover(config, "mangapill.com", "https://u", "T") is None
        assert scraper.calls == ["https://u"]  # the chosen source still asked
        assert lookups == []


# ─────────────────────────────────────────────────────────────────────
# App entry points
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_app(config, event_bus):
    submitted = []
    worker = SimpleNamespace(submit_task=lambda fn: submitted.append(fn) or fn())
    return SimpleNamespace(
        config=config, events=event_bus, worker=worker,
        network=SimpleNamespace(is_online=True),
        _cover_fallback_attempted=set(), submitted=submitted,
    )


class TestStartupBackfill:
    def _run(self, stub, monkeypatch):
        from memanga.gui.app import MeMangaApp
        monkeypatch.setattr(time, "sleep", lambda s: None)
        MeMangaApp._backfill_missing_covers(stub)

    def test_allowed_backfills(self, stub_app, config, lookups, monkeypatch):
        config.set("manga", [{"title": "One Piece", "source": "mangapill.com"}])
        self._run(stub_app, monkeypatch)
        assert lookups == ["One Piece"]
        assert config.get("manga")[0]["cover_url"] == _FALLBACK_URL

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_blocked_does_nothing(self, stub_app, config, lookups,
                                  monkeypatch, how):
        config.set("manga", [{"title": "One Piece", "source": "mangapill.com"}])
        _block_mangadex(config, how)
        self._run(stub_app, monkeypatch)
        assert stub_app.submitted == []
        assert lookups == []
        # Not marked failed, so allowing the lookup later still fills it.
        assert "cover_lookup_failed" not in config.get("manga")[0]


class TestBrokenCoverRepair:
    def _run(self, stub):
        from memanga.gui.app import MeMangaApp
        MeMangaApp._on_cover_load_failed(stub, {"url": _DEAD_URL, "error": True})

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_blocked_does_nothing(self, stub_app, config, lookups, how):
        config.set("manga", [{"title": "Naruto", "cover_url": _DEAD_URL}])
        _block_mangadex(config, how)
        self._run(stub_app)
        assert stub_app.submitted == []
        assert lookups == []
        assert config.get("manga")[0]["cover_url"] == _DEAD_URL
        # Not counted as tried: allowing the lookup later can still repair.
        assert stub_app._cover_fallback_attempted == set()

    def test_allowed_repairs(self, stub_app, config, lookups):
        config.set("manga", [{"title": "Naruto", "cover_url": _DEAD_URL}])
        self._run(stub_app)
        assert lookups == ["Naruto"]
        assert config.get("manga")[0]["cover_url"] == _FALLBACK_URL


# ─────────────────────────────────────────────────────────────────────
# Revoked while queued or between titles: the worker loops re-check
# before every lookup and stop (issue #337).
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def revoking_lookups(monkeypatch):
    """MangaDex lookup that turns MangaDex off right after the first
    call (as if the user flipped a switch mid-pass)."""
    import memanga.gui.cover_fallback as cf
    state = SimpleNamespace(calls=[], config=None, how=None)

    def fetch(title):
        state.calls.append(title)
        _block_mangadex(state.config, state.how)
        return None

    monkeypatch.setattr(cf, "fetch_mangadex_cover", fetch)
    return state


def _defer_tasks(stub):
    queued = []
    stub.worker = SimpleNamespace(submit_task=queued.append)
    return queued


class TestRevokedDuringBackfill:
    def _run(self, stub, monkeypatch):
        from memanga.gui.app import MeMangaApp
        monkeypatch.setattr(time, "sleep", lambda s: None)
        MeMangaApp._backfill_missing_covers(stub)

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_revoked_while_queued(self, stub_app, config, lookups,
                                  monkeypatch, how):
        config.set("manga", [{"title": "A"}, {"title": "B"}])
        queued = _defer_tasks(stub_app)
        self._run(stub_app, monkeypatch)
        assert len(queued) == 1
        _block_mangadex(config, how)
        queued[0]()
        assert lookups == []
        assert all("cover_lookup_failed" not in m for m in config.get("manga"))

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_revoked_between_titles(self, stub_app, config, revoking_lookups,
                                    monkeypatch, how):
        config.set("manga", [{"title": "A"}, {"title": "B"}, {"title": "C"}])
        revoking_lookups.config, revoking_lookups.how = config, how
        self._run(stub_app, monkeypatch)
        assert revoking_lookups.calls == ["A"]
        a, b, c = config.get("manga")
        assert a.get("cover_lookup_failed") is True  # A really was looked up
        assert "cover_lookup_failed" not in b
        assert "cover_lookup_failed" not in c


class TestRevokedDuringRepair:
    def _run(self, stub):
        from memanga.gui.app import MeMangaApp
        MeMangaApp._on_cover_load_failed(stub, {"url": _DEAD_URL, "error": True})

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_revoked_while_queued(self, stub_app, config, lookups, how):
        config.set("manga", [{"title": "Naruto", "cover_url": _DEAD_URL}])
        queued = _defer_tasks(stub_app)
        self._run(stub_app)
        assert len(queued) == 1
        _block_mangadex(config, how)
        queued[0]()
        assert lookups == []
        assert config.get("manga")[0]["cover_url"] == _DEAD_URL
        # Forgotten, so allowing the lookup again can still repair it.
        assert stub_app._cover_fallback_attempted == set()

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_revoked_between_titles(self, stub_app, config, revoking_lookups,
                                    how):
        # Two entries share one broken URL, so one task covers both.
        config.set("manga", [{"title": "A", "cover_url": _DEAD_URL},
                             {"title": "B", "cover_url": _DEAD_URL}])
        revoking_lookups.config, revoking_lookups.how = config, how
        self._run(stub_app)
        assert revoking_lookups.calls == ["A"]
        assert [m["cover_url"] for m in config.get("manga")] == [_DEAD_URL] * 2


class TestDetailRefetch:
    def _run(self, config, event_bus, monkeypatch):
        from memanga.gui.pages.detail import DetailPage
        stub = SimpleNamespace(app=SimpleNamespace(config=config, events=event_bus))
        with monkeypatch.context() as m:
            m.setattr(threading, "Thread", _SyncThread)
            DetailPage._refetch_cover(stub, "Naruto", "https://u", "mangapill.com")

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_blocked_skips_mangadex(self, config, event_bus, scraper, lookups,
                                    monkeypatch, how):
        config.set("manga", [{"title": "Naruto", "source": "mangapill.com"}])
        _block_mangadex(config, how)
        self._run(config, event_bus, monkeypatch)
        assert scraper.calls == ["https://u"]
        assert lookups == []
        assert "cover_url" not in config.get("manga")[0]

    def test_allowed_uses_mangadex(self, config, event_bus, scraper, lookups,
                                   monkeypatch):
        config.set("manga", [{"title": "Naruto", "source": "mangapill.com"}])
        self._run(config, event_bus, monkeypatch)
        assert lookups == ["Naruto"]
        assert config.get("manga")[0]["cover_url"] == _FALLBACK_URL


class TestAddManga:
    def _add(self, app_window, monkeypatch):
        from memanga.gui.pages import add_manga as mod
        # Keep the add flow on its online path whatever the test
        # machine's network: stop probing and forget any result.
        app_window.network.set_enabled(False)
        monkeypatch.setattr(app_window.worker, "check_updates",
                            lambda *a, **k: None)
        d = mod.AddMangaDialog(app_window, app_window)
        d._url_entry.setText("https://mangapill.com/manga/2/one-piece")
        d._title_entry.setText("One Piece")
        with monkeypatch.context() as m:
            m.setattr(threading, "Thread", _SyncThread)
            d._add_manga()

    @pytest.mark.parametrize("how", ["source_disabled", "setting_off"])
    def test_blocked_skips_mangadex(self, app_window, qapp, scraper, lookups,
                                    monkeypatch, how):
        _block_mangadex(app_window.config, how)
        self._add(app_window, monkeypatch)
        assert scraper.calls == ["https://mangapill.com/manga/2/one-piece"]
        assert lookups == []
        entry = app_window.config.get("manga")[0]
        assert entry["title"] == "One Piece"
        assert "cover_url" not in entry

    def test_allowed_uses_mangadex(self, app_window, qapp, scraper, lookups,
                                   monkeypatch):
        self._add(app_window, monkeypatch)
        assert lookups == ["One Piece"]
        assert app_window.config.get("manga")[0]["cover_url"] == _FALLBACK_URL
