"""Toast: readable in both themes, current after a theme switch, and
stacked instead of overlapping."""

from __future__ import annotations

import pytest


@pytest.fixture
def parent(qapp, theme):
    from PySide6.QtWidgets import QWidget
    widget = QWidget()
    widget.resize(800, 600)
    return widget


def _colours(toast):
    """(background, text) hex colours out of the toast's style sheet."""
    import re
    sheet = toast.styleSheet()
    background = re.search(r"background:\s*(#[0-9A-Fa-f]{6})", sheet).group(1)
    text = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", sheet).group(1)
    return background.upper(), text.upper()


class TestToastColours:
    @pytest.mark.parametrize("theme_name", ["dark", "light"])
    @pytest.mark.parametrize("kind,token", [
        ("info", "accent.primary"), ("success", "status.success"),
        ("warning", "status.warn"), ("warn", "status.warn"),
        ("error", "status.danger")])
    def test_text_is_the_on_colour_of_the_fill(self, parent, qapp, theme,
                                               theme_name, kind, token):
        from memanga.gui.components.toast import Toast
        theme.set_theme(theme_name, qapp)
        toks = theme.tokens()
        background, text = _colours(Toast(parent, "Saved", kind=kind))
        assert background == toks[token].upper()
        # Issue #395: never plain white on the dark theme's light fills.
        assert text == toks["accent.on_primary"].upper()

    def test_colours_follow_a_theme_switch(self, parent, qapp, theme):
        # They used to be read once, at import.
        from memanga.gui.components.toast import Toast
        dark = _colours(Toast(parent, "one"))
        theme.set_theme("light", qapp)
        light = _colours(Toast(parent, "two"))
        assert dark != light
        assert light[0] == theme.tokens()["accent.primary"].upper()

    def test_unknown_kind_uses_the_accent(self, parent, theme):
        from memanga.gui.components.toast import Toast
        background, _text = _colours(Toast(parent, "hm", kind="other"))
        assert background == theme.tokens()["accent.primary"].upper()

    def test_message_is_plain_text_and_named(self, parent):
        from PySide6.QtCore import Qt
        from memanga.gui.components.toast import Toast
        toast = Toast(parent, "<b>site said</b>")
        assert toast.textFormat() == Qt.TextFormat.PlainText
        assert toast.accessibleName() == "<b>site said</b>"


class TestToastStacking:
    def test_toasts_do_not_overlap(self, parent):
        from memanga.gui.components.toast import Toast
        first = Toast(parent, "first")
        second = Toast(parent, "second")
        third = Toast(parent, "third")
        assert first.y() < second.y() < third.y()
        assert second.y() >= first.y() + first.height()
        assert third.y() >= second.y() + second.height()

    def test_dismissing_one_closes_the_gap(self, parent):
        from memanga.gui.components.toast import Toast
        first = Toast(parent, "first")
        second = Toast(parent, "second")
        top = first.y()
        first._dismiss()
        assert second.y() == top

    def test_toasts_follow_the_parent_width(self, parent, qapp):
        from memanga.gui.components.toast import Toast
        from memanga.gui import theme as T
        parent.show()
        qapp.processEvents()
        toast = Toast(parent, "hello")
        parent.resize(500, 600)
        qapp.processEvents()
        assert toast.x() + toast.width() == parent.width() - T.PAD_LG

    def test_long_message_wraps_inside_the_parent(self, parent):
        from memanga.gui.components.toast import Toast
        toast = Toast(parent, "The source answered with an error. " * 12)
        assert toast.wordWrap()
        assert toast.width() <= 420
        assert toast.x() >= 0
        # Taller than a one-line toast.
        assert toast.height() > Toast(parent, "short").height()

    def test_toasts_on_different_parents_are_independent(self, parent, qapp):
        from PySide6.QtWidgets import QWidget
        from memanga.gui.components.toast import Toast
        other = QWidget()
        other.resize(800, 600)
        a = Toast(parent, "a")
        b = Toast(other, "b")
        assert a.y() == b.y()
