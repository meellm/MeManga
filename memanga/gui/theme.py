"""
Theme constants for MeManga GUI.
Calming green accent with dark/light mode support.
"""

# Accent colors
ACCENT = "#2fa572"
ACCENT_HOVER = "#28916a"
ACCENT_LIGHT = "#2d9b6e"
ACCENT_LIGHT_HOVER = "#258c5f"

# Dark mode palette
DARK = {
    "bg": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_card": "#1f2940",
    "bg_sidebar": "#111827",
    "bg_input": "#1f2940",
    "fg": "#e2e8f0",
    "fg_secondary": "#94a3b8",
    "fg_muted": "#64748b",
    "border": "#2d3748",
    "accent": ACCENT,
    "accent_hover": ACCENT_HOVER,
    "success": "#22c55e",
    "warning": "#eab308",
    "error": "#ef4444",
    "scrollbar": "#334155",
}

# Light mode palette
LIGHT = {
    "bg": "#f8fafc",
    "bg_secondary": "#f1f5f9",
    "bg_card": "#ffffff",
    "bg_sidebar": "#e2e8f0",
    "bg_input": "#ffffff",
    "fg": "#1e293b",
    "fg_secondary": "#475569",
    "fg_muted": "#94a3b8",
    "border": "#cbd5e1",
    "accent": ACCENT_LIGHT,
    "accent_hover": ACCENT_LIGHT_HOVER,
    "success": "#16a34a",
    "warning": "#ca8a04",
    "error": "#dc2626",
    "scrollbar": "#94a3b8",
}

# Typography
FONT_FAMILY = "Segoe UI"
FONT_SIZE_XS = 11
FONT_SIZE_SM = 12
FONT_SIZE_MD = 14
FONT_SIZE_LG = 16
FONT_SIZE_XL = 20
FONT_SIZE_XXL = 26

# Spacing
PAD_XS = 4
PAD_SM = 8
PAD_MD = 12
PAD_LG = 16
PAD_XL = 24

# Sidebar
SIDEBAR_WIDTH = 220
SIDEBAR_ICON_SIZE = 20

# Card dimensions
CARD_WIDTH = 180
CARD_HEIGHT = 280
CARD_COVER_HEIGHT = 230
CARD_RADIUS = 8

# Status colors
STATUS_COLORS = {
    "reading": "#22c55e",
    "on-hold": "#eab308",
    "dropped": "#ef4444",
    "completed": "#3b82f6",
}


def get_palette(mode: str) -> dict:
    """Get color palette for the given mode ('dark' or 'light')."""
    return DARK if mode == "dark" else LIGHT


def font(size: int = FONT_SIZE_MD, weight: str = "normal") -> tuple:
    """Create a font tuple."""
    return (FONT_FAMILY, size, weight)
