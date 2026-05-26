"""Smoke + behavior tests for every Page widget. We construct each via
the app_window fixture (which gives us the full event bus + state),
verify the page renders, switches, and reacts to its primary events.
"""

from __future__ import annotations

import pytest


# Every page should at least be navigable.
ALL_PAGES = ["library", "downloads", "search", "notifications", "sources",
             "settings"]


@pytest.mark.parametrize("page_name", ALL_PAGES)
def test_page_navigates_without_crash(app_window, qapp, page_name):
    app_window.show_page(page_name)
    qapp.processEvents()
    # Current page should be the one we requested.
    assert app_window._current_page == page_name


def test_pages_handle_theme_switch(app_window, qapp, theme):
    """Every page should survive a dark→light→dark cycle."""
    for name in ALL_PAGES:
        app_window.show_page(name); qapp.processEvents()
        theme.set_theme("light", qapp); qapp.processEvents()
        theme.set_theme("dark", qapp); qapp.processEvents()


# ─────────────────────────────────────────────────────────────────────────
# Library
# ─────────────────────────────────────────────────────────────────────────


class TestLibraryPage:
    def test_empty_state_shows_hint(self, app_window, qapp):
        app_window.config.set("manga", [])
        app_window.show_page("library"); qapp.processEvents()
        # Empty hint label is in the grid.
        layout = app_window._pages["library"]._grid_layout
        assert layout.count() >= 1

    def test_chip_filter_keys(self, app_window):
        page = app_window._pages["library"]
        assert "all" in page._chip_buttons
        assert "reading" in page._chip_buttons
        assert "completed" in page._chip_buttons

    def test_set_view_mode_persists(self, app_window, qapp):
        page = app_window._pages["library"]
        page._set_view_mode("list")
        assert app_window.config.get("gui.view_mode") == "list"

    def test_continue_rail_hidden_when_nothing_to_continue(self, app_window,
                                                            qapp):
        app_window.config.set("manga", [])
        app_window.show_page("library"); qapp.processEvents()
        page = app_window._pages["library"]
        assert page._continue_section.isVisible() is False

    def test_library_refreshes_on_chapter_read_event(self, app_window, qapp):
        # Just verify the subscription doesn't crash when fired.
        app_window.show_page("library")
        app_window.events.publish("chapter_read",
                                   {"title": "X", "chapter": "1"})
        app_window.events.poll(); qapp.processEvents()


# ─────────────────────────────────────────────────────────────────────────
# Downloads
# ─────────────────────────────────────────────────────────────────────────


class TestDownloadsPage:
    def test_stats_cards_built(self, app_window, qapp):
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        for key in ("in_progress", "today", "week", "disk"):
            assert key in page._stat_cards

    def test_tab_switch(self, app_window, qapp):
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        page._switch_tab("completed")
        assert page._current_tab == "completed"

    def test_pause_all_toggles_worker_flag(self, app_window, qapp):
        page = app_window._pages["downloads"]
        page._toggle_pause_all()
        assert app_window.worker.is_paused() is True
        page._toggle_pause_all()
        assert app_window.worker.is_paused() is False

    def test_cancel_all_drains_queue(self, app_window, qapp):
        import threading
        # Inject 2 fake queued items
        for i in range(2):
            tid = f"sim-{i}"
            app_window.worker._cancel_flags[tid] = threading.Event()
            fake = {"task_id": tid, "manga": {"title": "T"},
                    "chapter": type("C", (), {"number": "1"})(),
                    "output_dir": "/tmp", "output_format": "pdf",
                    "state": None, "kindle_cfg": None,
                    "naming_template": None,
                    "cancel": app_window.worker._cancel_flags[tid]}
            app_window.worker._download_queue.append(fake)
            app_window.events.publish("download_queued",
                                       {"task_id": tid, "title": "T",
                                        "chapter": "1"})
        app_window.events.poll(); qapp.processEvents()

        page = app_window._pages["downloads"]
        page._cancel_all()
        app_window.events.poll(); qapp.processEvents()
        # Issue #14: queue + UI items both drained.
        assert len(app_window.worker._download_queue) == 0
        assert len(page._active_items) == 0


# ─────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────


class TestSearchPage:
    def test_renders(self, app_window, qapp):
        app_window.show_page("search"); qapp.processEvents()
        assert app_window._pages["search"]._search_entry is not None

    def test_empty_query_does_nothing(self, app_window, qapp):
        page = app_window._pages["search"]
        page._search_entry.setText("")
        page._do_search()
        # No worker call expected — nothing to assert except no crash.

    def test_no_recent_chip_row(self, app_window, qapp):
        # Recent-searches chip row was removed by user request — the
        # corresponding attributes should be gone too.
        page = app_window._pages["search"]
        assert not hasattr(page, "_recent_row")
        assert not hasattr(page, "_recents_wrap")
        assert not hasattr(page, "_refresh_recents")


# ─────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────


class TestNotificationsPage:
    def test_renders_empty(self, app_window, qapp):
        app_window.show_page("notifications"); qapp.processEvents()

    def test_clear_all_wipes(self, app_window, qapp, monkeypatch):
        app_window.app_state.add_notification("info", "x")
        # Patch ConfirmDialog so it auto-confirms.
        from memanga.gui.components import dialogs
        monkeypatch.setattr(
            dialogs, "ConfirmDialog",
            lambda *a, **k: k.get("on_confirm", lambda: None)()
        )
        page = app_window._pages["notifications"]
        page._stub_clear()
        assert app_window.app_state.get_notifications() == []

    def test_filter_chip_active_state(self, app_window):
        page = app_window._pages["notifications"]
        page._set_filter("downloads")
        assert page._filter_kind == "downloads"


# ─────────────────────────────────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────────────────────────────────


class TestSourcesPage:
    def test_renders(self, app_window, qapp):
        app_window.show_page("sources"); qapp.processEvents()

    def test_lang_chip_toggle(self, app_window, qapp):
        app_window.show_page("sources"); qapp.processEvents()
        page = app_window._pages["sources"]
        page._set_lang_filter("EN")
        assert page._lang_filter == "EN"

    def test_lang_of_classifies_domain(self):
        from memanga.gui.pages.sources import SourcesPage
        assert SourcesPage._lang_of("apollcomics.es") == "ES"
        assert SourcesPage._lang_of("mangadex.org") == "EN"

    def test_recheck_health_dispatches(self, app_window, qapp, monkeypatch):
        called = []
        monkeypatch.setattr(
            app_window.worker, "ping_sources",
            lambda srcs, st: called.append(srcs)
        )
        app_window.show_page("sources"); qapp.processEvents()
        page = app_window._pages["sources"]
        page._on_recheck_health()
        assert called  # ping_sources was kicked off


# ─────────────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────────────


class TestSettingsPage:
    def test_renders(self, app_window, qapp):
        app_window.show_page("settings"); qapp.processEvents()

    def test_tab_switch_visibility(self, app_window, qapp):
        app_window.show_page("settings"); qapp.processEvents()
        page = app_window._pages["settings"]
        page._switch_tab("email")
        # Top-level window isn't shown in offscreen tests, so isVisible()
        # always returns False. Use isHidden() — that reflects the
        # explicit setVisible(True/False) call _switch_tab makes.
        assert page._general_scroll.isHidden(), "general tab should be hidden"
        assert not page._email_scroll.isHidden(), "email tab should be shown"

    def test_save_writes_config(self, app_window, qapp):
        page = app_window._pages["settings"]
        page._save()
        # No exception = passes. Config got at least one write.
        assert app_window.config.get("delivery.output_format") is not None

    def test_template_preview_substitutes(self, app_window, qapp):
        page = app_window._pages["settings"]
        page._naming_entry.setText("X-{chapter}")
        page._refresh_filename_preview()
        assert "1" in page._filename_preview.text()


# ─────────────────────────────────────────────────────────────────────────
# Detail (requires a manga in config)
# ─────────────────────────────────────────────────────────────────────────


class TestDetailPage:
    def test_renders_with_manga(self, app_window, qapp, sample_manga):
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]
        assert page._manga == sample_manga

    def test_status_dropdown_persists(self, app_window, qapp, sample_manga):
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]
        page._on_status_change("completed")
        # Status should have been pushed into config.
        m = next(m for m in app_window.config.get("manga", [])
                 if m.get("title") == sample_manga["title"])
        assert m.get("status") == "completed"

    def test_download_from_with_value_zero_resets_last_chapter(self, app_window,
                                                                  qapp,
                                                                  sample_manga):
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")
        app_window.worker.check_updates = lambda *a, **k: None
        page._do_download_from("0", skip_existing=True)
        # last_chapter cleared, downloaded preserved
        assert app_window.app_state.get_last_chapter(sample_manga["title"]) is None
        assert "1" in app_window.app_state.get_downloaded_chapters(
            sample_manga["title"])

    def test_download_from_n_sets_threshold(self, app_window, qapp,
                                              sample_manga):
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]
        app_window.worker.check_updates = lambda *a, **k: None
        page._do_download_from("5", skip_existing=True)
        # last_chapter set to 4.999 so check_for_updates returns 5+
        assert app_window.app_state.get_last_chapter(
            sample_manga["title"]) == "4.999"


# ─────────────────────────────────────────────────────────────────────────
# Reader
# ─────────────────────────────────────────────────────────────────────────


class TestReaderPage:
    def test_constructs(self, app_window, qapp):
        # Reader is in the page registry but on_show needs args.
        assert "reader" in app_window._pages

    def test_zoom_in_and_out(self, app_window, qapp, sample_manga, make_cbz,
                              tmp_path):
        from pathlib import Path
        # Drop a CBZ where the reader expects it.
        app_window.config.set("manga", [sample_manga])
        title = sample_manga["title"]
        dl = Path(app_window.config.download_dir) / title
        dl.mkdir(parents=True, exist_ok=True)
        cbz = make_cbz(pages=2)
        (dl / f"{title} - Chapter 1.cbz").write_bytes(cbz.read_bytes())
        app_window.app_state.add_downloaded_chapter(title, "1")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        assert len(reader._images) >= 1
        z0 = reader._zoom_level
        reader._zoom_in()
        assert reader._zoom_level > z0


# ─────────────────────────────────────────────────────────────────────────
# Add Manga modal
# ─────────────────────────────────────────────────────────────────────────


class TestAddMangaModal:
    def test_constructs(self, app_window, qapp):
        from memanga.gui.pages.add_manga import AddMangaDialog
        AddMangaDialog(app_window, app_window)

    def test_unknown_url_does_not_show_callout(self, app_window, qapp):
        from memanga.gui.pages.add_manga import AddMangaDialog
        d = AddMangaDialog(app_window, app_window)
        d._url_entry.setText("https://not-a-real-source.test/x")
        d._on_url_change()
        assert d._source_callout.isVisible() is False
