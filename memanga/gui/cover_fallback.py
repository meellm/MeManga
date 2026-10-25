"""
Cover fallback via MangaDex public API.

Many of the smaller scrapers don't expose `get_cover_url` (or it returns
None for some titles). MangaDex has a key-free public API that almost
always returns a usable cover for popular series, so we use it as a
fallback when the primary source can't provide one.

This module is intentionally GUI-only — the CLI never touches it.

Every caller asks `mangadex_fallback_allowed` first (issue #337): the
lookup contacts MangaDex, so it stays off when the user turned
MangaDex off in Sources or turned the lookup off in Settings.
"""

import re
from typing import Optional

import requests
from ..scrapers.mangadex import USER_AGENT


_MANGADEX_API = "https://api.mangadex.org/manga"
_COVER_BASE = "https://uploads.mangadex.org/covers"
_TIMEOUT = 10
_MANGADEX_DOMAIN = "mangadex.org"


def mangadex_fallback_allowed(config) -> bool:
    """Whether the MangaDex cover lookup may run.

    Needs ``gui.mangadex_cover_fallback`` on (the default) and
    mangadex.org not in ``sources.disabled``.
    """
    if config is None:
        return False
    if not config.get("gui.mangadex_cover_fallback", True):
        return False
    disabled = config.get("sources.disabled", []) or []
    return _MANGADEX_DOMAIN not in disabled


def find_cover(config, domain: str, url: str, title: str) -> Optional[str]:
    """Cover URL for a library entry: the entry's own source first,
    then MangaDex when `mangadex_fallback_allowed`. Used by Add Manga
    and by Detail after a rename.
    """
    cover = None
    try:
        from ..scrapers import get_scraper
        scraper = get_scraper(domain)
        if hasattr(scraper, "get_cover_url") and url:
            cover = scraper.get_cover_url(url)
    except Exception:
        cover = None
    if not cover and mangadex_fallback_allowed(config):
        try:
            cover = fetch_mangadex_cover(title)
        except Exception:
            cover = None
    return cover


def _normalize(text: str) -> str:
    """Lowercase + strip non-alphanumerics for fuzzy title matching."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _similarity(a: str, b: str) -> float:
    """Cheap symmetric similarity score (Jaccard on character bigrams).

    Avoids pulling in difflib for what's essentially a sanity check.
    """
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    def _bigrams(s: str) -> set:
        return {s[i : i + 2] for i in range(len(s) - 1)} or {s}

    ga, gb = _bigrams(na), _bigrams(nb)
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def fetch_mangadex_cover(title: str) -> Optional[str]:
    """Query MangaDex for a manga by title; return a usable cover URL or None.

    Picks the top result whose normalized title is reasonably close to the
    query (Jaccard ≥ 0.5). Returns a 512px-wide JPEG URL suitable for the
    library card / detail page.
    """
    if not title or not title.strip():
        return None

    try:
        resp = requests.get(
            _MANGADEX_API,
            params={
                "title": title.strip(),
                "limit": 5,
                "includes[]": "cover_art",
                "order[relevance]": "desc",
            },
            timeout=_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    for item in payload.get("data", []) or []:
        manga_id = item.get("id")
        if not manga_id:
            continue

        attrs = item.get("attributes", {}) or {}
        titles = attrs.get("title", {}) or {}
        alt_titles = attrs.get("altTitles", []) or []

        # Build the candidate title set: every language variant + alt titles.
        candidates = list(titles.values())
        for alt in alt_titles:
            candidates.extend(alt.values())

        best_sim = max((_similarity(title, c) for c in candidates if c), default=0.0)
        if best_sim < 0.5:
            continue

        # Find the cover_art relationship and resolve to a URL.
        for rel in item.get("relationships", []) or []:
            if rel.get("type") != "cover_art":
                continue
            file_name = (rel.get("attributes") or {}).get("fileName")
            if file_name:
                return f"{_COVER_BASE}/{manga_id}/{file_name}.512.jpg"

    return None
