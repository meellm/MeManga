"""
Lazy, off-UI-thread reader page loading (issue #389).

Covers header-only chapter indexing for every format, the per-page decode
and scale, the bounded pixmap cache, the worker loader's thread handoff
and stale-result handling, and the reader's page window: no decode on the
main thread, memory bounded by the window instead of the chapter length,
paged-mode prefetch, resume position and failed pages.
"""

import io
import threading
import time
import zipfile
from pathlib import Path

import pytest


def _png(size=(40, 60), color="white") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpg(size=(40, 60), color="white") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _stage_chapter(app_window, manga, make_cbz, *, pages, chapter="1"):
    """Drop a downloaded CBZ where the reader looks for it."""
    app_window.config.set("manga", [manga])
    title = manga["title"]
    dl = Path(app_window.config.download_dir) / title
    dl.mkdir(parents=True, exist_ok=True)
    cbz = make_cbz(pages=pages, name=f"ch{chapter}.cbz")
    (dl / f"{title} - Chapter {chapter}.cbz").write_bytes(cbz.read_bytes())
    app_window.app_state.add_downloaded_chapter(title, chapter)
    return title


def _settle(qtbot, reader):
    """Wait until every requested page has come back to the GUI thread."""
    qtbot.waitUntil(lambda: not reader._page_loader.has_pending(),
                    timeout=10000)


def _window_bound(reader):
    """Most pages the reader may hold decoded for its current position."""
    first, last, step = reader._visible_page_range()
    return ((last - first + 1)
            + (reader.PAGE_PREFETCH_AHEAD + reader.PAGE_PREFETCH_BEHIND)
            * step)


# ── Indexing ─────────────────────────────────────────────────────────────


class TestIndexing:
    def test_cbz_index_keeps_order_and_header_sizes(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_file
        cbz = tmp_path / "c.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            zf.writestr("page001.jpg", _jpg((50, 70)))
            zf.writestr("page000.png", _png((40, 60)))
            zf.writestr("notes.txt", b"not a page")
            zf.writestr("__MACOSX/page000.png", _png())
            # A block page saved under an image name is not a page.
            zf.writestr("page002.jpg", b"<html>blocked</html>")
        pages = index_chapter_file(cbz)
        assert [p.member for p in pages] == ["page000.png", "page001.jpg"]
        assert [(p.width, p.height) for p in pages] == [(40, 60), (50, 70)]

    def test_epub_index_lists_every_image(self, qapp, tmp_path):
        # The duplicate EPUB cover is a separate issue; the reader still
        # shows what the archive holds.
        from memanga.gui.pages.reader_pages import index_chapter_file
        epub = tmp_path / "c.epub"
        with zipfile.ZipFile(epub, "w") as zf:
            zf.writestr("mimetype", b"application/epub+zip")
            zf.writestr("images/cover.jpg", _jpg())
            zf.writestr("images/page000.jpg", _jpg())
        pages = index_chapter_file(epub)
        assert [p.member for p in pages] == ["images/cover.jpg",
                                             "images/page000.jpg"]

    def test_folder_index(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p001.png").write_bytes(_png((30, 90)))
        (tmp_path / "p000.jpg").write_bytes(_jpg((20, 40)))
        (tmp_path / "info.txt").write_text("x")
        pages = index_chapter_folder(tmp_path)
        assert [p.source.name for p in pages] == ["p000.jpg", "p001.png"]
        assert [(p.width, p.height) for p in pages] == [(20, 40), (30, 90)]

    def test_pdf_index_and_decode(self, qapp, tmp_path):
        import img2pdf
        from memanga.gui.pages.reader_pages import (KIND_PDF_PIKEPDF,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = tmp_path / "c.pdf"
        pdf.write_bytes(img2pdf.convert([_jpg((40, 60)), _jpg((40, 60))]))
        pages = index_chapter_file(pdf)
        assert len(pages) == 2
        if pages[0].kind == KIND_PDF_PIKEPDF:
            assert (pages[0].width, pages[0].height) == (40, 60)
        assert all(not decode_page(p).isNull() for p in pages)

    def test_unreadable_archive_indexes_empty(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_file
        bad = tmp_path / "c.cbz"
        bad.write_bytes(b"not a zip")
        assert index_chapter_file(bad) == []


# ── Decode / scale ───────────────────────────────────────────────────────


class TestRenderPage:
    def test_wide_page_shrinks_to_target_width(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (display_size,
                                                    index_chapter_folder,
                                                    render_page)
        (tmp_path / "p.png").write_bytes(_png((1000, 3000)))
        ref = index_chapter_folder(tmp_path)[0]
        img = render_page(ref, 500, 1.0)
        assert (img.width(), img.height()) == (500, 1500)
        # Placeholders use the same size, so the layout never jumps.
        assert display_size(1000, 3000, 500, 1.0) == img.size()

    def test_narrow_page_follows_zoom(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (display_size,
                                                    index_chapter_folder,
                                                    render_page)
        (tmp_path / "p.png").write_bytes(_png((400, 600)))
        ref = index_chapter_folder(tmp_path)[0]
        img = render_page(ref, 800, 1.5)
        assert (img.width(), img.height()) == (600, 900)
        assert display_size(400, 600, 800, 1.5) == img.size()

    def test_missing_source_decodes_null(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (KIND_ZIP, PageRef,
                                                    decode_page)
        ref = PageRef(tmp_path / "gone.cbz", KIND_ZIP, member="p.jpg",
                      width=10, height=10)
        assert decode_page(ref).isNull()


# ── Cache ────────────────────────────────────────────────────────────────


class TestPixmapCache:
    def test_byte_budget_evicts_least_recent(self, qapp):
        from PySide6.QtGui import QPixmap
        from memanga.gui.pages.reader_pages import PixmapCache, pixmap_bytes
        one = pixmap_bytes(QPixmap(100, 100))
        cache = PixmapCache(max_bytes=one * 2)
        for key in ("a", "b"):
            cache.put(key, QPixmap(100, 100))
        cache.get("a")  # a is now the most recent
        cache.put("c", QPixmap(100, 100))
        assert cache.keys() == ["a", "c"]
        assert cache.total_bytes <= cache.max_bytes

    def test_oversized_newest_entry_is_kept(self, qapp):
        from PySide6.QtGui import QPixmap
        from memanga.gui.pages.reader_pages import PixmapCache
        cache = PixmapCache(max_bytes=1)
        cache.put("a", QPixmap(10, 10))
        cache.put("b", QPixmap(10, 10))
        assert cache.keys() == ["b"]


# ── Loader thread handoff ────────────────────────────────────────────────


class TestPageLoader:
    def _ref(self, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p.png").write_bytes(_png((40, 60)))
        return index_chapter_folder(tmp_path)[0]

    def test_decodes_off_thread_and_delivers_on_gui_thread(
            self, qapp, qtbot, tmp_path, monkeypatch):
        from PySide6.QtCore import QObject, Qt
        from memanga.gui.pages import reader_pages
        decode_threads = []
        real_decode = reader_pages.decode_page

        def spy(ref):
            decode_threads.append(threading.current_thread())
            return real_decode(ref)
        monkeypatch.setattr(reader_pages, "decode_page", spy)

        class Receiver(QObject):
            """GUI-thread QObject, like the reader page."""
            def __init__(self):
                super().__init__()
                self.got = []

            def on_ready(self, *args):
                self.got.append((threading.current_thread(), args))

        loader = reader_pages.PageLoader()
        receiver = Receiver()
        loader.page_ready.connect(receiver.on_ready,
                                  Qt.ConnectionType.QueuedConnection)
        try:
            token = loader.token
            assert loader.request(0, self._ref(tmp_path), 800, 1.0)
            qtbot.waitUntil(lambda: bool(receiver.got), timeout=10000)
        finally:
            loader.shutdown()
        delivered = receiver.got
        assert decode_threads
        assert all(t is not threading.main_thread() for t in decode_threads)
        assert decode_threads[0].name.startswith("memanga-reader")
        thread, (got_token, index, _w, _zoom, image) = delivered[0]
        assert thread is threading.main_thread()
        assert (got_token, index) == (token, 0)
        assert not image.isNull()

    def test_reset_makes_results_stale(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import PageLoader
        loader = PageLoader()
        try:
            old = loader.token
            loader.request(0, self._ref(tmp_path), 800, 1.0)
            loader.reset()
            assert not loader.has_pending()
            assert loader.finish(old, (0, 800, 1.0)) is False
        finally:
            loader.shutdown()

    def test_shutdown_refuses_new_work(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import PageLoader
        loader = PageLoader()
        loader.shutdown()
        assert loader.request(0, self._ref(tmp_path), 800, 1.0) is False

    def test_wait_idle_matches_a_folder_chapter_by_its_images(
            self, qapp, tmp_path, monkeypatch):
        from memanga.gui.pages import reader_pages
        folder = tmp_path / "Chapter 1"
        other = tmp_path / "Chapter 2"
        folder.mkdir()
        other.mkdir()
        ref = self._ref(folder)
        gate = threading.Event()
        started = threading.Event()

        def held_decode(ref):
            started.set()
            gate.wait(10)
            return reader_pages.QImage()
        monkeypatch.setattr(reader_pages, "decode_page", held_decode)
        loader = reader_pages.PageLoader()
        try:
            loader.request(0, ref, 800, 1.0)
            assert started.wait(5)
            # The job reads folder/p.png: the folder is busy, others not.
            assert loader.wait_idle(0, folder) is False
            assert loader.wait_idle(0, ref.source) is False
            assert loader.wait_idle(0, other) is True
            gate.set()
            assert loader.wait_idle(5, folder) is True
        finally:
            gate.set()
            loader.shutdown()


# ── Reader page window ───────────────────────────────────────────────────


@pytest.fixture
def decode_spy(monkeypatch):
    """Record which thread decodes which page."""
    from memanga.gui.pages import reader_pages
    calls = []
    real_decode = reader_pages.decode_page

    def spy(ref):
        calls.append((ref.member, threading.current_thread()))
        return real_decode(ref)
    monkeypatch.setattr(reader_pages, "decode_page", spy)
    return calls


class TestReaderLazyLoading:
    def test_open_decodes_only_the_window_and_never_on_main_thread(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            decode_spy):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=30)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        # Every page is known (and laid out) up front...
        assert len(reader._images) == 30
        assert len(reader._page_labels) == 30
        _settle(qtbot, reader)

        # ...but only the pages around the reading position were decoded.
        assert decode_spy, "the visible page was never decoded"
        assert all(t is not threading.main_thread() for _, t in decode_spy)
        decoded = {member for member, _ in decode_spy}
        assert len(decoded) <= _window_bound(reader) < 30
        assert "page000.jpg" in decoded
        assert "page029.jpg" not in decoded

    def test_scrolling_keeps_memory_bounded(self, app_window, qapp, qtbot,
                                            sample_manga, make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=30)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        assert 0 in reader._shown_pages

        sb = reader._scroll.verticalScrollBar()
        assert sb.maximum() > 0
        sb.setValue(sb.maximum() // 2)
        _settle(qtbot, reader)

        first, last, _ = reader._visible_page_range()
        assert first > 2
        assert set(range(first, last + 1)) <= reader._shown_pages
        # The first page left the window: its pixmap is released.
        assert 0 not in reader._shown_pages
        assert reader._page_slots[0].pixmap().isNull()
        assert len(reader._shown_pages) <= _window_bound(reader) + 2
        assert reader._page_cache.total_bytes <= reader.PAGE_CACHE_BYTES

    def test_cache_budget_holds_while_reading_through(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=20)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        reader._page_cache.max_bytes = 3 * 400 * 600 * 4
        sb = reader._scroll.verticalScrollBar()
        for step in range(1, 11):
            sb.setValue(sb.maximum() * step // 10)
            _settle(qtbot, reader)
            assert (reader._page_cache.total_bytes
                    <= reader._page_cache.max_bytes
                    or len(reader._page_cache) == 1)

    def test_single_mode_prefetches_next_pages(self, app_window, qapp,
                                               qtbot, sample_manga,
                                               make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=8)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        cached = {key[0] for key in reader._page_cache.keys()}
        assert {0, 1, 2, 3} <= cached
        assert 7 not in cached

        # The prefetched page shows at once, without waiting for a worker.
        reader._go_to_page(1)
        assert not reader._page_labels[0].pixmap().isNull()

    def test_double_mode_prefetches_whole_spreads(self, app_window, qapp,
                                                  qtbot, sample_manga,
                                                  make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=12)
        app_window.config.set("gui.reader_view_mode", "double")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        cached = {key[0] for key in reader._page_cache.keys()}
        assert set(range(0, 8)) <= cached
        reader._go_to_page(2)
        assert all(not lbl.pixmap().isNull() for lbl in reader._page_labels)

    def test_continuous_resume_decodes_restored_position(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        title = _stage_chapter(app_window, sample_manga, make_cbz, pages=20)
        app_window.app_state.set_reader_position(
            title, "1", mode="continuous", scroll_ratio=0.5)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()  # restore is deferred one event-loop turn
        qapp.processEvents()
        reader = app_window._pages["reader"]
        sb = reader._scroll.verticalScrollBar()
        assert sb.value() == pytest.approx(sb.maximum() * 0.5,
                                           abs=sb.maximum() * 0.05)
        _settle(qtbot, reader)
        first, last, _ = reader._visible_page_range()
        assert first > 2
        assert set(range(first, last + 1)) <= reader._shown_pages
        assert 0 not in reader._shown_pages
        assert not app_window.app_state.is_chapter_read(title, "1")

    def test_previous_chapter_results_are_ignored(self, app_window, qapp,
                                                  qtbot, sample_manga,
                                                  make_cbz):
        from PySide6.QtGui import QImage
        _stage_chapter(app_window, sample_manga, make_cbz, pages=4,
                       chapter="1")
        _stage_chapter(app_window, sample_manga, make_cbz, pages=4,
                       chapter="2")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        old_token = reader._page_loader.token
        reader._go_next_chapter()
        assert reader._chapter == "2"
        _settle(qtbot, reader)

        stale = QImage(7, 7, QImage.Format.Format_RGB32)
        key = (3, reader._page_target_w, reader._zoom_level)
        reader._page_cache.clear()
        reader._on_page_ready(old_token, *key, stale)
        assert key not in reader._page_cache
        assert reader._page_slots[3].pixmap().isNull() or \
            reader._page_slots[3].pixmap().width() != 7

    def test_failed_page_shows_placeholder_and_is_not_retried(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        from PySide6.QtGui import QImage
        from memanga.gui.pages import reader_pages
        calls = []

        def broken(ref):
            calls.append(ref.member)
            return QImage()
        monkeypatch.setattr(reader_pages, "decode_page", broken)
        _stage_chapter(app_window, sample_manga, make_cbz, pages=3)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)

        assert 0 in reader._failed_pages
        assert "couldn't be loaded" in reader._page_slots[0].text()
        before = len(calls)
        reader._update_page_window()
        _settle(qtbot, reader)
        assert len(calls) == before

    def test_leaving_the_reader_releases_pages(self, app_window, qapp,
                                               qtbot, sample_manga,
                                               make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=6)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        assert len(reader._page_cache)
        app_window.show_page("detail", manga=sample_manga)
        assert len(reader._page_cache) == 0
        assert not reader._shown_pages
        assert not reader._page_loader.has_pending()

    def test_close_stops_the_page_workers(self, app_window, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p.png").write_bytes(_png())
        ref = index_chapter_folder(tmp_path)[0]
        reader = app_window._pages["reader"]
        app_window.close()
        assert reader._page_loader.request(0, ref, 800, 1.0) is False

    def test_zoom_resizes_continuous_pages_in_place(self, app_window, qapp,
                                                    qtbot, sample_manga,
                                                    make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=12)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        labels = list(reader._page_labels)
        old_width = labels[0].width()
        old_key = (0, reader._page_target_w, reader._zoom_level)
        assert old_key in reader._page_cache

        reader._zoom_in()
        # Same widgets, new sizes: no per-page widget rebuild on zoom.
        assert reader._page_labels == labels
        assert labels[0].width() > old_width
        assert reader._image_layout.indexOf(reader._next_footer) >= 0

        _settle(qtbot, reader)
        new_key = (0, reader._page_target_w, reader._zoom_level)
        assert new_key != old_key and new_key in reader._page_cache
        assert 0 in reader._shown_pages
        assert reader._page_slots[0].pixmap().size() == labels[0].size()


class TestRemoveAfterReadWithLazyPages:
    """Pages are decoded from the chapter file on demand, so
    remove-after-read (#104) deletes it only once the reader leaves the
    chapter, after its page jobs are cancelled — exactly once."""

    def _finish_chapter(self, app_window, qapp, qtbot, sample_manga,
                        make_cbz, chapters=("1",)):
        app_window.config.set("reader.remove_after_read", True)
        for chapter in chapters:
            title = _stage_chapter(app_window, sample_manga, make_cbz,
                                   pages=20, chapter=chapter)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga,
                             chapter=chapters[0])
        qapp.processEvents()
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        sb = reader._scroll.verticalScrollBar()
        assert sb.maximum() > 0
        sb.setValue(sb.maximum())
        qapp.processEvents()
        _settle(qtbot, reader)
        artifact = (Path(app_window.config.download_dir) / title
                    / f"{title} - Chapter {chapters[0]}.cbz")
        return reader, title, artifact

    def test_revisit_after_zoom_renders_until_the_chapter_is_left(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        # Marked read at once; the file stays while the chapter is open.
        assert app_window.app_state.is_chapter_read(title, "1")
        assert artifact.exists()
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert 0 not in reader._shown_pages  # first page was released

        reader._zoom_in()  # new size: no cached pixmap fits any more
        reader._scroll.verticalScrollBar().setValue(0)
        qapp.processEvents()
        _settle(qtbot, reader)
        assert 0 in reader._shown_pages
        assert not reader._page_slots[0].pixmap().isNull()
        assert not reader._failed_pages

        app_window.show_page("detail", manga=sample_manga)
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")

    def test_removal_runs_exactly_once(self, app_window, qapp, qtbot,
                                       sample_manga, make_cbz, monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        calls = []
        real_remove = reader._remove_after_read
        monkeypatch.setattr(reader, "_remove_after_read",
                            lambda *args: (calls.append(args),
                                           real_remove(*args)))
        app_window.show_page("detail", manga=sample_manga)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        app_window.show_page("detail", manga=sample_manga)
        app_window.close()
        assert calls == [(title, "1", artifact)]
        assert not artifact.exists()

    def test_next_chapter_removes_the_finished_one(self, app_window, qapp,
                                                   qtbot, sample_manga,
                                                   make_cbz):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz,
            chapters=("1", "2"))
        assert artifact.exists()
        reader._go_next_chapter()
        assert reader._chapter == "2"
        assert reader._images
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_downloaded(title, "2")

    def test_close_removes_before_the_final_state_flush(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        from memanga.state import State
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        app_window.close()
        assert not artifact.exists()
        saved = State(app_window.config.config_dir)
        assert not saved.is_chapter_downloaded(title, "1")
        assert saved.is_chapter_read(title, "1")

    def test_removal_waits_for_a_running_decode(self, app_window, qapp,
                                                qtbot, sample_manga,
                                                make_cbz, monkeypatch):
        from memanga.gui.pages import reader_pages
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        events = []
        gate = threading.Event()
        real_decode = reader_pages.decode_page

        def slow_decode(ref):
            events.append("decode-start")
            gate.wait(5)
            image = real_decode(ref)
            events.append("decode-end")  # the file read has finished
            return image
        monkeypatch.setattr(reader_pages, "decode_page", slow_decode)
        real_remove = reader._remove_after_read
        monkeypatch.setattr(reader, "_remove_after_read",
                            lambda *args: (events.append("remove"),
                                           real_remove(*args)))

        reader._zoom_in()  # new size: workers start decoding again
        qtbot.waitUntil(lambda: "decode-start" in events, timeout=5000)
        release = threading.Timer(0.3, gate.set)
        release.start()
        try:
            app_window.show_page("detail", manga=sample_manga)
        finally:
            gate.set()
            release.cancel()

        removed_at = events.index("remove")
        before = events[:removed_at]
        assert before.count("decode-start") == before.count("decode-end")
        assert "decode-start" not in events[removed_at:]
        assert not artifact.exists()

    def _hold_decodes(self, reader, monkeypatch, qtbot):
        """Make the next page decodes block until the returned gate is
        set, and start them."""
        from memanga.gui.pages import reader_pages
        gate = threading.Event()
        started = threading.Event()
        real_decode = reader_pages.decode_page

        def stuck_decode(ref):
            started.set()
            gate.wait(30)
            return real_decode(ref)
        monkeypatch.setattr(reader_pages, "decode_page", stuck_decode)
        reader._zoom_in()  # new size: workers start decoding again
        qtbot.waitUntil(started.is_set, timeout=5000)
        return gate

    @pytest.mark.slow
    def test_removal_past_the_deadline_is_kept_and_retried(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        # Pages left showing the chapter must refresh once it is removed.
        refreshed = []
        detail = app_window._pages["detail"]
        library = app_window._pages["library"]
        monkeypatch.setattr(
            detail, "_refresh_chapter_list",
            lambda: refreshed.append(("detail", app_window.app_state
                                      .is_chapter_downloaded(title, "1"))))
        monkeypatch.setattr(
            library, "_on_check_done",
            lambda: refreshed.append(("library", app_window.app_state
                                      .is_chapter_downloaded(title, "1"))))
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            began = time.monotonic()
            app_window.show_page("detail", manga=sample_manga)
            # The UI waited out the deadline, but no longer.
            assert time.monotonic() - began < reader.REMOVAL_WAIT_S + 1.5
            # A decode still reads the file: nothing deleted, nothing lost.
            assert artifact.exists()
            assert app_window.app_state.is_chapter_downloaded(title, "1")
            assert reader._removal_queue == [(title, "1", artifact)]
            assert reader._removal_timer.isActive()
        finally:
            gate.set()

        qtbot.waitUntil(lambda: not artifact.exists(), timeout=10000)
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        assert reader._removal_queue == []
        assert not reader._removal_timer.isActive()
        # Still on Detail, no navigation: both pages heard of the removal
        # and saw the chapter as no longer downloaded.
        qtbot.waitUntil(lambda: ("detail", False) in refreshed
                        and ("library", False) in refreshed, timeout=5000)
        assert detail._stats_label.text().startswith("Downloaded: 0 chapters")

    @pytest.mark.slow
    def test_reopening_a_queued_chapter_keeps_it_until_left_again(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            app_window.show_page("detail", manga=sample_manga)
            assert reader._removal_queue == [(title, "1", artifact)]
            # The held decode ends just before the reopen, so the loader
            # is idle during the reopen's bounded wait: the exact window
            # in which the queued removal used to delete the file.
            gate.set()
            app_window.show_page("reader", manga=sample_manga, chapter="1")
        finally:
            gate.set()

        assert artifact.exists()
        assert reader._removal_queue == []
        assert reader._pending_removal == (title, "1", artifact)
        assert len(reader._images) == 20
        _settle(qtbot, reader)
        # The zoom that started the held decodes moved the end of the
        # chapter below the read threshold, so Back saved a resume
        # position (#106) and the reopen restores it. Whatever position
        # that is, the pages on screen come from the kept file.
        first, last, _ = reader._visible_page_range()
        assert set(range(first, last + 1)) <= reader._shown_pages
        assert not reader._page_slots[first].pixmap().isNull()
        assert not reader._failed_pages
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        # The retry timer leaves the open chapter alone.
        qtbot.wait(3 * reader.REMOVAL_RETRY_MS)
        assert artifact.exists()

        app_window.show_page("detail", manga=sample_manga)
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")

    @pytest.mark.slow
    def test_close_with_a_stuck_decode_keeps_the_chapter(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            app_window.close()
        finally:
            gate.set()
        # No retry is possible after close: file and state stay in step,
        # and the user is told why.
        assert artifact.exists()
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        assert any("still in use" in n["message"]
                   for n in app_window.app_state.get_notifications())
        assert reader._removal_queue == []


class TestChapterRemovedRefresh:
    """chapter_removed, published after a deferred remove-after-read,
    refreshes pages already showing the manga without navigation."""

    def test_visible_detail_refreshes_hero_and_list(self, app_window, qapp,
                                                    sample_manga,
                                                    monkeypatch):
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        for chapter in ("1", "2"):
            app_window.app_state.add_downloaded_chapter(title, chapter)
        app_window.show()
        app_window.show_page("detail", manga=sample_manga)
        detail = app_window._pages["detail"]
        assert detail._stats_label.text().startswith("Downloaded: 2 chapters")
        lists = []
        real_refresh = detail._refresh_chapter_list
        monkeypatch.setattr(detail, "_refresh_chapter_list",
                            lambda: (lists.append(True), real_refresh()))

        app_window.app_state.remove_downloaded_chapter(title, "1")
        app_window.events.publish("chapter_removed",
                                  {"title": "Other Manga", "chapter": "1"})
        app_window.events.poll()
        assert lists == []  # another manga: untouched

        app_window.events.publish("chapter_removed",
                                  {"title": title, "chapter": "1"})
        app_window.events.poll()
        assert lists == [True]
        assert detail._stats_label.text().startswith("Downloaded: 1 chapters")

    def test_library_schedules_its_refresh(self, app_window, qapp,
                                           sample_manga, monkeypatch):
        library = app_window._pages["library"]
        calls = []
        monkeypatch.setattr(library, "_on_check_done",
                            lambda: calls.append(True))
        app_window.events.publish("chapter_removed",
                                  {"title": sample_manga["title"],
                                   "chapter": "1"})
        app_window.events.poll()
        assert calls == [True]
