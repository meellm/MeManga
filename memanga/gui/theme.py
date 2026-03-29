"""
Theme constants for MeManga GUI.
"""

# Accent colors
ACCENT = "#669F2A"
ACCENT_HOVER = "#578A22"
ACCENT_LIGHT = "#5C8F26"
ACCENT_LIGHT_HOVER = "#4D7A1F"

# Dark mode palette
DARK = {
    "bg": "#0A0D12",
    "bg_secondary": "#0F1319",
    "bg_card": "#141920",
    "bg_sidebar": "#080B0F",
    "bg_input": "#141920",
    "fg": "#F3F4F6",
    "fg_secondary": "#B0B5BC",
    "fg_muted": "#6B7280",
    "border": "#1F2937",
    "accent": ACCENT,
    "accent_hover": ACCENT_HOVER,
    "success": "#669F2A",
    "warning": "#EAB308",
    "error": "#EF4444",
    "scrollbar": "#1F2937",
}

# Light mode palette
LIGHT = {
    "bg": "#F3F4F6",
    "bg_secondary": "#E5E7EB",
    "bg_card": "#ffffff",
    "bg_sidebar": "#D1D5DB",
    "bg_input": "#ffffff",
    "fg": "#0A0D12",
    "fg_secondary": "#374151",
    "fg_muted": "#6B7280",
    "border": "#D1D5DB",
    "accent": ACCENT_LIGHT,
    "accent_hover": ACCENT_LIGHT_HOVER,
    "success": "#669F2A",
    "warning": "#CA8A04",
    "error": "#DC2626",
    "scrollbar": "#9CA3AF",
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
    "reading": "#669F2A",
    "on-hold": "#EAB308",
    "dropped": "#EF4444",
    "completed": "#3B82F6",
}


def get_palette(mode: str) -> dict:
    """Get color palette for the given mode ('dark' or 'light')."""
    return DARK if mode == "dark" else LIGHT


def font(size: int = FONT_SIZE_MD, weight: str = "normal") -> tuple:
    """Create a font tuple."""
    return (FONT_FAMILY, size, weight)
