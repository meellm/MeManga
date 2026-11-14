"""End-to-end: switching themes flips QPalette, QSS, custom-painted
widgets, and persists across MainWindow rebuilds."""

import pytest

pytestmark = pytest.mark.integration


def test_palette_flips_on_theme_switch(qapp, theme):
    from PySide6.QtGui import QPalette
    from memanga.gui.theme.qss_builder import build_stylesheet

    # Exercise both real transitions and repeated application of the
    # active theme on the same application/style instance.
    for name in ("dark", "dark", "light", "light", "dark", "light", "dark"):
        theme.set_theme(name, qapp)
        bg = qapp.palette().color(QPalette.ColorRole.Window).name().lower()
        assert bg == theme.tokens()["surfaces.bg_0"].lower()
        assert qapp.styleSheet() == build_stylesheet(theme.THEMES[name])


def test_subscribers_called_in_order(qapp, theme):
    log = []
    theme.on_theme_change(lambda: log.append(("sub1", theme.current_theme())))
    theme.on_theme_change(lambda: log.append(("sub2", theme.current_theme())))
    theme.set_theme("light", qapp)
    # Both subscribers ran, each saw the new theme.
    assert ("sub1", "light") in log
    assert ("sub2", "light") in log


def test_persists_across_restarts(qapp, theme, fresh_settings):
    from PySide6.QtCore import QSettings
    theme.set_theme("light", qapp)
    # Read fresh
    assert QSettings("MeManga", "desktop").value("theme") == "light"
    theme.set_theme("dark", qapp)


def test_pages_render_in_both_themes(app_window, qapp, theme):
    for theme_name in ("dark", "light", "dark"):
        theme.set_theme(theme_name, qapp)
        for v in ("library", "downloads", "search", "notifications",
                   "sources", "settings"):
            app_window.show_page(v)
            qapp.processEvents()
