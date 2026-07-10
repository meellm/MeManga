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
# Probe semantics (issue #84 — false offline on networks that block
# TCP/53 to public resolvers while normal HTTPS works)
# ─────────────────────────────────────────────────────────────────────


class TestTcpProbe:
    def _patch_connect(self, monkeypatch, exc):
        import memanga.gui.network_status as ns

        def _raise(*a, **k):
            raise exc

        monkeypatch.setattr(ns.socket, "create_connection", _raise)
        return ns

    def test_refused_connection_counts_as_online(self, monkeypatch):
        # A refusal (e.g. RST for TCP/53 on filtered networks) proves
        # the network path works — must not flip the app offline.
        ns = self._patch_connect(monkeypatch, ConnectionRefusedError())
        assert ns._tcp_probe("1.1.1.1", 53, 0.1) is True

    def test_policy_blocked_connection_counts_as_online(self, monkeypatch):
        # Windows 11 reserves DoH resolver IPs and returns WSAEACCES;
        # local policy blocks are not offline evidence either.
        ns = self._patch_connect(monkeypatch, PermissionError())
        assert ns._tcp_probe("1.1.1.1", 443, 0.1) is True

    def test_timeout_counts_as_offline(self, monkeypatch):
        import socket
        ns = self._patch_connect(monkeypatch, socket.timeout())
        assert ns._tcp_probe("1.1.1.1", 53, 0.1) is False

    def test_name_resolution_failure_counts_as_offline(self, monkeypatch):
        import socket
        ns = self._patch_connect(monkeypatch, socket.gaierror())
        assert ns._tcp_probe("cloudflare.com", 443, 0.1) is False

    def test_unreachable_network_counts_as_offline(self, monkeypatch):
        import errno
        ns = self._patch_connect(
            monkeypatch, OSError(errno.ENETUNREACH, "unreachable"))
        assert ns._tcp_probe("1.1.1.1", 53, 0.1) is False


class TestCheckConnectivity:
    def test_falls_back_to_https_when_tcp53_fails(self, monkeypatch):
        from memanga.gui import network_status as ns
        calls = []

        def fake_probe(host, port, timeout):
            calls.append((host, port))
            return port == 443

        monkeypatch.setattr(ns, "_tcp_probe", fake_probe)
        assert ns._check_connectivity() is True
        assert calls[0][1] == 53          # cheap endpoint tried first
        assert calls[1][1] == 443         # then the HTTPS fallback

    def test_stops_at_first_reachable_endpoint(self, monkeypatch):
        from memanga.gui import network_status as ns
        calls = []
        monkeypatch.setattr(
            ns, "_tcp_probe",
            lambda h, p, t: calls.append((h, p)) or True)
        assert ns._check_connectivity() is True
        assert len(calls) == 1

    def test_offline_only_when_every_endpoint_fails(self, monkeypatch):
        from memanga.gui import network_status as ns
        calls = []
        monkeypatch.setattr(
            ns, "_tcp_probe",
            lambda h, p, t: bool(calls.append((h, p))))
        assert ns._check_connectivity() is False
        assert len(calls) == len(ns.PROBE_ENDPOINTS)


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
        # Offline events carry seq=-1 so the UI knows they don't
        # correspond to any real search generation.
        assert len(started) == 1
        assert started[0]["query"] == "piece"
        assert started[0]["total_sources"] == 0
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
