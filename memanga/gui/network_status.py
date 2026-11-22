"""
Centralised network connectivity check for the GUI.

Why we don't trust ``requests.exceptions.ConnectionError`` alone:
    A scraper that hits the network will retry 3 times with exponential
    back-off before giving up. With 100+ scrapers fanned out in parallel,
    that's a 90-second freeze on the search bar (and the same on
    "Check all") any time the user's WiFi blinks. We instead probe
    cheap TCP endpoints every few seconds and *publish* the result
    so every page can short-circuit network work the moment we go
    offline — and re-enable it the moment we recover.

Probe:
    Try a short list of TCP endpoints in order and treat the machine as
    online as soon as one is reachable. The first candidate is
    Cloudflare's 1.1.1.1:53 (cheap, no name lookup); if that fails we
    fall back to HTTPS ports on well-known hostnames, because some
    networks block outbound TCP/53 to public resolvers while normal
    HTTPS traffic works fine (see issue #84). We never speak the
    protocol — we only care that a socket opens.

    A connection that is actively refused or blocked by local policy
    still counts as online: getting a refusal back proves the network
    path works, it just means that particular endpoint won't take the
    connection. Only timeouts, unreachable-network errors and
    name-resolution failures count as offline evidence.

Settings (issue #337):
    ``gui.network_check`` turns the monitor off entirely — no probe is
    ever sent and the app simply assumes it is online.
    ``gui.network_check_hosts`` replaces the built-in hosts with the
    user's own ``host:port`` list. A list with no valid entry probes
    nothing; it never falls back to the built-in hosts.

Events published:
    "network_online"  → emitted on the first probe AND on every offline
                        → online transition. Pages should re-enable UI.
    "network_offline" → emitted on every online → offline transition.
                        Pages should disable network-requiring controls
                        and show the offline banner.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional


# Probe parameters. Keep the offline interval short so the user gets
# their UI back fast when the WiFi recovers; keep the online interval
# loose so we don't spam probes while everything is fine.
#
# Endpoints are tried in order until one succeeds. 1.1.1.1:53 stays
# first because it needs no DNS lookup; the :443 fallbacks cover
# networks that block TCP/53 to public resolvers. Use content
# hostnames (not resolver IPs) on :443 — Windows 11 reserves DoH
# resolver IPs like 1.1.1.1:443 and refuses direct connections.
PROBE_ENDPOINTS = (
    ("1.1.1.1", 53),
    ("cloudflare.com", 443),
    ("github.com", 443),
)
PROBE_TIMEOUT = 3.0
ONLINE_INTERVAL = 30.0      # re-check every 30 s while online
OFFLINE_INTERVAL = 5.0      # re-check every 5 s while offline


class NetworkMonitor:
    """Background thread that probes a small set of cheap endpoints at
    a cadence depending on the current online/offline state and
    publishes transitions on the GUI EventBus.
    """

    def __init__(self, events, endpoints=None):
        self._events = events
        # None means the built-in hosts; an empty tuple means probe
        # nothing (user hosts that are all invalid, issue #337).
        self._endpoints = (PROBE_ENDPOINTS if endpoints is None
                           else tuple(endpoints))
        self._online: Optional[bool] = None    # None until first probe
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Bumped by stop(): a probe started before a stop never counts,
        # even when start() runs again before that probe finishes.
        self._generation = 0

    # ── public API ────────────────────────────────────────────────

    @property
    def is_online(self) -> bool:
        """Last-known online state. Optimistic on first call (True) so
        we don't block the UI before the first probe completes.
        """
        with self._lock:
            return self._online is not False

    def start(self):
        """Spawn the monitor thread (idempotent)."""
        # Clear first: a thread stopped moments ago (Settings off, then
        # on again) is still alive and just keeps running.
        self._stop.clear()
        if not self._endpoints:
            return  # nothing to probe: stay optimistic, send nothing
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="network-monitor", daemon=True,
        )
        self._thread.start()

    def stop(self):
        with self._lock:
            self._generation += 1
        self._stop.set()

    def set_enabled(self, enabled: bool):
        """Turn background probing on or off (Settings, issue #337).

        Turning it off forgets the last result, so the app goes back to
        assuming it is online; if it was showing offline, publish
        ``network_online`` so the banner and disabled controls recover.
        """
        if enabled:
            self.start()
            return
        self.stop()
        with self._lock:
            was_offline = self._online is False
            self._online = None
        if was_offline:
            try:
                self._events.publish("network_online", {})
            except Exception:
                pass

    def force_recheck(self):
        """Manual re-probe (used by an explicit 'Retry' button in the
        offline banner)."""
        threading.Thread(
            target=self._probe_and_publish, name="network-recheck", daemon=True,
        ).start()

    # ── internals ─────────────────────────────────────────────────

    def _run(self):
        # First probe immediately; afterwards sleep + re-probe.
        while not self._stop.is_set():
            self._probe_and_publish()
            interval = (OFFLINE_INTERVAL if self._online is False
                          else ONLINE_INTERVAL)
            # Sleep in small slices so stop() responds fast.
            slept = 0.0
            while slept < interval and not self._stop.is_set():
                time.sleep(0.5)
                slept += 0.5

    def _probe_and_publish(self):
        if not self._endpoints:
            return  # nothing to probe: never report offline
        with self._lock:
            generation = self._generation
        online = _check_connectivity(self._endpoints)
        with self._lock:
            if self._stop.is_set() or generation != self._generation:
                return  # stopped or turned off while this probe ran
            changed = (self._online is None) or (self._online != online)
            prev = self._online
            self._online = online
        if not changed:
            return
        # First-probe edge: only publish if we're DEFINITELY offline.
        # An optimistic "online" first probe is the default UI state,
        # no need to fan out an event for it.
        if prev is None and online:
            return
        topic = "network_online" if online else "network_offline"
        try:
            self._events.publish(topic, {})
        except Exception:
            # Never raise from a daemon probe thread.
            pass


def configured_endpoints(config) -> tuple:
    """The probe hosts from ``gui.network_check_hosts``.

    Unset or an empty list means the built-in PROBE_ENDPOINTS.
    Otherwise only the valid ``host:port`` entries are used; with none
    (or a value that is not a list) the result is empty and nothing is
    probed, so a typo never sends probes to hosts the user replaced.
    """
    from ..config import parse_host_port
    raw = config.get("gui.network_check_hosts", []) if config else []
    if raw == []:
        return PROBE_ENDPOINTS
    if not isinstance(raw, list):
        return ()
    return tuple(ep for ep in map(parse_host_port, raw) if ep)


def invalid_hosts(config) -> list:
    """Entries of ``gui.network_check_hosts`` that are not ``host:port``."""
    from ..config import parse_host_port
    raw = config.get("gui.network_check_hosts", []) if config else []
    if not isinstance(raw, list):
        return [raw]
    return [h for h in raw if parse_host_port(h) is None]


def _check_connectivity(endpoints=PROBE_ENDPOINTS) -> bool:
    """Probe endpoints in order; online as soon as one is reachable."""
    for host, port in endpoints:
        if _tcp_probe(host, port, PROBE_TIMEOUT):
            return True
    return False


def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    """Try to open a TCP socket to (host, port).

    Returns True if the connection succeeds — or if it is actively
    refused / blocked by policy (ConnectionRefusedError,
    PermissionError). A refusal is a response: it proves the network
    path works and only this endpoint won't accept the connection.

    Returns False on name-resolution failure, unreachable network or
    timeout — the errors a genuinely dead link produces.
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except (ConnectionRefusedError, PermissionError):
        return True
    except (socket.gaierror, OSError):
        return False
    try:
        sock.close()
    except Exception:
        pass
    return True
