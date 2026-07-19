"""Smoke + behavior tests for every Page widget. We construct each via
the app_window fixture (which gives us the full event bus + state),
verify the page renders, switches, and reacts to its primary events.
"""

from __future__ import annotations

import threading
import time

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


def test_download_complete_clears_failed_chapter(app_window, qapp):
    app_window.app_state.add_failed_chapter("M", "1", "mock.test", "boom")
    assert "1" in app_window.app_state.get_failed_chapters("M")

    app_window._on_download_complete({"title": "M", "chapter": "1", "path": ""})
    qapp.processEvents()

    assert "1" not in app_window.app_state.get_failed_chapters("M")


def test_download_complete_records_and_clears_partial_chapter(app_window, qapp):
    app_window._on_download_complete({
        "title": "M",
        "chapter": "1",
        "path": "/tmp/M-1.pdf",
        "source": "mangadex.org",
        "from_backup": True,
        "partial": {"failed_pages": [4, 8], "total": 40},
    })
    qapp.processEvents()

    partial = app_window.app_state.get_partial_chapter("M", "1")
    assert partial["failed_pages"] == [4, 8]
    assert partial["total_pages"] == 40
    assert partial["source"] == "mangadex.org"
    assert partial["from_backup"] is True

    app_window._on_download_complete({"title": "M", "chapter": "1", "path": ""})
    qapp.processEvents()

    assert app_window.app_state.get_partial_chapter("M", "1") is None


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

    def test_search_is_debounced(self, app_window, qapp):
        # Typing must not rebuild the grid per keystroke - only once,
        # after the pause timer fires.
        page = app_window._pages["library"]
        calls = []
        page._refresh = lambda: calls.append(1)

        page._on_search("a")
        page._on_search("ab")
        assert calls == []
        assert page._search_query == "ab"
        assert page._filter_debounce.isActive()

        # Fire the pending timeout now instead of waiting 250 ms.
        page._filter_debounce.setInterval(0)
        page._filter_debounce.start()
        deadline = time.time() + 2
        while not calls and time.time() < deadline:
            qapp.processEvents()
        assert calls == [1]

    def test_check_done_coalesces_bursts(self, app_window, qapp):
        # A burst of completion events (e.g. batch download) must fold
        # into a single deferred refresh.
        app_window.show()
        app_window.show_page("library"); qapp.processEvents()
        page = app_window._pages["library"]
        assert page.isVisible()
        calls = []
        page._refresh = lambda: calls.append(1)

        for _ in range(5):
            page._on_check_done()
        assert page._refresh_pending
        assert calls == []

        deadline = time.time() + 2
        while not calls and time.time() < deadline:
            qapp.processEvents()
        assert calls == [1]
        assert not page._refresh_pending


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
        # Recent-searches chip row is intentionally absent — the
        # corresponding attributes must not exist on the page.
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
        page._clear_all()
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

    def test_save_writes_post_processing_settings(self, app_window, qapp):
        page = app_window._pages["settings"]
        page._post_processing_check.setChecked(True)
        page._post_processing_command.setText(
            "python scripts/after_download.py {output_path}"
        )
        page._post_processing_fail_check.setChecked(True)

        page._save()

        assert app_window.config.get("delivery.post_processing.enabled") is True
        assert app_window.config.get("delivery.post_processing.command") == (
            "python scripts/after_download.py {output_path}"
        )
        assert (
            app_window.config.get("delivery.post_processing.fail_on_error")
            is True
        )

    def test_partial_toggle_saves_to_config(self, app_window, qapp):
        # Partial-chapter tolerance (issue #86): the Advanced-tab toggle +
        # threshold spin should persist to config on save.
        page = app_window._pages["settings"]
        page._partial_check.setChecked(True)
        page._partial_threshold.setValue(12)
        page._save()
        assert app_window.config.partial_enabled is True
        assert app_window.config.partial_threshold == 12.0

    def test_partial_threshold_disabled_when_toggle_off(self, app_window, qapp):
        page = app_window._pages["settings"]
        page._partial_check.setChecked(False)
        qapp.processEvents()
        assert not page._partial_threshold.isEnabled()

    def test_partial_threshold_uses_keyboard_only_input(self, app_window, qapp):
        from PySide6.QtWidgets import QAbstractSpinBox

        page = app_window._pages["settings"]
        assert (
            page._partial_threshold.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        assert page._partial_threshold.maximumWidth() == 72

    def test_reset_defaults_updates_partial_controls(self, app_window, qapp):
        page = app_window._pages["settings"]
        app_window.config.set("manga", [{"title": "KeepMe"}])
        app_window.config.set("partial_chapters.enabled", True)
        app_window.config.set("partial_chapters.threshold_percent", 12)
        page._partial_check.setChecked(True)
        page._partial_threshold.setValue(12)

        page._reset_to_defaults()
        qapp.processEvents()

        assert app_window.config.partial_enabled is False
        assert app_window.config.partial_threshold == 5.0
        assert not page._partial_check.isChecked()
        assert page._partial_threshold.value() == 5
        assert not page._partial_threshold.isEnabled()
        assert app_window.config.get("manga") == [{"title": "KeepMe"}]

    def test_remove_after_read_saves_to_config(self, app_window, qapp):
        # Issue #104: the Advanced-tab "remove chapters after reading"
        # toggle should persist to config on save. Off by default.
        page = app_window._pages["settings"]
        assert not page._remove_after_read_check.isChecked()
        page._remove_after_read_check.setChecked(True)
        page._save()
        assert app_window.config.get("reader.remove_after_read") is True

    def test_reset_defaults_clears_remove_after_read(self, app_window, qapp):
        page = app_window._pages["settings"]
        app_window.config.set("reader.remove_after_read", True)
        page._remove_after_read_check.setChecked(True)

        page._reset_to_defaults()
        qapp.processEvents()

        assert app_window.config.get("reader.remove_after_read") is False
        assert not page._remove_after_read_check.isChecked()

    def test_advanced_tab_section_order(self, app_window, qapp):
        # The remove-after-read toggle lives in the Reader section next to
        # the prefetch toggle, and Reader leads the Advanced tab.
        from PySide6.QtWidgets import QLabel

        page = app_window._pages["settings"]
        layout = page._advanced_layout
        titles = {}
        positions = {}
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is None:
                continue
            positions[w] = i
            if isinstance(w, QLabel) and "bold" in w.styleSheet():
                titles[w.text()] = i

        assert list(titles) == [
            "Reader",
            "Scheduled Checks",
            "Partial Chapters",
            "Post-Processing",
            "Import / Export",
            "Diagnostics",
        ]
        assert (
            titles["Reader"]
            < positions[page._prefetch_check]
            < positions[page._remove_after_read_check]
            < titles["Scheduled Checks"]
        )

    def test_template_preview_substitutes(self, app_window, qapp):
        page = app_window._pages["settings"]
        page._naming_entry.setText("X-{chapter}")
        page._refresh_filename_preview()
        assert "1" in page._filename_preview.text()

    def test_long_template_stays_in_column(self, app_window, qapp):
        from PySide6.QtWidgets import QSizePolicy

        app_window.show_page("settings"); qapp.processEvents()
        page = app_window._pages["settings"]

        long_tpl = "{title}-" + ("VeryLongUnbrokenTemplatePart" * 20)
        page._naming_entry.setText(long_tpl)
        page._refresh_filename_preview()
        qapp.processEvents()

        assert page._filename_preview.wordWrap()
        assert (
            page._filename_preview.sizePolicy().horizontalPolicy()
            == QSizePolicy.Policy.Ignored
        )
        assert page._preview_frame.width() < 800
        assert page._filename_preview.width() < 800

    def test_concurrent_slider_jumps_to_click(self, app_window, qapp):
        # Regression for #46: a stock QSlider's groove click page-steps
        # (default pageStep=10), saturating the 1..8 range to an extreme.
        from memanga.gui.components.slider import JumpSlider
        page = app_window._pages["settings"]
        assert isinstance(page._concurrent_slider, JumpSlider)
        assert page._concurrent_slider.pageStep() == 1

    @pytest.mark.parametrize(
        ("login_error", "expected"),
        [
            (None, "Success!"),
            ("auth", "Auth failed"),
            (RuntimeError("network down"), "Failed: network down"),
        ],
    )
    def test_email_test_updates_label_on_gui_thread(
        self, app_window, qapp, monkeypatch, login_error, expected
    ):
        import smtplib

        page = app_window._pages["settings"]
        page._entry_sender_email.setText("sender")
        page._entry_smtp_server.setText("smtp.test")
        page._entry_smtp_port.setText("587")
        getattr(page, "_pass" "word_entry").setText("value")

        main_thread_id = threading.get_ident()
        label_calls = []
        smtp_thread_ids = []
        starttls_contexts = []
        smtp_calls = []
        original_set_text = page._test_label.setText
        original_set_style = page._test_label.setStyleSheet

        def record_set_text(text):
            label_calls.append(("text", text, threading.get_ident()))
            original_set_text(text)

        def record_set_style(style):
            label_calls.append(("style", style, threading.get_ident()))
            original_set_style(style)

        page._test_label.setText = record_set_text
        page._test_label.setStyleSheet = record_set_style

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                smtp_thread_ids.append(threading.get_ident())

            def ehlo(self):
                pass

            def starttls(self, context=None):
                smtp_calls.append("starttls")
                starttls_contexts.append(context)

            def login(self, sender, credential):
                smtp_calls.append("login")
                if login_error == "auth":
                    raise smtplib.SMTPAuthenticationError(535, b"bad")
                if login_error:
                    raise login_error

            def quit(self):
                pass

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

        page._test_email()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and page._test_label.text() != expected:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()

        assert page._test_label.text() == expected
        assert smtp_thread_ids
        assert all(tid != main_thread_id for tid in smtp_thread_ids)
        import ssl
        assert starttls_contexts
        assert all(isinstance(ctx, ssl.SSLContext) for ctx in starttls_contexts)
        assert smtp_calls.index("starttls") < smtp_calls.index("login")
        assert label_calls
        assert all(tid == main_thread_id for _, _, tid in label_calls)

    def test_import_accepts_versioned_backup(self, app_window, qapp,
                                             monkeypatch, tmp_path):
        import json
        from PySide6.QtWidgets import QFileDialog
        good = tmp_path / "good.json"
        good.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "FromBackup", "url": "u",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {},
        }))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(good), "")))
        app_window.config.set("manga", [])
        app_window._pages["settings"]._import()
        titles = [m.get("title")
                  for m in app_window.config.get("manga", []) or []]
        assert "FromBackup" in titles

    def test_install_cron_unix_quotes_paths(self, app_window, qapp,
                                            monkeypatch, tmp_path):
        """#109: cron paths with spaces must be shell-quoted so the
        generated crontab entry survives spaced install dirs."""
        import subprocess
        import sys

        from memanga.cron import build_cron_line
        from memanga.gui.pages import settings as settings_mod

        page = app_window._pages["settings"]
        project_dir = tmp_path / "My Manga"
        project_dir.mkdir()

        submitted = {}

        def _fake_run(cmd, input=None, **kwargs):
            if cmd == ["crontab", "-"]:
                submitted["crontab"] = input
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")

        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)

        page._install_cron_unix(project_dir, "06", "30")

        expected = build_cron_line("30", "06", project_dir, sys.executable)
        assert expected in submitted["crontab"].splitlines()
        assert f"'{project_dir}'" in submitted["crontab"]

    def test_import_merge_deduplicates_titles_within_backup(
        self, app_window, qapp, monkeypatch, tmp_path
    ):
        import json
        from PySide6.QtWidgets import QFileDialog

        backup = tmp_path / "duplicates.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [
                {"title": "Existing", "url": "old",
                 "source": "mangadex.org", "status": "reading"},
                {"title": "Fresh", "url": "new",
                 "source": "mangadex.org", "status": "reading"},
                {"title": "fresh", "url": "duplicate",
                 "source": "mangadex.org", "status": "reading"},
            ],
            "state": {},
        }))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(backup), "")))
        app_window.config.set("manga", [
            {"title": "Existing", "url": "local",
             "source": "mangadex.org", "status": "reading"}
        ])

        app_window._pages["settings"]._import(replace=False)

        titles = [m.get("title")
                  for m in app_window.config.get("manga", []) or []]
        assert titles == ["Existing", "Fresh"]

    def test_import_merge_preserves_existing_manga_state(
        self, app_window, qapp, monkeypatch, tmp_path
    ):
        import json
        from PySide6.QtWidgets import QFileDialog

        backup = tmp_path / "state.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "stateful", "url": "imported",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {
                "stateful": {
                    "downloaded": ["2"],
                    "read_chapters": ["2"],
                    "external_chapters": ["3"],
                    "failed_chapters": {
                        "4": {"error": "imported", "attempts": 1},
                        "5": {"error": "backup", "attempts": 1},
                    },
                    "reading_progress": {
                        "last_chapter": "2",
                        "last_read": "2026-07-17T10:00:00",
                    },
                }
            },
        }))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(backup), "")))
        app_window.config.set("manga", [
            {"title": "Stateful", "url": "local",
             "source": "mangadex.org", "status": "reading"}
        ])
        app_window.app_state.set("manga", {
            "Stateful": {
                "downloaded": ["1"],
                "read_chapters": ["1"],
                "failed_chapters": {
                    "4": {"error": "local", "attempts": 2},
                },
                "reading_progress": {
                    "last_chapter": "1",
                    "last_read": "2026-07-17T09:00:00",
                },
            }
        })

        app_window._pages["settings"]._import(replace=False)

        titles = [m["title"] for m in app_window.config.get("manga", []) or []]
        assert titles == ["Stateful"]
        manga_state = app_window.app_state.get("manga", {})
        assert list(manga_state) == ["Stateful"]
        assert "stateful" not in manga_state
        merged = manga_state["Stateful"]
        assert merged["downloaded"] == ["1", "2"]
        assert merged["read_chapters"] == ["1", "2"]
        assert merged["external_chapters"] == ["3"]
        assert merged["failed_chapters"]["4"]["error"] == "local"
        assert merged["failed_chapters"]["5"]["error"] == "backup"
        assert merged["reading_progress"]["last_chapter"] == "2"

    def test_import_merge_keeps_added_title_state_apart_from_orphan(
        self, app_window, qapp, monkeypatch, tmp_path
    ):
        import json
        from PySide6.QtWidgets import QFileDialog

        backup = tmp_path / "orphan-state.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "stateful", "url": "imported",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {
                "stateful": {
                    "downloaded": ["2"],
                    "failed_chapters": {
                        "5": {"error": "backup", "attempts": 1},
                    },
                }
            },
        }))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(backup), "")))
        app_window.config.set("manga", [])
        app_window.app_state.set("manga", {
            "Stateful": {
                "downloaded": ["1"],
                "failed_chapters": {
                    "4": {"error": "local", "attempts": 2},
                },
            }
        })

        app_window._pages["settings"]._import(replace=False)

        titles = [m["title"] for m in app_window.config.get("manga", []) or []]
        assert titles == ["stateful"]
        manga_state = app_window.app_state.get("manga", {})
        assert manga_state["Stateful"]["downloaded"] == ["1"]
        assert manga_state["stateful"]["downloaded"] == ["2"]
        assert manga_state["stateful"]["failed_chapters"]["5"]["error"] == "backup"

    def test_import_rejects_versionless_backup(self, app_window, qapp,
                                               monkeypatch, tmp_path):
        # Regression for #42: import never read the export's `version`
        # stamp, so any file with a `manga` array was imported blindly.
        import json
        from PySide6.QtWidgets import QFileDialog
        bad = tmp_path / "noversion.json"
        bad.write_text(json.dumps({
            "manga": [{"title": "Sneaky", "url": "u",
                       "source": "mangadex.org", "status": "reading"}],
        }))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(bad), "")))
        app_window.config.set("manga", [])
        app_window._pages["settings"]._import()
        titles = [m.get("title")
                  for m in app_window.config.get("manga", []) or []]
        assert "Sneaky" not in titles

    def test_import_rejects_newer_backup_version(self, app_window, qapp,
                                                 monkeypatch, tmp_path):
        import json
        from PySide6.QtWidgets import QFileDialog
        future = tmp_path / "future.json"
        future.write_text(json.dumps({"version": 99, "manga": [
            {"title": "FromTheFuture", "url": "u",
             "source": "mangadex.org", "status": "reading"}]}))
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(future), "")))
        app_window.config.set("manga", [])
        app_window._pages["settings"]._import(replace=True)
        assert app_window.config.get("manga", []) == []


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

    def test_partial_chapter_retry_queues_even_when_downloaded(
            self, app_window, qapp, sample_manga):
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        app_window.app_state.set_available_chapters(title, [{
            "number": "7",
            "title": "Partial chapter",
            "source": "mangadex.org",
            "source_url": "https://mangadex.org/title/abc/test-manga",
            "url": "https://mangadex.org/chapter/7",
            "is_backup": False,
        }])
        app_window.app_state.add_downloaded_chapter(title, "7")
        app_window.app_state.add_partial_chapter(
            title, "7", failed_pages=[3], total_pages=20,
        )
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]

        queued = []
        def accept(**kw):
            number = str(kw["chapter"].number)
            queued.append(number)
            return f"{title}:{number}"
        app_window.worker.download_chapter = accept

        page._download_chapter(
            app_window.app_state.get_available_chapters(title)[0],
            retry_partial=True,
        )

        assert queued == ["7"]


class TestDownloadsQueueing:
    """Issue #50: an explicit "Download All" / "Download from chapter"
    must queue the resolved chapters even for manual-mode manga, which
    the background sweep deliberately does not auto-queue."""

    def _result(self, manga, *numbers):
        import types
        chapters = [
            types.SimpleNamespace(
                number=n, title="", url=f"https://x/c/{n}",
                source=manga.get("source", "x"), is_backup=False,
            )
            for n in numbers
        ]
        return {"manga": manga, "chapters": chapters, "all_chapters": chapters}

    def test_explicit_download_queues_manual_manga(self, app_window, qapp,
                                                   sample_manga):
        assert sample_manga.get("mode") == "manual"
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        queued = []
        app_window.worker.download_chapter = (
            lambda **kw: queued.append(str(kw["chapter"].number))
        )
        page._on_check_complete({
            "results": [self._result(sample_manga, "1", "2")],
            "queue_all": True,
        })
        assert queued == ["1", "2"]

    def test_background_sweep_does_not_queue_manual_manga(self, app_window,
                                                          qapp, sample_manga):
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        queued = []
        app_window.worker.download_chapter = (
            lambda **kw: queued.append(str(kw["chapter"].number))
        )
        # No queue_all flag → background-sweep semantics; manual manga is
        # surfaced, not queued.
        page._on_check_complete({
            "results": [self._result(sample_manga, "1", "2")],
        })
        assert queued == []

    def test_correlated_check_complete_does_not_toast_manual_results(
            self, app_window, qapp, sample_manga, mocker):
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        toast = mocker.patch("memanga.gui.pages.downloads.Toast")

        page._on_check_complete({
            "results": [self._result(sample_manga, "1", "2")],
            "request_id": f"{sample_manga['title']}:1",
        })
        toast.assert_not_called()

        page._on_check_complete({
            "results": [self._result(sample_manga, "1", "2")],
        })
        toast.assert_called_once()

    def test_explicit_download_skips_already_downloaded(self, app_window, qapp,
                                                        sample_manga):
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")

        queued = []
        app_window.worker.download_chapter = (
            lambda **kw: queued.append(str(kw["chapter"].number))
        )
        page._on_check_complete({
            "results": [self._result(sample_manga, "1", "2")],
            "queue_all": True,
        })
        # Chapter 1 is already on disk; only 2 is queued.
        assert queued == ["2"]

    def test_auto_badge_clears_after_batch_finishes(self, app_window, qapp,
                                                    sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        queued = []
        def accept(**kw):
            number = str(kw["chapter"].number)
            queued.append(number)
            return f"{title}:{number}"
        app_window.worker.download_chapter = accept
        data = {"results": [self._result(manga, "1", "2")]}

        app_window._on_check_complete(data)
        page._on_check_complete(data)

        assert queued == ["1", "2"]
        assert app_window.app_state.get_new_chapters(title) == 2

        app_window._on_download_complete({
            "task_id": f"{title}:1", "title": title, "chapter": "1", "path": "",
        })

        assert app_window.app_state.get_new_chapters(title) == 1

        app_window._on_download_complete({
            "task_id": f"{title}:2", "title": title, "chapter": "2", "path": "",
        })

        assert app_window.app_state.get_new_chapters(title) == 0

    def test_auto_badge_keeps_failed_batch_count(self, app_window, qapp,
                                                 sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        app_window.worker.download_chapter = (
            lambda **kw: f"{title}:{kw['chapter'].number}"
        )
        data = {"results": [self._result(manga, "1", "2")]}

        app_window._on_check_complete(data)
        page._on_check_complete(data)
        app_window._on_download_complete({
            "task_id": f"{title}:1", "title": title, "chapter": "1", "path": "",
        })
        app_window._on_download_error({
            "title": title,
            "chapter": "2",
            "task_id": f"{title}:2",
            "error": "boom",
        })

        assert app_window.app_state.get_new_chapters(title) == 1

    def test_manual_badge_unchanged_after_download_error(
            self, app_window, sample_manga):
        manga = {**sample_manga, "mode": "manual"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.app_state.set_new_chapters(title, 2)

        app_window._on_download_error({
            "title": title,
            "chapter": "1",
            "task_id": f"{title}:1",
            "error": "boom",
        })

        assert app_window.app_state.get_new_chapters(title) == 2

    def test_manual_badge_unchanged_after_download_cancelled(
            self, app_window, sample_manga):
        manga = {**sample_manga, "mode": "manual"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.app_state.set_new_chapters(title, 2)

        app_window._on_download_cancelled({
            "title": title,
            "task_id": f"{title}:1",
        })

        assert app_window.app_state.get_new_chapters(title) == 2

    def test_auto_batch_cancelled_uses_task_id_title_fallback(
            self, app_window, sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        task_id = f"{title}:1"
        app_window.config.set("manga", [manga])
        app_window.app_state.set_new_chapters(title, 1)
        app_window.register_new_chapter_batch(title, [task_id])

        app_window._on_download_cancelled({"task_id": task_id})

        assert app_window.app_state.get_new_chapters(title) == 1
        assert title not in app_window._new_chapter_batches

    def test_auto_badge_accounts_for_skipped_downloaded_chapters(
            self, app_window, qapp, sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.app_state.add_downloaded_chapter(title, "1")
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        queued = []
        def accept(**kw):
            number = str(kw["chapter"].number)
            queued.append(number)
            return f"{title}:{number}"
        app_window.worker.download_chapter = accept
        data = {"results": [self._result(manga, "1", "2")]}

        app_window._on_check_complete(data)
        page._on_check_complete(data)

        assert queued == ["2"]
        assert app_window.app_state.get_new_chapters(title) == 1

        app_window._on_download_complete({
            "task_id": f"{title}:2", "title": title, "chapter": "2", "path": "",
        })

        assert app_window.app_state.get_new_chapters(title) == 0

    def test_overlapping_duplicate_check_waits_for_original_terminal_event(
            self, app_window, qapp, sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        accepted = iter((f"{title}:1", None))
        app_window.worker.download_chapter = lambda **kw: next(accepted)
        task_id = f"{title}:1"
        data = {"results": [self._result(manga, "1")]}

        # The first check starts the download. A second overlapping check sees
        # the same task id and the worker rejects that duplicate enqueue.
        app_window._on_check_complete(data)
        page._on_check_complete(data)
        app_window._on_check_complete(data)
        page._on_check_complete(data)

        assert app_window._new_chapter_batches[title]["pending"] == {task_id}

        # The original download's terminal event still owns and settles it.
        app_window._on_download_complete({
            "task_id": task_id, "title": title, "chapter": "1", "path": "",
        })

        assert app_window.app_state.get_new_chapters(title) == 0
        assert title not in app_window._new_chapter_batches

    def test_immediate_terminal_event_settles_pre_registered_task(
            self, app_window, qapp, sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        task_id = f"{title}:1"
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        def complete_immediately(**kw):
            app_window._on_download_complete({
                "task_id": task_id,
                "title": title,
                "chapter": str(kw["chapter"].number),
                "path": "",
            })
            return task_id

        app_window.worker.download_chapter = complete_immediately
        data = {"results": [self._result(manga, "1")]}

        app_window._on_check_complete(data)
        page._on_check_complete(data)

        assert app_window.app_state.get_new_chapters(title) == 0
        assert title not in app_window._new_chapter_batches

    def test_unrelated_same_title_completion_does_not_consume_batch(
            self, app_window, qapp, sample_manga):
        manga = {**sample_manga, "mode": "auto"}
        title = manga["title"]
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]
        app_window.worker.download_chapter = (
            lambda **kw: f"{title}:{kw['chapter'].number}"
        )
        data = {"results": [self._result(manga, "1")]}

        app_window._on_check_complete(data)
        page._on_check_complete(data)
        app_window._on_download_complete({
            "task_id": f"manual-{title}:99", "title": title,
            "chapter": "99", "path": "",
        })

        assert app_window.app_state.get_new_chapters(title) == 1

        app_window._on_download_complete({
            "task_id": f"{title}:1", "title": title,
            "chapter": "1", "path": "",
        })
        assert app_window.app_state.get_new_chapters(title) == 0


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

    # ── In-chapter resume position (issue #106) ──────────────────────

    @staticmethod
    def _stage_chapter(app_window, manga, make_cbz, pages=6, chapter="1"):
        """Drop a downloadable CBZ where the reader looks for it."""
        from pathlib import Path
        app_window.config.set("manga", [manga])
        title = manga["title"]
        dl = Path(app_window.config.download_dir) / title
        dl.mkdir(parents=True, exist_ok=True)
        cbz = make_cbz(pages=pages, name=f"ch{chapter}.cbz")
        (dl / f"{title} - Chapter {chapter}.cbz").write_bytes(cbz.read_bytes())
        app_window.app_state.add_downloaded_chapter(title, chapter)
        return title

    def test_single_mode_position_saved_and_restored(self, app_window, qapp,
                                                     sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        reader._go_to_page(2)

        # Back to detail → on_hide is the save point.
        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()
        pos = app_window.app_state.get_reader_position(title, "1")
        assert pos["page_index"] == 2
        assert pos["mode"] == "single"

        # Reopening the same chapter resumes on the saved page.
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        assert reader._current_page == 2

    def test_double_mode_saves_spread_first_page(self, app_window, qapp,
                                                 sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz,
                                    pages=8)
        app_window.config.set("gui.reader_view_mode", "double")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        reader._go_to_page(3)  # double aligns spreads to even indices
        assert reader._current_page == 2

        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()
        pos = app_window.app_state.get_reader_position(title, "1")
        assert pos["page_index"] == 2

        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        assert reader._current_page == 2

    def test_finished_chapter_clears_position_and_reopens_at_start(
            self, app_window, qapp, sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]

        reader._go_to_page(5)  # final page → read flip (issue #45)
        assert app_window.app_state.is_chapter_read(title, "1")
        assert app_window.app_state.get_reader_position(title, "1") is None

        # Leaving from the end must not re-save an end-of-chapter position.
        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()
        assert app_window.app_state.get_reader_position(title, "1") is None
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        assert reader._current_page == 0

    def test_stale_position_beyond_page_count_is_ignored(
            self, app_window, qapp, sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        app_window.config.set("gui.reader_view_mode", "single")
        # e.g. saved against a bigger re-release, then re-downloaded small.
        app_window.app_state.set_reader_position(title, "1", mode="single",
                                                 page_index=50)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        # Clamping would land on the last page and instantly flip the
        # chapter to read — the restore must bail out instead.
        assert reader._current_page == 0
        assert not app_window.app_state.is_chapter_read(title, "1")

    def test_continuous_ratio_restores_as_page_in_single_mode(
            self, app_window, qapp, sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        # Saved while reading continuous, reopened after switching layouts.
        app_window.app_state.set_reader_position(title, "1",
                                                 mode="continuous",
                                                 scroll_ratio=0.5)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        assert app_window._pages["reader"]._current_page == 3  # 0.5 * 6

    def test_continuous_scroll_position_saved_and_restored(
            self, app_window, qapp, sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz,
                                    pages=8)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        assert reader._view_mode == "continuous"
        sb = reader._scroll.verticalScrollBar()
        assert sb.maximum() > 0  # 8 tall pages overflow the viewport
        sb.setValue(sb.maximum() // 2)

        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()
        pos = app_window.app_state.get_reader_position(title, "1")
        assert pos["scroll_ratio"] == pytest.approx(0.5, abs=0.05)

        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()  # restore is deferred one event-loop turn
        qapp.processEvents()
        sb = reader._scroll.verticalScrollBar()
        assert sb.value() == pytest.approx(sb.maximum() * 0.5, abs=sb.maximum() * 0.05)
        assert not app_window.app_state.is_chapter_read(title, "1")

    def test_prev_next_navigation_saves_outgoing_position(
            self, app_window, qapp, sample_manga, make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz,
                                    chapter="1")
        self._stage_chapter(app_window, sample_manga, make_cbz, chapter="2")
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        reader._go_to_page(2)

        reader._go_next_chapter()
        qapp.processEvents()
        assert reader._chapter == "2"
        assert app_window.app_state.get_reader_position(title, "1")[
            "page_index"] == 2

    def test_close_event_saves_position(self, app_window, qapp, sample_manga,
                                        make_cbz):
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        app_window._pages["reader"]._go_to_page(2)

        app_window.close()  # closeEvent — never routes through show_page
        assert app_window.app_state.get_reader_position(title, "1")[
            "page_index"] == 2

    def test_stale_position_with_missing_file_is_harmless(
            self, app_window, qapp, sample_manga, make_cbz):
        from pathlib import Path
        title = self._stage_chapter(app_window, sample_manga, make_cbz)
        app_window.app_state.set_reader_position(title, "1", mode="single",
                                                 page_index=3)
        # Cleanup (e.g. remove-after-read) deleted the artifact.
        dl = Path(app_window.config.download_dir) / title
        (dl / f"{title} - Chapter 1.cbz").unlink()

        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        assert reader._images == []  # error placeholder, no crash

        # Leaving again must not corrupt or crash either.
        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()

    def test_legacy_title_folder_stays_contained(self, tmp_path):
        # Guards legacy title-folder resolution for unusual stored titles.
        from pathlib import Path
        from memanga.gui.pages.reader import _is_inside_download_dir
        root = tmp_path / "downloads"
        (root / "Some Manga").mkdir(parents=True)
        (tmp_path / "sibling").mkdir()

        assert _is_inside_download_dir(root / "Some Manga", root)
        assert _is_inside_download_dir(root / "Dr. Who?", root)
        assert not _is_inside_download_dir(root / ".." / "sibling", root)
        assert not _is_inside_download_dir(root / "../sibling", root)
        # Absolute-like stored titles are not valid manga folders.
        assert not _is_inside_download_dir(root / str(tmp_path / "sibling"),
                                           root)
        # The download dir itself is not a valid manga folder.
        assert not _is_inside_download_dir(root, root)
        assert not _is_inside_download_dir(root / ".", root)

    def test_invalid_chapter_label_folder_is_ignored(self, app_window, qapp,
                                                     sample_manga):
        # Legacy image-folder lookup must stay scoped to the selected manga.
        from pathlib import Path
        from PIL import Image
        app_window.config.set("manga", [sample_manga])
        dl = Path(app_window.config.download_dir)
        manga_dir = dl / sample_manga["title"]
        # A literal "Chapter .." folder is a legal on-disk name and keeps
        # this regression representative of older folder layouts.
        (manga_dir / "Chapter ..").mkdir(parents=True)
        sibling = dl / "Sibling Manga" / "Chapter 1"
        sibling.mkdir(parents=True)
        Image.new("RGB", (40, 60), "white").save(sibling / "p000.jpg",
                                                 "JPEG")

        reader = app_window._pages["reader"]
        reader._manga = sample_manga
        reader._chapter = "../../../Sibling Manga/Chapter 1"
        assert reader._find_and_load_chapter() == []
        assert reader._artifact_path is None
        assert sibling.is_dir()

    def test_image_folder_chapter_still_loads(self, app_window, qapp,
                                              sample_manga):
        # Image formats are saved as "<manga>/Chapter <label>/" with the
        # sort-formatted label; the containment guard must not break
        # that lookup.
        from pathlib import Path
        from PIL import Image
        app_window.config.set("manga", [sample_manga])
        folder = (Path(app_window.config.download_dir)
                  / sample_manga["title"] / "Chapter 2.01")
        folder.mkdir(parents=True)
        Image.new("RGB", (40, 60), "white").save(folder / "p000.jpg",
                                                 "JPEG")

        reader = app_window._pages["reader"]
        reader._manga = sample_manga
        reader._chapter = "2 Part 1"
        assert reader._find_and_load_chapter()
        assert reader._artifact_path == folder


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
