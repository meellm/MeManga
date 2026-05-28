"""Shared pytest fixtures for the MeManga test suite (CLI variant).

Everything every CLI-facing test needs lives here:
- An isolated temp HOME so config/state never touch the real
  ``~/.config/memanga``
- Helpers to build a mock manga + a mock scraper that never hits the
  network
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator  # noqa: F401 — re-exported for downstream tests

import pytest


# Make `memanga` importable when pytest is invoked from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Isolation: every test gets a clean HOME
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_home(monkeypatch, tmp_path) -> Path:
    """Redirect HOME (and APPDATA / XDG_CONFIG_HOME) to a tmp dir so
    no test ever writes to the real config. Returns the new home
    path so tests can poke at created files.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "memanga").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────
# Domain models: State, Config
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def state(isolated_home):
    """Fresh State instance with no manga / no history."""
    from memanga.state import State
    return State(config_dir=isolated_home / ".config" / "memanga")


@pytest.fixture
def config(isolated_home, monkeypatch):
    """Fresh Config instance pointed at the isolated home."""
    from memanga import config as cfg_mod
    # Config infers its path from $HOME — isolated_home already
    # redirected that, so this just wraps it.
    return cfg_mod.Config()


@pytest.fixture
def sample_manga():
    """A canonical manga dict used as input by many tests."""
    return {
        "title": "Test Manga",
        "url": "https://mangadex.org/title/abc/test-manga",
        "source": "mangadex.org",
        "status": "reading",
        "mode": "manual",
        "fallback_delay_days": 2,
    }


@pytest.fixture
def sample_manga_with_backup():
    return {
        "title": "Backup Manga",
        "status": "reading",
        "mode": "auto",
        "fallback_delay_days": 3,
        "sources": [
            {"source": "mangadex.org",
             "url": "https://mangadex.org/title/abc/backup-manga"},
            {"source": "mangafire.to",
             "url": "https://mangafire.to/manga/abc.def"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Mock scrapers — never hit the network
# ─────────────────────────────────────────────────────────────────────────


class MockScraper:
    """Minimal scraper that returns a deterministic chapter list.
    Use as a drop-in for any real scraper in downloader tests.
    """

    name = "mock"
    base_url = "https://mock.test"

    def __init__(self, chapters: int = 5, raise_on_fetch: bool = False):
        from memanga.scrapers.base import Chapter
        self._chapters = [
            Chapter(number=str(i), title=f"Mock Chapter {i}",
                    url=f"https://mock.test/c/{i}")
            for i in range(1, chapters + 1)
        ]
        self._raise_on_fetch = raise_on_fetch
        self._page_count = 3

    def search(self, query: str):
        from memanga.scrapers.base import Manga
        return [Manga(title=f"{query} result", url="https://mock.test/r")]

    def get_chapters(self, url: str):
        if self._raise_on_fetch:
            raise RuntimeError("simulated scraper failure")
        return self._chapters

    def get_pages(self, chapter_url: str):
        return [f"https://mock.test/page/{i}.jpg" for i in range(self._page_count)]

    def download_image(self, url: str, path):
        from pathlib import Path
        from PIL import Image
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 300), "white").save(path)
        return True

    def get_cover_url(self, manga_url: str):
        return "https://mock.test/cover.jpg"


@pytest.fixture
def mock_scraper():
    return MockScraper()


@pytest.fixture
def patch_get_scraper(monkeypatch, mock_scraper):
    """Make ``memanga.scrapers.get_scraper(...)`` always return the mock."""
    import memanga.scrapers as scrapers_pkg
    import memanga.downloader as dl
    monkeypatch.setattr(scrapers_pkg, "get_scraper", lambda d: mock_scraper)
    monkeypatch.setattr(dl, "get_scraper", lambda d: mock_scraper)
    return mock_scraper


# ─────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def make_cbz(tmp_path):
    """Factory: build a CBZ at the given path with N JPEG pages."""
    import io
    import zipfile
    from PIL import Image

    def _make(pages: int = 3, name: str = "test.cbz") -> Path:
        out = tmp_path / name
        with zipfile.ZipFile(out, "w") as zf:
            for i in range(pages):
                buf = io.BytesIO()
                Image.new("RGB", (400, 600), "white").save(buf, "JPEG")
                zf.writestr(f"page{i:03d}.jpg", buf.getvalue())
        return out
    return _make
