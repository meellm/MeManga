"""Issue #48 — when a stored cover URL fails to download (dead CDN
link, hotlink block, non-image response), the app must try to replace
it via the MangaDex fallback instead of leaving a permanent
placeholder. `_backfill_missing_covers` only covers entries with no
URL at all, so the failure path needs its own hook.

The handler is exercised unbound on a stub app object — constructing a
full MeMangaApp window per test is slow and none of the widgets are
involved.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest


_DEAD_URL = "https://cdn.readdetectiveconan.com/file/mangapill/i/580.webp"
_FALLBACK_URL = "https://uploads.mangadex.org/covers/abc/def.512.jpg"


@pytest.fixture
def worker(event_bus):
    from memanga.gui.workers import BackgroundWorker
    w = BackgroundWorker(event_bus)
    yield w
    w.shutdown()


@pytest.fixture
def stub_app(config, event_bus, worker):
    return SimpleNamespace(
        config=config,
        events=event_bus,
        worker=worker,
        _cover_fallback_attempted=set(),
    )


def _handle(stub, data):
    from memanga.gui.app import MeMangaApp
    MeMangaApp._on_cover_load_failed(stub, data)


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestCoverLoadFailedFallback:
    def test_dead_library_url_replaced(self, stub_app, config, event_bus,
                                       monkeypatch):
        config.set("manga", [{
            "title": "Blue Lock",
            "source": "mangapill.com",
            "url": "https://mangapill.com/manga/580/blue-lock",
            "cover_url": _DEAD_URL,
        }])
        import memanga.gui.cover_fallback as cf
        monkeypatch.setattr(cf, "fetch_mangadex_cover",
                            lambda title: _FALLBACK_URL)

        updated = []
        event_bus.subscribe("library_updated", lambda d: updated.append(d))

        _handle(stub_app, {"url": _DEAD_URL, "error": True})

        assert _wait_for(
            lambda: config.get("manga")[0].get("cover_url") == _FALLBACK_URL)
        event_bus.poll()
        assert updated and updated[0]["title"] == "Blue Lock"

    def test_attempted_once_per_url(self, stub_app, config, monkeypatch):
        config.set("manga", [{"title": "Blue Lock", "cover_url": _DEAD_URL}])
        calls = []
        import memanga.gui.cover_fallback as cf
        monkeypatch.setattr(cf, "fetch_mangadex_cover",
                            lambda title: calls.append(title) or None)

        _handle(stub_app, {"url": _DEAD_URL, "error": True})
        assert _wait_for(lambda: len(calls) == 1)
        # The same broken cover repainting must not re-query MangaDex.
        _handle(stub_app, {"url": _DEAD_URL, "error": True})
        time.sleep(0.2)
        assert calls == ["Blue Lock"]

    def test_url_not_in_library_is_noop(self, stub_app, config, monkeypatch):
        # Search-result covers also flow through cover_loaded; a failed
        # one has no library entry to repair.
        config.set("manga", [{"title": "Other", "cover_url": "https://x/y.jpg"}])
        calls = []
        import memanga.gui.cover_fallback as cf
        monkeypatch.setattr(cf, "fetch_mangadex_cover",
                            lambda title: calls.append(title) or None)

        _handle(stub_app, {"url": _DEAD_URL, "error": True})
        time.sleep(0.2)
        assert calls == []

    def test_success_and_offline_events_ignored(self, stub_app):
        _handle(stub_app, {"url": _DEAD_URL})  # no error flag
        _handle(stub_app, {"url": _DEAD_URL, "error": True, "offline": True})
        assert stub_app._cover_fallback_attempted == set()
