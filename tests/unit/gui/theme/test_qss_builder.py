"""Tests for memanga.gui.theme.qss_builder — turns tokens into QSS."""

import pytest


class TestBuildStylesheet:
    def test_returns_nonempty_string(self):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        qss = build_stylesheet(THEMES["dark"])
        assert isinstance(qss, str)
        assert len(qss) > 500

    def test_contains_required_selectors(self):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        qss = build_stylesheet(THEMES["dark"])
        # Every page chrome selector should appear at least once.
        for sel in ("QMainWindow", "QPushButton", "QLineEdit", "QComboBox",
                    "QScrollBar", "QFrame", "QMenu", "QToolTip"):
            assert sel in qss, f"missing selector: {sel}"

    def test_substitutes_theme_colors(self):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        dark_qss = build_stylesheet(THEMES["dark"])
        light_qss = build_stylesheet(THEMES["light"])
        # Dark contains dark surface colors; light contains light surfaces.
        assert THEMES["dark"]["surfaces"]["bg_0"] in dark_qss
        assert THEMES["light"]["surfaces"]["bg_0"] in light_qss
        # Inverse — light bg_0 should not appear in dark QSS.
        assert THEMES["light"]["surfaces"]["bg_0"] not in dark_qss

    def test_accent_primary_used_for_active_nav(self):
        from memanga.gui.theme.tokens import THEMES
        from memanga.gui.theme.qss_builder import build_stylesheet
        qss = build_stylesheet(THEMES["dark"])
        assert 'variant="nav"' in qss or "class=\"nav\"" in qss


class TestApplyTheme:
    def test_apply_sets_palette_and_stylesheet(self, qapp, theme):
        from PySide6.QtGui import QPalette
        # Sample a palette role — should match dark bg_0 after apply.
        bg = qapp.palette().color(QPalette.ColorRole.Window).name().lower()
        assert bg == theme.tokens()["surfaces.bg_0"].lower()

    def test_set_theme_round_trips(self, qapp, theme):
        from PySide6.QtGui import QPalette
        theme.set_theme("light", qapp)
        assert theme.current_theme() == "light"
        light_bg = qapp.palette().color(QPalette.ColorRole.Window).name().lower()
        theme.set_theme("dark", qapp)
        dark_bg = qapp.palette().color(QPalette.ColorRole.Window).name().lower()
        assert light_bg != dark_bg

    def test_unknown_theme_name_noop(self, theme, qapp):
        before = theme.current_theme()
        theme.set_theme("not-a-theme", qapp)
        assert theme.current_theme() == before

    def test_on_theme_change_fires(self, qapp, theme):
        calls = []
        theme.on_theme_change(lambda: calls.append(theme.current_theme()))
        theme.set_theme("light", qapp)
        assert calls == ["light"]
        theme.set_theme("dark", qapp)
        assert calls == ["light", "dark"]


class TestRepeatedApply:
    """Repeated applications refresh the style without changing the theme."""

    @pytest.fixture
    def sheets_set(self, qapp, theme, monkeypatch):
        """Every style sheet handed to the application from here on."""
        real = qapp.setStyleSheet
        seen = []

        def _set(sheet):
            seen.append(sheet)
            real(sheet)

        monkeypatch.setattr(qapp, "setStyleSheet", _set)
        return seen

    @staticmethod
    def _sheet(theme, name):
        from memanga.gui.theme.qss_builder import build_stylesheet
        return build_stylesheet(theme.THEMES[name])

    @staticmethod
    def _window_colour(qapp):
        from PySide6.QtGui import QPalette
        return qapp.palette().color(QPalette.ColorRole.Window).name().lower()

    def test_same_theme_is_reapplied(self, qapp, theme, sheets_set):
        theme.apply(qapp)
        theme.apply(qapp)
        assert sheets_set == [self._sheet(theme, "dark")] * 2
        assert qapp.styleSheet() == self._sheet(theme, "dark")
        assert self._window_colour(qapp) == theme.tokens()["surfaces.bg_0"].lower()

    def test_a_switch_is_applied_once_and_takes_effect(self, qapp, theme,
                                                       sheets_set):
        theme.set_theme("light", qapp)
        assert sheets_set == [self._sheet(theme, "light")]
        assert qapp.styleSheet() == self._sheet(theme, "light")
        assert self._window_colour(qapp) == theme.tokens()["surfaces.bg_0"].lower()

        theme.set_theme("dark", qapp)
        assert sheets_set == [self._sheet(theme, "light"),
                              self._sheet(theme, "dark")]
        assert self._window_colour(qapp) == theme.tokens()["surfaces.bg_0"].lower()

    def test_choosing_the_active_theme_still_notifies(self, qapp, theme,
                                                      sheets_set):
        # Reapplying the active theme still notifies subscribers once.
        calls = []
        subscriber = lambda: calls.append(theme.current_theme())  # noqa: E731
        theme.on_theme_change(subscriber)
        try:
            theme.set_theme("dark", qapp)
        finally:
            theme.off_theme_change(subscriber)
        assert calls == ["dark"]
        assert sheets_set == [self._sheet(theme, "dark")]

    def test_a_sheet_set_by_someone_else_is_replaced(self, qapp, theme,
                                                     sheets_set):
        qapp.setStyleSheet("QLabel { color: red; }")
        theme.apply(qapp)
        assert qapp.styleSheet() == self._sheet(theme, "dark")
        assert sheets_set[-1] == self._sheet(theme, "dark")

    def test_widget_made_after_repeated_apply_is_styled(
            self, qapp, theme, sheets_set):
        # Newly created widgets inherit the current application sheet.
        from PySide6.QtWidgets import QPushButton
        theme.apply(qapp)
        button = QPushButton("Save")
        button.setProperty("variant", "primary")
        button.ensurePolished()
        accent = theme.tokens()["accent.primary"].lower()
        assert button.palette().button().color().name().lower() == accent
        assert sheets_set == [self._sheet(theme, "dark")]
