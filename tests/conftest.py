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
import subprocess
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
    # Path.home() on Windows resolves USERPROFILE and ignores HOME
    # (Python 3.8+), so without this the suite reads and writes the
    # developer's real config/state and download directories.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    # A developer's MEMANGA_CONFIG_DIR would point the CLI elsewhere.
    monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
    # Nor may their log level or NO_COLOR change what the CLI prints.
    monkeypatch.delenv("MEMANGA_LOG_LEVEL", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    # Nor may an injected SMTP password replace the stored one (#247).
    monkeypatch.delenv("MEMANGA_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("MEMANGA_SMTP_PASSWORD_FILE", raising=False)
    # Issue #249: the default root is the platform config folder. Pin it
    # to the isolated ~/.config/memanga on every OS so the suite behaves
    # the same on Windows and macOS as on Linux.
    from memanga import config as config_mod
    monkeypatch.setattr(config_mod, "platform_config_dir",
                        lambda *args, **kwargs: tmp_path / ".config" / "memanga")
    (tmp_path / ".config" / "memanga").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_output_setup():
    """Undo what a `cli.main()` run set up for output (issue #226).

    main() installs logging handlers and may swap the CLI consoles for
    plain ones; neither may leak into the next test.
    """
    cli = sys.modules.get("memanga.cli")
    saved = (cli.console, cli.err_console) if cli is not None else None
    yield
    output = sys.modules.get("memanga.output")
    if output is not None:
        output.reset_logging()
    cli = sys.modules.get("memanga.cli")
    if cli is None:
        return
    if saved is None:
        from rich.console import Console
        saved = (Console(), Console(stderr=True))
    cli.console, cli.err_console = saved


@pytest.fixture(autouse=True)
def _reset_scraper_cache():
    """get_scraper() reuses instances and request spacing is shared per
    scraper class (issue #254); neither may carry over to the next test."""
    yield
    scrapers = sys.modules.get("memanga.scrapers")
    if scrapers is not None:
        scrapers.clear_scraper_cache()
    base = sys.modules.get("memanga.scrapers.base")
    if base is not None:
        base.reset_request_spacing()


# ─────────────────────────────────────────────────────────────────────────
# Config directory lock (issue #244): a real second process holds it
# ─────────────────────────────────────────────────────────────────────────

_HOLD_LOCK = """
import sys
from memanga.process_lock import ConfigDirLock
ConfigDirLock(sys.argv[1]).acquire()
print("locked", flush=True)
sys.stdin.readline()
"""

_TRY_LOCK = """
import sys
from memanga.process_lock import ConfigDirBusy, ConfigDirLock
try:
    ConfigDirLock(sys.argv[1]).acquire()
except ConfigDirBusy:
    sys.exit(3)
"""


class LockHolder:
    """Holds config directory locks from separate Python processes."""

    def __init__(self):
        self._procs = []

    def _python(self, code, config_dir, **kwargs):
        return [sys.executable, "-c", code, str(config_dir)], dict(
            cwd=str(_REPO_ROOT), text=True, **kwargs)

    def hold(self, config_dir) -> subprocess.Popen:
        """Start a process that holds the lock until release()/kill()."""
        cmd, kwargs = self._python(_HOLD_LOCK, config_dir)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **kwargs)
        self._procs.append(proc)
        if proc.stdout.readline().strip() != "locked":
            proc.kill()
            _, err = proc.communicate(timeout=30)
            raise RuntimeError(f"lock holder failed: {err}")
        return proc

    def release(self, proc):
        """Let the holder exit normally, releasing its lock."""
        proc.stdin.close()
        proc.wait(timeout=30)

    def can_lock(self, config_dir) -> bool:
        """True when another process could take the lock right now."""
        cmd, kwargs = self._python(_TRY_LOCK, config_dir)
        result = subprocess.run(cmd, capture_output=True, timeout=60, **kwargs)
        if result.returncode not in (0, 3):
            raise RuntimeError(f"lock probe failed: {result.stderr}")
        return result.returncode == 0

    def close(self):
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                pipe.close()


@pytest.fixture
def lock_holder() -> Iterator[LockHolder]:
    holder = LockHolder()
    try:
        yield holder
    finally:
        holder.close()


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
    monkeypatch.setattr(dl.updates, "get_scraper", lambda d: mock_scraper)
    monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: mock_scraper)
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
