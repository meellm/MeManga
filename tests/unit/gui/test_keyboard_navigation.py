"""
Keyboard operation and focus visibility of the desktop app (issue #396).

Custom click targets must answer the keys a button answers, focus rings
must be drawn for keyboard focus only, keyboard focus must follow a page
change, and the reader keys documented in the README must work.
"""

from pathlib import Path

import pytest


def _key(key, mods=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.Type.KeyPress, key,
                     mods if mods is not None else Qt.KeyboardModifier.NoModifier)


# ── Key helpers ──────────────────────────────────────────────────────────


class TestKeyHelpers:
    def test_activation_keys(self, qapp):
        from PySide6.QtCore import Qt
        from memanga.gui.components.keyboard import is_activation
        assert is_activation(_key(Qt.Key.Key_Return))
        assert is_activation(_key(Qt.Key.Key_Space))
        assert is_activation(_key(Qt.Key.Key_Enter,
                                  Qt.KeyboardModifier.KeypadModifier))
        assert not is_activation(_key(Qt.Key.Key_Return,
                                      Qt.KeyboardModifier.ControlModifier))
        assert not is_activation(_key(Qt.Key.Key_A))

    def test_context_menu_keys(self, qapp):
        from PySide6.QtCore import Qt
        from memanga.gui.components.keyboard import is_context_menu
        assert is_context_menu(_key(Qt.Key.Key_Menu))
        assert is_context_menu(_key(Qt.Key.Key_F10,
                                    Qt.KeyboardModifier.ShiftModifier))
        assert not is_context_menu(_key(Qt.Key.Key_F10))


# ── Cards and rows ───────────────────────────────────────────────────────


class TestCardsAnswerKeys:
    def test_manga_card(self, theme, sample_manga):
        from PySide6.QtCore import Qt
        from memanga.gui.components.manga_card import MangaCard
        opened, menus = [], []
        card = MangaCard(None, manga=sample_manga,
                         on_click=opened.append,
                         on_right_click=lambda m, x, y: menus.append(m))
        assert card.focusPolicy() == Qt.FocusPolicy.TabFocus
        card.keyPressEvent(_key(Qt.Key.Key_Return))
        card.keyPressEvent(_key(Qt.Key.Key_Space))
        assert opened == [sample_manga, sample_manga]
        card.keyPressEvent(_key(Qt.Key.Key_F10,
                                Qt.KeyboardModifier.ShiftModifier))
        card.keyPressEvent(_key(Qt.Key.Key_Menu))
        assert menus == [sample_manga, sample_manga]
        card.keyPressEvent(_key(Qt.Key.Key_A))
        assert len(opened) == 2

    def test_manga_row(self, theme, sample_manga):
        from PySide6.QtCore import Qt
        from memanga.gui.components.manga_row import MangaRow
        opened, menus = [], []
        row = MangaRow(None, manga=sample_manga, on_click=opened.append,
                       on_right_click=lambda m, x, y: menus.append(m))
        assert row.focusPolicy() == Qt.FocusPolicy.TabFocus
        row.keyPressEvent(_key(Qt.Key.Key_Return))
        row.keyPressEvent(_key(Qt.Key.Key_Menu))
        assert opened == [sample_manga]
        assert menus == [sample_manga]

    def test_continue_card(self, theme, sample_manga):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
        from memanga.gui.components.continue_card import ContinueCard
        opened = []
        card = ContinueCard(None, manga=sample_manga, cover_pixmap=QPixmap(),
                            last_chapter="1", progress_pct=10,
                            on_click=opened.append)
        assert card.focusPolicy() == Qt.FocusPolicy.TabFocus
        card.keyPressEvent(_key(Qt.Key.Key_Space))
        assert opened == [sample_manga]

    def test_theme_card_picks_theme(self, theme):
        from PySide6.QtCore import Qt
        from memanga.gui.components.theme_picker import ThemePicker
        picker = ThemePicker()
        card = picker._cards["light"]
        assert card.focusPolicy() == Qt.FocusPolicy.TabFocus
        card.keyPressEvent(_key(Qt.Key.Key_Return))
        assert theme.current_theme() == "light"


class TestModeDropdownKeyboard:
    def test_triggering_an_item_picks_it(self, theme, qtbot):
        from memanga.gui.components.mode_dropdown import ModeDropdown
        d = ModeDropdown(initial="auto")
        manual = d._menu.actions()[1]
        with qtbot.waitSignal(d.value_changed, timeout=1000) as blocker:
            manual.trigger()
        assert blocker.args == ["manual"]
        assert d.value() == "manual"

    def test_focused_item_is_highlighted(self, theme):
        from memanga.gui.components.mode_dropdown import ModeDropdown
        d = ModeDropdown(initial="auto")
        item = d._menu.actions()[0].defaultWidget()
        item._set_highlight(True)
        assert "background-color" in item.styleSheet()
        item._set_highlight(False)
        assert item.styleSheet() == ""


# ── Focus ring for keyboard focus only ───────────────────────────────────


def _user_input(kind):
    """A real key or mouse press delivered through the application, as
    the installed input tracker sees it."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from memanga.gui.focus import install_focus_marker
    install_focus_marker(QApplication.instance())
    target = QWidget()
    if kind == "key":
        QTest.keyClick(target, Qt.Key.Key_Tab)
    elif kind == "modifier":
        QTest.keyClick(target, Qt.Key.Key_Shift)
    else:
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)


class TestInputModality:
    def _press(self, kind):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent
        if kind == "mouse":
            return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1),
                               QPointF(1, 1), Qt.MouseButton.LeftButton,
                               Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
        key = Qt.Key.Key_Shift if kind == "modifier" else Qt.Key.Key_Return
        return QKeyEvent(QEvent.Type.KeyPress, key,
                         Qt.KeyboardModifier.NoModifier)

    def test_tracks_last_input(self, qapp):
        from memanga.gui.focus import InputModality
        m = InputModality()
        assert not m.keyboard  # at launch: no ring before any input
        m.eventFilter(None, self._press("key"))
        assert m.keyboard
        m.eventFilter(None, self._press("modifier"))
        assert m.keyboard
        m.eventFilter(None, self._press("mouse"))
        assert not m.keyboard
        m.eventFilter(None, self._press("modifier"))  # Shift before a click
        assert not m.keyboard

    def test_never_consumes_events(self, qapp):
        from memanga.gui.focus import InputModality
        m = InputModality()
        for kind in ("key", "modifier", "mouse"):
            assert m.eventFilter(None, self._press(kind)) is False


class TestFocusMarker:
    def test_keyboard_focus_marks_visible(self, qapp):
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.focus import mark_focus_source
        _user_input("key")
        prev, btn = QPushButton("a"), QPushButton("x")
        mark_focus_source(prev, btn)
        assert btn.property("focusVisible") == "true"

    def test_focus_with_no_previous_widget_follows_last_input(self, qapp):
        # Live recheck R1: after a keyboard page change focus arrives with
        # no previous focus widget (show_page cleared it, or Qt restores
        # it on activation). It used to be marked "false" for that alone,
        # so "Check all" had focus but no ring.
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.focus import mark_focus_source
        btn = QPushButton("x")
        _user_input("key")
        mark_focus_source(None, btn)
        assert btn.property("focusVisible") == "true"
        _user_input("mouse")
        mark_focus_source(None, btn)
        assert btn.property("focusVisible") == "false"

    def test_pointer_focus_marks_hidden(self, qapp):
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.focus import mark_focus_source
        prev, btn = QPushButton("a"), QPushButton("x")
        btn.setProperty("focusVisible", "true")
        _user_input("mouse")
        _user_input("modifier")  # Shift+click stays a click
        mark_focus_source(prev, btn)
        assert btn.property("focusVisible") == "false"

    def test_focus_given_for_the_user_follows_last_input(self, qapp):
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.focus import give_focus
        btn = QPushButton("x")
        btn.setProperty("focusVisible", "false")
        _user_input("key")
        give_focus(btn)
        assert btn.property("focusVisible") == "true"
        _user_input("mouse")
        give_focus(btn)  # already focused: no focusChanged, still marked
        assert btn.property("focusVisible") == "false"

    def test_mouse_focus_marks_hidden(self, qapp, monkeypatch):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        from memanga.gui import focus

        class _Pressed:
            @staticmethod
            def mouseButtons():
                return Qt.MouseButton.LeftButton

        _user_input("key")
        monkeypatch.setattr(focus, "QGuiApplication", _Pressed)
        prev, btn = QPushButton("a"), QPushButton("x")
        btn.setProperty("focusVisible", "true")
        focus.mark_focus_source(prev, btn)
        assert btn.property("focusVisible") == "false"

    def test_non_buttons_are_left_alone(self, qapp):
        from PySide6.QtWidgets import QLineEdit
        from memanga.gui.focus import mark_focus_source
        entry = QLineEdit()
        mark_focus_source(None, entry)
        assert entry.property("focusVisible") is None

    def test_window_installs_marker(self, app_window, qapp):
        assert qapp.property("memangaFocusMarker") is True


class TestFocusRingStyles:
    @pytest.mark.parametrize("name", ["dark", "light"])
    def test_rings_are_keyboard_only_and_cover_variants(self, name):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        qss = build_stylesheet(THEMES[name])
        accent = THEMES[name]["accent"]["primary"]
        for sel in ('QPushButton[focusVisible="true"]:focus',
                    'QPushButton[variant="primary"][focusVisible="true"]:focus',
                    'QPushButton[variant="nav"][focusVisible="true"]:focus',
                    'QPushButton[variant="tab"][focusVisible="true"]:focus',
                    'QPushButton[variant="chip"][focusVisible="true"]:focus',
                    'QCheckBox[focusVisible="true"]::indicator:focus',
                    'QFrame[role="theme_card"]:focus',
                    'QFrame[class="card"]:focus',
                    'QToolButton:focus',
                    'QFrame[role="card_2"][focusWithin="true"]'):
            assert sel in qss, sel
        assert f"border: 2px solid {accent};" in qss
        # Menu items the arrow keys are on get a solid highlight.
        assert f"QMenu::item:selected {{ background: {accent};" in qss
        # No bare QPushButton:focus rule: a click must not leave a ring.
        assert "QPushButton:focus" not in qss

    def test_ring_room_is_reserved_so_labels_do_not_move(self):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        qss = build_stylesheet(THEMES["dark"])
        nav = qss.split('QPushButton[variant="nav"], QPushButton[class="nav"] {', 1)[1]
        nav = nav.split("}", 1)[0]
        assert "border: 2px solid transparent;" in nav
        assert "padding: 6px 10px 11px 10px;" in nav


# ── Focus follows page changes ───────────────────────────────────────────


def test_first_focusable_skips_scroll_areas_and_labels(qapp):
    from PySide6.QtWidgets import (QLabel, QPushButton, QScrollArea,
                                   QVBoxLayout, QWidget)
    from memanga.gui.focus import first_focusable
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.addWidget(QScrollArea())
    lay.addWidget(QLabel("text"))
    btn = QPushButton("go")
    lay.addWidget(btn)
    box.show()
    try:
        assert first_focusable(box) is btn
    finally:
        box.close()


def test_scrolled_out_controls_are_not_first(qapp):
    from PySide6.QtWidgets import (QPushButton, QScrollArea, QVBoxLayout,
                                   QWidget)
    from memanga.gui.focus import first_focusable
    box = QWidget()
    lay = QVBoxLayout(box)
    area = QScrollArea()
    content = QWidget()
    content.setFixedSize(300, 3000)
    hidden_below = QPushButton("far below", content)
    hidden_below.move(0, 2800)
    area.setWidget(content)
    lay.addWidget(area)
    shown = QPushButton("below the area, on screen")
    lay.addWidget(shown)
    box.resize(320, 300)
    box.show()
    try:
        qapp.processEvents()
        area.verticalScrollBar().setValue(2700)  # "far below" now in view
        qapp.processEvents()
        # Reading order would pick the button in the area, which is
        # higher on screen once scrolled; it is in view, so it wins.
        assert first_focusable(box) is hidden_below
        area.verticalScrollBar().setValue(0)  # scrolled out again
        qapp.processEvents()
        assert first_focusable(box) is shown
    finally:
        box.close()





def test_first_focusable_uses_reading_order_not_creation_order(qapp):
    # The live and unit failures: a page's widgets rebuilt after start-up
    # come before its header in the window's focus chain.
    from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QVBoxLayout,
                                   QWidget)
    from memanga.gui.focus import first_focusable
    box = QWidget()
    lay = QVBoxLayout(box)
    later = QPushButton("lower, made first")
    header = QHBoxLayout()
    right = QPushButton("right")
    left = QPushButton("left")
    header.addWidget(left)
    header.addWidget(right)
    lay.addLayout(header)
    lay.addWidget(later)
    replaced = QPushButton("about to be replaced")
    lay.insertWidget(0, replaced)
    replaced.hide()
    box.show()
    try:
        assert first_focusable(box) is left
    finally:
        box.close()


def _active_library(app_window, qtbot, manga_list):
    from PySide6.QtWidgets import QApplication
    app_window.config.set("manga", manga_list)
    library = app_window._pages["library"]
    library._set_view_mode("grid")
    library._refresh()
    app_window.show()
    app_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is app_window,
                    timeout=5000)
    qtbot.waitUntil(lambda: all(c.isVisible() for _m, c in library._cards),
                    timeout=2000)
    return library


def _focused():
    from PySide6.QtWidgets import QApplication
    return QApplication.focusWidget()


def _on_text(page, text):
    """Real application focus is on a visible button of ``page`` whose
    label contains ``text``."""
    from PySide6.QtWidgets import QPushButton
    w = _focused()
    return (isinstance(w, QPushButton) and w.isVisible()
            and page.isAncestorOf(w) and text in w.text())


def test_quick_second_page_change_still_gets_focus(
        app_window, qapp, qtbot, sample_manga):
    # Enter on a card, then Alt+Left before control returns to the event
    # loop: the first handoff hasn't run, so nothing has focus at the
    # second change. The handoff must carry over to Library, and the
    # stale one for Detail must not fire.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    library = _active_library(app_window, qtbot, [sample_manga])
    _manga, card = library._cards[0]
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(card.hasFocus, timeout=2000)

    QTest.keyClick(card, Qt.Key.Key_Return)  # through the app, as typed
    assert _focused() is None  # handoff to Detail still pending
    app_window.show_page("library")

    qtbot.waitUntil(lambda: _on_text(library, "Check all"), timeout=2000)
    qapp.processEvents()
    assert _on_text(library, "Check all")
    assert app_window._current_page == "library"
    assert _focused().property("focusVisible") == "true"


def test_card_opened_from_keyboard_takes_focus_to_detail(
        app_window, qapp, qtbot, sample_manga):
    # Live check: focus ended on a Detail widget that was about to be
    # replaced (or its scroll area), so the first Tab only reached
    # "‹ Library". Focus must settle on that button itself.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    library = _active_library(app_window, qtbot, [sample_manga])
    _manga, card = library._cards[0]
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(card.hasFocus, timeout=2000)

    QTest.keyClick(card, Qt.Key.Key_Return)  # through the app, as typed

    detail = app_window._pages["detail"]
    assert app_window._current_page == "detail"

    def on_back_button():
        w = _focused()
        return (isinstance(w, QPushButton) and w.isVisible()
                and detail.isAncestorOf(w) and "Library" in w.text())
    qtbot.waitUntil(on_back_button, timeout=2000)
    assert _focused().property("focusVisible") == "true"
    # It stays there once the old widgets are gone.
    qapp.processEvents()
    assert on_back_button()


def test_handoff_runs_after_the_pages_own_posted_events(
        app_window, qapp, qtbot, sample_manga):
    # Live recheck R1: the handoff was a 0 ms timer, whose place relative
    # to the events that show Detail's rebuilt widgets depends on the
    # event dispatcher. Posted events alone (no timers) must now be enough
    # to put a marked ring on the new "‹ Library".
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    library = _active_library(app_window, qtbot, [sample_manga])
    _manga, card = library._cards[0]
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(card.hasFocus, timeout=2000)

    QTest.keyClick(card, Qt.Key.Key_Return)
    assert _focused() is None
    qapp.sendPostedEvents()

    detail = app_window._pages["detail"]
    assert _on_text(detail, "Library")
    assert _focused().property("focusVisible") == "true"


def test_card_opened_with_the_mouse_gets_focus_but_no_ring(
        app_window, qapp, qtbot, sample_manga):
    # Mouse behaviour kept: focus still follows into Detail (it was in
    # the Library filter), but a click leaves no ring, as on any button.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    library = _active_library(app_window, qtbot, [sample_manga])
    library._search_entry.setFocus(Qt.FocusReason.MouseFocusReason)
    qtbot.waitUntil(library._search_entry.hasFocus, timeout=2000)
    _manga, card = library._cards[0]

    QTest.mouseClick(card, Qt.MouseButton.LeftButton)

    detail = app_window._pages["detail"]
    qtbot.waitUntil(lambda: _on_text(detail, "Library"), timeout=2000)
    assert _focused().property("focusVisible") == "false"


def test_back_from_detail_lands_on_library_not_sidebar(
        app_window, qapp, qtbot, sample_manga):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    library = _active_library(app_window, qtbot, [sample_manga])
    _manga, card = library._cards[0]
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(card.hasFocus, timeout=2000)
    QTest.keyClick(card, Qt.Key.Key_Return)  # through the app, as typed
    detail = app_window._pages["detail"]
    # Real focus on Detail's first control before leaving it. (An earlier
    # `detail.isAncestorOf(_focused() or detail)` was true with no focus
    # at all, so the test left Detail before its handoff ran.)
    qtbot.waitUntil(lambda: _on_text(detail, "Library"), timeout=2000)

    app_window.show_page("library")

    def describe():
        # Everything needed to tell the possible causes apart: no focus
        # at all, focus kept only by an inactive window, the page not
        # shown, or no control found to focus.
        from PySide6.QtWidgets import QApplication
        from memanga.gui.focus import first_focusable

        def name(w):
            if w is None:
                return "None"
            page = next((n for n, p in app_window._pages.items()
                         if p is w or p.isAncestorOf(w)), "no page")
            return (f"{type(w).__name__} "
                    f"{getattr(w, 'text', lambda: '')()!r} on {page} "
                    f"visible={w.isVisible()}")
        return (f"app focus={name(_focused())}; "
                f"window focus={name(app_window.focusWidget())}; "
                f"active={QApplication.activeWindow() is app_window}; "
                f"library visible={library.isVisible()}, "
                f"current={app_window._stack.currentWidget() is library}; "
                f"first_focusable={name(first_focusable(library))}")

    # The first control in reading order: "Check all" in the header.
    def on_check_all():
        w = _focused()
        return (isinstance(w, QPushButton) and w.isVisible()
                and library.isAncestorOf(w) and "Check all" in w.text())
    try:
        qtbot.waitUntil(on_check_all, timeout=2000)
    except Exception:
        pytest.fail(f"focus after Detail → Library: {describe()}")
    # Still there once the replaced cards are gone.
    qapp.processEvents()
    assert on_check_all(), describe()
    assert _focused().property("focusVisible") == "true"


def test_sidebar_navigation_keeps_focus_in_sidebar(app_window, qapp, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app_window.show()
    app_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is app_window,
                    timeout=5000)
    nav = app_window._sidebar._buttons["settings"]
    nav.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(nav.hasFocus, timeout=2000)
    nav.click()
    qapp.processEvents()
    qapp.processEvents()
    assert app_window._current_page == "settings"
    assert nav.hasFocus()


def test_focus_returns_to_card_after_quick_action(
        app_window, qapp, qtbot, sample_manga, monkeypatch):
    # Live check: after "Set: On hold" from the keyboard menu the cards
    # were rebuilt and focus was gone.
    from PySide6.QtCore import Qt
    from memanga.gui.pages import library as library_mod

    def _pick_on_hold(parent, x, y, items):
        dict(i for i in items if i[0])["Set: On hold"]()

    monkeypatch.setattr(library_mod, "ContextMenu", _pick_on_hold)
    library = _active_library(app_window, qtbot, [sample_manga])
    _manga, card = library._cards[0]
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(card.hasFocus, timeout=2000)

    card.keyPressEvent(_key(Qt.Key.Key_Menu))

    def new_card_focused():
        cards = [c for m, c in library._cards
                 if m.get("title") == sample_manga["title"]]
        return bool(cards) and cards[0] is not card and cards[0].hasFocus()
    qtbot.waitUntil(new_card_focused, timeout=2000)
    status = next(m for m in app_window.config.get("manga", [])
                  if m["title"] == sample_manga["title"])["status"]
    assert status == "on-hold"


# ── No invisible Tab stops ───────────────────────────────────────────────


def test_page_scroll_areas_are_not_tab_stops(app_window):
    # Live check: Library, Detail, Settings, Search and Notifications each
    # had one Tab stop with no ring: the page scroll area.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea
    for name, page in app_window._pages.items():
        for area in page.findChildren(QScrollArea):
            assert area.focusPolicy() == Qt.FocusPolicy.NoFocus, name


def test_page_down_scrolls_from_a_control_outside_the_scroll_area(
        theme, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
    from memanga.gui.pages.base import BasePage
    page = BasePage(None, app=None)
    lay = QVBoxLayout(page)
    area = QScrollArea()
    tall = QWidget()
    tall.setMinimumHeight(3000)
    area.setWidget(tall)
    lay.addWidget(area)
    page.resize(400, 300)
    page.show()
    try:
        qapp.processEvents()
        bar = area.verticalScrollBar()
        assert bar.maximum() > 0
        page.keyPressEvent(_key(Qt.Key.Key_PageDown))
        assert bar.value() == min(bar.maximum(), bar.pageStep())
        page.keyPressEvent(_key(Qt.Key.Key_PageUp))
        assert bar.value() == 0
    finally:
        page.close()


# ── Search field, menus, dialogs ─────────────────────────────────────────


def test_search_bar_shows_focus_of_its_borderless_field(app_window, qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication
    entry = app_window._pages["search"]._search_entry
    bar = entry.parentWidget()
    QApplication.sendEvent(entry, QFocusEvent(
        QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert bar.property("focusWithin") == "true"
    QApplication.sendEvent(entry, QFocusEvent(
        QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    assert bar.property("focusWithin") == "false"


class TestModalFocus:
    def _modal(self):
        from PySide6.QtWidgets import QLineEdit, QPushButton
        from memanga.gui.components.modal import ModalDialog

        class _Dialog(ModalDialog):
            def build_body(self):
                self.field_a = QLineEdit()
                self.field_b = QLineEdit()
                self.body_layout.addWidget(self.field_a)
                self.body_layout.addWidget(self.field_b)
                self.ok_btn = QPushButton("Add")
                self.foot_layout.addWidget(self.ok_btn)

        return _Dialog(None, "Test")

    @staticmethod
    def _tab_walk(qtbot, dialog, start, presses):
        """Press Tab ``presses`` times from ``start`` with the dialog
        shown and active; return each widget that took focus. Real key
        presses, not the raw focus chain, which also lists widgets Tab
        skips (labels, frames)."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        dialog.show()
        dialog.activateWindow()
        qtbot.waitUntil(lambda: QApplication.activeWindow() is dialog,
                        timeout=5000)
        start.setFocus(Qt.FocusReason.TabFocusReason)
        qtbot.waitUntil(start.hasFocus, timeout=2000)
        seen = []
        for _ in range(presses):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
            seen.append(QApplication.focusWidget())
        return seen

    def test_tab_order_follows_the_layout(self, theme, qtbot):
        # Live check: Tab went "Add → × → Cancel".
        d = self._modal()
        try:
            seen = self._tab_walk(qtbot, d, d._close_btn, 5)
        finally:
            d.close()
        assert seen == [d.field_a, d.field_b, d.cancel_btn, d.ok_btn,
                        d._close_btn]

    def test_download_from_dialog_tab_order(self, theme, qtbot,
                                            sample_manga):
        from PySide6.QtWidgets import QPushButton
        from memanga.gui.components.download_from_modal import (
            DownloadFromModal)
        d = DownloadFromModal(None, sample_manga, on_confirm=lambda *a: None)
        start = next(b for b in d.findChildren(QPushButton)
                     if b.text() == "Start download")
        try:
            seen = self._tab_walk(qtbot, d, d._close_btn, 5)
        finally:
            d.close()
        assert seen == [d._chapter_input, d._skip_check, d.cancel_btn,
                        start, d._close_btn]

    def test_foot_buttons_get_an_unclipped_ring(self, theme):
        # Live check: the foot's sheet cut Cancel's ring at top and bottom.
        d = self._modal()
        sheet = d.cancel_btn.parentWidget().styleSheet()
        rule = sheet.split('QPushButton[focusVisible="true"]:focus', 1)[1]
        assert "border: 2px solid" in rule
        assert "border-radius: 6px" in rule


# ── Shortcuts ────────────────────────────────────────────────────────────


def _shortcut(widget, keys):
    from PySide6.QtGui import QKeySequence, QShortcut
    seq = QKeySequence(keys)
    matches = [s for s in widget.findChildren(QShortcut) if s.key() == seq]
    assert matches, f"no shortcut {seq.toString()} on {widget!r}"
    return matches[0]


class TestShortcuts:
    @pytest.mark.parametrize("page_name, field", [
        ("library", "_search_entry"),
        ("sources", "_filter_entry"),
        ("search", "_search_entry"),
    ])
    def test_find_focuses_the_filter(self, app_window, qapp, qtbot,
                                     page_name, field):
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QApplication
        app_window.show()
        app_window.activateWindow()
        qtbot.waitUntil(lambda: QApplication.activeWindow() is app_window,
                        timeout=5000)
        app_window.show_page(page_name)
        page = app_window._pages[page_name]
        entry = getattr(page, field)
        entry.setText("abc")
        _shortcut(page, QKeySequence.StandardKey.Find).activated.emit()
        qapp.processEvents()
        assert entry.hasFocus()
        assert entry.selectedText() == "abc"

    def test_back_on_detail_returns_to_library(self, app_window, qapp,
                                               sample_manga):
        from PySide6.QtGui import QKeySequence
        app_window.config.set("manga", [sample_manga])
        app_window.show_page("detail", manga=sample_manga)
        qapp.processEvents()
        detail = app_window._pages["detail"]
        _shortcut(detail, QKeySequence.StandardKey.Back).activated.emit()
        assert app_window._current_page == "library"

    def test_ctrl_comma_opens_settings(self, app_window, qapp):
        _shortcut(app_window, "Ctrl+,").activated.emit()
        assert app_window._current_page == "settings"


# ── Reader ───────────────────────────────────────────────────────────────


def _open_reader(app_window, qapp, sample_manga, make_cbz, pages=3):
    app_window.config.set("manga", [sample_manga])
    dl = Path(app_window.config.download_dir) / sample_manga["title"]
    dl.mkdir(parents=True, exist_ok=True)
    (dl / f"{sample_manga['title']} - Chapter 1.cbz").write_bytes(
        make_cbz(pages=pages, name="ch1.cbz").read_bytes())
    app_window.app_state.add_downloaded_chapter(sample_manga["title"], "1")
    app_window.show_page("reader", manga=sample_manga, chapter="1")
    qapp.processEvents()
    return app_window._pages["reader"]


class TestReaderKeys:
    def test_ctrl_0_resets_zoom(self, app_window, qapp, sample_manga,
                                make_cbz):
        from PySide6.QtCore import Qt
        reader = _open_reader(app_window, qapp, sample_manga, make_cbz)
        reader._zoom_in()
        assert reader._zoom_level != pytest.approx(1.0)
        reader.keyPressEvent(_key(Qt.Key.Key_0,
                                  Qt.KeyboardModifier.ControlModifier))
        assert reader._zoom_level == pytest.approx(1.0)
        assert reader._zoom_label.text() == "100%"

    def test_plain_0_does_not_reset_zoom(self, app_window, qapp,
                                         sample_manga, make_cbz):
        from PySide6.QtCore import Qt
        reader = _open_reader(app_window, qapp, sample_manga, make_cbz)
        reader._zoom_in()
        zoomed = reader._zoom_level
        reader.keyPressEvent(_key(Qt.Key.Key_0))
        assert reader._zoom_level == pytest.approx(zoomed)

    def test_continuous_page_keys_scroll(self, app_window, qapp,
                                         sample_manga, make_cbz):
        from PySide6.QtCore import Qt
        reader = _open_reader(app_window, qapp, sample_manga, make_cbz)
        bar = reader._scroll.verticalScrollBar()
        assert bar.maximum() > 0, "test needs content taller than the viewport"
        reader.keyPressEvent(_key(Qt.Key.Key_PageDown))
        assert bar.value() == min(bar.maximum(), bar.pageStep())
        reader.keyPressEvent(_key(Qt.Key.Key_PageUp))
        assert bar.value() == 0
        reader.keyPressEvent(_key(Qt.Key.Key_Space))
        assert bar.value() > 0
        reader.keyPressEvent(_key(Qt.Key.Key_End))
        assert bar.value() == bar.maximum()
        reader.keyPressEvent(_key(Qt.Key.Key_Home))
        assert bar.value() == 0
        assert str(reader._chapter) == "1"

    def test_clicks_leave_focus_on_the_page(self, app_window, qapp,
                                            sample_manga, make_cbz):
        from PySide6.QtCore import Qt
        reader = _open_reader(app_window, qapp, sample_manga, make_cbz)
        assert reader._scroll.focusPolicy() == Qt.FocusPolicy.NoFocus
        for btn, _icon in reader._mode_btns.values():
            assert btn.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert reader._next_btn.focusPolicy() == Qt.FocusPolicy.TabFocus
