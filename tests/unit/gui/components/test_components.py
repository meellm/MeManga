"""Smoke + behavior tests for every component widget in
memanga/gui/components/. Each test verifies the widget builds without
exceptions and exposes a sensible API; deeper interactions are tested
in dedicated files.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────
# BrandMark
# ─────────────────────────────────────────────────────────────────────────


class TestBrandMark:
    def test_constructs_with_default_size(self, theme):
        from memanga.gui.components.brand_mark import BrandMark
        b = BrandMark(size=34)
        assert b.size().width() == 34
        assert b.size().height() == 34

    def test_small_variant(self, theme):
        from memanga.gui.components.brand_mark import BrandMark
        b = BrandMark(size=18)
        assert b.size().width() == 18

    def test_repaints_on_theme_change(self, qapp, theme):
        from memanga.gui.components.brand_mark import BrandMark
        b = BrandMark(size=34)
        # The paint method reads tokens fresh; flip theme + verify no crash.
        theme.set_theme("light", qapp)
        b.update()
        theme.set_theme("dark", qapp)
        b.update()


# ─────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────


class TestSidebar:
    def test_constructs(self, qapp, theme, app_window):
        # Sidebar lives inside MeMangaApp.
        assert app_window._sidebar is not None

    def test_has_all_nav_buttons(self, app_window):
        for key in ("library", "downloads", "search", "notifications",
                    "sources", "settings"):
            assert key in app_window._sidebar._buttons

    def test_set_active_marks_button(self, app_window):
        app_window._sidebar.set_active("library")
        assert app_window._sidebar._buttons["library"].property("active") == "true"
        assert app_window._sidebar._buttons["downloads"].property("active") != "true"

    def test_detail_highlights_library(self, app_window):
        # Sub-views of library should keep library highlighted.
        app_window._sidebar.set_active("detail")
        assert app_window._sidebar._buttons["library"].property("active") == "true"

    def test_set_count_zero_clears_badge_text(self, app_window):
        """Regression: set_count(0) used to leave the badge label text
        as the previous number ("1") even though the widget was hidden.
        set_active() then re-derived the count from that stale text and
        resurrected the badge after Mark all read."""
        btn = app_window._sidebar._buttons["notifications"]
        btn.set_count(5)
        assert btn._badge.text() == "5"
        btn.set_count(0)
        assert btn._badge.text() == ""
        # Switching active page must not bring the badge back.
        app_window._sidebar.set_active("library")
        # _refresh_badges uses live state — should still be hidden.
        assert btn._badge.isHidden() or btn._badge.text() == ""


# ─────────────────────────────────────────────────────────────────────────
# MangaCard + ContinueCard
# ─────────────────────────────────────────────────────────────────────────


class TestMangaCard:
    def test_constructs(self, theme, sample_manga):
        from PySide6.QtGui import QPixmap
        from memanga.gui.components.manga_card import MangaCard
        c = MangaCard(None, manga=sample_manga, cover_image=QPixmap(),
                      new_count=0, read_count=0, total_count=0)
        assert c.size().width() > 0

    def test_sub_text_shows_read_when_total_known(self, sample_manga):
        from memanga.gui.components.manga_card import MangaCard
        t = MangaCard._sub_text(sample_manga, new_count=0,
                                 read_count=5, total_count=10)
        assert "5/10" in t

    def test_sub_text_appends_new_count(self, sample_manga):
        from memanga.gui.components.manga_card import MangaCard
        t = MangaCard._sub_text(sample_manga, new_count=3,
                                 read_count=5, total_count=10)
        assert "+3" in t

    def test_update_cover_does_not_crash(self, theme, sample_manga):
        from PySide6.QtGui import QPixmap
        from memanga.gui.components.manga_card import MangaCard
        c = MangaCard(None, manga=sample_manga, cover_image=None,
                      new_count=0)
        c.update_cover(QPixmap())


class TestContinueCard:
    def test_constructs(self, theme, sample_manga):
        from PySide6.QtGui import QPixmap
        from memanga.gui.components.continue_card import ContinueCard
        c = ContinueCard(None, manga=sample_manga, cover_pixmap=QPixmap(),
                         last_chapter="5", progress_pct=42.0,
                         on_click=lambda *a: None)
        assert c.height() > 0

    def test_click_invokes_callback(self, theme, sample_manga, qtbot):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap, QMouseEvent
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtWidgets import QApplication
        from memanga.gui.components.continue_card import ContinueCard
        captured = []
        c = ContinueCard(None, manga=sample_manga, cover_pixmap=QPixmap(),
                         last_chapter="1", progress_pct=10,
                         on_click=lambda m: captured.append(m))
        # Synthesize a press event.
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress,
                         QPointF(10, 10), QPointF(10, 10),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        c.mousePressEvent(ev)
        assert captured == [sample_manga]


# ─────────────────────────────────────────────────────────────────────────
# Status / Mode dropdowns
# ─────────────────────────────────────────────────────────────────────────


class TestStatusDropdown:
    def test_constructs(self, theme):
        from memanga.gui.components.status_dropdown import StatusDropdown
        d = StatusDropdown(initial="reading")
        assert d.value() == "reading"

    def test_set_value_updates(self, theme):
        from memanga.gui.components.status_dropdown import StatusDropdown
        d = StatusDropdown(initial="reading")
        d.set_value("completed")
        assert d.value() == "completed"

    def test_emits_value_changed(self, theme, qtbot):
        from memanga.gui.components.status_dropdown import StatusDropdown
        d = StatusDropdown(initial="reading")
        with qtbot.waitSignal(d.value_changed, timeout=1000) as blocker:
            d._set_value("completed", emit=True)
        assert blocker.args == ["completed"]


class TestModeDropdown:
    def test_constructs(self, theme):
        from memanga.gui.components.mode_dropdown import ModeDropdown
        d = ModeDropdown(initial="auto")
        assert d.value() == "auto"

    def test_set_value(self, theme):
        from memanga.gui.components.mode_dropdown import ModeDropdown
        d = ModeDropdown(initial="auto")
        d.set_value("manual")
        assert d.value() == "manual"

    def test_unknown_value_rejected(self, theme):
        from memanga.gui.components.mode_dropdown import ModeDropdown
        d = ModeDropdown(initial="auto")
        d.set_value("bogus")
        assert d.value() == "auto"


# ─────────────────────────────────────────────────────────────────────────
# ThemePicker
# ─────────────────────────────────────────────────────────────────────────


class TestThemePicker:
    def test_constructs(self, qapp, theme):
        from memanga.gui.components.theme_picker import ThemePicker
        p = ThemePicker()
        assert "dark" in p._cards and "light" in p._cards

    def test_clicking_card_switches_theme(self, qapp, theme):
        from memanga.gui.components.theme_picker import ThemePicker
        p = ThemePicker()
        p._on_pick("light")
        assert theme.current_theme() == "light"
        p._on_pick("dark")
        assert theme.current_theme() == "dark"


# ─────────────────────────────────────────────────────────────────────────
# Modal base class
# ─────────────────────────────────────────────────────────────────────────


class TestModalDialog:
    def test_constructs_with_title(self, qapp, theme):
        from memanga.gui.components.modal import ModalDialog
        m = ModalDialog(None, title="Test")
        assert m.panel.width() == 520

    def test_small_width(self, qapp, theme):
        from memanga.gui.components.modal import ModalDialog
        m = ModalDialog(None, title="T", width=440)
        assert m.panel.width() == 440

    def test_esc_closes(self, qapp, theme, qtbot):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from memanga.gui.components.modal import ModalDialog
        m = ModalDialog(None, title="T")
        # Esc → reject
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                       Qt.KeyboardModifier.NoModifier)
        m.keyPressEvent(ev)


class TestDownloadFromModal:
    def test_constructs(self, qapp, theme, sample_manga):
        from memanga.gui.components.download_from_modal import DownloadFromModal
        captured = []
        m = DownloadFromModal(None, sample_manga,
                              on_confirm=lambda *a: captured.append(a))
        # Default chapter input value
        assert m._chapter_input.text() == "1"

    def test_invalid_chapter_does_not_call_callback(self, qapp, theme,
                                                     sample_manga):
        from memanga.gui.components.download_from_modal import DownloadFromModal
        captured = []
        m = DownloadFromModal(None, sample_manga,
                              on_confirm=lambda *a: captured.append(a))
        m._chapter_input.setText("not-a-number")
        m._do_confirm()
        assert captured == []


# ─────────────────────────────────────────────────────────────────────────
# Toast — fire-and-forget popup
# ─────────────────────────────────────────────────────────────────────────


class TestToast:
    def test_constructs(self, qapp, theme):
        from memanga.gui.components.toast import Toast
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        t = Toast(parent, "hello", kind="info")
        assert t is not None


# ─────────────────────────────────────────────────────────────────────────
# SearchResultRow
# ─────────────────────────────────────────────────────────────────────────


class TestSearchResultRow:
    def test_constructs_with_add_button(self, qapp, theme):
        from memanga.gui.components.search_result import SearchResultRow
        r = SearchResultRow(None, result={"title": "Blue Lock",
                                            "url": "https://x/m",
                                            "source": "mangadex.org"},
                              on_add=lambda _: None)
        assert hasattr(r, "_add_btn")
        # Chapter chip starts hidden so 0-chapter sources aren't loud.
        assert r._count_chip.isHidden()

    def test_set_chapter_count_shows_chip(self, qapp, theme):
        from memanga.gui.components.search_result import SearchResultRow
        r = SearchResultRow(None, result={"title": "X", "url": "u",
                                            "source": "s"}, on_add=None)
        r.set_chapter_count(47)
        assert not r._count_chip.isHidden()
        assert "47" in r._count_chip.text()

    def test_zero_chapters_stays_hidden(self, qapp, theme):
        """User explicitly asked: if found chapters is 0, don't show
        the chip — they want to immediately see which sources are
        out-of-date / don't have the manga."""
        from memanga.gui.components.search_result import SearchResultRow
        r = SearchResultRow(None, result={"title": "X", "url": "u",
                                            "source": "s"}, on_add=None)
        r.set_chapter_count(0)
        assert r._count_chip.isHidden()

    def test_failed_lookup_stays_hidden(self, qapp, theme):
        from memanga.gui.components.search_result import SearchResultRow
        r = SearchResultRow(None, result={"title": "X", "url": "u",
                                            "source": "s"}, on_add=None)
        r.set_chapter_count(-1)
        assert r._count_chip.isHidden()

    def test_clicking_add_invokes_callback_with_result(self, qapp, theme):
        from memanga.gui.components.search_result import SearchResultRow
        captured = []
        result = {"title": "T", "url": "u", "source": "s"}
        r = SearchResultRow(None, result=result, on_add=lambda x: captured.append(x))
        r._add_btn.click()
        assert captured == [result]


# ─────────────────────────────────────────────────────────────────────────
# Asset icons
# ─────────────────────────────────────────────────────────────────────────


class TestIcons:
    def test_known_icon_returns_qicon(self):
        from memanga.gui.assets.icons import icon
        i = icon("library", "#ffffff", size=16)
        assert not i.isNull()

    def test_unknown_icon_returns_empty(self):
        from memanga.gui.assets.icons import icon
        i = icon("not-a-real-icon", "#ffffff", size=16)
        assert i.isNull()

    @pytest.mark.parametrize("name", [
        "library", "download", "search", "sources", "notifications",
        "settings", "plus", "refresh", "chevron_down", "x_close",
        "folder", "check", "trash", "bell", "view_single", "view_dual",
        "book_open", "check_circle", "download_tray", "external",
    ])
    def test_all_documented_icons_render(self, name):
        from memanga.gui.assets.icons import icon
        i = icon(name, "#666666", size=24)
        assert not i.isNull(), f"{name} failed to render"


# ─────────────────────────────────────────────────────────────────────────
# JumpSlider
# ─────────────────────────────────────────────────────────────────────────


class TestJumpSlider:
    """Regression for #46: clicking the groove of a short-range slider
    page-stepped (default pageStep=10) straight to the minimum or
    maximum instead of the clicked position."""

    def _make(self, theme, qtbot):
        from memanga.gui.components.slider import JumpSlider
        s = JumpSlider()
        s.setMinimum(1)
        s.setMaximum(8)
        s.resize(280, 24)
        qtbot.addWidget(s)
        s.show()
        return s

    def _click_at(self, slider, x):
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QMouseEvent
        pos = QPointF(x, slider.height() / 2)
        for etype in (QMouseEvent.Type.MouseButtonPress,
                      QMouseEvent.Type.MouseButtonRelease):
            ev = QMouseEvent(etype, pos, pos,
                             Qt.MouseButton.LeftButton,
                             Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier)
            if etype == QMouseEvent.Type.MouseButtonPress:
                slider.mousePressEvent(ev)
            else:
                slider.mouseReleaseEvent(ev)

    def test_page_step_is_one(self, theme, qtbot):
        s = self._make(theme, qtbot)
        assert s.pageStep() == 1

    def test_click_center_sets_middle_value(self, theme, qtbot):
        s = self._make(theme, qtbot)
        s.setValue(1)
        self._click_at(s, s.width() / 2)
        assert s.value() in (4, 5), (
            f"center click gave {s.value()}, expected mid-range"
        )

    def test_click_does_not_saturate_to_extremes(self, theme, qtbot):
        s = self._make(theme, qtbot)
        s.setValue(4)
        # Click ~3/4 of the way along the groove: a stock QSlider would
        # page-step (by 10) and slam to the maximum.
        self._click_at(s, s.width() * 0.75)
        assert s.value() not in (1, 8), (
            f"groove click saturated to {s.value()}"
        )
        assert s.value() > 4

    def test_click_left_quarter_lowers_value(self, theme, qtbot):
        s = self._make(theme, qtbot)
        s.setValue(8)
        self._click_at(s, s.width() * 0.25)
        assert 1 < s.value() < 4

    def test_click_at_ends_reaches_extremes(self, theme, qtbot):
        s = self._make(theme, qtbot)
        s.setValue(4)
        self._click_at(s, 1)
        assert s.value() == 1
        self._click_at(s, s.width() - 1)
        assert s.value() == 8
