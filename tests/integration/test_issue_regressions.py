"""Regression tests for previously-fixed numbered bugs.

If any of these go red, a previously-fixed bug has come back.

| Issue | Description |
|---|---|
| #13 | Background ignored app theme and followed OS appearance |
| #14 | Cancel All did not clear queued downloads |
| #15 | Download All re-queued already-downloaded chapters |
| #16 | Ctrl+wheel zoom in reader |
| #18 | Read chapters not tracked per chapter |
| #20 | "Download from chapter X" downloaded all chapters |
| #21 | No pan/drag when zoomed in reader |
| #23 | Non-image format downloads written to root, not <dir>/<title>/ |
| #40 | Pause All / Resume All dropped queued downloads |
"""

from __future__ import annotations

import pytest
import threading


pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────────
# #13 — Background obeys app theme, not OS appearance
# ─────────────────────────────────────────────────────────────────────────


def test_issue_13_palette_matches_token(qapp, theme):
    from PySide6.QtGui import QPalette
    for theme_name in ("dark", "light"):
        theme.set_theme(theme_name, qapp)
        pal_bg = qapp.palette().color(QPalette.ColorRole.Window).name().lower()
        token_bg = theme.tokens()["surfaces.bg_0"].lower()
        assert pal_bg == token_bg, (
            f"#13 regression: in {theme_name} theme, palette Window={pal_bg} "
            f"!= token bg_0={token_bg}"
        )


# ─────────────────────────────────────────────────────────────────────────
# #14 — Cancel All clears queued items
# ─────────────────────────────────────────────────────────────────────────


def test_issue_14_cancel_all_drains_queue(app_window, qapp):
    # Inject 3 fake queued downloads
    for i in range(3):
        tid = f"sim-{i}"
        app_window.worker._cancel_flags[tid] = threading.Event()
        fake = {"task_id": tid, "manga": {"title": "T"},
                "chapter": type("C", (), {"number": str(i)})(),
                "output_dir": "/tmp", "output_format": "pdf",
                "state": None, "kindle_cfg": None, "naming_template": None,
                "cancel": app_window.worker._cancel_flags[tid]}
        app_window.worker._download_queue.append(fake)
        app_window.events.publish("download_queued",
                                   {"task_id": tid, "title": "T", "chapter": str(i)})
    app_window.events.poll(); qapp.processEvents()

    page = app_window._pages["downloads"]
    page._cancel_all()
    app_window.events.poll(); qapp.processEvents()

    assert len(app_window.worker._download_queue) == 0
    assert len(page._active_items) == 0


# ─────────────────────────────────────────────────────────────────────────
# #15 — Library "Download All" preserves downloaded list
# ─────────────────────────────────────────────────────────────────────────


def test_issue_15_preserves_downloaded_list(app_window, qapp, sample_manga,
                                              patch_get_scraper, monkeypatch):
    app_window.config.set("manga", [sample_manga])
    for c in ("1", "2", "3"):
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], c)

    monkeypatch.setattr(app_window.worker, "check_updates",
                         lambda *a, **k: None)
    page = app_window._pages["library"]
    page._ctx_download_all(sample_manga)

    downloaded = app_window.app_state.get_downloaded_chapters(
        sample_manga["title"])
    # Issue #15 regression check — the destructive `reset_manga_progress(0)`
    # used to wipe these.
    assert "1" in downloaded and "2" in downloaded and "3" in downloaded


# ─────────────────────────────────────────────────────────────────────────
# #16 — Ctrl+wheel zoom
# ─────────────────────────────────────────────────────────────────────────


def test_issue_16_ctrl_wheel_zooms(app_window, qapp, sample_manga, make_cbz,
                                     tmp_path):
    from pathlib import Path
    from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QWheelEvent
    app_window.config.set("manga", [sample_manga])
    dl = Path(app_window.config.download_dir) / sample_manga["title"]
    dl.mkdir(parents=True, exist_ok=True)
    (dl / f"{sample_manga['title']} - Chapter 1.cbz").write_bytes(
        make_cbz(pages=1).read_bytes())
    app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()

    reader = app_window._pages["reader"]
    z0 = reader._zoom_level
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50),
                     QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.ControlModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    handled = reader.eventFilter(reader._scroll.viewport(), ev)
    assert handled is True
    assert reader._zoom_level > z0


def test_issue_16_plain_wheel_does_not_zoom(app_window, qapp, sample_manga,
                                              make_cbz, tmp_path):
    from pathlib import Path
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    app_window.config.set("manga", [sample_manga])
    dl = Path(app_window.config.download_dir) / sample_manga["title"]
    dl.mkdir(parents=True, exist_ok=True)
    (dl / f"{sample_manga['title']} - Chapter 1.cbz").write_bytes(
        make_cbz(pages=1).read_bytes())
    app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()
    reader = app_window._pages["reader"]
    z0 = reader._zoom_level
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50),
                     QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    reader.eventFilter(reader._scroll.viewport(), ev)
    assert reader._zoom_level == z0


# ─────────────────────────────────────────────────────────────────────────
# #18 — Per-chapter read tracking
# ─────────────────────────────────────────────────────────────────────────


def test_issue_18_chapter_read_state_persists(state):
    state.mark_chapter_read("Naruto", "5")
    assert state.is_chapter_read("Naruto", "5")
    state.unmark_chapter_read("Naruto", "5")
    assert not state.is_chapter_read("Naruto", "5")


def test_issue_18_library_card_shows_read_count(theme, sample_manga):
    from memanga.gui.components.manga_card import MangaCard
    text = MangaCard._sub_text(sample_manga, new_count=0,
                                 read_count=7, total_count=12)
    assert "7/12" in text


# ─────────────────────────────────────────────────────────────────────────
# #20 — Download from chapter X respects the start point
# ─────────────────────────────────────────────────────────────────────────


def test_issue_20_from_chapter_threshold(app_window, qapp, sample_manga):
    app_window.config.set("manga", [sample_manga])
    app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
    page = app_window._pages["detail"]
    app_window.worker.check_updates = lambda *a, **k: None
    page._do_download_from("5", skip_existing=True)
    # State's last_chapter is set just below 5 so check_for_updates
    # returns only chapters >= 5
    assert app_window.app_state.get_last_chapter(
        sample_manga["title"]) == "4.999"


# ─────────────────────────────────────────────────────────────────────────
# #21 — Click-and-drag pan when zoomed
# ─────────────────────────────────────────────────────────────────────────


def test_issue_21_drag_pans_when_zoomed(app_window, qapp, sample_manga,
                                          make_cbz):
    from pathlib import Path
    from PySide6.QtCore import Qt, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    app_window.config.set("manga", [sample_manga])
    dl = Path(app_window.config.download_dir) / sample_manga["title"]
    dl.mkdir(parents=True, exist_ok=True)
    (dl / f"{sample_manga['title']} - Chapter 1.cbz").write_bytes(
        make_cbz(pages=1).read_bytes())
    app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()
    reader = app_window._pages["reader"]
    # Zoom in so content overflows the viewport vertically.
    reader._zoom_in(); reader._zoom_in()
    qapp.processEvents()
    vp = reader._scroll.viewport()
    v0 = reader._scroll.verticalScrollBar().value()
    # Press + drag
    press = QMouseEvent(QEvent.Type.MouseButtonPress,
                        QPointF(100, 100), QPointF(100, 100),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    reader.eventFilter(vp, press)
    move = QMouseEvent(QEvent.Type.MouseMove,
                       QPointF(100, 50), QPointF(100, 50),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    reader.eventFilter(vp, move)
    v1 = reader._scroll.verticalScrollBar().value()
    assert v1 > v0  # scroll position advanced


# ─────────────────────────────────────────────────────────────────────────
# #23 — Every output format under <dir>/<manga>/
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["pdf", "epub", "cbz", "zip", "jpg"])
def test_issue_23_all_formats_under_manga_subfolder(fmt, tmp_path,
                                                      patch_get_scraper):
    from memanga.downloader import download_chapter
    import types
    class S:
        def add_downloaded_chapter(self, *a, **k): pass
        def is_chapter_downloaded(self, *a, **k): return False
        def get_pending_backup(self, *a, **k): return None
        def set_pending_backup(self, *a, **k): pass
        def clear_pending_backup(self, *a, **k): pass
    out = tmp_path / "downloads"
    manga = {"title": "Bleach", "url": "https://mock.test/m",
             "source": "mock.test"}
    chapter = types.SimpleNamespace(
        number="1", title="", url="https://mock.test/c/1",
        source="mock.test", source_url="https://mock.test/c/1",
        is_backup=False)
    from pathlib import Path
    path = Path(download_chapter(manga, chapter, out, fmt, S()))
    assert path.relative_to(out).parts[0] == "Bleach"


# ─────────────────────────────────────────────────────────────────────────
# #40 — Pause All / Resume All keeps the queue and the Active tab
# ─────────────────────────────────────────────────────────────────────────


def test_issue_40_pause_resume_keeps_queue(app_window, qapp, monkeypatch):
    """Pause All must hold queued downloads; Resume All must refill every
    free slot. Resume used to release a slot no job ever held, so each
    toggle dequeued an item past the concurrency cap (where pause could
    no longer hold it) while a clean resume restarted only one job.
    """
    import time
    import types
    import memanga.downloader as dl

    # Gated fake downloader: jobs stay "in flight" until released.
    gates: dict[str, threading.Event] = {}

    def fake_download_chapter(manga, chapter, output_dir, output_format,
                               state, progress_callback=None,
                               naming_template=None, cancel_event=None):
        gates[f"{manga['title']}:{chapter.number}"].wait(timeout=10)
        return None

    monkeypatch.setattr(dl, "download_chapter", fake_download_chapter)
    # Force the optimistic online path so download_chapter queues
    # instead of erroring on runners without network.
    monkeypatch.setattr(app_window.worker, "network", None)

    def pump(predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app_window.events.poll()
            qapp.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    worker = app_window.worker
    page = app_window._pages["downloads"]

    # Queue 4 chapters: 2 start (max concurrent), 2 wait in the queue.
    for i in range(1, 5):
        tid = f"M:{i}"
        gates[tid] = threading.Event()
        worker.download_chapter({"title": "M"},
                                 types.SimpleNamespace(number=str(i)),
                                 "/tmp", "pdf", None)
    assert pump(lambda: len(page._active_items) == 4)

    # Pause All, then let the 2 in-flight finish — the queue must hold
    # and the queued rows must stay visible in the Active tab.
    page._toggle_pause_all()
    gates["M:1"].set()
    gates["M:2"].set()
    assert pump(lambda: worker._active_downloads == 0)
    assert [it["task_id"] for it in worker._download_queue] == ["M:3", "M:4"]
    assert "M:3" in page._active_items and "M:4" in page._active_items

    # Resume All — BOTH free slots must refill, draining the queue.
    page._toggle_pause_all()
    assert pump(lambda: worker._active_downloads == 2)
    assert len(worker._download_queue) == 0

    gates["M:3"].set()
    gates["M:4"].set()
    assert pump(lambda: worker._active_downloads == 0)
