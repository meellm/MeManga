"""Live HTTP reachability check for every scraper domain.

For each scraper registered in memanga.scrapers.SCRAPERS we GET the
site's base_url and classify what comes back. Cheap — one request
per domain. Run on a schedule (weekly?) to catch dead sites early.

Skipped by default — opt in with:
    pytest -m live tests/scrapers/live/test_live_reachability.py -v
"""

from __future__ import annotations

import pytest

from memanga.scrapers import SCRAPERS, get_scraper

from _helpers import (  # injected onto sys.path by conftest.py
    probe_url, assert_alive,
    STATUS_OK, STATUS_PROTECTED,
)


# ─────────────────────────────────────────────────────────────────────
# Build the (domain, base_url) parameter list at import time. We
# resolve to the scraper's configured base_url where possible so we
# probe what the scraper actually requests, not just the raw domain.
# ─────────────────────────────────────────────────────────────────────


def _build_probe_targets():
    seen_urls = set()
    out = []
    for domain in sorted(SCRAPERS.keys()):
        # Skip www. aliases — they share base_url
        try:
            scraper = get_scraper(domain)
        except Exception:
            out.append((domain, f"https://{domain}"))
            continue

        url = None
        # NuxtSSR uses BASE_URL (uppercase)
        for attr in ("base_url", "BASE_URL"):
            v = getattr(scraper, attr, None)
            if v:
                url = v
                break
        if not url:
            url = f"https://{domain}"

        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append((domain, url))
    return out


_TARGETS = _build_probe_targets()


@pytest.mark.live
@pytest.mark.health
@pytest.mark.parametrize("domain,base_url",
                          _TARGETS,
                          ids=[d for d, _ in _TARGETS])
def test_scraper_site_is_reachable(domain, base_url, health_recorder):
    """Probe scraper homepage; record outcome; fail only on hard errors."""
    result = probe_url(base_url)
    health_recorder(result)

    # Print one-liner so even when running without -v you see the
    # classification.
    print(f"[{result.status:9s}] {domain:38s} {result.detail}")

    # PROTECTED sites are not failures — they're Cloudflare-protected
    # and the scraper bypasses with cloudscraper/Playwright in real use.
    if result.status == STATUS_PROTECTED:
        pytest.skip(f"Cloudflare-protected (real scraper bypasses): {result.detail}")

    assert_alive(result)
