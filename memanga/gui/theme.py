"""
MeManga GUI Theme — dual dark/light palette with dynamic QSS generation.
"""

# ── Dark Mode Palette ──
DARK = {
    "bg": "#0F1117",
    "bg_secondary": "#141820",
    "bg_card": "#1A1D27",
    "bg_sidebar": "#0B0D13",
    "bg_input": "#1A1D27",
    "border": "#252A36",
    "fg": "#E8EAED",
    "fg_secondary": "#9AA0AB",
    "fg_muted": "#5F6673",
    "accent": "#66B22A",
    "accent_hover": "#5A9D24",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "error": "#F87171",
    "scrollbar": "#2A2F3B",
    "scrollbar_hover": "#3A4050",
}

# ── Light Mode Palette ──
LIGHT = {
    "bg": "#F8F9FB",
    "bg_secondary": "#EEF0F4",
    "bg_card": "#FFFFFF",
    "bg_sidebar": "#EBEDF2",
    "bg_input": "#FFFFFF",
    "border": "#D5D9E0",
    "fg": "#1A1D27",
    "fg_secondary": "#5F6673",
    "fg_muted": "#9AA0AB",
    "accent": "#4D8C1F",
    "accent_hover": "#3E7518",
    "success": "#16A34A",
    "warning": "#CA8A04",
    "error": "#DC2626",
    "scrollbar": "#C5CAD3",
    "scrollbar_hover": "#A8B0BC",
}

# ── Shared constants (palette-independent) ──
STATUS_COLORS = {
    "reading": "#4ADE80",
    "on-hold": "#FBBF24",
    "dropped": "#F87171",
    "completed": "#60A5FA",
}

SIDEBAR_WIDTH = 180
CARD_WIDTH = 170
CARD_HEIGHT = 260
CARD_COVER_HEIGHT = 210
CARD_RADIUS = 8

FONT_FAMILY = "Segoe UI"
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

# ── Active palette (set by apply_theme) ──
BG = DARK["bg"]
BG_SECONDARY = DARK["bg_secondary"]
BG_CARD = DARK["bg_card"]
BG_SIDEBAR = DARK["bg_sidebar"]
BG_INPUT = DARK["bg_input"]
BORDER = DARK["border"]
FG = DARK["fg"]
FG_SECONDARY = DARK["fg_secondary"]
FG_MUTED = DARK["fg_muted"]
ACCENT = DARK["accent"]
ACCENT_HOVER = DARK["accent_hover"]
SUCCESS = DARK["success"]
WARNING = DARK["warning"]
ERROR = DARK["error"]
SCROLLBAR = DARK["scrollbar"]
SCROLLBAR_HOVER = DARK["scrollbar_hover"]


def get_palette(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


def apply_theme(mode: str):
    """Update module-level color variables to match the given mode."""
    global BG, BG_SECONDARY, BG_CARD, BG_SIDEBAR, BG_INPUT, BORDER
    global FG, FG_SECONDARY, FG_MUTED, ACCENT, ACCENT_HOVER
    global SUCCESS, WARNING, ERROR, SCROLLBAR, SCROLLBAR_HOVER

    p = get_palette(mode)
    BG = p["bg"]
    BG_SECONDARY = p["bg_secondary"]
    BG_CARD = p["bg_card"]
    BG_SIDEBAR = p["bg_sidebar"]
    BG_INPUT = p["bg_input"]
    BORDER = p["border"]
    FG = p["fg"]
    FG_SECONDARY = p["fg_secondary"]
    FG_MUTED = p["fg_muted"]
    ACCENT = p["accent"]
    ACCENT_HOVER = p["accent_hover"]
    SUCCESS = p["success"]
    WARNING = p["warning"]
    ERROR = p["error"]
    SCROLLBAR = p["scrollbar"]
    SCROLLBAR_HOVER = p["scrollbar_hover"]


def generate_stylesheet(mode: str = "dark") -> str:
    """Generate QSS stylesheet for the given mode."""
    p = get_palette(mode)

    return f"""
/* ── Base ── */
QMainWindow, QWidget#central, QDialog {{
    background-color: {p["bg"]};
    color: {p["fg"]};
    font-family: "{FONT_FAMILY}";
}}

QLabel {{
    color: {p["fg"]};
    background: transparent;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {p["bg_card"]};
    color: {p["fg"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 14px;
    font-size: {FONT_SIZE_SM}pt;
}}

QPushButton:hover {{
    background-color: {p["border"]};
    border-color: {p["fg_muted"]};
}}

QPushButton:pressed {{
    background-color: {p["bg_secondary"]};
}}

QPushButton[class="accent"] {{
    background-color: {p["accent"]};
    color: #ffffff;
    border: none;
    font-weight: bold;
}}

QPushButton[class="accent"]:hover {{
    background-color: {p["accent_hover"]};
}}

QPushButton[class="danger"] {{
    background-color: {p["error"]};
    color: #ffffff;
    border: none;
}}

QPushButton[class="danger"]:hover {{
    background-color: #DC2626;
}}

QPushButton[class="flat"] {{
    background: transparent;
    border: none;
    color: {p["fg_secondary"]};
}}

QPushButton[class="flat"]:hover {{
    background-color: {p["bg_card"]};
    color: {p["fg"]};
}}

/* ── Inputs ── */
QLineEdit {{
    background-color: {p["bg_input"]};
    color: {p["fg"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: {FONT_SIZE_SM}pt;
    selection-background-color: {p["accent"]};
}}

QLineEdit:focus {{
    border-color: {p["accent"]};
}}

QComboBox {{
    background-color: {p["bg_input"]};
    color: {p["fg"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: {FONT_SIZE_SM}pt;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {p["bg_card"]};
    color: {p["fg"]};
    border: 1px solid {p["border"]};
    selection-background-color: {p["accent"]};
    selection-color: #ffffff;
}}

QCheckBox, QRadioButton {{
    color: {p["fg"]};
    spacing: 6px;
    font-size: {FONT_SIZE_SM}pt;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p["border"]};
    background: {p["bg_input"]};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p["accent"]};
    border-color: {p["accent"]};
}}

/* ── Scroll ── */
QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {p["scrollbar"]};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p["scrollbar_hover"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}

QScrollBar::handle:horizontal {{
    background: {p["scrollbar"]};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {p["scrollbar_hover"]};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}

/* ── Progress Bar ── */
QProgressBar {{
    background-color: {p["border"]};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {p["accent"]};
    border-radius: 3px;
}}

/* ── Sidebar ── */
QWidget#sidebar {{
    background-color: {p["bg_sidebar"]};
    border-right: 1px solid {p["border"]};
}}

QPushButton[class="nav"] {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {p["fg_secondary"]};
    text-align: left;
    padding: 8px 12px;
    font-size: {FONT_SIZE_SM}pt;
}}

QPushButton[class="nav"]:hover {{
    background-color: {p["bg_card"]};
    color: {p["fg"]};
}}

QPushButton[class="nav"][active="true"] {{
    background-color: {p["accent"]};
    color: #ffffff;
    font-weight: bold;
}}

/* ── Cards ── */
QFrame[class="card"] {{
    background-color: {p["bg_card"]};
    border: 1px solid {p["border"]};
    border-radius: {CARD_RADIUS}px;
}}

QFrame[class="card"]:hover {{
    border-color: {p["accent"]};
}}

/* ── Tabs ── */
QPushButton[class="tab"] {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    color: {p["fg_muted"]};
    padding: 6px 14px;
    font-size: {FONT_SIZE_SM}pt;
}}

QPushButton[class="tab"]:hover {{
    color: {p["fg"]};
    border-bottom-color: {p["border"]};
}}

QPushButton[class="tab"][active="true"] {{
    color: {p["accent"]};
    font-weight: bold;
    border-bottom-color: {p["accent"]};
}}

/* ── Tooltips ── */
QToolTip {{
    background-color: {p["bg_card"]};
    color: {p["fg"]};
    border: 1px solid {p["border"]};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ── Menu ── */
QMenu {{
    background: {p["bg_card"]};
    border: 1px solid {p["border"]};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 20px;
    color: {p["fg"]};
    border-radius: 4px;
}}

QMenu::item:selected {{
    background: {p["border"]};
}}

QMenu::separator {{
    height: 1px;
    background: {p["border"]};
    margin: 4px 8px;
}}
"""
