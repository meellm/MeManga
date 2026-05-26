"""
Shared pytest fixtures for the MeManga test suite.

Everything every test needs lives here:
- A single QApplication for the whole session (PySide6 forbids multiple)
- An isolated temp HOME so config/state never touch the user's real
  ~/.config/memanga
- A clean QSettings instance per test
- Helpers to build mock manga + mock scrapers
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Process-level environment — must run before any Qt imports
# ─────────────────────────────────────────────────────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Force the Geist warning off — clutters every test run.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")


# Make `memanga` importable when pytest is invoked from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Isolation: every test gets a clean HOME
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_home(monkeypatch, tmp_path) -> Path:
    """Redirect HOME (and APPDATA/XDG_CONFIG_HOME) to a tmp dir so the
    test never writes to the developer's real config.
    Returns the new home path so tests can poke at created files.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "memanga").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────
# Qt: one QApplication for the whole session
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def qapp_session():
    """Single QApplication shared across the suite — PySide6 only allows
    one QApplication per process and tearing it down between tests is
    flaky on macOS, so we hold one for the session."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
    yield app
    # Don't call app.quit() — pytest-qt does its own shutdown.


@pytest.fixture
def qapp(qapp_session, isolated_home):
    """Per-test alias that pulls in HOME isolation automatically."""
    return qapp_session


@pytest.fixture
def fresh_settings(monkeypatch, isolated_home):
    """Reset QSettings so theme persistence and other QSettings-backed
    state start clean each test."""
    from PySide6.QtCore import QSettings
    # QSettings writes under HOME/Library on macOS, HOME/.config on
    # Linux — both are inside our isolated_home tmpdir already.
    s = QSettings("MeManga", "desktop-test")
    s.clear()
    s.sync()
    yield s
    s.clear()
    s.sync()


# ─────────────────────────────────────────────────────────────────────────
# Theme: reload tokens fresh each test so persisted theme doesn't leak
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def theme(qapp, fresh_settings):
    """Import the theme package + reset _current so tests pick the
    default dark theme. Returns the module so tests can call
    `theme.set_theme()`, `theme.tokens()` etc."""
    from memanga.gui import theme as T
    T._current = None
    T.apply(qapp)
    return T


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
    # Some Config implementations infer the path from $HOME, so the
    # isolated_home fixture already did the work.
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
    Use as a drop-in for any real scraper in `downloader` tests.
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
    """Make `memanga.scrapers.get_scraper(...)` always return the mock."""
    import memanga.scrapers as scrapers_pkg
    import memanga.downloader as dl
    monkeypatch.setattr(scrapers_pkg, "get_scraper", lambda d: mock_scraper)
    monkeypatch.setattr(dl, "get_scraper", lambda d: mock_scraper)
    return mock_scraper


# ─────────────────────────────────────────────────────────────────────────
# MainWindow construction — slow, gated behind a fixture
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_window(qapp, theme, isolated_home):
    """Fully-constructed MeMangaApp window. Use sparingly — each
    construction registers every page and starts a few QTimers."""
    from memanga.gui.app import MeMangaApp
    w = MeMangaApp()
    yield w
    try:
        w.worker.shutdown()
    except Exception:
        pass
    w.close()


# ─────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus():
    from memanga.gui.events import EventBus
    return EventBus()


@pytest.fixture
def make_cbz(tmp_path):
    """Factory: build a CBZ at the given path with N JPEG pages."""
    import io, zipfile
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
