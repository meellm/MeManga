"""Shared helpers for live scraper health checks.

Imported by the live test files via a sys.path shim (see conftest.py).
Kept separate from conftest.py so the helpers stay importable as plain
Python rather than only as pytest fixtures.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

import pytest
import requests


# Status constants — used in test output and the JSON report.
STATUS_OK = "OK"
STATUS_DEAD = "DEAD"
STATUS_PROTECTED = "PROTECTED"
STATUS_HTTP_ERROR = "HTTP_ERROR"
STATUS_STALE = "STALE"
STATUS_SKIP = "SKIP"


@dataclass
class HealthResult:
    """One row in the per-run health report."""
    domain: str
    status: str
    detail: str = ""
    elapsed_ms: float = 0.0
    extra: dict = field(default_factory=dict)


LIVE_TIMEOUT = 15  # seconds
LIVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def probe_url(url: str, timeout: float = LIVE_TIMEOUT) -> HealthResult:
    """Reach a URL and classify what came back."""
    domain = url.split("//", 1)[-1].split("/", 1)[0]
    t0 = time.monotonic()
    try:
        resp = requests.get(url, headers=LIVE_HEADERS, timeout=timeout,
                              allow_redirects=True)
    except requests.exceptions.SSLError as e:
        return HealthResult(domain, STATUS_DEAD, f"ssl error: {e!s}",
                              (time.monotonic() - t0) * 1000)
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            socket.gaierror) as e:
        return HealthResult(domain, STATUS_DEAD, f"connection error: {e!s}",
                              (time.monotonic() - t0) * 1000)
    except requests.exceptions.RequestException as e:
        return HealthResult(domain, STATUS_HTTP_ERROR, f"request error: {e!s}",
                              (time.monotonic() - t0) * 1000)

    elapsed = (time.monotonic() - t0) * 1000

    # 403/503 with a Cloudflare hint → site is alive but blocking us
    if resp.status_code in (403, 503):
        body_lower = resp.text[:2000].lower()
        if any(s in body_lower for s in
                ("cloudflare", "cf-ray", "just a moment", "ddos protection")):
            return HealthResult(domain, STATUS_PROTECTED,
                                  f"HTTP {resp.status_code} (Cloudflare-style)",
                                  elapsed)
        return HealthResult(domain, STATUS_HTTP_ERROR,
                              f"HTTP {resp.status_code}", elapsed)

    if resp.status_code >= 400:
        return HealthResult(domain, STATUS_HTTP_ERROR,
                              f"HTTP {resp.status_code}", elapsed)

    # Suspicious tiny body
    if len(resp.text) < 200:
        return HealthResult(domain, STATUS_STALE,
                              f"HTTP 200 but body only {len(resp.text)} bytes",
                              elapsed)

    return HealthResult(domain, STATUS_OK,
                          f"HTTP {resp.status_code} ({len(resp.text)} bytes)",
                          elapsed)


def assert_alive(result: HealthResult):
    """Fail the test if the site is unreachable.

    PROTECTED is NOT a hard fail — Cloudflare often blocks requests-lib
    probes even when the scraper (with cloudscraper/Playwright) works
    fine. We surface it but don't fail.
    """
    if result.status in (STATUS_DEAD, STATUS_HTTP_ERROR):
        pytest.fail(f"[{result.status}] {result.domain}: {result.detail}")
    if result.status == STATUS_STALE:
        pytest.fail(f"[STALE] {result.domain}: {result.detail}")


def assert_parsed_something(scraper_call, *args, min_items: int = 1):
    """Call scraper_call(*args); fail if it returns 0 results.

    Wraps exceptions into STALE-style failures so they show up in the
    report cleanly rather than as stack traces.
    """
    try:
        result = scraper_call(*args)
    except Exception as e:
        pytest.fail(f"[STALE] scraper raised: {type(e).__name__}: {e!s}")
    if not result or len(result) < min_items:
        pytest.fail(f"[STALE] scraper returned {len(result) if result else 0} items, "
                     f"expected ≥ {min_items} (HTML structure may have changed)")
    return result
