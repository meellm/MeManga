"""Single-series sites answer search from a fixed title list, offline.

Their search results must be valid ``Manga`` objects: an unknown keyword
argument used to raise ``TypeError`` for every matching query, so the
source failed in every search sweep.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.base import Manga


CASES = [
    ("kenganashura.com", "kengan ashura", [
        ("Kengan Ashura", "https://kenganashura.com/manga/kengan-ashura-chapter-1/"),
        ("Kengan Omega", "https://kenganashura.com/manga/kengan-omega-chapter-1/"),
    ]),
    ("oyasumipunpun.com", "oyasumi punpun", [
        ("Oyasumi Punpun (Goodnight Punpun)", "https://oyasumipunpun.com"),
    ]),
    ("readkingdomfree.com", "kingdom", [
        ("Kingdom", "https://www.readkingdomfree.com/"),
    ]),
]


@pytest.mark.parametrize("domain,query,expected", CASES,
                         ids=[c[0] for c in CASES])
def test_matching_query_returns_series(domain, query, expected):
    results = get_scraper(domain).search(query)
    assert all(isinstance(r, Manga) for r in results)
    assert [(r.title, r.url) for r in results] == expected
    assert all(r.cover_url is None for r in results)


@pytest.mark.parametrize("domain", [c[0] for c in CASES])
def test_unrelated_query_returns_nothing(domain):
    assert get_scraper(domain).search("solo leveling") == []
