"""Shared fixtures for tests/scrapers/.

All helpers are exposed as fixtures so test modules don't need to
import them (which would require this directory to be a package, and
that conflicts with the unrelated tests/unit/scrapers/ package).

Patterns:
    def test_x(fake_response):           # FakeResponse class
        ...
    def test_y(load_fixture):            # load_fixture(*parts)
        ...
    def test_z(patch_html, scraper):     # patch_html(scraper, html_map)
        ...
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ──────────────────────────────────────────────────────────────────────
# FakeResponse: stand-in for requests.Response. Implements just enough
# of the surface that any scraper touches.
# ──────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str = "", *, status: int = 200,
                 content: bytes | None = None, json_data=None):
        self._text = text
        self.status_code = status
        self._content = content if content is not None else text.encode("utf-8")
        self._json = json_data

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._content

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self._text)

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError
            raise HTTPError(f"{self.status_code} error")


# ──────────────────────────────────────────────────────────────────────
# Fixture-loader helpers — disk → text/dict
# ──────────────────────────────────────────────────────────────────────


def _load_fixture(*parts: str) -> str:
    return FIXTURES_DIR.joinpath(*parts).read_text(encoding="utf-8")


def _load_json_fixture(*parts: str) -> dict:
    return json.loads(_load_fixture(*parts))


# ──────────────────────────────────────────────────────────────────────
# Patcher helpers — inject canned HTML/JSON into a scraper instance
# ──────────────────────────────────────────────────────────────────────


def _patch_html(monkeypatch, scraper, html_map):
    """Patch scraper._get_html.

    html_map: str | callable(url)->str | dict {url_substr: html}
    """
    if isinstance(html_map, str):
        body = html_map
        def _fake(url, *a, **k):
            return body
    elif callable(html_map):
        _fake = lambda url, *a, **k: html_map(url)
    else:
        def _fake(url, *a, **k):
            for needle, content in html_map.items():
                if needle in url:
                    return content
            raise AssertionError(f"unexpected URL fetched: {url!r}")
    monkeypatch.setattr(scraper, "_get_html", _fake)


def _patch_json(monkeypatch, scraper, json_map):
    """Patch scraper._get_json."""
    if isinstance(json_map, dict) and all(isinstance(v, dict)
                                             for v in json_map.values()):
        def _fake(url, *a, **k):
            for needle, payload in json_map.items():
                if needle in url:
                    return payload
            raise AssertionError(f"unexpected URL fetched: {url!r}")
    elif callable(json_map):
        _fake = lambda url, *a, **k: json_map(url)
    else:
        payload = json_map
        def _fake(url, *a, **k):
            return payload
    monkeypatch.setattr(scraper, "_get_json", _fake)


def _patch_request(monkeypatch, scraper, *, text="", content=None, status=200):
    """Patch scraper._request to return a FakeResponse."""
    resp = _FakeResponse(text=text, content=content, status=status)
    monkeypatch.setattr(scraper, "_request", lambda *a, **k: resp)
    return resp


# ──────────────────────────────────────────────────────────────────────
# Public fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_response():
    """The FakeResponse class — instantiate with .text/.content/.json_data."""
    return _FakeResponse


@pytest.fixture
def load_fixture():
    """Read a fixture file: load_fixture('nuxt_ssr', 'chapter.html')."""
    return _load_fixture


@pytest.fixture
def load_json_fixture():
    return _load_json_fixture


@pytest.fixture
def patch_html(monkeypatch):
    """patch_html(scraper, html_str_or_dict_or_callable)."""
    def _bind(scraper, html_map):
        _patch_html(monkeypatch, scraper, html_map)
    return _bind


@pytest.fixture
def patch_json(monkeypatch):
    def _bind(scraper, json_map):
        _patch_json(monkeypatch, scraper, json_map)
    return _bind


@pytest.fixture
def patch_request(monkeypatch):
    def _bind(scraper, *, text="", content=None, status=200):
        return _patch_request(monkeypatch, scraper,
                                text=text, content=content, status=status)
    return _bind
