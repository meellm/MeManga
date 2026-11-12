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

import weakref

from .tokens import THEMES, DEFAULT_THEME, flat
from .qss_builder import build_stylesheet
from PySide6.QtCore import QSettings

_current = None
_subscribers: list = []


class _MethodSubscriber:
    """A subscribed bound method, holding its object weakly.

    Cards, rows and drop-downs subscribe when they are built and are
    thrown away on the next page refresh. Held strongly, each of them
    stayed in the subscriber list for the rest of the session and every
    theme switch called into widgets Qt had already deleted. Held
    weakly, a subscriber goes away with its widget.
    """

    __slots__ = ("_ref", "_name")

    def __init__(self, owner, name):
        self._ref = weakref.ref(owner)
        self._name = name

    def matches(self, callback) -> bool:
        return (getattr(callback, "__self__", None) is self._ref()
                and self._ref() is not None
                and getattr(callback, "__name__", None) == self._name)

    def resolve(self):
        """The method to call, or None once its object is gone."""
        owner = self._ref()
        if owner is None or not _alive(owner):
            return None
        return getattr(owner, self._name, None)


def _alive(obj) -> bool:
    """False for a Qt object whose C++ side has been deleted."""
    try:
        import shiboken6
    except Exception:
        return True
    try:
        # Only Qt wrappers can be invalid; anything else is alive for as
        # long as it is referenced.
        if not isinstance(obj, shiboken6.Object):
            return True
        return bool(shiboken6.isValid(obj))
    except Exception:
        return True


def _wrap(callback):
    """Subscriber entry for ``callback``: weak for a bound method of an
    object that allows weak references, the callback itself otherwise
    (functions, lambdas, closures), which stay subscribed until removed.
    """
    owner = getattr(callback, "__self__", None)
    name = getattr(callback, "__name__", None)
    if owner is None or not name or isinstance(owner, type(weakref)):
        return callback
    try:
        return _MethodSubscriber(owner, name)
    except TypeError:
        return callback


def _same(entry, callback) -> bool:
    if isinstance(entry, _MethodSubscriber):
        return entry.matches(callback)
    return entry is callback or entry == callback


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
    for entry in list(_subscribers):
        if isinstance(entry, _MethodSubscriber):
            cb = entry.resolve()
            if cb is None:
                # Its widget is gone: drop it instead of calling into it.
                try:
                    _subscribers.remove(entry)
                except ValueError:
                    pass
                continue
        else:
            cb = entry
        try:
            cb()
        except Exception:
            pass


def apply(qapp):
    """Generate QSS + a matching QPalette for the current theme and apply
    both to the QApplication.

    The QSS handles every widget that respects stylesheet rules. The
    QPalette covers the rest — Fusion's native frame backgrounds,
    top-level frameless dialogs before QSS paints, scrollbar tracks
    that don't go through QSS, tooltip text, text-selection highlight,
    and any custom widget that calls ``self.palette().color(...)``.

    Without the palette swap, Qt6 inherits the OS palette (light gray
    on macOS / Windows light mode), which leaks through as a white
    flash on launch and around the frameless modal panels.

    Re-apply both even when their values match: setting the stylesheet
    also asks Qt to re-polish existing widgets.
    """
    sheet = build_stylesheet(THEMES[current_theme()])
    qapp.setStyleSheet(sheet)
    palette = _build_palette(THEMES[current_theme()])
    qapp.setPalette(palette)
    # setStyleSheet handles widget re-polishing. polish(QApplication)
    # initializes the application style; it does not refresh selectors.


def _build_palette(theme: dict):
    """Translate our token table into a QPalette so widgets that ignore
    QSS (or paint before QSS applies) still pick up our theme colors.

    All three palette groups (Active / Inactive / Disabled) are set
    explicitly — Qt copies them independently and missing groups would
    fall back to OS-default colors.
    """
    from PySide6.QtGui import QPalette, QColor
    from .tokens import flat

    t = flat(theme)
    p = QPalette()

    bg_0 = QColor(t["surfaces.bg_0"])
    bg_1 = QColor(t["surfaces.bg_1"])
    bg_2 = QColor(t["surfaces.bg_2"])
    bg_3 = QColor(t["surfaces.bg_3"])
    t_1 = QColor(t["text.t_1"])
    t_2 = QColor(t["text.t_2"])
    t_3 = QColor(t["text.t_3"])
    accent = QColor(t["accent.primary"])
    on_accent = QColor(t["accent.on_primary"])

    pairs = [
        (QPalette.ColorRole.Window, bg_0),
        (QPalette.ColorRole.WindowText, t_1),
        (QPalette.ColorRole.Base, bg_1),
        (QPalette.ColorRole.AlternateBase, bg_2),
        (QPalette.ColorRole.ToolTipBase, bg_1),
        (QPalette.ColorRole.ToolTipText, t_1),
        (QPalette.ColorRole.Text, t_1),
        (QPalette.ColorRole.Button, bg_2),
        (QPalette.ColorRole.ButtonText, t_1),
        (QPalette.ColorRole.BrightText, on_accent),
        (QPalette.ColorRole.Link, accent),
        (QPalette.ColorRole.LinkVisited, accent),
        (QPalette.ColorRole.Highlight, accent),
        (QPalette.ColorRole.HighlightedText, on_accent),
        (QPalette.ColorRole.PlaceholderText, t_3),
        (QPalette.ColorRole.Mid, bg_3),
        (QPalette.ColorRole.Midlight, bg_2),
        (QPalette.ColorRole.Dark, bg_0),
        (QPalette.ColorRole.Shadow, bg_0),
        (QPalette.ColorRole.Light, bg_2),
    ]
    # Apply to every state group so the OS palette never leaks back in.
    for group in (QPalette.ColorGroup.Active,
                  QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, color in pairs:
            p.setColor(group, role, color)
    # Disabled text is dimmer.
    for role in (QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, t_2)
    return p


def on_theme_change(callback):
    """Subscribe to theme switches. Callback takes no args.

    A bound method is held weakly and unsubscribes itself when its
    object goes away; pass a method (not a lambda around one) from
    widgets that are created and destroyed while the app runs. Plain
    functions and lambdas stay subscribed until `off_theme_change`.
    """
    if any(_same(entry, callback) for entry in _subscribers):
        return
    _subscribers.append(_wrap(callback))


def off_theme_change(callback):
    for entry in list(_subscribers):
        if _same(entry, callback):
            _subscribers.remove(entry)


def subscriber_count() -> int:
    """Live subscribers, after dropping those whose object is gone."""
    for entry in list(_subscribers):
        if isinstance(entry, _MethodSubscriber) and entry.resolve() is None:
            _subscribers.remove(entry)
    return len(_subscribers)


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
