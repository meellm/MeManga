"""
MeManga theme system.

The token table in `tokens.py` is the source of truth for every color and
spacing value the UI uses. `qss_builder.py` interpolates those tokens into
a single QSS string at runtime. Switching themes = swap the active token
dict and re-apply the stylesheet.

Public entry points:
    set_theme(name)             — switch active theme (writes QSettings)
    current_theme()             — "dark" or "light"
    apply(qapp)                 — generate QSS for the current theme and apply
    on_theme_change(callback)   — subscribe to theme changes (no args)
    tokens()                    — flat dotted-key view of current tokens
"""

from .tokens import THEMES, DEFAULT_THEME, flat
from .qss_builder import build_stylesheet
from PySide6.QtCore import QSettings

_current = None
_subscribers: list = []


def _load_persisted() -> str:
    s = QSettings("MeManga", "desktop")
    val = s.value("theme", DEFAULT_THEME)
    if val not in THEMES:
        return DEFAULT_THEME
    return val


def current_theme() -> str:
    global _current
    if _current is None:
        _current = _load_persisted()
    return _current


def tokens() -> dict:
    """Flat dict of dotted-key tokens for the current theme."""
    return flat(THEMES[current_theme()])


def set_theme(name: str, qapp=None):
    """Switch theme. Persists to QSettings, re-applies stylesheet on qapp
    (if given), notifies subscribers. Subscribers should repaint any
    custom-painted widgets (paintEvent-driven brand mark, cover cards, etc.)
    """
    global _current
    if name not in THEMES:
        return
    _current = name
    QSettings("MeManga", "desktop").setValue("theme", name)
    if qapp is not None:
        apply(qapp)
    for cb in list(_subscribers):
        try:
            cb()
        except Exception:
            pass


def apply(qapp):
    """Generate QSS for the current theme and apply to the QApplication."""
    qapp.setStyleSheet(build_stylesheet(THEMES[current_theme()]))
    # Force a polish pass so style-property-driven selectors re-evaluate.
    try:
        qapp.style().polish(qapp)
    except Exception:
        pass


def on_theme_change(callback):
    """Subscribe to theme switches. Callback takes no args."""
    if callback not in _subscribers:
        _subscribers.append(callback)


def off_theme_change(callback):
    if callback in _subscribers:
        _subscribers.remove(callback)


def generate_stylesheet() -> str:
    """Back-compat: legacy ``from .. import theme; theme.generate_stylesheet()``.

    Returns QSS for the *currently active* theme. New code should call
    :func:`apply` to set the stylesheet on a QApplication directly.
    """
    return build_stylesheet(THEMES[current_theme()])


# ─────────────────────────────────────────────────────────────────────────
# Back-compat constants
# ─────────────────────────────────────────────────────────────────────────
# Existing pages were written against `theme.py` flat constants
# (T.BG, T.ACCENT, T.PAD_XL, etc.). Until those screens are migrated to
# the token-based system, we expose the same names but resolve them from
# the currently-active theme. Recomputed via `_refresh_legacy_constants()`
# on each theme change.
# ─────────────────────────────────────────────────────────────────────────

SIDEBAR_WIDTH = 232
# Manga card sizing — kept in sync with components/manga_card.py
# (CARD_W=170, COVER_H=170*1.5=255, CARD_H=COVER_H+50=305).
CARD_WIDTH = 170
CARD_HEIGHT = 305
CARD_COVER_HEIGHT = 255
CARD_RADIUS = 8

FONT_FAMILY = "Geist, Inter, Segoe UI, sans-serif"
FONT_SIZE_XS = 10
FONT_SIZE_SM = 11
FONT_SIZE_MD = 13
FONT_SIZE_LG = 15
FONT_SIZE_XL = 19
FONT_SIZE_XXL = 24

PAD_XS = 4
PAD_SM = 6
PAD_MD = 10
PAD_LG = 14
PAD_XL = 20

# Status accent colors (legacy callers expect bare hex strings).
# Re-resolved on each theme change by _refresh_legacy_constants.
STATUS_COLORS = {
    "reading": "#A0C780",
    "on-hold": "#DDA962",
    "dropped": "#DC7E72",
    "completed": "#BBABDE",
}

# Color constants — defaults to dark theme; refreshed on theme switch.
BG = THEMES["dark"]["surfaces"]["bg_0"]
BG_SECONDARY = THEMES["dark"]["surfaces"]["bg_1"]
BG_CARD = THEMES["dark"]["surfaces"]["bg_2"]
BG_SIDEBAR = THEMES["dark"]["surfaces"]["bg_1"]
BG_INPUT = THEMES["dark"]["surfaces"]["bg_1"]
BORDER = THEMES["dark"]["surfaces"]["border"]
FG = THEMES["dark"]["text"]["t_1"]
FG_SECONDARY = THEMES["dark"]["text"]["t_2"]
FG_MUTED = THEMES["dark"]["text"]["t_3"]
ACCENT = THEMES["dark"]["accent"]["primary"]
ACCENT_HOVER = THEMES["dark"]["accent"]["primary_2"]
SUCCESS = THEMES["dark"]["status"]["success"]
WARNING = THEMES["dark"]["status"]["warn"]
ERROR = THEMES["dark"]["status"]["danger"]
SCROLLBAR = THEMES["dark"]["scrollbar"]["thumb"]
SCROLLBAR_HOVER = THEMES["dark"]["scrollbar"]["thumb_hover"]


def _refresh_legacy_constants():
    """Repoint legacy module-level constants (BG, FG, ACCENT, …) at the
    currently-active theme. Called automatically on every theme switch.

    Existing pages that read e.g. ``T.ACCENT`` at construct time won't
    auto-update (Qt widgets cache styles), so they should also subscribe
    to :func:`on_theme_change` to re-apply per-widget styling.
    """
    global BG, BG_SECONDARY, BG_CARD, BG_SIDEBAR, BG_INPUT, BORDER
    global FG, FG_SECONDARY, FG_MUTED, ACCENT, ACCENT_HOVER
    global SUCCESS, WARNING, ERROR, SCROLLBAR, SCROLLBAR_HOVER, STATUS_COLORS

    th = THEMES[current_theme()]
    BG = th["surfaces"]["bg_0"]
    BG_SECONDARY = th["surfaces"]["bg_1"]
    BG_CARD = th["surfaces"]["bg_2"]
    BG_SIDEBAR = th["surfaces"]["bg_1"]
    BG_INPUT = th["surfaces"]["bg_1"]
    BORDER = th["surfaces"]["border"]
    FG = th["text"]["t_1"]
    FG_SECONDARY = th["text"]["t_2"]
    FG_MUTED = th["text"]["t_3"]
    ACCENT = th["accent"]["primary"]
    ACCENT_HOVER = th["accent"]["primary_2"]
    SUCCESS = th["status"]["success"]
    WARNING = th["status"]["warn"]
    ERROR = th["status"]["danger"]
    SCROLLBAR = th["scrollbar"]["thumb"]
    SCROLLBAR_HOVER = th["scrollbar"]["thumb_hover"]
    STATUS_COLORS = {
        "reading": th["accent"]["primary"],
        "on-hold": th["status"]["warn"],
        "dropped": th["status"]["danger"],
        "completed": th["secondary_lilac"]["primary"],
    }


# Make sure the legacy constants reflect the persisted theme on import.
_refresh_legacy_constants()
# And keep them fresh whenever someone calls set_theme().
on_theme_change(_refresh_legacy_constants)
