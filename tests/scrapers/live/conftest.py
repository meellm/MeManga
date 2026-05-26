"""Shared infrastructure for live scraper health checks.

These tests are NOT run by default. Opt in with:

    pytest -m live tests/scrapers/live/                # all health checks
    pytest -m live tests/scrapers/live/test_live_reachability.py -v
    pytest -m live tests/scrapers/live/test_live_parsing.py -v

Run a single domain:

    pytest -m live tests/scrapers/live/ -k mangadex.org -v

Capture a JSON report:

    pytest -m live tests/scrapers/live/ --health-report=health.json

Failures are classified in the test name so you can scan the output:
  - DEAD        : DNS lookup failed, connection refused, timeout
  - PROTECTED   : Cloudflare/anti-bot 403/503 (site exists, blocked us)
  - HTTP_ERROR  : 4xx/5xx response
  - STALE       : site responded but the scraper extracted nothing
                  (likely the HTML structure changed)
  - OK          : reachable + scraper extracted real data
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# Make `_helpers` importable as `from _helpers import probe_url, ...`
# from any test file in this directory. (No package layout because
# tests/scrapers/ is intentionally not a package — would collide with
# tests/unit/scrapers/.)
# ─────────────────────────────────────────────────────────────────────


_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ─────────────────────────────────────────────────────────────────────
# CLI option: --health-report=path.json
# ─────────────────────────────────────────────────────────────────────


def pytest_addoption(parser):
    grp = parser.getgroup("scraper-health")
    grp.addoption(
        "--health-report",
        action="store",
        default=None,
        help="Path to write a JSON health report after live tests run.",
    )


# Session-scoped accumulator. Tests append via the `health_recorder`
# fixture; the session-finish hook writes it to disk.
_RESULTS: list = []


@pytest.fixture
def health_recorder():
    """Append-only accumulator for HealthResult rows."""
    def _record(r):
        _RESULTS.append(r)
    return _record


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--health-report")
    if not path or not _RESULTS:
        return
    from _helpers import (
        STATUS_OK, STATUS_DEAD, STATUS_PROTECTED, STATUS_HTTP_ERROR,
        STATUS_STALE, STATUS_SKIP,
    )
    out = {
        "summary": {
            "total": len(_RESULTS),
            "ok": sum(1 for r in _RESULTS if r.status == STATUS_OK),
            "dead": sum(1 for r in _RESULTS if r.status == STATUS_DEAD),
            "protected": sum(1 for r in _RESULTS if r.status == STATUS_PROTECTED),
            "http_error": sum(1 for r in _RESULTS if r.status == STATUS_HTTP_ERROR),
            "stale": sum(1 for r in _RESULTS if r.status == STATUS_STALE),
            "skip": sum(1 for r in _RESULTS if r.status == STATUS_SKIP),
        },
        "results": [asdict(r) for r in _RESULTS],
    }
    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
