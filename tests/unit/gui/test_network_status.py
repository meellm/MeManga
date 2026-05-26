"""Tests for the offline-aware behaviour wired into the GUI.

Covers:
  - NetworkMonitor publishes online/offline events on transitions
  - BackgroundWorker short-circuits when offline
  - OfflineBanner shows/hides on events
"""

from __future__ import annotations

import time

import pytest


# ─────────────────────────────────────────────────────────────────────
# NetworkMonitor
# ─────────────────────────────────────────────────────────────────────


class TestNetworkMonitor:
    def test_default_state_is_optimistic(self, event_bus):
        from memanga.gui.network_status import NetworkMonitor
        m = NetworkMonitor(event_bus)
        # Before any probe completes, treat the world as online so the
        # UI doesn't show the banner at startup before we even checked.
        assert m.is_online is True

    def test_offline_probe_marks_offline_and_publishes(self, event_bus, monkeypatch):
        from memanga.gui import network_status as ns
        monkeypatch.setattr(ns, "_tcp_probe", lambda *a, **k: False)
        m = ns.NetworkMonitor(event_bus)

        seen = []
        event_bus.subscribe("network_offline", lambda d: seen.append(("off", d)))
        event_bus.subscribe("network_online", lambda d: seen.append(("on", d)))

        m._probe_and_publish()
        event_bus.poll()
        assert m.is_online is False
        assert ("off", {}) in seen
        assert all(k != "on" for k, _ in seen)

    def test_recovery_publishes_online(self, event_bus, monkeypatch):
        from memanga.gui import network_status as ns
        m = ns.NetworkMonitor(event_bus)

        # Force a confirmed offline state first.
        monkeypatch.setattr(ns, "_tcp_probe", lambda *a, **k: False)
        m._probe_and_publish()
        event_bus.poll()

        # Then come back online.
        monkeypatch.setattr(ns, "_tcp_probe", lambda *a, **k: True)
        seen = []
        event_bus.subscribe("network_online", lambda d: seen.append(d))
        m._probe_and_publish()
        event_bus.poll()
        assert m.is_online is True
        assert seen == [{}]


# ─────────────────────────────────────────────────────────────────────
# BackgroundWorker offline gates
# ─────────────────────────────────────────────────────────────────────


class _FakeMonitor:
    """Stand-in for NetworkMonitor whose `is_online` is controllable."""
    def __init__(self, online: bool):
        self._online = online

    @property
    def is_online(self):
        return self._online


class TestWorkerOfflineGates:
    def test_check_updates_offline_publishes_error_and_completes(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        w.network = _FakeMonitor(online=False)

        errors, completes = [], []
        event_bus.subscribe("check_error", lambda d: errors.append(d))
        event_bus.subscribe("check_complete", lambda d: completes.append(d))

        w.check_updates([{"title": "X", "source": "mock.test", "url": "u"}],
                          state=None, config=None)
        event_bus.poll()
        assert errors and errors[0]["title"] == "Offline"
        assert completes == [{"results": []}]

    def test_search_offline_short_circuits(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        w.network = _FakeMonitor(online=False)

        started, complete = [], []
        event_bus.subscribe("search_started", lambda d: started.append(d))
        event_bus.subscribe("search_complete", lambda d: complete.append(d))
        w.search_manga("piece", ["mangadex.org", "mangapill.com"])
        event_bus.poll()
        assert started == [{"query": "piece", "total_sources": 0}]
        assert complete and complete[0].get("offline") is True

    def test_download_chapter_offline_publishes_error(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        import types
        w = BackgroundWorker(event_bus)
        w.network = _FakeMonitor(online=False)

        errors = []
        event_bus.subscribe("download_error", lambda d: errors.append(d))
        chapter = types.SimpleNamespace(number="1", url="u")
        w.download_chapter({"title": "X"}, chapter, "/tmp", "pdf", state=None)
        event_bus.poll()
        assert errors and errors[0].get("offline") is True
        assert "Offline" in errors[0]["error"]

    def test_fetch_cover_offline_marks_failed(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        w.network = _FakeMonitor(online=False)

        class _Cache:
            failed = []
            def mark_failed(self, url): self.failed.append(url)
            def save_to_disk(self, url, content): raise AssertionError("not called")
        cache = _Cache()
        loaded = []
        event_bus.subscribe("cover_loaded", lambda d: loaded.append(d))
        w.fetch_cover("https://x/c.jpg", cache=cache)
        event_bus.poll()
        assert "https://x/c.jpg" in cache.failed
        assert loaded[0].get("offline") is True

    def test_ping_sources_offline_short_circuits(self, event_bus):
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        w.network = _FakeMonitor(online=False)

        updated = []
        event_bus.subscribe("sources_health_updated", lambda d: updated.append(d))
        w.ping_sources(["mangadex.org"], state=None)
        event_bus.poll()
        assert updated and updated[0].get("offline") is True

    def test_worker_without_monitor_stays_online(self, event_bus):
        """No monitor wired → treat as online (back-compat for tests
        that don't set up a NetworkMonitor)."""
        from memanga.gui.workers import BackgroundWorker
        w = BackgroundWorker(event_bus)
        assert w.network is None
        assert w._is_offline() is False


# ─────────────────────────────────────────────────────────────────────
# OfflineBanner
# ─────────────────────────────────────────────────────────────────────


class TestOfflineBanner:
    def test_starts_hidden(self, qapp, theme):
        from memanga.gui.components.offline_banner import OfflineBanner
        b = OfflineBanner(None)
        assert b.isHidden()

    def test_shows_on_offline_event(self, qapp, theme, event_bus):
        from memanga.gui.components.offline_banner import OfflineBanner
        b = OfflineBanner(None, events=event_bus)
        event_bus.publish("network_offline", {})
        event_bus.poll()
        assert not b.isHidden()

    def test_hides_on_online_event(self, qapp, theme, event_bus):
        from memanga.gui.components.offline_banner import OfflineBanner
        b = OfflineBanner(None, events=event_bus)
        b.set_online(False)
        assert not b.isHidden()
        event_bus.publish("network_online", {})
        event_bus.poll()
        assert b.isHidden()

    def test_retry_button_invokes_callback(self, qapp, theme):
        from memanga.gui.components.offline_banner import OfflineBanner
        called = []
        b = OfflineBanner(None, on_retry=lambda: called.append(1))
        b._retry_btn.click()
        assert called == [1]
