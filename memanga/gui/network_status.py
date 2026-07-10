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

    def __init__(self, events):
        self._events = events
        self._online: Optional[bool] = None    # None until first probe
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

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
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="network-monitor", daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

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
        online = _check_connectivity()
        with self._lock:
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


def _check_connectivity() -> bool:
    """Probe endpoints in order; online as soon as one is reachable."""
    for host, port in PROBE_ENDPOINTS:
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
