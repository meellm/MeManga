"""Per-domain source health shown on the Sources screen."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ..output import redact_diagnostic
from ._base import StateDomain, snapshot


class SourceHealthStore(StateDomain):
    """Probe results per source domain: status, errors and latency."""

    __slots__ = ()

    # Latency above which a successful probe is flagged "warning" instead
    # of "ok". Healthy sites on an ordinary connection routinely answer in
    # 500-2000 ms, so a lower bound paints almost every source yellow. This
    # threshold reserves the warning tier for responses that are genuinely
    # sluggish.
    SLOW_LATENCY_MS = 2500

    def update(self, domain: str, success: bool,
               error_msg: str = "", latency_ms: Optional[int] = None) -> None:
        """Update health status for a source domain.

        ``latency_ms`` (optional) records the round-trip time of the
        probe that produced this status update. Drives the "Xms" badge
        in the Sources screen.
        """
        with self._backend._locked() as data:
            if "source_health" not in data:
                data["source_health"] = {}
            now = datetime.now().isoformat()
            health = data["source_health"].get(domain, {"error_count": 0})
            if success:
                health["last_success"] = now
                health["error_count"] = 0
                # Flag only genuinely slow responses; see SLOW_LATENCY_MS.
                if latency_ms is not None and latency_ms > self.SLOW_LATENCY_MS:
                    health["status"] = "warning"
                else:
                    health["status"] = "ok"
            else:
                health["last_error"] = now
                # Issue #342: redacted, and up to DETAIL_MAX_CHARS (with a
                # cut note) instead of a 100-character slice.
                health["last_error_msg"] = redact_diagnostic(error_msg)
                health["error_count"] = health.get("error_count", 0) + 1
                health["status"] = "warning" if health["error_count"] < 3 else "error"
            if latency_ms is not None:
                health["latency_ms"] = int(latency_ms)
            data["source_health"][domain] = health
            self._backend._mark_dirty()

    def get(self, domain: str) -> Dict[str, Any]:
        """Get health info for a source."""
        with self._backend._locked() as data:
            return snapshot(data.get("source_health", {}).get(domain, {}))

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get health info for all sources. Entries are copies — probes
        update the stored dicts in place."""
        with self._backend._locked() as data:
            return snapshot(data.get("source_health", {}))
