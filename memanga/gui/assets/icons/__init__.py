"""
Lucide-style stroke icons rendered as colored SVGs at runtime.

QIcon doesn't natively support `currentColor` from a static SVG, so we
template the stroke color into the SVG string and return a QIcon. This
lets nav buttons and toolbar buttons re-color on theme switch.

Usage:
    from memanga.gui.assets.icons import icon
    button.setIcon(icon("library", color=T.tokens()["text.t_2"], size=18))
"""

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


# Lucide-style stroke icons — 24x24 viewBox, stroke-width 1.7, no fill.
# Source: HTML prototype paths. {color} is replaced at render time.
ICONS: dict[str, str] = {
    "library": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 4h6v16H4z"/><path d="M10 4h6v16h-6z"/><path d="M17 5l3 1-3 14"/>'
        '</g></svg>'
    ),
    "download": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 4v12"/><path d="M7 11l5 5 5-5"/><path d="M4 20h16"/>'
        '</g></svg>'
    ),
    "search": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'
        '</g></svg>'
    ),
    "sources": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
        '<path d="M12 3a14 14 0 0 1 0 18"/><path d="M12 3a14 14 0 0 0 0 18"/>'
        '</g></svg>'
    ),
    "notifications": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
        '<path d="M10 21a2 2 0 0 0 4 0"/>'
        '</g></svg>'
    ),
    "settings": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
        '</g></svg>'
    ),
    "plus": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round">'
        '<path d="M12 5v14M5 12h14"/></g></svg>'
    ),
    "refresh": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'
        '</g></svg>'
    ),
    "chevron_down": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m6 9 6 6 6-6"/></g></svg>'
    ),
    "x_close": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round">'
        '<path d="M6 6l12 12M18 6L6 18"/></g></svg>'
    ),
    "folder": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></g></svg>'
    ),
    "check": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m5 12 5 5L20 7"/></g></svg>'
    ),
    "trash": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 6h18"/><path d="M8 6v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>'
        '</g></svg>'
    ),
    "bell": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
        '<path d="M10 21a2 2 0 0 0 4 0"/></g></svg>'
    ),
    # Continuous-scroll glyph: pages stacked vertically, the lower one
    # cropped by the viewport (issue #32 reader layout toggle).
    "view_continuous": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linejoin="round">'
        '<rect x="6" y="2" width="12" height="9" rx="1"/>'
        '<path d="M6 15h12M6 15v7M18 15v7"/>'
        '</g></svg>'
    ),
    # Single-page glyph: one upright rectangle (issue #24 dual-page toggle).
    "view_single": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linejoin="round">'
        '<rect x="6" y="3" width="12" height="18" rx="1"/>'
        '</g></svg>'
    ),
    # Dual-page glyph: two side-by-side rectangles.
    "view_dual": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linejoin="round">'
        '<rect x="3" y="4" width="8" height="16" rx="1"/>'
        '<rect x="13" y="4" width="8" height="16" rx="1"/>'
        '</g></svg>'
    ),
    # Open book glyph — used in chapter rows for "Read" (opened in
    # Reader at least once). Visually distinct from "Downloaded" check.
    "book_open": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M2 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H2z"/>'
        '<path d="M22 4h-7a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h8z"/>'
        '</g></svg>'
    ),
    # Filled check-circle — used for chapter rows that have a file on
    # disk but the user hasn't opened them yet ("Downloaded" sub-state).
    "check_circle": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="m8 12 3 3 5-6"/>'
        '</g></svg>'
    ),
    # Down-arrow into tray — "Not downloaded" chapter rows.
    "download_tray": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 3v12"/>'
        '<path d="m7 10 5 5 5-5"/>'
        '<path d="M4 21h16"/>'
        '</g></svg>'
    ),
    # External-link icon — chapter is marked "Read elsewhere" via the
    # onboarding "I'm on chapter N" sentinel.
    "external": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>'
        '<path d="M14 4h6v6"/>'
        '<path d="m10 14 10-10"/>'
        '</g></svg>'
    ),
}


def icon(name: str, color: str, size: int = 16) -> QIcon:
    """Render an SVG icon at the requested color + size as a QIcon."""
    svg_template = ICONS.get(name)
    if not svg_template:
        return QIcon()  # silently empty so missing names don't crash

    svg_bytes = QByteArray(svg_template.format(color=color).encode("utf-8"))
    renderer = QSvgRenderer(svg_bytes)

    img = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    renderer.render(painter)
    painter.end()

    return QIcon(QPixmap.fromImage(img))
