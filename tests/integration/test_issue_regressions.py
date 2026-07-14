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
| #32 | Reader page-by-page mode with left/right arrow navigation |
| #40 | Pause All / Resume All dropped queued downloads |
| #43 | Arrow keys dead in the reader |
| #45 | Chapter marked read before reaching the end |
| #49 | "Next chapter" button label invisible |
| #55 | Detail page blank when Email to Kindle delivery selected |
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
                               naming_template=None, cancel_event=None,
                               **kwargs):
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


# ─────────────────────────────────────────────────────────────────────────
# #43 — Arrow keys navigate the reader
# ─────────────────────────────────────────────────────────────────────────


def _open_reader(app_window, qapp, sample_manga, make_cbz, chapters=("1",),
                 pages=1):
    """Download fake chapters and open the reader on the first one."""
    from pathlib import Path
    app_window.config.set("manga", [sample_manga])
    dl = Path(app_window.config.download_dir) / sample_manga["title"]
    dl.mkdir(parents=True, exist_ok=True)
    for ch in chapters:
        (dl / f"{sample_manga['title']} - Chapter {ch}.cbz").write_bytes(
            make_cbz(pages=pages, name=f"ch{ch}.cbz").read_bytes())
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], ch)
    app_window.show_page("reader", manga=sample_manga, chapter=chapters[0])
    qapp.processEvents()
    return app_window._pages["reader"]


def _press(reader, key):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    reader.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_issue_43_down_up_arrows_scroll(app_window, qapp, sample_manga,
                                          make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=3)
    bar = reader._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "test needs content taller than the viewport"
    assert bar.value() == 0

    _press(reader, Qt.Key.Key_Down)
    assert bar.value() > 0
    _press(reader, Qt.Key.Key_Up)
    assert bar.value() == 0


def test_issue_43_left_right_arrows_change_chapter(app_window, qapp,
                                                     sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz,
                          chapters=("1", "2"))
    assert reader._scroll.horizontalScrollBar().maximum() == 0

    _press(reader, Qt.Key.Key_Right)
    qapp.processEvents()
    assert str(reader._chapter) == "2"
    _press(reader, Qt.Key.Key_Left)
    qapp.processEvents()
    assert str(reader._chapter) == "1"


def test_issue_43_right_arrow_pans_when_zoomed(app_window, qapp,
                                                 sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz,
                          chapters=("1", "2"))
    # The offscreen platform never lays out wide-enough content, so give
    # the scrollbar the range a zoomed-in page would have.
    hbar = reader._scroll.horizontalScrollBar()
    hbar.setRange(0, 500)

    _press(reader, Qt.Key.Key_Right)
    assert hbar.value() > 0          # panned…
    assert str(reader._chapter) == "1"  # …without switching chapters


# ─────────────────────────────────────────────────────────────────────────
# #45 — Reader only marks read near the end
# ─────────────────────────────────────────────────────────────────────────


def test_issue_45_reader_does_not_mark_middle_as_read(app_window, qapp,
                                                       sample_manga, make_cbz):
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=8)
    title = sample_manga["title"]
    bar = reader._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "test needs scrollable reader content"

    bar.setValue(bar.maximum() // 2)
    qapp.processEvents()

    assert not app_window.app_state.is_chapter_read(title, "1")


def test_issue_45_reader_marks_read_at_end(app_window, qapp, sample_manga,
                                            make_cbz):
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=8)
    title = sample_manga["title"]
    bar = reader._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "test needs scrollable reader content"

    bar.setValue(bar.maximum())
    qapp.processEvents()

    assert app_window.app_state.is_chapter_read(title, "1")


# ─────────────────────────────────────────────────────────────────────────
# #32 — Page-by-page reading modes (single / two-up) with arrow keys
# ─────────────────────────────────────────────────────────────────────────


def test_issue_32_single_mode_arrows_turn_pages(app_window, qapp,
                                                  sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz,
                          chapters=("1", "2"), pages=4)
    reader._set_view_mode("single")
    qapp.processEvents()
    assert reader._current_page == 0
    assert len(reader._page_labels) == 1  # only the current page rendered

    _press(reader, Qt.Key.Key_Right)
    assert reader._current_page == 1
    _press(reader, Qt.Key.Key_Left)
    assert reader._current_page == 0
    # Clamped at the first page — and crucially Left/Right never fall
    # through to the continuous-mode chapter jump.
    _press(reader, Qt.Key.Key_Left)
    assert reader._current_page == 0
    assert str(reader._chapter) == "1"


def test_issue_32_single_mode_space_pgdn_home_end(app_window, qapp,
                                                    sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=5)
    reader._set_view_mode("single")

    _press(reader, Qt.Key.Key_Space)
    assert reader._current_page == 1
    _press(reader, Qt.Key.Key_PageDown)
    assert reader._current_page == 2
    _press(reader, Qt.Key.Key_PageUp)
    assert reader._current_page == 1
    _press(reader, Qt.Key.Key_End)
    assert reader._current_page == 4
    _press(reader, Qt.Key.Key_Home)
    assert reader._current_page == 0


def test_issue_32_double_mode_steps_by_spread(app_window, qapp,
                                                sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=5)
    reader._set_view_mode("double")
    qapp.processEvents()
    assert reader._current_page == 0
    assert len(reader._page_labels) == 2  # one spread = two pages

    _press(reader, Qt.Key.Key_Right)
    assert reader._current_page == 2
    _press(reader, Qt.Key.Key_End)
    # Last spread of a 5-page chapter holds only the odd final page.
    assert reader._current_page == 4
    assert len(reader._page_labels) == 1
    _press(reader, Qt.Key.Key_Left)
    assert reader._current_page == 2


def test_issue_32_right_at_last_page_stays_in_chapter(app_window, qapp,
                                                        sample_manga,
                                                        make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz,
                          chapters=("1", "2"), pages=2)
    reader._set_view_mode("single")
    _press(reader, Qt.Key.Key_End)
    assert reader._current_page == 1
    _press(reader, Qt.Key.Key_Right)
    assert reader._current_page == 1
    assert str(reader._chapter) == "1"


def test_issue_32_up_down_scroll_within_page_when_zoomed(app_window, qapp,
                                                           sample_manga,
                                                           make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=3)
    reader._set_view_mode("single")
    reader._zoom_in(); reader._zoom_in()
    qapp.processEvents()
    bar = reader._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "test needs the page to overflow the viewport"

    _press(reader, Qt.Key.Key_Down)
    assert bar.value() > 0           # scrolled within the page…
    assert reader._current_page == 0  # …without turning it
    _press(reader, Qt.Key.Key_Up)
    assert bar.value() == 0


def test_issue_32_last_page_marks_chapter_read(app_window, qapp,
                                                 sample_manga, make_cbz):
    from PySide6.QtCore import Qt
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=4)
    reader._set_view_mode("single")
    title = sample_manga["title"]
    assert not app_window.app_state.is_chapter_read(title, "1")

    _press(reader, Qt.Key.Key_End)
    qapp.processEvents()
    assert app_window.app_state.is_chapter_read(title, "1")


def test_issue_32_mode_persists_per_manga(app_window, qapp, sample_manga,
                                            make_cbz):
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz)
    reader._set_view_mode("single")

    entry = next(m for m in app_window.config.get("manga", [])
                 if m.get("title") == sample_manga["title"])
    assert entry.get("reader_mode") == "single"

    # Leave the reader and come back — the manga reopens single-page.
    app_window.show_page("library"); qapp.processEvents()
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()
    assert reader._view_mode == "single"


def test_issue_32_legacy_dual_page_config_maps_to_double(app_window, qapp,
                                                           sample_manga,
                                                           make_cbz):
    app_window.config.set("gui.reader_dual_page", True)
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz, pages=4)
    assert reader._view_mode == "double"


def test_issue_32_detail_layout_dropdown_persists(app_window, qapp,
                                                    sample_manga):
    app_window.config.set("manga", [sample_manga])
    app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
    page = app_window._pages["detail"]
    page._on_layout_change("single")

    entry = next(m for m in app_window.config.get("manga", [])
                 if m.get("title") == sample_manga["title"])
    assert entry.get("reader_mode") == "single"


# ─────────────────────────────────────────────────────────────────────────
# #49 — "Next chapter" button label invisible
# ─────────────────────────────────────────────────────────────────────────


def _luminance_spread(widget) -> float:
    """Render the widget and return the gap between its darkest and
    lightest interior pixel (border and corner radius excluded). A
    legible label separates text from fill; an invisible one renders
    near-uniform."""
    img = widget.grab().toImage()
    inset = 6
    lo, hi = 1.0, 0.0
    for y in range(inset, img.height() - inset):
        for x in range(inset, img.width() - inset):
            c = img.pixelColor(x, y)
            lum = (0.2126 * c.redF() + 0.7152 * c.greenF()
                   + 0.0722 * c.blueF())
            lo = min(lo, lum)
            hi = max(hi, lum)
    return hi - lo


def test_issue_49_next_chapter_label_legible(app_window, qapp, theme,
                                             sample_manga, make_cbz):
    """A selector-less stylesheet on the reader's scroll area cascaded
    into every descendant, repainting the next-chapter button's accent
    background with bg_0 while the label kept its dark on_primary color
    — invisible text in dark mode, near-invisible in light.
    """
    from PySide6.QtWidgets import QPushButton
    reader = _open_reader(app_window, qapp, sample_manga, make_cbz,
                          chapters=("1", "2"))
    btns = [b for b in reader._scroll.findChildren(QPushButton)
            if b.text().startswith("Next: Chapter")]
    assert len(btns) == 1, "next-chapter button missing at end of chapter 1"
    btn = btns[0]
    assert "2" in btn.text()

    for theme_name in ("dark", "light"):
        theme.set_theme(theme_name, qapp)
        qapp.processEvents()
        spread = _luminance_spread(btn)
        assert spread > 0.25, (
            f"#49 regression: next-chapter label illegible in {theme_name} "
            f"theme (luminance spread {spread:.3f})"
        )


# ─────────────────────────────────────────────────────────────────────────
# #55 — Detail page blank when Email to Kindle delivery is selected
# ─────────────────────────────────────────────────────────────────────────


def test_issue_55_detail_renders_with_email_delivery(app_window, qapp,
                                                     sample_manga):
    """Config.email_enabled returned the kindle_email *string*, which the
    detail page passed straight into QCheckBox.setChecked(). PySide6
    rejects non-bool arguments with a TypeError, aborting _rebuild()
    mid-way and leaving the page blank except for the back button.
    """
    app_window.config.set("delivery.mode", "email")
    app_window.config.set("email.kindle_email", "reader@kindle.com")
    app_window.config.set("manga", [sample_manga])

    app_window.show_page("detail", manga=sample_manga)
    qapp.processEvents()

    page = app_window._pages["detail"]
    assert app_window._current_page == "detail"
    assert page._kindle_check.isChecked() is True
    # The page actually rendered past the back button.
    assert page._layout.count() > 1


def test_issue_55_email_enabled_is_bool(config):
    """email_enabled must be a real bool in every config state, never the
    kindle_email string leaking through `and` short-circuiting."""
    assert config.email_enabled is False  # default: local mode

    config.set("delivery.mode", "email")
    assert config.email_enabled is False  # email mode, no address yet

    config.set("email.kindle_email", "reader@kindle.com")
    assert config.email_enabled is True

    config.set("delivery.mode", "local")
    assert config.email_enabled is False
