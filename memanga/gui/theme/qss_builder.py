"""
Generate the global QSS string from a theme token dict.

Approach: define a single Python f-string template with dotted-key
substitutions from the flat token table. No file I/O, no jinja — just
explicit substitution so it's easy to debug.

QSS is not full CSS. Things QSS cannot do (gradients on rounded shapes,
backdrop blur, transform translate, drop-shadow on widgets without
QGraphicsDropShadowEffect, animations) are handled in paintEvent on
individual widgets. The QSS here handles: backgrounds, borders, radius,
padding, font, color, hover/pressed/checked pseudo-states, scrollbars.
"""

from .tokens import flat, TYPOGRAPHY, RADII


def build_stylesheet(theme: dict) -> str:
    """Build the application-wide QSS for the given theme dict."""
    t = flat(theme)

    # Pull common values out for readability.
    bg_0 = t["surfaces.bg_0"]
    bg_1 = t["surfaces.bg_1"]
    bg_2 = t["surfaces.bg_2"]
    bg_3 = t["surfaces.bg_3"]
    bg_4 = t["surfaces.bg_4"]
    border = t["surfaces.border"]
    border_s = t["surfaces.border_strong"]
    root_bg = t["surfaces.root_bg"]

    t_1 = t["text.t_1"]
    t_2 = t["text.t_2"]
    t_3 = t["text.t_3"]

    a_primary = t["accent.primary"]
    a_primary_2 = t["accent.primary_2"]
    a_on = t["accent.on_primary"]
    a_soft10 = t["accent.soft_10"]
    a_soft16 = t["accent.soft_16"]

    danger = t["status.danger"]
    danger_soft = t["status.danger_soft"]
    warn = t["status.warn"]
    warn_soft = t["status.warn_soft"]

    sb_thumb = t["scrollbar.thumb"]
    sb_thumb_h = t["scrollbar.thumb_hover"]

    fam = TYPOGRAPHY["family_sans"]
    fam_mono = TYPOGRAPHY["family_mono"]
    sz_body = TYPOGRAPHY["size_body"]
    sz_label = TYPOGRAPHY["size_label"]
    sz_hint = TYPOGRAPHY["size_hint"]
    sz_section = TYPOGRAPHY["size_section_label"]
    sz_h1 = TYPOGRAPHY["size_h1"]
    sz_detail = TYPOGRAPHY["size_detail_title"]
    sz_card = TYPOGRAPHY["size_card_title"]
    sz_brand = TYPOGRAPHY["size_brand"]
    sz_brand_v = TYPOGRAPHY["size_brand_version"]

    rxs = RADII["xs"]
    rsm = RADII["sm"]
    rmd = RADII["md"]
    rlg = RADII["lg"]

    return f"""
/* ════════════════════════════════════════════════════════════════
   Base
   ════════════════════════════════════════════════════════════════ */
QMainWindow, QWidget#central, QDialog {{
    background-color: {root_bg};
    color: {t_1};
    font-family: {fam};
    font-size: {sz_body}pt;
}}

QWidget#main_area, QStackedWidget#main_area {{
    background-color: {bg_0};
}}

/* Page classes — pages explicitly fill bg_0 so Fusion's default beige
   doesn't leak through. Children inherit only if they don't have their
   own background. Selecting by class name avoids the descendant-combinator
   problem (which would beat our primary-button rule on specificity ties). */
LibraryPage, DownloadsPage, SearchPage, SourcesPage,
NotificationsPage, SettingsPage, DetailPage, ReaderPage {{
    background-color: {bg_0};
}}

/* Scroll areas + their inner content must be transparent so the page bg
   shows through. Without these, Fusion fills the viewport beige. */
QAbstractScrollArea, QAbstractScrollArea > QWidget {{
    background-color: transparent;
}}
QAbstractScrollArea > QWidget#qt_scrollarea_viewport > QWidget {{
    background-color: transparent;
}}

QLabel {{
    color: {t_1};
    background: transparent;
}}

QLabel[role="t1"]   {{ color: {t_1}; }}
QLabel[role="t2"]   {{ color: {t_2}; }}
QLabel[role="t3"]   {{ color: {t_3}; }}
QLabel[role="hint"] {{ color: {t_3}; font-size: {sz_hint}pt; }}
QLabel[role="meta"] {{ color: {t_2}; font-size: {sz_hint}pt; }}
QLabel[role="mono"] {{ font-family: {fam_mono}; }}
QLabel[role="mono_meta"] {{ font-family: {fam_mono}; color: {t_3}; font-size: {sz_hint - 1}pt; }}
QLabel[role="section"] {{
    color: {t_3};
    font-size: {sz_section - 2}pt;
    font-weight: 600;
    letter-spacing: 1.2px;
}}
QLabel[role="h1"]   {{ font-size: {sz_h1}pt; font-weight: 600; color: {t_1}; }}
QLabel[role="detail_title"] {{ font-size: {sz_detail}pt; font-weight: 700; color: {t_1}; }}
QLabel[role="card_title"] {{ font-size: {sz_card}pt; font-weight: 600; color: {t_1}; }}

/* ════════════════════════════════════════════════════════════════
   Buttons
   ════════════════════════════════════════════════════════════════ */
QPushButton {{
    background-color: {bg_2};
    color: {t_1};
    border: 1px solid {border};
    border-radius: {rsm}px;
    padding: 6px 14px;
    font-size: {sz_body}pt;
}}
QPushButton:hover {{
    background-color: {bg_3};
    border-color: {border_s};
}}
QPushButton:pressed {{
    background-color: {bg_4};
}}
QPushButton:disabled {{
    color: {t_3};
    background-color: {bg_1};
    border-color: {border};
}}

/* Keyboard focus ring (issue #396). Qt has no :focus-visible, so the
   app sets focusVisible="true" on a button only when it took focus
   without a mouse press; a clicked button keeps its normal look. The
   ring is 2px and the padding gives back the extra pixel, so the label
   doesn't move. Variants below that change padding restate it.
   `outline: none` drops the style's own dotted box inside the label,
   which the ring replaces. */
QPushButton[focusVisible="true"]:focus {{
    border: 2px solid {a_primary};
    padding: 5px 13px;
    outline: none;
}}

QPushButton[variant="primary"], QPushButton[class="accent"] {{
    background-color: {a_primary};
    color: {a_on};
    border: 1px solid {a_primary};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover, QPushButton[class="accent"]:hover {{
    background-color: {a_primary_2};
    border-color: {a_primary_2};
}}
/* An accent ring would vanish on the accent fill. */
QPushButton[variant="primary"][focusVisible="true"]:focus,
QPushButton[class="accent"][focusVisible="true"]:focus {{
    border-color: {t_1};
}}

QPushButton[variant="ghost"], QPushButton[class="flat"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t_2};
}}
QPushButton[variant="ghost"]:hover, QPushButton[class="flat"]:hover {{
    background-color: {bg_2};
    color: {t_1};
}}

QPushButton[variant="danger"], QPushButton[class="danger"] {{
    background: transparent;
    color: {danger};
    border: 1px solid {danger_soft};
}}
QPushButton[variant="danger"]:hover, QPushButton[class="danger"]:hover {{
    background-color: {danger_soft};
}}

QPushButton[size="sm"] {{
    padding: 4px 10px;
    font-size: {sz_hint}pt;
    border-radius: {rxs}px;
}}
QPushButton[size="sm"][focusVisible="true"]:focus {{
    padding: 3px 9px;
}}

/* Nav items (sidebar) — symmetric padding pulls the text upward in
   the 40-px button so descenders ('g' in "Settings", 'y' in
   "Library") get the full bottom margin. The button height already
   accounts for the extra room. The transparent 2px border is the
   focus ring's room (issue #396); padding is 2px less to match. */
QPushButton[variant="nav"], QPushButton[class="nav"] {{
    background: transparent;
    border: 2px solid transparent;
    border-radius: {rsm}px;
    color: {t_2};
    text-align: left;
    padding: 6px 10px 11px 10px;
    font-size: {sz_body}pt;
    font-weight: 500;
}}
QPushButton[variant="nav"][focusVisible="true"]:focus,
QPushButton[class="nav"][focusVisible="true"]:focus {{
    border-color: {a_primary};
    padding: 6px 10px 11px 10px;
}}
QPushButton[variant="nav"]:hover, QPushButton[class="nav"]:hover {{
    background-color: {bg_2};
    color: {t_1};
}}
QPushButton[variant="nav"][active="true"],
QPushButton[class="nav"][active="true"] {{
    color: {a_primary};
    background-color: {a_soft10};
}}
/* Nav button with a count badge needs extra right padding so the text
   doesn't slide under the badge. */
QPushButton[variant="nav"][hasBadge="true"],
QPushButton[class="nav"][hasBadge="true"],
QPushButton[variant="nav"][hasBadge="true"][focusVisible="true"]:focus,
QPushButton[class="nav"][hasBadge="true"][focusVisible="true"]:focus {{
    padding-right: 42px;
}}

/* Tabs — the underline is the bottom edge of a transparent 2px
   border, which also gives the focus ring its room (issue #396). */
QPushButton[variant="tab"], QPushButton[class="tab"] {{
    background: transparent;
    border: 2px solid transparent;
    border-radius: 0;
    color: {t_2};
    /* Extra bottom padding so the descender on 'y' in History/Library
       isn't clipped above the underline border. */
    padding: 8px 14px 12px 14px;
    font-size: {sz_body}pt;
    font-weight: 500;
}}
QPushButton[variant="tab"]:hover, QPushButton[class="tab"]:hover {{
    color: {t_1};
}}
QPushButton[variant="tab"][active="true"],
QPushButton[class="tab"][active="true"] {{
    color: {a_primary};
    border-bottom-color: {a_primary};
    font-weight: 600;
}}
QPushButton[variant="tab"][focusVisible="true"]:focus,
QPushButton[class="tab"][focusVisible="true"]:focus {{
    border-color: {a_primary};
    padding: 8px 14px 12px 14px;
}}

/* Chip-style (segmented filter buttons). The transparent 2px border is
   the focus ring's room (issue #396). */
QPushButton[variant="chip"] {{
    background: transparent;
    border: 2px solid transparent;
    border-radius: {rxs}px;
    color: {t_2};
    padding: 3px 10px;
    font-size: {sz_hint + 0.5}pt;
    font-weight: 500;
}}
QPushButton[variant="chip"][focusVisible="true"]:focus {{
    border-color: {a_primary};
    padding: 3px 10px;
}}
QPushButton[variant="chip"]:hover {{
    color: {t_1};
}}
QPushButton[variant="chip"][active="true"] {{
    background-color: {bg_3};
    color: {t_1};
}}

/* Icon button — 32x32 square */
QPushButton[variant="icon"] {{
    background-color: {bg_2};
    border: 1px solid {border};
    color: {t_2};
    padding: 0;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
    border-radius: {rsm}px;
}}
QPushButton[variant="icon"]:hover {{
    background-color: {bg_3};
    color: {t_1};
}}
QPushButton[variant="icon"][focusVisible="true"]:focus {{
    padding: 0;
}}

/* ════════════════════════════════════════════════════════════════
   Inputs
   ════════════════════════════════════════════════════════════════ */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {bg_1};
    color: {t_1};
    border: 1px solid {border};
    border-radius: {rsm}px;
    padding: 6px 12px;
    font-size: {sz_body}pt;
    selection-background-color: {a_primary};
    selection-color: {a_on};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {a_primary};
}}
QLineEdit[role="mono"] {{ font-family: {fam_mono}; }}

QComboBox {{
    background-color: {bg_1};
    color: {t_1};
    border: 1px solid {border};
    border-radius: {rsm}px;
    padding: 6px 28px 6px 12px;
    font-size: {sz_body}pt;
}}
QComboBox:hover {{ border-color: {border_s}; }}
QComboBox:focus {{ border-color: {a_primary}; }}
QComboBox::drop-down {{
    border: none; width: 22px;
    subcontrol-origin: padding; subcontrol-position: right center;
}}
/* QSS can't really draw a triangle for ::down-arrow reliably across
   styles (Fusion overrides it). Setting `image: none` removes Fusion's
   default native arrow, and we lean on the unicode ▾ which renders
   consistently on every OS. The arrow's color comes from Qt's
   FocusPolicy + the color we set on QComboBox::down-arrow text. */
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
}}
/* Add a real caret via a sub-element label-style hack: paint over the
   space we reserved on the right of the combobox. */
QComboBox::drop-down {{
    border: none;
    width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background-color: {bg_1};
    color: {t_1};
    border: 1px solid {border_s};
    border-radius: {rsm}px;
    selection-background-color: {a_soft10};
    selection-color: {a_primary};
    outline: none;
    padding: 4px;
}}

/* Checkbox + radio */
QCheckBox, QRadioButton {{
    color: {t_1};
    spacing: 8px;
    font-size: {sz_body}pt;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border_s};
    background: {bg_1};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {a_primary};
    border-color: {a_primary};
}}
/* Keyboard focus (issue #396): a 2px ring in text colour, which shows
   on the accent fill of a checked box too. The box shrinks by the extra
   border so the label doesn't move. */
QCheckBox[focusVisible="true"]::indicator:focus,
QRadioButton[focusVisible="true"]::indicator:focus {{
    border: 2px solid {t_1};
    width: 14px; height: 14px;
}}
QCheckBox[focusVisible="true"]:focus, QRadioButton[focusVisible="true"]:focus {{
    outline: none;
}}

/* ════════════════════════════════════════════════════════════════
   Scrollbars
   ════════════════════════════════════════════════════════════════ */
QScrollArea {{ background: transparent; border: none; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {sb_thumb};
    border-radius: 5px;
    min-height: 30px;
    border: 2px solid transparent;
    background-clip: padding;
}}
QScrollBar::handle:vertical:hover {{ background: {sb_thumb_h}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0; background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 0 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: {sb_thumb};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {sb_thumb_h}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0; background: transparent;
}}

/* ════════════════════════════════════════════════════════════════
   Progress bar
   ════════════════════════════════════════════════════════════════ */
QProgressBar {{
    background-color: {bg_3};
    border: none;
    border-radius: 2px;
    max-height: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {a_primary};
    border-radius: 2px;
}}

/* ════════════════════════════════════════════════════════════════
   Shell — sidebar, title bar, cards, page chrome
   ════════════════════════════════════════════════════════════════ */
QWidget#title_bar {{
    background-color: {bg_1};
    border-bottom: 1px solid {border};
}}

QWidget#sidebar {{
    background-color: {bg_1};
    border-right: 1px solid {border};
}}

QWidget#sidebar_footer {{
    background-color: {bg_1};
    border-top: 1px solid {border};
}}

QFrame#sync_card {{
    background-color: {bg_2};
    border: 1px solid {border};
    border-radius: {rmd}px;
}}

/* Cards */
QFrame[role="card"], QFrame[class="card"] {{
    background-color: {bg_1};
    border: 1px solid {border};
    border-radius: {rmd}px;
}}
/* Cards that open something (list rows, continue-reading cards) take
   keyboard focus (issue #396). The border stays 1px so the content
   doesn't move; the tint makes the change easy to spot. */
QFrame[role="card"]:focus, QFrame[class="card"]:focus {{
    border-color: {a_primary};
    background-color: {a_soft10};
}}
QFrame[role="card_2"] {{
    background-color: {bg_2};
    border: 1px solid {border};
    border-radius: {rmd}px;
}}
/* A borderless field inside the box has focus (Search, issue #396):
   the same accent edge as a focused text field. */
QFrame[role="card_2"][focusWithin="true"] {{
    border-color: {a_primary};
}}

/* Stat card variant */
QFrame[role="stat_card"] {{
    background-color: {bg_1};
    border: 1px solid {border};
    border-radius: {rmd}px;
}}

/* Settings card variant — taller padding */
QFrame[role="settings_card"] {{
    background-color: {bg_1};
    border: 1px solid {border};
    border-radius: {rmd}px;
}}

/* Page header divider */
QFrame#page_header_divider {{
    background-color: {border};
    max-height: 1px; min-height: 1px;
    border: none;
}}

/* Theme picker card — active gets accent border */
QFrame[role="theme_card"] {{
    background-color: {bg_2};
    border: 2px solid {border};
    border-radius: {rmd}px;
}}
QFrame[role="theme_card"][selected="true"] {{
    border-color: {a_primary};
    background-color: {a_soft10};
}}
/* Keyboard focus (issue #396) in text colour, so it reads apart from
   the accent border of the selected card. */
QFrame[role="theme_card"]:focus {{
    border-color: {t_1};
}}

/* Chapter / download / history row */
QFrame[role="row"] {{
    background: transparent;
    border: none;
    border-top: 1px solid {border};
}}
QFrame[role="row"]:hover {{ background-color: {bg_2}; }}

/* Detail chapter rows. Styled here, by role, instead of one style sheet
   per row widget: a long series has thousands of these, and rows built
   this way follow a theme switch on their own. */
QFrame[role="chapter_row"] {{
    background: transparent;
    border: none;
    border-top: 1px solid {border};
}}
QFrame[role="chapter_row"][first="true"] {{ border-top: none; }}
QLabel[role="row_title"] {{
    font-size: {sz_hint}pt; font-weight: 500; color: {t_1};
}}
QLabel[role="row_title"][read="true"] {{ font-weight: 400; color: {t_3}; }}
QLabel[role="chapter_state"] {{
    background-color: {bg_2};
    border-radius: {rsm}px;
}}
QLabel[role="chapter_state"][state="read"] {{ background-color: {a_primary}; }}
QLabel[role="chapter_state"][state="downloaded"] {{ background-color: {a_soft10}; }}
QLabel[role="chapter_state"][state="partial"],
QLabel[role="chapter_state"][state="external"] {{ background-color: {warn_soft}; }}

/* Centered "nothing here" text of a list or grid. */
QLabel[role="empty"] {{
    color: {t_2};
    font-size: {sz_body}pt;
    padding: 48px;
}}

/* ════════════════════════════════════════════════════════════════
   Badges
   ════════════════════════════════════════════════════════════════ */
QLabel[role="badge_new"] {{
    background-color: {a_primary};
    color: {a_on};
    padding: 2px 7px;
    border-radius: 999px;
    font-size: {TYPOGRAPHY["size_badge"]}pt;
    font-weight: 600;
}}
QLabel[role="badge_count"] {{
    background-color: {bg_2};
    color: {t_3};
    padding: 1px 6px;
    border-radius: 999px;
    font-family: {fam_mono};
    font-size: {sz_hint - 1}pt;
}}
QLabel[role="badge_count_active"] {{
    background-color: {a_soft16};
    color: {a_primary};
    padding: 1px 6px;
    border-radius: 999px;
    font-family: {fam_mono};
    font-size: {sz_hint - 1}pt;
}}

/* ════════════════════════════════════════════════════════════════
   Tooltip / menu
   ════════════════════════════════════════════════════════════════ */
QToolTip {{
    background-color: {bg_1};
    color: {t_1};
    border: 1px solid {border_s};
    padding: 4px 8px;
    border-radius: {rxs}px;
}}
QMenu {{
    background: {bg_1};
    border: 1px solid {border_s};
    border-radius: {rsm}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 14px;
    color: {t_1};
    border-radius: {rxs}px;
}}
/* Solid accent highlight, like a native menu, so the item the arrow
   keys are on is easy to see (issue #396). */
QMenu::item:selected {{ background: {a_primary}; color: {a_on}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {t_2};
    padding: 4px 8px;
    border-radius: {rxs}px;
}}
QToolButton:hover {{
    background-color: {bg_2};
    color: {t_1};
}}
QToolButton:focus {{ border-color: {a_primary}; }}

/* Close button (Windows/Linux frameless) gets red hover */
QPushButton#title_close_btn:hover {{
    background-color: #C4382E;
    color: #FFFFFF;
}}
"""
