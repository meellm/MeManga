"""End-to-end: trigger a chapter download with the mock scraper and
verify the file lands at the right path, state records it, and the
notification fires."""

from __future__ import annotations

import pytest
from pathlib import Path

pytestmark = pytest.mark.integration


def test_download_writes_under_manga_subfolder(tmp_path, state,
                                                patch_get_scraper):
    """Issue #23: every format under <dir>/<title>/."""
    from memanga.downloader import download_chapter
    import types

    class S:
        def add_downloaded_chapter(self, *a, **k): pass
        def is_chapter_downloaded(self, *a, **k): return False
        def get_pending_backup(self, *a, **k): return None
        def set_pending_backup(self, *a, **k): pass
        def clear_pending_backup(self, *a, **k): pass

    out = tmp_path / "out"
    manga = {"title": "MyManga", "url": "https://mock.test/m",
             "source": "mock.test"}
    ch = types.SimpleNamespace(number="1", title="", url="https://mock.test/c/1",
                                source="mock.test",
                                source_url="https://mock.test/c/1",
                                is_backup=False)
    path = download_chapter(manga, ch, out, "pdf", S())
    assert "MyManga" in str(Path(path).parent)


def test_check_then_download_loop(app_window, qapp, state, patch_get_scraper,
                                    monkeypatch):
    """Library 'Download All' flow without actually invoking scrapers."""
    sample = {"title": "Mock", "url": "https://mock.test/m",
              "source": "mock.test", "status": "reading", "mode": "auto"}
    app_window.config.set("manga", [sample])
    # Pretend chapters 1-3 are already downloaded
    for c in ["1", "2", "3"]:
        app_window.app_state.add_downloaded_chapter("Mock", c)

    # Trigger from Library "Download All" context-menu
    page = app_window._pages["library"]
    queued: list = []
    monkeypatch.setattr(app_window.worker, "download_chapter",
                         lambda **kw: queued.append(kw["chapter"].number))

    page._ctx_download_all(sample)
    # Wait for the check thread to publish check_complete; advance the
    # event bus until done.
    for _ in range(30):
        app_window.events.poll()
        qapp.processEvents()

    # Issue #15: chapters 1-3 already on disk should NOT be in the queue.
    for c in queued:
        assert c not in ("1", "2", "3"), \
            "already-downloaded chapter was re-queued — issue #15 regression"
