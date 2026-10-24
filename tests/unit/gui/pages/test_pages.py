"""Smoke + behavior tests for every Page widget. We construct each via
the app_window fixture (which gives us the full event bus + state),
verify the page renders, switches, and reacts to its primary events.
"""

from __future__ import annotations

import threading
import time

import pytest


def _dialog_recorder(opened):
    """Stand-in for ErrorDetailsDialog that records instead of blocking."""
    class _Dialog:
        def __init__(self, parent, details, summary="", title="Error details",
                     **kwargs):
            self._args = dict(details=details, summary=summary, title=title,
                              **kwargs)

        def exec(self):
            opened.append(self._args)
    return _Dialog


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


def test_download_complete_leaves_records_and_history_to_pipeline(
        app_window, qapp):
    # Issues #295, #240: the worker's chapter pipeline writes the chapter
    # records and the download history before it publishes
    # download_complete; the handler must not write a second set.
    app_window.app_state.add_failed_chapter("M", "1", "mock.test", "boom")
    history_before = len(app_window.app_state.get("download_history", []))

    app_window._on_download_complete({"title": "M", "chapter": "1", "path": ""})
    qapp.processEvents()

    history = app_window.app_state.get("download_history", [])
    assert len(history) == history_before
    assert any(n["message"] == "Downloaded M Ch. 1"
               for n in app_window.app_state.get("notifications", []))
    assert "1" in app_window.app_state.get_failed_chapters("M")
    assert not app_window.app_state.is_chapter_downloaded("M", "1")


def test_download_complete_partial_adds_no_second_warning(app_window, qapp):
    # The pipeline already added the partial warning.
    notes_before = len(app_window.app_state.get("notifications", []))

    app_window._on_download_complete({
        "title": "M",
        "chapter": "1",
        "path": "/tmp/M-1.pdf",
        "source": "mangadex.org",
        "from_backup": True,
        "partial": {"failed_pages": [4, 8], "total": 40},
    })
    qapp.processEvents()

    assert len(app_window.app_state.get("notifications", [])) == notes_before
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
    def test_check_error_toast_is_short_and_redacted(
            self, app_window, qapp, monkeypatch, isolated_home):
        # Issue #342: the toast is a summary pointing to Notifications.
        from memanga.gui.pages import downloads as downloads_mod
        toasts = []
        monkeypatch.setattr(downloads_mod, "Toast",
                            lambda parent, text, kind="info", **k:
                            toasts.append((text, kind)))
        page = app_window._pages["downloads"]
        title = f"{isolated_home}/Manga/Title " + "t" * 80
        error = ("HTTPSConnectionPool(host='127.0.0.1', port=9): Max retries "
                 "exceeded password=hunter22 (Caused by NewConnectionError("
                 "'Connection refused'))")
        page._on_check_error({"title": title, "error": error})

        (text, kind), = toasts
        assert kind == "error"
        assert text.startswith("Error: ~/Manga/")
        assert text.endswith("(details in Notifications)")
        assert str(isolated_home) not in text and "hunter22" not in text
        assert len(text) < 140

        page._on_check_error({"title": "T", "error": error, "request_id": 1})
        assert len(toasts) == 1

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

    def test_source_failures_open_on_request(self, app_window, qapp,
                                              monkeypatch):
        # Issue #342: why sources failed is one click away, redacted and
        # whole, and is never turned into notifications.
        from memanga.gui.pages import search as search_mod
        opened = []
        monkeypatch.setattr(search_mod, "ErrorDetailsDialog",
                            _dialog_recorder(opened))
        page = app_window._pages["search"]
        assert page._failures_btn.isHidden()
        before = len(app_window.app_state.get_notifications())
        cause = ("SSLError: HTTPSConnectionPool(host='a.test', port=443): "
                 "Max retries exceeded with url: /search?q=x&token=abc123 "
                 "(Caused by SSLError(SSLCertVerificationError(1, "
                 "'certificate verify failed: certificate has expired')))")
        page._on_source_failed({"source": "a.test", "seq": -1, "error": cause})
        page._on_source_failed({"source": "b.test", "seq": -1,
                                "error": "RuntimeError: blocked (HTTP 403)"})

        assert not page._failures_btn.isHidden()
        assert page._failures_btn.accessibleName()
        page._failures_btn.click()
        text = opened[0]["details"]
        assert "certificate has expired" in text
        assert "b.test: RuntimeError: blocked (HTTP 403)" in text
        assert "abc123" not in text
        assert opened[0]["summary"] == "2 sources failed in this search."
        assert opened[0]["complete"] is True
        assert len(app_window.app_state.get_notifications()) == before

    def test_long_source_failures_are_bounded_and_marked_partial(
            self, app_window, qapp, monkeypatch):
        # Issue #342: a long cause is kept whole up to the per-source
        # bound; past it the cut is marked and the dialog says partial.
        from memanga.gui.pages import search as search_mod
        opened = []
        monkeypatch.setattr(search_mod, "ErrorDetailsDialog",
                            _dialog_recorder(opened))
        page = app_window._pages["search"]
        within = "a" * 15_000 + " CAUSE: certificate has expired"
        beyond = "b" * (search_mod.SOURCE_ERROR_MAX_CHARS + 50) + " LOST TAIL"
        page._on_source_failed({"source": "a.test", "seq": -1, "error": within})
        page._on_source_failed({"source": "b.test", "seq": -1, "error": beyond})
        page._failures_btn.click()

        args = opened[0]
        assert "a.test: " + within in args["details"]
        assert "LOST TAIL" not in args["details"]
        assert "more characters cut]" in args["details"]
        assert args["complete"] is False
        assert "1 of these errors is shortened" in args["notice"]

    def test_search_failure_total_is_bounded(self, app_window, qapp):
        from memanga.gui.pages import search as search_mod
        page = app_window._pages["search"]
        error = "c" * search_mod.SOURCE_ERROR_MAX_CHARS
        sources = search_mod.SEARCH_ERRORS_MAX_CHARS // len(error) + 2
        for i in range(sources):
            page._on_source_failed({"source": f"s{i}.test", "seq": -1,
                                    "error": error})
        kept = sum(len(e) for _, e in page._sources_failed)
        assert page._failures_kept_chars == search_mod.SEARCH_ERRORS_MAX_CHARS
        assert kept < search_mod.SEARCH_ERRORS_MAX_CHARS + 100 * sources
        assert page._failures_cut == 2

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

    def test_error_details_open_from_the_row(self, app_window, qapp,
                                             monkeypatch):
        # Issue #342: a shortened error has a keyboard-reachable Details
        # button that opens the complete error.
        from PySide6.QtCore import Qt
        from memanga.gui.pages import notifications as page_mod
        full = ("All sources failed for 'T': src.test: HTTPSConnectionPool("
                "host='127.0.0.1', port=9): Max retries exceeded with url: /x "
                "(Caused by NewConnectionError('Connection refused'))")
        app_window.app_state.add_notification(
            "error", "Check failed: T - All sources failed for 'T': src.test…",
            details=full)
        app_window.app_state.add_notification("download", "Saved <b>Ch. 1</b>")
        opened = []
        monkeypatch.setattr(page_mod, "ErrorDetailsDialog",
                            _dialog_recorder(opened))

        page = app_window._pages["notifications"]
        page._refresh()
        rows = page.findChildren(page_mod.NotificationRow)
        error_row = next(r for r in rows if r._details == full)
        assert all(r._details_btn is None for r in rows if not r._details)
        btn = error_row._details_btn
        assert btn.text() == "Details"
        assert "details" in btn.accessibleName().lower()
        assert btn.focusPolicy() & Qt.FocusPolicy.TabFocus
        btn.click()
        assert len(opened) == 1
        assert opened[0]["details"] == full
        assert opened[0]["summary"] == (
            "Check failed: T - All sources failed for 'T': src.test…")
        assert opened[0]["complete"] is True

        # Messages are shown literally, never as rich text.
        from PySide6.QtWidgets import QLabel
        texts = [lbl for lbl in page.findChildren(QLabel)
                 if lbl.text() == "Saved <b>Ch. 1</b>"]
        assert texts and texts[0].textFormat() == Qt.TextFormat.PlainText


    def test_long_error_details_open_whole_from_side_file(
            self, app_window, qapp, monkeypatch):
        # Issue #342: an error past the inline preview still opens whole,
        # actionable tail included.
        from memanga.gui.pages import notifications as page_mod
        from memanga.output import DETAIL_MAX_CHARS
        full = "x" * (DETAIL_MAX_CHARS + 300) + " CAUSE: certificate expired"
        app_window.app_state.add_notification("error", "Failed: T - x…",
                                              details=full)
        opened = []
        monkeypatch.setattr(page_mod, "ErrorDetailsDialog",
                            _dialog_recorder(opened))

        page = app_window._pages["notifications"]
        page._refresh()
        row = next(r for r in page.findChildren(page_mod.NotificationRow)
                   if r._notif.get("details_chars"))
        row._details_btn.click()

        assert opened[0]["details"] == full
        assert opened[0]["complete"] is True
        assert opened[0]["total_chars"] == len(full)


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

    @pytest.fixture
    def toasts(self, monkeypatch):
        from memanga.gui.pages import settings as settings_mod
        shown = []
        monkeypatch.setattr(settings_mod, "Toast",
                            lambda parent, message, **kw: shown.append((message, kw)))
        return shown

    def test_save_password_without_keyring_warns_with_path(
            self, app_window, qapp, monkeypatch, toasts):
        # Issue #247: the plaintext fallback is never silent in the app.
        import keyring

        def broken(*a):
            raise RuntimeError("no backend")
        monkeypatch.setattr(keyring, "set_password", broken)
        monkeypatch.setattr(keyring, "get_password", broken)
        page = app_window._pages["settings"]
        page._password_entry.setText("gui-secret-pw")
        page._save()

        cfg = app_window.config
        assert cfg.get("email.app_password") == "gui-secret-pw"
        assert len(toasts) == 1
        message, kw = toasts[0]
        assert kw.get("kind") == "warning"
        assert str(cfg.config_path) in message
        assert "plain text" in message
        assert "chmod 600" in message
        assert "gui-secret-pw" not in message

    def test_save_password_in_keyring_reports_success(
            self, app_window, qapp, monkeypatch, toasts):
        import keyring
        store = {}
        monkeypatch.setattr(keyring, "set_password",
                            lambda s, u, p: store.__setitem__((s, u), p))
        monkeypatch.setattr(keyring, "get_password",
                            lambda s, u: store.get((s, u)))
        page = app_window._pages["settings"]
        page._password_entry.setText("gui-secret-pw")
        page._save()

        assert store == {("memanga", "app_password"): "gui-secret-pw"}
        assert app_window.config.get("email.app_password") == ""
        assert toasts == [("Settings saved", {"kind": "success"})]

    @pytest.mark.parametrize("fmt", ["cbz", "zip", "jpg"])
    def test_save_kindle_with_unsupported_format_warns(
            self, app_window, qapp, toasts, fmt):
        # Issue #362: the settings are saved, but the user learns that
        # chapters in this format won't reach the Kindle.
        page = app_window._pages["settings"]
        page._radio_email.setChecked(True)
        page._format_combo.setCurrentText(fmt)
        page._save()

        cfg = app_window.config
        assert (cfg.delivery_mode, cfg.output_format) == ("email", fmt)
        assert len(toasts) == 1
        message, kw = toasts[0]
        assert kw.get("kind") == "warning"
        assert message.startswith("Settings saved.")
        assert "can't be sent to Kindle" in message
        assert "PDF or EPUB" in message

    @pytest.mark.parametrize("email, fmt", [
        (True, "pdf"), (True, "epub"), (False, "cbz"),
    ])
    def test_save_without_kindle_format_conflict_reports_success(
            self, app_window, qapp, toasts, email, fmt):
        page = app_window._pages["settings"]
        (page._radio_email if email else page._radio_local).setChecked(True)
        page._format_combo.setCurrentText(fmt)
        page._save()

        assert toasts == [("Settings saved", {"kind": "success"})]

    # Issue #345: which manga email delivery applies to.

    def test_kindle_scope_is_asked_only_for_email(self, app_window, qapp):
        page = app_window._pages["settings"]
        assert app_window.config.delivery_mode == "local"
        page._load_config_into_widgets()
        assert not page._radio_scope_selected.isEnabled()
        assert not page._radio_scope_all.isEnabled()
        page._radio_email.setChecked(True)
        assert page._radio_scope_selected.isEnabled()
        assert page._radio_scope_all.isEnabled()
        # Turning email on never proposes sending the whole library.
        assert page._radio_scope_selected.isChecked()

    def test_turning_email_on_saves_selected_scope(self, app_window, qapp,
                                                   toasts):
        page = app_window._pages["settings"]
        page._load_config_into_widgets()
        page._radio_email.setChecked(True)
        page._save()
        assert app_window.config.get("email.kindle_scope") == "selected"

    def test_every_manga_choice_is_saved(self, app_window, qapp, toasts):
        page = app_window._pages["settings"]
        page._radio_email.setChecked(True)
        page._radio_scope_all.setChecked(True)
        page._save()
        assert app_window.config.get("email.kindle_scope") == "all"

    def test_local_save_leaves_scope_unset(self, app_window, qapp, toasts):
        page = app_window._pages["settings"]
        page._radio_local.setChecked(True)
        page._save()
        assert app_window.config.get("email.kindle_scope") is None

    @pytest.mark.parametrize("stored, all_checked", [
        (None, True),          # email before the choice existed: every manga
        ("selected", False),
        ("all", True),
    ])
    def test_email_config_shows_its_scope(self, app_window, qapp, stored,
                                          all_checked):
        cfg = app_window.config
        cfg.set("delivery.mode", "email")
        if stored is not None:
            cfg.set("email.kindle_scope", stored)
        page = app_window._pages["settings"]
        page._load_config_into_widgets()
        assert page._radio_scope_all.isChecked() is all_checked
        assert page._radio_scope_selected.isChecked() is not all_checked

    @pytest.fixture
    def smtp_logins(self, monkeypatch):
        """Run the SMTP test synchronously against a fake server and
        record each login as (user, password)."""
        import smtplib
        import types
        from memanga.gui.pages import settings as settings_mod
        logins = []

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass

            def ehlo(self):
                pass

            def starttls(self, **k):
                pass

            def login(self, user, password):
                logins.append((user, password))

            def quit(self):
                pass

        class SyncThread:
            def __init__(self, target, daemon=None):
                self._target = target

            def start(self):
                self._target()
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(settings_mod, "threading",
                            types.SimpleNamespace(Thread=SyncThread))
        return logins

    def _fill_smtp_test(self, page, typed_password):
        page._entry_sender_email.setText("sender@example.invalid")
        page._entry_smtp_server.setText("smtp.example.invalid")
        page._entry_smtp_port.setText("587")
        page._password_entry.setText(typed_password)

    def test_smtp_test_uses_typed_password_without_override(
            self, app_window, qapp, smtp_logins):
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._test_email()
        assert smtp_logins == [("sender@example.invalid", "typed-pw")]
        assert page._test_label.text() == "Success!"

    def test_check_login_on_port_465_uses_implicit_tls(
            self, app_window, qapp, smtp_logins, monkeypatch):
        # Issue #366: with the default email.smtp_tls (auto), the typed
        # port picks the TLS mode, the same way delivery does.
        import smtplib
        from unittest.mock import MagicMock
        factory = MagicMock()
        monkeypatch.setattr(smtplib, "SMTP_SSL", factory)
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._entry_smtp_port.setText("465")
        page._test_email()
        assert smtp_logins == []  # no plain connection
        assert factory.call_args.args == ("smtp.example.invalid", 465)
        factory.return_value.login.assert_called_once_with(
            "sender@example.invalid", "typed-pw")
        assert page._test_label.text() == "Success!"

    @pytest.fixture
    def smtp_sends(self, smtp_logins, monkeypatch):
        """On top of smtp_logins: record each message sent."""
        import smtplib
        sent = []
        monkeypatch.setattr(smtplib.SMTP, "send_message",
                            lambda self, msg: sent.append(msg), raising=False)
        return sent

    def test_check_login_sends_nothing(self, app_window, qapp, smtp_sends,
                                       smtp_logins):
        # Issue #339: the quick check stays login-only, and says so.
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._entry_kindle_email.setText("reader@kindle.example.invalid")
        page._test_email()
        assert smtp_logins == [("sender@example.invalid", "typed-pw")]
        assert smtp_sends == []
        assert page._login_test_btn.text() == "Check Login"
        assert "Sends nothing" in page._login_test_btn.toolTip()

    @pytest.mark.parametrize("width", [1100, 800])
    def test_email_test_hint_is_not_clipped(self, app_window, qapp, width):
        # The wrapped hint gets the height its text needs and sits
        # between the checkbox and the test buttons without overlap.
        app_window.resize(width, 1000)
        app_window.show()
        app_window.show_page("settings")
        page = app_window._pages["settings"]
        page._switch_tab("email")
        for _ in range(5):
            qapp.processEvents()

        hint = page._test_hint
        assert hint.wordWrap()
        assert hint.height() >= hint.heightForWidth(hint.width())
        assert hint.height() > hint.fontMetrics().lineSpacing() * 2
        check = page._delete_after_check.geometry()
        buttons = page._login_test_btn.geometry()
        assert check.bottom() < hint.geometry().top()
        assert hint.geometry().bottom() < buttons.top()

    def test_email_test_hint_shrinks_when_widened(self, app_window, qapp):
        # The hint's height follows its width both ways: narrowing and
        # then widening gives back the height the text needs, not the
        # tallest height it ever had.
        app_window.show()
        app_window.show_page("settings")
        page = app_window._pages["settings"]
        page._switch_tab("email")
        hint = page._test_hint
        heights = {}
        for width in (1100, 800, 1500, 1100):
            app_window.resize(width, 1000)
            for _ in range(5):
                qapp.processEvents()
            need = hint.heightForWidth(hint.width())
            assert need <= hint.height() <= need + 1
            assert hint.minimumHeight() == 0
            assert hint.geometry().bottom() < page._login_test_btn.geometry().top()
            heights.setdefault(width, []).append(hint.height())
        assert heights[1500][0] < heights[800][0]
        assert heights[1100][0] == heights[1100][1]

    def test_email_tab_fits_minimum_window_width(self, app_window, qapp):
        # At the 900 px minimum window width the whole Email tab, the
        # guidance and a long test result fit in the viewport (the tab
        # never scrolls horizontally), and still do after a resize.
        from PySide6.QtCore import QPoint
        app_window.show()
        app_window.show_page("settings")
        page = app_window._pages["settings"]
        page._switch_tab("email")
        page._show_test_status(
            "Test PDF accepted; check your Kindle", "green")
        viewport = page._email_scroll.viewport()
        for width in (900, 1500, 900):
            app_window.resize(width, 1000)
            for _ in range(5):
                qapp.processEvents()
            assert page._email_scroll.widget().width() <= viewport.width()
            for widget in (page._entry_kindle_email, page._password_entry,
                           page._test_hint, page._login_test_btn,
                           page._send_test_btn, page._test_label):
                right = widget.mapTo(viewport, QPoint(widget.width(), 0)).x()
                assert right <= viewport.width()
            for label in (page._test_hint, page._test_label):
                assert label.height() >= label.heightForWidth(label.width())
            assert (page._test_hint.geometry().bottom()
                    < page._login_test_btn.geometry().top())
            assert (page._login_test_btn.geometry().bottom()
                    < page._test_label.geometry().top())

    def test_send_test_pdf_uses_typed_settings(
            self, app_window, qapp, smtp_sends, smtp_logins):
        # Issue #365 / #339: a real test document to the typed address.
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._entry_kindle_email.setText(" reader@kindle.example.invalid ")
        page._send_test_email()

        assert smtp_logins == [("sender@example.invalid", "typed-pw")]
        (msg,) = smtp_sends
        assert msg["To"] == "reader@kindle.example.invalid"
        (attachment,) = msg.get_payload()
        assert attachment.get_content_type() == "application/pdf"
        assert attachment.get_payload(decode=True).startswith(b"%PDF-")
        assert page._test_label.text() == "Test PDF accepted; check your Kindle"
        assert "does not prove" in page._test_label.toolTip()
        note = app_window.app_state.get_notifications()[0]
        assert note["type"] == "kindle"
        assert "does not prove" in note["details"]
        assert page._send_test_btn.isEnabled()
        assert page._login_test_btn.isEnabled()

    def test_send_test_pdf_uses_active_override(
            self, app_window, qapp, smtp_sends, smtp_logins, monkeypatch,
            tmp_path):
        # Issue #247: the password delivery will actually use.
        secret = tmp_path / "smtp_password"
        secret.write_text("file-pw\n", encoding="utf-8")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", str(secret))
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._entry_kindle_email.setText("reader@kindle.example.invalid")
        page._send_test_email()
        assert smtp_logins == [("sender@example.invalid", "file-pw")]
        assert len(smtp_sends) == 1

    def test_send_test_pdf_needs_kindle_email(
            self, app_window, qapp, smtp_sends, smtp_logins):
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._entry_kindle_email.setText("")
        page._send_test_email()
        assert page._test_label.text() == "Fill Kindle email"
        assert smtp_logins == [] and smtp_sends == []
        assert page._send_test_btn.isEnabled()

    def test_send_test_pdf_failure_is_redacted_and_reenables(
            self, app_window, qapp, smtp_logins, monkeypatch):
        import smtplib
        from memanga import output
        monkeypatch.setattr(output, "_secrets", set())

        def refuse(self, msg):
            raise smtplib.SMTPRecipientsRefused(
                {"reader@kindle.example.invalid":
                 (550, b"5.1.1 no such user, password typed-pw-4321")})
        monkeypatch.setattr(smtplib.SMTP, "send_message", refuse,
                            raising=False)
        monkeypatch.setattr(smtplib.SMTP, "close", lambda self: None,
                            raising=False)
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw-4321")
        page._entry_kindle_email.setText("reader@kindle.example.invalid")
        page._send_test_email()

        assert page._test_label.text().startswith("Failed: ")
        note = app_window.app_state.get_notifications()[0]
        assert note["message"].startswith("Email test failed - ")
        assert "550 5.1.1 no such user" in note["details"]
        for text in (page._test_label.text(), page._test_label.toolTip(),
                     note["message"], note["details"]):
            assert "typed-pw-4321" not in text
            assert "reader@kindle.example.invalid" not in text
        assert page._send_test_btn.isEnabled()
        assert page._login_test_btn.isEnabled()

    def test_smtp_test_uses_active_override(
            self, app_window, qapp, smtp_logins, monkeypatch, tmp_path):
        # Issue #247: test the password delivery will actually use.
        secret = tmp_path / "smtp_password"
        secret.write_text("file-pw\n", encoding="utf-8")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", str(secret))
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._test_email()
        assert smtp_logins == [("sender@example.invalid", "file-pw")]
        assert page._test_label.text() == "Success!"
        assert "MEMANGA_SMTP_PASSWORD_FILE" in page._test_label.toolTip()
        assert "file-pw" not in page._test_label.toolTip()

    def test_smtp_test_failure_keeps_full_redacted_detail(
            self, app_window, qapp, smtp_logins, monkeypatch):
        # Issue #342: a short label; the full server reply on hover and
        # in Notifications, without the password or the address.
        import smtplib
        from memanga import output
        monkeypatch.setattr(output, "_secrets", set())
        reply = ("Connection closed after credentials typed-pw-1234 for "
                 "sender@example.invalid: 421 4.7.0 Try again later, closing "
                 "connection. See https://help.example.invalid/smtp")

        class FailingSMTP:
            def __init__(self, *a, **k):
                pass

            def ehlo(self):
                pass

            def starttls(self, **k):
                pass

            def login(self, user, password):
                raise smtplib.SMTPServerDisconnected(reply)

            def quit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw-1234")
        page._test_email()

        label = page._test_label.text()
        assert label.startswith("Failed: ") and label.endswith("…")
        note = app_window.app_state.get_notifications()[0]
        assert note["message"].startswith("Email test failed - ")
        assert note["details"].endswith("See https://help.example.invalid/smtp")
        assert "help.example.invalid/smtp" in page._test_label.toolTip()
        for text in (label, page._test_label.toolTip(), note["message"],
                     note["details"]):
            assert "typed-pw-1234" not in text
            assert "sender@example.invalid" not in text

    def test_smtp_test_uses_configured_timeout_and_reports_timeout(
            self, app_window, qapp, smtp_logins, monkeypatch):
        # Issue #361: the Settings test shares the bounded login and says
        # when the server did not answer in time.
        import smtplib
        seen = {}

        class StalledSMTP:
            def __init__(self, host, port, timeout=None):
                seen["timeout"] = timeout
                try:
                    raise TimeoutError("timed out")
                except TimeoutError:
                    raise smtplib.SMTPServerDisconnected(
                        "Connection unexpectedly closed: timed out")

        monkeypatch.setattr(smtplib, "SMTP", StalledSMTP)
        app_window.config.set("email.smtp_timeout", 5)
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._test_email()
        assert seen == {"timeout": 5}
        assert page._test_label.text() == "Timed out"
        assert "within 5 seconds" in page._test_label.toolTip()

    def test_error_toast_short_with_full_redacted_notification(
            self, app_window, qapp, monkeypatch, isolated_home, caplog):
        # Issue #342: cron/task/export/import failures toast a summary;
        # the whole error goes to Notifications and the log.
        import logging
        from memanga.gui.pages import settings as settings_mod
        toasts = []
        monkeypatch.setattr(settings_mod, "Toast",
                            lambda parent, text, kind="info", **k:
                            toasts.append((text, kind)))
        target = isolated_home / "Exports" / "memanga_export.json"
        error = OSError(13, "Permission denied while writing the export "
                        "file; check the folder permissions", str(target))
        page = app_window._pages["settings"]

        with caplog.at_level(logging.ERROR, logger="memanga.gui.pages.settings"):
            page._error_toast("Export failed", error)

        (text, kind), = toasts
        assert kind == "error"
        assert text.startswith("Export failed: ")
        assert text.endswith("(details in Notifications)")
        note = app_window.app_state.get_notifications()[0]
        assert note["message"].startswith("Export failed - ")
        assert "~" in note["details"]
        assert note["details"].endswith("memanga_export.json'")
        for shown in (text, note["message"], note["details"]):
            assert str(isolated_home) not in shown
        assert any("Export failed" in r.getMessage() for r in caplog.records)

    def test_smtp_test_reports_unusable_override(
            self, app_window, qapp, smtp_logins, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", str(tmp_path / "missing"))
        page = app_window._pages["settings"]
        self._fill_smtp_test(page, "typed-pw")
        page._test_email()
        # Never falls back to the typed password, and never logs in.
        assert smtp_logins == []
        assert page._test_label.text() == "Password variable unusable"
        tip = page._test_label.toolTip()
        assert "MEMANGA_SMTP_PASSWORD_FILE" in tip
        assert "typed-pw" not in tip

    def test_mangadex_quality_choice_saves_and_resets(self, app_window, qapp):
        page = app_window._pages["settings"]
        assert page._mangadex_quality.currentData() is False
        page._mangadex_quality.setCurrentIndex(1)
        page._save()
        assert app_window.config.get("mangadex.data_saver") is True
        page._reset_to_defaults()
        assert app_window.config.get("mangadex.data_saver") is False
        assert page._mangadex_quality.currentData() is False

    def test_reset_defaults_keeps_removed_mangadex_groups(self, app_window, qapp):
        page = app_window._pages["settings"]
        group = "0e1f2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b"
        app_window.config.set("mangadex.data_saver", True)
        app_window.config.set("mangadex.removed_group_ids", [group])
        page._reset_to_defaults()
        assert app_window.config.get("mangadex.data_saver") is False
        assert app_window.config.get("mangadex.removed_group_ids") == [group]

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
        # Shows the zero-padded chapter the downloader writes (#241).
        assert page._filename_preview.text().startswith("X-0001.000.")

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

            def close(self):
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

    def test_scheduling_controls_enabled_when_supported(
            self, app_window, qapp, monkeypatch):
        """#324, #336: source/pip installs keep the scheduling controls."""
        from memanga.gui.pages import settings as settings_mod

        monkeypatch.setattr(settings_mod, "scheduled_checks_supported",
                            lambda: True)
        page = app_window._pages["settings"]
        page._apply_scheduling_capability()

        assert page._cron_check.isEnabled()
        assert page._cron_time.isEnabled()
        assert page._cron_install_btn.isEnabled()
        assert page._cron_install_btn.toolTip() == ""
        assert page._cron_unavailable_hint.isHidden()

    def test_frozen_build_disables_scheduling_and_explains(
            self, app_window, qapp, monkeypatch):
        """#324, #336: the desktop build cannot run a headless check, so
        installing one is turned off with the reason and the alternative;
        Remove and Status stay usable for a task set up earlier."""
        from memanga.gui.pages import settings as settings_mod

        monkeypatch.setattr(settings_mod, "scheduled_checks_supported",
                            lambda: False)
        page = app_window._pages["settings"]
        page._apply_scheduling_capability()

        for widget in (page._cron_check, page._cron_time,
                       page._cron_install_btn):
            assert not widget.isEnabled()
            assert widget.toolTip() == settings_mod.SCHEDULING_UNAVAILABLE_TEXT
            assert (widget.accessibleDescription()
                    == settings_mod.SCHEDULING_UNAVAILABLE_TEXT)
        hint = page._cron_unavailable_hint
        assert not hint.isHidden()
        assert "memanga cron install" in hint.text()
        assert "Remove and Status" in hint.text()
        assert page._cron_remove_btn.isEnabled()
        assert page._cron_status_btn.isEnabled()

    @pytest.mark.parametrize("system", ["Linux", "Windows"])
    def test_frozen_build_install_runs_no_scheduler(
            self, app_window, qapp, monkeypatch, toasts, system):
        """#324, #336: no crontab/schtasks call and no config change."""
        from memanga import cron as cron_mod
        from memanga.gui.pages import settings as settings_mod

        calls = []
        monkeypatch.setattr(settings_mod, "scheduled_checks_supported",
                            lambda: False)
        monkeypatch.setattr(cron_mod.platform, "system", lambda: system)
        monkeypatch.setattr(settings_mod.subprocess, "run",
                            lambda cmd, **kw: calls.append(cmd))
        app_window.config.set("cron.enabled", False)
        app_window.config.set("cron.time", "06:00")
        page = app_window._pages["settings"]
        page._cron_time.setText("07:30")

        page._install_cron()

        assert calls == []
        assert app_window.config.get("cron.enabled") is False
        assert app_window.config.get("cron.time") == "06:00"
        assert toasts and toasts[-1][1].get("kind") == "info"

    @pytest.mark.parametrize("managed_task", [True, False])
    def test_frozen_build_save_after_remove_keeps_cron_state(
            self, app_window, qapp, monkeypatch, toasts, tmp_path,
            managed_task):
        """#324: the disabled checkbox still shows the old value, so a
        later Save must not re-enable a check Remove took out, and must
        not change cron settings when there was nothing to remove."""
        import sys

        from memanga.config import Config
        from memanga.cron import build_cron_line
        from memanga.gui.pages import settings as settings_mod

        cfg = app_window.config
        cfg.set("cron.enabled", True)
        cfg.set("cron.time", "05:15")
        cfg.set("delivery.delete_after_send", False)
        cfg.save()
        monkeypatch.setattr(settings_mod, "scheduled_checks_supported",
                            lambda: False)
        page = app_window._pages["settings"]
        page._cron_check.setChecked(True)
        page._cron_time.setText("07:30")
        page._apply_scheduling_capability()
        existing = self._USER_CRONTAB
        if managed_task:
            managed = build_cron_line("15", "05", tmp_path, sys.executable)
            existing += f"{managed}\n"
        submitted = self._fake_crontab(monkeypatch, existing)

        page._remove_cron()
        page._delete_after_check.setChecked(True)
        page._save()

        assert ("crontab" in submitted) is managed_task
        assert page._cron_check.isChecked() is not managed_task
        saved = Config(cfg.config_dir)
        assert saved.get("cron.enabled") is not managed_task
        assert saved.get("cron.time") == "05:15"
        assert saved.get("delivery.delete_after_send") is True

    def test_install_cron_unix_quotes_paths(self, app_window, qapp,
                                            monkeypatch, tmp_path):
        """#109: cron paths with spaces must be shell-quoted so the
        generated crontab entry survives spaced install dirs. #232: the
        line runs the current interpreter from the config root, not the
        package directory or a checkout-local venv."""
        import subprocess
        import sys
        from pathlib import Path

        import memanga
        from memanga import cron as cron_mod
        from memanga.cron import build_cron_line
        from memanga.gui.pages import settings as settings_mod

        page = app_window._pages["settings"]
        config_dir = tmp_path / "My Manga"
        config_dir.mkdir()
        monkeypatch.setattr(app_window.config, "config_dir", config_dir)
        python = "/opt/pipx venvs/memanga/bin/python"
        monkeypatch.setattr(sys, "executable", python)
        # Installed-package branch: nothing to cd into but the config root.
        monkeypatch.setattr(settings_mod, "source_checkout_root",
                            lambda: None)

        submitted = {}

        def _fake_run(cmd, input=None, **kwargs):
            if cmd == ["crontab", "-"]:
                submitted["crontab"] = input
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 1, "",
                                               "no crontab for tester\n")

        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Linux")

        page._cron_time.setText("06:30")
        page._install_cron()

        expected = build_cron_line(30, 6, config_dir, python)
        assert expected in submitted["crontab"].splitlines()
        assert f"'{config_dir}/memanga.log'" in submitted["crontab"]
        assert f"'{python}' -m memanga" in submitted["crontab"]
        package_parent = str(Path(memanga.__file__).resolve().parent.parent)
        assert package_parent not in submitted["crontab"]

    def test_install_cron_windows_uses_running_interpreter(
            self, app_window, qapp, monkeypatch):
        """#232: the scheduled task runs sys.executable, never a
        checkout-local venv/Scripts/python.exe."""
        import subprocess
        import sys

        from memanga import cron as cron_mod
        from memanga.cron import build_task_command
        from memanga.gui.pages import settings as settings_mod

        python = r"C:\Program Files\Python312\python.exe"
        monkeypatch.setattr(sys, "executable", python)
        calls = []

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Windows")
        app_window.config.set("cron.enabled", False)
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")

        page._install_cron()

        create, = [c for c in calls if c[1] == "/create"]
        assert create[create.index("/st") + 1] == "06:30"
        command = create[create.index("/tr") + 1]
        assert command == build_task_command(
            python, source_root=settings_mod.source_checkout_root())
        assert f'"{python}" -m memanga check --auto --quiet' in command
        assert app_window.config.get("cron.enabled") is True

    def test_install_cron_unix_keeps_explicit_config_dir(
            self, app_window, qapp, monkeypatch, tmp_path):
        """#249: a window started with --config-dir/$MEMANGA_CONFIG_DIR
        schedules the check on that directory, like `cron install`."""
        import shlex
        import sys

        from memanga.gui.pages import settings as settings_mod

        root = tmp_path / "My Manga cfg"
        monkeypatch.setattr(app_window, "explicit_config_dir", root)
        monkeypatch.setattr(settings_mod, "source_checkout_root",
                            lambda: None)
        submitted = self._fake_crontab(monkeypatch, "")
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")
        page._install_cron()

        line, = [l for l in submitted["crontab"].splitlines() if l]
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        i = command.index("memanga")
        assert command[i + 1:i + 4] == ["--config-dir", root.as_posix(), "check"]

    def test_install_cron_windows_keeps_explicit_config_dir(
            self, app_window, qapp, monkeypatch, tmp_path):
        import subprocess
        import sys

        from memanga import cron as cron_mod
        from memanga.cron import build_task_command
        from memanga.gui.pages import settings as settings_mod

        python = r"C:\Program Files\Python312\python.exe"
        monkeypatch.setattr(sys, "executable", python)
        root = tmp_path / "My Manga cfg"
        monkeypatch.setattr(app_window, "explicit_config_dir", root)
        calls = []

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Windows")
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")
        page._install_cron()

        create, = [c for c in calls if c[1] == "/create"]
        command = create[create.index("/tr") + 1]
        assert command == build_task_command(
            python, config_dir=root,
            source_root=settings_mod.source_checkout_root())
        assert "--config-dir" in command

    def test_window_without_objects_uses_explicit_dir(self, qapp, theme,
                                                      tmp_path):
        """#249: MeMangaApp built with only an explicit directory loads
        config and state there, never from the default."""
        from memanga.gui.app import MeMangaApp
        root = tmp_path / "portable"
        w = MeMangaApp(explicit_config_dir=root)
        try:
            assert w.config.config_dir == w.app_state.config_dir == root
            w.reload_data()
            assert w.config.config_dir == w.app_state.config_dir == root
        finally:
            try:
                w.worker.shutdown()
            except Exception:
                pass
            w.close()

    def test_install_cron_unix_source_checkout_runs_from_checkout(
            self, app_window, qapp, monkeypatch, tmp_path):
        """#232: a requirements-only checkout venv needs the checkout as
        working dir; the log still goes to the config root."""
        import shlex
        import sys

        from memanga.gui.pages import settings as settings_mod

        checkout = tmp_path / "My Checkout"
        monkeypatch.setattr(settings_mod, "source_checkout_root",
                            lambda: checkout)
        config_dir = app_window.config.config_dir
        submitted = self._fake_crontab(monkeypatch, "")
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")
        page._install_cron()

        line, = [l for l in submitted["crontab"].splitlines() if l]
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        assert command[:4] == ["cd", str(checkout), "&&", sys.executable]
        assert command[-3:] == [">>", str(config_dir / "memanga.log"), "2>&1"]

    def _fake_crontab(self, monkeypatch, existing, read_rc=0, read_err="",
                      write_rc=0):
        import subprocess

        from memanga import cron as cron_mod
        from memanga.gui.pages import settings as settings_mod

        submitted = {}

        def _fake_run(cmd, input=None, **kwargs):
            if cmd == ["crontab", "-"]:
                submitted["crontab"] = input
                return subprocess.CompletedProcess(cmd, write_rc, "", "")
            if cmd == ["crontab", "-r"]:
                submitted["removed"] = True
                return subprocess.CompletedProcess(cmd, write_rc, "", "")
            return subprocess.CompletedProcess(cmd, read_rc, existing, read_err)

        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Linux")
        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
        return submitted

    _USER_CRONTAB = (
        "# memanga docker job\n"
        "\n"
        "0 5 * * * docker compose -f /srv/memanga/compose.yaml run --rm memanga check\n"
    )

    def test_cron_install_unix_keeps_unrelated_lines(self, app_window, qapp,
                                                     monkeypatch, tmp_path):
        """#231: only the managed line is replaced."""
        import sys

        from memanga.cron import build_cron_line

        config_dir = app_window.config.config_dir
        from memanga.cron import source_checkout_root

        source_root = source_checkout_root()
        old = build_cron_line("15", "03", config_dir, sys.executable,
                              source_root=source_root)
        submitted = self._fake_crontab(
            monkeypatch, f"{old}\n{self._USER_CRONTAB}")
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")
        page._install_cron()

        expected = build_cron_line(30, 6, config_dir, sys.executable,
                                   source_root=source_root)
        assert submitted["crontab"] == f"{self._USER_CRONTAB}{expected}\n"

    def test_cron_remove_unix_only_touches_managed_line(self, app_window, qapp,
                                                        monkeypatch, tmp_path):
        import sys

        from memanga.cron import build_cron_line

        page = app_window._pages["settings"]
        app_window.config.set("cron.enabled", True)
        submitted = self._fake_crontab(monkeypatch, self._USER_CRONTAB)
        page._remove_cron()
        assert submitted == {}
        assert app_window.config.get("cron.enabled") is True

        managed = build_cron_line("30", "06", tmp_path, sys.executable)
        submitted = self._fake_crontab(
            monkeypatch, f"{self._USER_CRONTAB}{managed}\n")
        page._remove_cron()
        assert submitted["crontab"] == self._USER_CRONTAB
        assert app_window.config.get("cron.enabled") is False

    def test_cron_status_unix_requires_managed_line(self, app_window, qapp,
                                                    monkeypatch):
        page = app_window._pages["settings"]
        self._fake_crontab(monkeypatch, self._USER_CRONTAB)
        page._check_cron_status()
        assert page._cron_status_label.text().startswith("No cron found")
        assert "crontab -e" in page._cron_status_label.text()

        self._fake_crontab(monkeypatch, "30 2 * * * /usr/local/bin/backup.sh\n")
        page._check_cron_status()
        assert page._cron_status_label.text() == "No cron found"

    def test_cron_install_save_failure_says_cron_was_installed(
            self, app_window, qapp, monkeypatch, toasts, tmp_path):
        """#297: when config.yaml cannot be saved after the cron line was
        written, the slot does not raise and the toast says the check is
        installed but its settings were not saved, never "setup failed"."""
        from memanga.persist import SaveError

        cfg = app_window.config
        cfg.set("cron.enabled", False)

        def _failing_save():
            raise SaveError(tmp_path / "config.yaml",
                            OSError(28, "No space left on device"))

        monkeypatch.setattr(cfg, "save", _failing_save)
        submitted = self._fake_crontab(monkeypatch, self._USER_CRONTAB)
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")

        page._install_cron()

        assert "# memanga-managed" in submitted["crontab"]
        (text, kw), = toasts
        assert kw.get("kind") == "error"
        assert text.startswith(
            "Cron installed, but its settings could not be saved: ")
        assert "setup failed" not in text
        # In memory the settings match the installed schedule, so a later
        # successful Save writes them.
        assert cfg.get("cron.enabled") is True
        assert cfg.get("cron.time") == "06:30"
        note = app_window.app_state.get_notifications()[0]
        assert note["message"].startswith("Cron installed, but its settings")

    def test_cron_install_unix_refuses_unreadable_crontab(self, app_window, qapp,
                                                          monkeypatch, tmp_path):
        """#231: a read error other than "no crontab" must not overwrite."""
        app_window.config.set("cron.enabled", False)
        submitted = self._fake_crontab(monkeypatch, "", read_rc=1,
                                       read_err="crontab: Permission denied\n")
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")
        page._install_cron()
        assert submitted == {}
        assert not app_window.config.get("cron.enabled")

    def test_cron_remove_unix_write_failure_keeps_config(self, app_window, qapp,
                                                         monkeypatch, tmp_path):
        import sys

        from memanga.cron import build_cron_line

        app_window.config.set("cron.enabled", True)
        managed = build_cron_line("30", "06", tmp_path, sys.executable)
        self._fake_crontab(monkeypatch, f"{managed}\n", write_rc=1)
        app_window._pages["settings"]._remove_cron()
        assert app_window.config.get("cron.enabled") is True

    def test_cron_remove_unix_last_line_deletes_crontab(self, app_window,
                                                        qapp, monkeypatch,
                                                        tmp_path):
        """#297: like `memanga cron remove`, an emptied crontab is
        deleted rather than written back empty."""
        import sys

        from memanga.cron import build_cron_line

        app_window.config.set("cron.enabled", True)
        managed = build_cron_line("30", "06", tmp_path, sys.executable)
        submitted = self._fake_crontab(monkeypatch, f"\n{managed}\n")
        app_window._pages["settings"]._remove_cron()
        assert submitted == {"removed": True}
        assert app_window.config.get("cron.enabled") is False

    @pytest.mark.parametrize("action", ["_remove_cron", "_check_cron_status"])
    def test_cron_unix_unreadable_crontab_changes_nothing(
            self, app_window, qapp, monkeypatch, toasts, action):
        """#297: Remove and Status share install's read check, so a
        permission error is never shown as "no cron"."""
        app_window.config.set("cron.enabled", True)
        page = app_window._pages["settings"]
        submitted = self._fake_crontab(monkeypatch, "", read_rc=1,
                                       read_err="crontab: Permission denied\n")
        getattr(page, action)()

        assert submitted == {}
        assert app_window.config.get("cron.enabled") is True
        if action == "_check_cron_status":
            assert page._cron_status_label.text() == "Check failed"
        else:
            assert toasts[-1][1].get("kind") == "error"

    def _fake_schtasks(self, monkeypatch, delete_rc=0, tn_rc=0, query_rc=0,
                       listing=""):
        """Fake schtasks; records ``(argv, kwargs)``. ``tn_rc`` answers
        ``/query /tn``, ``query_rc``/``listing`` the CSV task list."""
        import subprocess

        from memanga import cron as cron_mod
        from memanga.gui.pages import settings as settings_mod

        calls = []

        def _fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[:3] == ["schtasks", "/query", "/tn"]:
                rc, stdout = tn_rc, ""
            elif cmd[1] == "/query":
                rc, stdout = query_rc, listing
            else:
                rc, stdout = {"/delete": delete_rc}.get(cmd[1], 0), ""
            return subprocess.CompletedProcess(cmd, rc, stdout,
                                               "ERROR: Access is denied.\n")

        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Windows")
        monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
        return calls

    @pytest.mark.parametrize(
        "delete_rc, query_rc, listing, enabled_after, kind",
        [(0, 0, "", False, "success"),                  # removed
         (1, 0, '"\\Backup","N/A","Ready"\n', True, "info"),  # no task
         (1, 0, '"\\MeManga_AutoCheck","N/A","Ready"\n',
          True, "error"),                               # task not deleted
         (1, 1, "", True, "error")])                    # list unreadable
    def test_cron_remove_windows_checks_result(
            self, app_window, qapp, monkeypatch, toasts, delete_rc, query_rc,
            listing, enabled_after, kind):
        """#297: Remove only turns the setting off when schtasks really
        deleted the task (it used to report success regardless), and only
        says there is none when the task list shows that."""
        from memanga.cron import SCHEDULER_TIMEOUT, WINDOWS_TASK_NAME

        app_window.config.set("cron.enabled", True)
        calls = self._fake_schtasks(monkeypatch, delete_rc,
                                    query_rc=query_rc, listing=listing)

        app_window._pages["settings"]._remove_cron()

        assert app_window.config.get("cron.enabled") is enabled_after
        assert toasts[-1][1].get("kind") == kind
        argv, kwargs = calls[0]
        assert argv == ["schtasks", "/delete", "/tn", WINDOWS_TASK_NAME, "/f"]
        assert kwargs["timeout"] == SCHEDULER_TIMEOUT
        if delete_rc:
            assert calls[1][0] == ["schtasks", "/query", "/fo", "csv", "/nh"]

    @pytest.mark.parametrize("tn_rc, query_rc, listing, text", [
        (0, 0, "", "Task installed"),
        (1, 0, '"\\MeManga_AutoCheck","N/A","Ready"\n', "Task installed"),
        (1, 0, '"\\Backup","N/A","Ready"\n', "No task found"),
        (1, 1, "", "Check failed"),   # denied / scheduler unavailable
    ])
    def test_cron_status_windows(self, app_window, qapp, monkeypatch,
                                 tn_rc, query_rc, listing, text):
        from memanga.cron import SCHEDULER_TIMEOUT, WINDOWS_TASK_NAME

        page = app_window._pages["settings"]
        calls = self._fake_schtasks(monkeypatch, tn_rc=tn_rc,
                                    query_rc=query_rc, listing=listing)
        page._check_cron_status()
        argv, kwargs = calls[0]
        assert argv == ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME]
        assert kwargs["timeout"] == SCHEDULER_TIMEOUT
        assert kwargs["capture_output"] and kwargs["text"]
        assert len(calls) == (1 if tn_rc == 0 else 2)
        assert page._cron_status_label.text() == text

    @pytest.mark.parametrize("action", ["_install_cron", "_remove_cron",
                                        "_check_cron_status"])
    def test_cron_undecodable_output_reports_error(
            self, app_window, qapp, monkeypatch, toasts, action):
        """#297: a UnicodeDecodeError from text=True decoding must reach
        the user as an error, not escape the Qt slot silently."""
        from memanga import cron as cron_mod
        from memanga.gui.pages import settings as settings_mod

        def _undecodable(cmd, **kwargs):
            raise UnicodeDecodeError("utf-8", b"\xe9", 0, 1,
                                     "invalid continuation byte")

        monkeypatch.setattr(cron_mod.platform, "system", lambda: "Linux")
        monkeypatch.setattr(settings_mod.subprocess, "run", _undecodable)
        app_window.config.set("cron.enabled", True)
        page = app_window._pages["settings"]
        page._cron_time.setText("06:30")

        getattr(page, action)()

        assert app_window.config.get("cron.enabled") is True
        if action == "_check_cron_status":
            assert page._cron_status_label.text() == "Check failed"
        else:
            text, kw = toasts[-1]
            assert kw.get("kind") == "error"
            assert text.startswith("Could not read crontab; nothing changed")

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

    # ── About (issue #343) ──

    @pytest.fixture
    def about_stubs(self, monkeypatch):
        """Fixed About data; records the thread the slow checks ran on."""
        from memanga import doctor
        check_threads = []
        monkeypatch.setattr(doctor, "about_basics", lambda: {
            "version": "9.9.9", "install_mode": "frozen", "frozen": True,
            "python": "3.12.1 (CPython)", "os": "Windows-11-10.0.22631-SP0",
            "machine": "AMD64", "qt": "6.7.2 (PySide6 6.7.2)",
            "playwright": "1.48.0",
        })

        def checks():
            check_threads.append(threading.get_ident())
            return {
                "keyring": {"available": True, "plaintext": False,
                            "backend": "keyring.backends.Windows.WinVaultKeyring"},
                "browsers": {"status": "ok",
                             "installed": {"firefox": True, "chromium": False}},
            }
        monkeypatch.setattr(doctor, "about_checks", checks)
        return check_threads

    @staticmethod
    def _wait_for(qapp, predicate):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not predicate():
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()

    def test_about_tab_is_listed_and_switches(self, app_window, qapp, about_stubs):
        page = app_window._pages["settings"]
        assert "about" in page._tab_buttons
        page._switch_tab("about")
        assert not page._about_scroll.isHidden()
        assert page._general_scroll.isHidden()
        assert page._advanced_scroll.isHidden()

    def test_about_checks_wait_for_first_visit(self, app_window, qapp, about_stubs):
        # Building Settings at startup must not start Playwright.
        page = app_window._pages["settings"]
        page._switch_tab("general")
        page._switch_tab("advanced")
        qapp.processEvents()
        assert about_stubs == []
        assert page._about_info is None

    def test_about_rows_fill_in_from_background_checks(
            self, app_window, qapp, about_stubs):
        page = app_window._pages["settings"]
        main_thread = threading.get_ident()
        page._switch_tab("about")
        # Basics show at once; the slow rows say they are still checking.
        assert page._about_values["MeManga"].text() == "9.9.9"
        assert page._about_values["Frozen"].text() == "yes"

        browsers = page._about_values["Browsers"]
        self._wait_for(qapp, lambda: browsers.text() != "Checking…")
        assert browsers.text() == "firefox installed, chromium missing"
        assert page._about_values["Keyring"].text() == (
            "keyring.backends.Windows.WinVaultKeyring (available)")
        assert page._about_values["Install"].accessibleName() == (
            "Install: packaged app")
        assert about_stubs and all(t != main_thread for t in about_stubs)

        # A second visit reuses the result instead of probing again.
        page._switch_tab("general")
        page._switch_tab("about")
        qapp.processEvents()
        assert len(about_stubs) == 1

    def test_copy_diagnostics_puts_summary_on_clipboard(
            self, app_window, qapp, about_stubs):
        from PySide6.QtGui import QGuiApplication
        page = app_window._pages["settings"]
        page._switch_tab("about")
        self._wait_for(qapp, lambda: page._about_values["Browsers"].text() != "Checking…")

        page._copy_about_btn.click()
        copied = QGuiApplication.clipboard().text()
        assert copied.splitlines()[0] == "MeManga: 9.9.9"
        assert "Frozen: yes" in copied
        assert "Browsers: firefox installed, chromium missing" in copied
        assert "Keyring: keyring.backends.Windows.WinVaultKeyring (available)" in copied
        assert page._copy_about_btn.text() == "Copied"
        page._reset_copy_about_label()
        assert page._copy_about_btn.text() == "Copy diagnostics"

    def test_copy_diagnostics_waits_for_pending_checks(
            self, app_window, qapp, about_stubs, monkeypatch):
        # Copying while the checks run would paste "Checking…" rows.
        from PySide6.QtGui import QGuiApplication
        from memanga import doctor
        finished_checks = doctor.about_checks
        release = threading.Event()

        def slow_checks():
            release.wait(2.0)
            return finished_checks()
        monkeypatch.setattr(doctor, "about_checks", slow_checks)

        page = app_window._pages["settings"]
        assert not page._copy_about_btn.isEnabled()
        clipboard = QGuiApplication.clipboard()
        clipboard.setText("before")
        try:
            page._switch_tab("about")
            qapp.processEvents()
            assert page._about_values["Browsers"].text() == "Checking…"
            assert not page._copy_about_btn.isEnabled()
            page._copy_about_btn.click()
            page._copy_about()
            assert clipboard.text() == "before"
            assert page._copy_about_btn.text() == "Copy diagnostics"
        finally:
            release.set()

        self._wait_for(qapp, page._copy_about_btn.isEnabled)
        assert page._copy_about_btn.isEnabled()
        page._copy_about_btn.click()
        copied = clipboard.text()
        assert "Checking…" not in copied
        assert "Browsers: firefox installed, chromium missing" in copied

    def test_copy_diagnostics_available_after_failed_checks(
            self, app_window, qapp, about_stubs, monkeypatch):
        from PySide6.QtGui import QGuiApplication
        from memanga import doctor

        def failed_checks():
            raise RuntimeError("probe crashed")
        monkeypatch.setattr(doctor, "about_checks", failed_checks)

        page = app_window._pages["settings"]
        page._switch_tab("about")
        self._wait_for(qapp, page._copy_about_btn.isEnabled)
        assert page._copy_about_btn.isEnabled()

        page._copy_about_btn.click()
        copied = QGuiApplication.clipboard().text()
        assert "Browsers: could not be checked" in copied
        assert "Keyring: none (unavailable)" in copied
        assert "probe crashed" not in copied


# ─────────────────────────────────────────────────────────────────────────
# Detail (requires a manga in config)
# ─────────────────────────────────────────────────────────────────────────


class TestDetailPage:
    def test_renders_with_manga(self, app_window, qapp, sample_manga):
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        page = app_window._pages["detail"]
        assert page._manga == sample_manga

    @pytest.mark.parametrize("scope, own, checked", [
        (None, None, True),
        ("selected", None, False),
        ("selected", True, True),
        ("all", False, False),
    ])
    def test_kindle_toggle_follows_scope(self, app_window, qapp, sample_manga,
                                         scope, own, checked):
        # Issue #345: without its own choice a manga follows the
        # Settings choice of which manga to send.
        cfg = app_window.config
        cfg.set("delivery.mode", "email")
        cfg.set("email.kindle_email", "reader@example.com")
        if scope is not None:
            cfg.set("email.kindle_scope", scope)
        manga = dict(sample_manga)
        if own is not None:
            manga["send_to_kindle"] = own
        cfg.set("manga", [manga])
        app_window.show_page("detail", manga=manga); qapp.processEvents()
        assert app_window._pages["detail"]._kindle_check.isChecked() is checked

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

    @pytest.mark.parametrize("send_to_kindle", [True, False])
    def test_download_passes_shared_email_settings(
            self, app_window, qapp, sample_manga, monkeypatch, send_to_kindle):
        # Issue #296: the Detail page builds its delivery settings with
        # the shared helper; a manga that opted out sends nothing.
        from memanga.email_settings import EmailSettings
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: "pw")
        cfg = app_window.config
        cfg.set("delivery.mode", "email")
        cfg.set("email.kindle_email", "reader@example.com")
        cfg.set("email.sender_email", "sender@example.com")
        cfg.set("email.smtp_server", "smtp.example.test")
        cfg.set("email.smtp_port", 2525)
        manga = {**sample_manga, "send_to_kindle": send_to_kindle}
        title = manga["title"]
        cfg.set("manga", [manga])
        app_window.app_state.set_available_chapters(title, [{
            "number": "7", "title": "", "source": "mangadex.org",
            "source_url": "https://mangadex.org/title/abc/test-manga",
            "url": "https://mangadex.org/chapter/7", "is_backup": False,
        }])
        app_window.show_page("detail", manga=manga); qapp.processEvents()
        page = app_window._pages["detail"]
        calls = []
        app_window.worker.download_chapter = lambda **kw: calls.append(kw)

        page._download_chapter(app_window.app_state.get_available_chapters(title)[0])

        (call,) = calls
        if send_to_kindle:
            assert call["kindle_cfg"] == EmailSettings(
                kindle_email="reader@example.com",
                sender_email="sender@example.com",
                smtp_server="smtp.example.test", smtp_port=2525,
                smtp_timeout=60, max_email_mb=25, app_password="pw")
        else:
            assert call["kindle_cfg"] is None

    @staticmethod
    def _undelivered_page(app_window, qapp, sample_manga, tmp_path):
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        path = tmp_path / "ch8.pdf"
        path.write_bytes(b"%PDF")
        app_window.app_state.add_downloaded_chapter(title, "8")
        app_window.app_state.failures.add_undelivered(
            title, "8", str(path), "SMTP down")
        app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
        return app_window._pages["detail"]

    @staticmethod
    def _send_button(page):
        from PySide6.QtWidgets import QPushButton
        return next(b for b in page._chapters_container.findChildren(QPushButton)
                    if b.text() in ("Send", "Sending…"))

    def test_undelivered_chapter_offers_send(
            self, app_window, qapp, sample_manga, tmp_path, monkeypatch):
        # Issue #360: a chapter that never reached the Kindle says so and
        # can be sent again from its row.
        from PySide6.QtWidgets import QLabel
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: "pw")
        app_window.config.set("delivery.mode", "email")
        app_window.config.set("email.kindle_email", "reader@example.com")
        app_window.config.set("email.sender_email", "sender@example.com")
        page = self._undelivered_page(app_window, qapp, sample_manga, tmp_path)
        texts = [lbl.text() for lbl in page._chapters_container.findChildren(QLabel)]
        assert "Not sent to Kindle" in texts

        calls = []
        app_window.worker.send_pending = (
            lambda manga, number, state, kindle_cfg, **kw:
            calls.append((manga["title"], number, kindle_cfg.kindle_email,
                          kindle_cfg.app_password)))
        self._send_button(page).click()
        qapp.processEvents()

        assert calls == [(sample_manga["title"], "8", "reader@example.com", "pw")]
        assert self._send_button(page).text() == "Sending…"

        app_window.app_state.failures.clear_undelivered(sample_manga["title"], "8")
        page._on_kindle_resend_done({"title": sample_manga["title"],
                                     "chapter": "8", "sent": True})
        assert page._sending == set()
        from PySide6.QtCore import QCoreApplication, QEvent
        page._refresh_chapter_list()
        # The old rows are deleteLater'd; flush them so only the rebuilt
        # rows are inspected.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        texts = [lbl.text() for lbl in page._chapters_container.findChildren(QLabel)]
        assert "Not sent to Kindle" not in texts

    def test_send_needs_email_delivery(
            self, app_window, qapp, sample_manga, tmp_path):
        app_window.config.set("delivery.mode", "local")
        page = self._undelivered_page(app_window, qapp, sample_manga, tmp_path)
        calls = []
        app_window.worker.send_pending = lambda *a, **kw: calls.append(a)

        page._send_pending("8")

        assert calls == []
        assert app_window.app_state.failures.get_undelivered(sample_manga["title"])

    def test_send_refused_when_manga_opted_out(
            self, app_window, qapp, sample_manga, tmp_path, monkeypatch):
        # Issue #341: per-manga Kindle opt-out wins over global email.
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: "pw")
        app_window.config.set("delivery.mode", "email")
        app_window.config.set("email.kindle_email", "reader@example.com")
        app_window.config.set("email.sender_email", "sender@example.com")
        manga = {**sample_manga, "send_to_kindle": False}
        page = self._undelivered_page(app_window, qapp, manga, tmp_path)
        calls = []
        app_window.worker.send_pending = lambda *a, **kw: calls.append(a)

        page._send_pending("8")

        assert calls == []
        assert app_window.app_state.failures.get_undelivered(manga["title"])


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

    def test_queued_jobs_carry_shared_email_settings(
            self, app_window, qapp, sample_manga, monkeypatch):
        # Issue #296: one settings object per job when email delivery
        # applies; None for a manga that opted out (#341).
        from memanga.email_settings import EmailSettings
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: "pw")
        cfg = app_window.config
        cfg.set("delivery.mode", "email")
        cfg.set("email.kindle_email", "reader@example.com")
        cfg.set("email.sender_email", "sender@example.com")
        opted_out = {**sample_manga, "title": "Opted Out",
                     "send_to_kindle": False}
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        queued = {}
        app_window.worker.download_chapter = (
            lambda **kw: queued.__setitem__(kw["manga"]["title"],
                                            kw["kindle_cfg"]))
        page._on_check_complete({
            "results": [self._result(sample_manga, "1"),
                        self._result(opted_out, "1")],
            "queue_all": True,
        })

        assert queued == {
            sample_manga["title"]: EmailSettings(
                kindle_email="reader@example.com",
                sender_email="sender@example.com",
                smtp_timeout=60, max_email_mb=25, app_password="pw"),
            "Opted Out": None,
        }

    def test_queued_jobs_stay_local_without_email_delivery(
            self, app_window, qapp, sample_manga):
        app_window.config.set("email.kindle_email", "reader@example.com")
        assert app_window.config.delivery_mode == "local"
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        queued = []
        app_window.worker.download_chapter = (
            lambda **kw: queued.append(kw["kindle_cfg"]))
        page._on_check_complete({
            "results": [self._result(sample_manga, "1")],
            "queue_all": True,
        })

        assert queued == [None]

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

    def test_background_sweep_queues_entry_without_mode(self, app_window,
                                                        qapp, sample_manga):
        # Issue #341: shared policy; an older entry with no mode is auto.
        manga = {k: v for k, v in sample_manga.items() if k != "mode"}
        app_window.config.set("manga", [manga])
        app_window.show_page("downloads"); qapp.processEvents()
        page = app_window._pages["downloads"]

        queued = []
        app_window.worker.download_chapter = (
            lambda **kw: queued.append(str(kw["chapter"].number))
        )
        page._on_check_complete({"results": [self._result(manga, "1", "2")]})
        assert queued == ["1", "2"]

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
