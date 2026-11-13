"""Settings → General at the default window size, and its theme-coloured
details after a theme switch made on that page."""

from __future__ import annotations


def test_general_tab_fits_and_follows_a_theme_switch(app_window, qapp,
                                                    theme, monkeypatch):
    # One window for both checks: each window costs a full page setup.
    from memanga.gui.assets import icons
    from memanga.gui.components.theme_picker import ThemePicker

    app_window.resize(1100, 750)
    app_window.show()
    app_window.show_page("settings")
    page = app_window._pages["settings"]
    page._switch_tab("general")
    qapp.processEvents()
    qapp.processEvents()

    # Live finding: the Light theme card was cut off at the right edge.
    scroll = page._general_scroll
    viewport = scroll.viewport()
    assert scroll.widget().width() <= viewport.width()
    assert not scroll.horizontalScrollBar().isVisible()
    picker = scroll.widget().findChild(ThemePicker)
    assert not picker.is_stacked()
    for card in picker._cards.values():
        right = card.mapTo(viewport, card.rect().topRight()).x()
        assert right < viewport.width()

    # Icons and accent text drawn once kept the old theme's colours.
    drawn = []
    real_icon = icons.icon

    def recording_icon(name, color, *args, **kwargs):
        drawn.append((name, color))
        return real_icon(name, color, *args, **kwargs)

    monkeypatch.setattr(icons, "icon", recording_icon)
    theme.set_theme("light")  # subscribers only; no app restyle needed
    toks = theme.tokens()
    for name in ("refresh", "settings", "bell", "info"):
        assert (name, toks["text.t_2"]) in drawn
    assert toks["accent.primary"] in page._concurrent_value_lbl.styleSheet()
