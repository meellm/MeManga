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
