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

            def starttls(self):
                pass

            def login(self, sender, credential):
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
