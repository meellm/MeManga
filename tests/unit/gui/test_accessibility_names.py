"""
Accessible names and descriptions for icon-only buttons, painted cards,
unlabeled fields and progress bars (issue #394).

Read through Qt's accessibility layer — the interface a screen-reader
bridge consumes — rather than the widget properties alone, so a name Qt
would not publish fails here too.
"""

from pathlib import Path

import pytest


def _name(widget) -> str:
    from PySide6.QtGui import QAccessible
    return QAccessible.queryAccessibleInterface(widget).text(
        QAccessible.Text.Name)


def _desc(widget) -> str:
    from PySide6.QtGui import QAccessible
    return QAccessible.queryAccessibleInterface(widget).text(
        QAccessible.Text.Description)


# ── Sidebar ──────────────────────────────────────────────────────────────


class TestSidebar:
    def test_nav_names_have_no_icon_padding(self, app_window):
        buttons = app_window._sidebar._buttons
        assert _name(buttons["library"]) == "Library"
        assert _name(buttons["notifications"]) == "Notifications"
        for btn in buttons.values():
            assert _name(btn) == _name(btn).strip() != ""

    def test_badge_count_is_described(self, app_window):
        btn = app_window._sidebar._buttons["notifications"]
        btn.set_count(3)
        assert _desc(btn) == "3 unread notifications"
        btn.set_count(1)
        assert _desc(btn) == "1 unread notification"
        btn.set_count(0)
        assert _desc(btn) == ""

    def test_sync_progress_is_named(self, app_window):
        assert _name(app_window._sidebar._sync_progress) == (
            "Auto-check progress")


# ── Cards ────────────────────────────────────────────────────────────────


class TestCards:
    def test_manga_card_named_by_title_with_painted_state(
            self, theme, sample_manga):
        from memanga.gui.components.manga_card import MangaCard
        card = MangaCard(None, manga=sample_manga, cover_image=None,
                         new_count=2, read_count=3, total_count=10)
        assert _name(card) == "Test Manga"
        desc = _desc(card)
        assert "Reading" in desc
        assert "read 3 of 10 chapters" in desc
        assert "2 new" in desc
        assert "opens details" in desc

    def test_manga_row_named_by_title(self, theme, sample_manga):
        from memanga.gui.components.manga_row import MangaRow
        row = MangaRow(None, manga=sample_manga,
                       state_data={"downloaded": ["1", "2"]}, new_count=1)
        assert _name(row) == "Test Manga"
        desc = _desc(row)
        assert "mangadex.org" in desc
        assert "2 chapters downloaded" in desc
        assert "1 new" in desc

    def test_continue_card_named_by_title(self, theme, sample_manga):
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QProgressBar
        from memanga.gui.components.continue_card import ContinueCard
        card = ContinueCard(None, manga=sample_manga, cover_pixmap=QPixmap(),
                            last_chapter="5", progress_pct=40)
        assert _name(card) == "Test Manga"
        assert "chapter 5" in _desc(card)
        assert _name(card.findChild(QProgressBar)) == "Reading progress"

    def test_search_result_add_says_what_it_adds(self, theme):
        from memanga.gui.components.search_result import SearchResultRow
        row = SearchResultRow(None, {"title": "Blue Lock",
                                     "source": "mangadex.org",
                                     "url": "https://mangadex.org/x"},
                              on_add=lambda *_: None)
        assert _name(row._add_btn) == "+ Add"
        assert "Blue Lock" in _desc(row._add_btn)
        assert "mangadex.org" in _desc(row._add_btn)


# ── Library ──────────────────────────────────────────────────────────────


class TestLibrary:
    def test_filter_sort_and_view_toggles_are_named(self, app_window):
        page = app_window._pages["library"]
        assert _name(page._search_entry) == "Filter library"
        # Qt on Linux publishes a combo box's current item as its name,
        # so the purpose must also reach the published description.
        assert page._sort_menu.accessibleName() == "Sort library"
        assert _name(page._sort_menu)
        assert _desc(page._sort_menu) == "Sort order of the library"
        assert _name(page._view_buttons["grid"]) == "Grid view"
        assert _name(page._view_buttons["list"]) == "List view"

    def test_current_view_is_described(self, app_window, qapp):
        page = app_window._pages["library"]
        page._set_view_mode("grid")
        page._set_view_mode("list")
        assert _desc(page._view_buttons["list"]) == "Current view"
        assert _desc(page._view_buttons["grid"]) == "Show covers in a grid"
        page._set_view_mode("grid")
        assert _desc(page._view_buttons["grid"]) == "Current view"
        assert _desc(page._view_buttons["list"]) == "Show a compact list"

    def test_grid_cards_are_named(self, app_window, sample_manga):
        app_window.config.set("manga", [sample_manga])
        page = app_window._pages["library"]
        page._set_view_mode("grid")
        # The window opens on Library, so show_page("library") is a
        # no-op here; rebuild the grid from the new config directly.
        page._refresh()
        assert [_name(card) for _m, card in page._cards] == ["Test Manga"]


# ── Detail ───────────────────────────────────────────────────────────────


def test_detail_remove_says_which_manga(app_window, qapp, sample_manga):
    from PySide6.QtWidgets import QPushButton
    app_window.config.set("manga", [sample_manga])
    app_window.show_page("detail", manga=sample_manga); qapp.processEvents()
    page = app_window._pages["detail"]
    remove = [b for b in page.findChildren(QPushButton)
              if b.text() == "Remove"]
    assert remove
    assert "Test Manga" in _desc(remove[0])


# ── Search / Sources ─────────────────────────────────────────────────────


def test_search_field_is_named(app_window):
    assert _name(app_window._pages["search"]._search_entry) == "Search manga"


def test_source_checkboxes_are_named(app_window, qapp, qtbot):
    from PySide6.QtWidgets import QCheckBox
    app_window.show_page("sources"); qapp.processEvents()
    page = app_window._pages["sources"]
    assert _name(page._filter_entry) == "Filter sources"
    qtbot.waitUntil(lambda: bool(page.findChildren(QCheckBox)), timeout=5000)
    for check in page.findChildren(QCheckBox):
        assert _name(check)
        assert check.text() == "" or _name(check) == check.text()


# ── Downloads ────────────────────────────────────────────────────────────


def test_download_row_cancel_and_progress_are_named(qapp, theme):
    from memanga.gui.components.progress_item import ProgressItem
    from PySide6.QtWidgets import QPushButton
    item = ProgressItem(None, task_id="T:1", title="Some Manga",
                        chapter="7", on_cancel=lambda _id: None)
    cancel = item.findChild(QPushButton)
    assert cancel.text() == "x"
    assert _name(cancel) == "Cancel download"
    assert _desc(cancel) == "Some Manga - Ch. 7"
    assert _name(item._progress) == "Download progress"


# ── Reader ───────────────────────────────────────────────────────────────


@pytest.fixture
def reader(app_window, qapp, sample_manga, make_cbz):
    app_window.config.set("manga", [sample_manga])
    title = sample_manga["title"]
    dl = Path(app_window.config.download_dir) / title
    dl.mkdir(parents=True, exist_ok=True)
    cbz = make_cbz(pages=3, name="ch1.cbz")
    (dl / f"{title} - Chapter 1.cbz").write_bytes(cbz.read_bytes())
    app_window.app_state.add_downloaded_chapter(title, "1")
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()
    return app_window._pages["reader"]


class TestReader:
    def test_layout_buttons_are_named(self, reader):
        names = {mode: _name(btn)
                 for mode, (btn, _icon) in reader._mode_btns.items()}
        assert names == {"continuous": "Continuous scroll",
                         "single": "Single page",
                         "double": "Two-page spread"}

    def test_current_layout_is_described(self, reader):
        reader._set_view_mode("single")
        single, _ = reader._mode_btns["single"]
        double, _ = reader._mode_btns["double"]
        assert _desc(single).endswith("current layout")
        assert not _desc(double).endswith("current layout")
        assert _desc(double) == "Two-page spreads"

    def test_zoom_and_progress_are_named(self, reader):
        from PySide6.QtWidgets import QPushButton
        names = {_name(b) for b in reader.findChildren(QPushButton)}
        assert {"Zoom out", "Zoom in"} <= names
        assert "−" not in names and "+" not in names
        assert _name(reader._progress_track) == "Reading progress"


# ── Settings ─────────────────────────────────────────────────────────────


class TestSettings:
    def test_tab_names_have_no_icon_padding(self, app_window):
        tabs = app_window._pages["settings"]._tab_buttons
        assert [_name(b) for b in tabs.values()] == [
            "General", "Kindle / Email", "Advanced", "About"]

    def test_fields_are_named_by_their_label(self, app_window):
        page = app_window._pages["settings"]
        assert _name(page._dir_entry) == "Download Directory"
        assert _name(page._naming_entry) == "File naming template"
        assert _name(page._concurrent_slider) == "Concurrent downloads"
        assert _name(page._entry_kindle_email) == "Kindle Email"
        assert _name(page._entry_sender_email) == "Sender Email"
        assert _name(page._entry_smtp_server) == "SMTP Server"
        assert _name(page._entry_smtp_port) == "SMTP Port"
        assert _name(page._password_entry) == "App Password"
        assert _name(page._cron_time) == "Daily auto-check time"
        assert _name(page._partial_threshold) == "Max pages allowed to fail"
        assert _name(page._post_processing_command) == (
            "Post-processing command")

    def test_combo_boxes_publish_their_purpose(self, app_window):
        # The published name may be the current item (Linux), so the
        # purpose is checked in the published description, and the
        # visible heading is tied to the combo as its label.
        page = app_window._pages["settings"]
        fmt, quality = page._format_combo, page._mangadex_quality
        assert fmt.accessibleName() == "Output format"
        assert _desc(fmt).startswith("Output format for downloaded chapters")
        assert quality.accessibleName() == "MangaDex image quality"
        assert _desc(quality) == "Image quality for MangaDex downloads"
        fmt.setCurrentText("epub")
        quality.setCurrentIndex(1)
        assert _desc(fmt).startswith("Output format for downloaded chapters")
        assert _desc(quality) == "Image quality for MangaDex downloads"
        from PySide6.QtWidgets import QLabel
        buddies = {lbl.text(): lbl.buddy() for lbl in page.findChildren(QLabel)
                   if lbl.buddy() is not None}
        assert buddies["Output Format"] is fmt
        assert buddies["MangaDex Image Quality"] is quality

    def test_cron_time_keeps_disabled_reason_description(
            self, app_window, monkeypatch):
        from memanga.gui.pages import settings as settings_mod
        page = app_window._pages["settings"]
        monkeypatch.setattr(settings_mod, "scheduled_checks_supported",
                            lambda: False)
        page._apply_scheduling_capability()
        assert _name(page._cron_time) == "Daily auto-check time"
        assert _desc(page._cron_time) == settings_mod.SCHEDULING_UNAVAILABLE_TEXT

    def test_theme_cards_are_named_with_selected_state(self, qapp, theme):
        from memanga.gui.components.theme_picker import ThemePicker
        picker = ThemePicker()
        dark, light = picker._cards["dark"], picker._cards["light"]
        assert _name(dark) == "Dark theme"
        assert _name(light) == "Light theme"
        assert _desc(dark).startswith("Selected")
        assert not _desc(light).startswith("Selected")
        picker._on_pick("light")
        assert _desc(light).startswith("Selected")
        assert not _desc(dark).startswith("Selected")
