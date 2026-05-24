"""
Design tokens — mirror of memanga-pyside6-spec.json `tokens.themes`.

This is the single source of truth for colors. Every widget pulls from
here (directly via `tokens()` or indirectly via QSS substitution).

Don't hardcode hex anywhere outside this file.
"""

DEFAULT_THEME = "dark"

THEMES = {
    "dark": {
        "label": "Dark — warm ink-on-page inverse",
        "surfaces": {
            "bg_0": "#16130F",
            "bg_1": "#211D17",
            "bg_2": "#2A251E",
            "bg_3": "#332E26",
            "bg_4": "#3E372E",
            "border": "#2D2920",
            "border_strong": "#3F3930",
            "root_bg": "#0E0B07",
        },
        "text": {
            "t_1": "#F1ECDF",
            "t_2": "#BCB6A5",
            "t_3": "#8A836F",
            "t_4": "#4F483D",
        },
        "accent": {
            "primary": "#A0C780",
            "primary_2": "#80AB60",
            "on_primary": "#11160A",
            "soft_10": "rgba(160,199,128,0.12)",
            "soft_16": "rgba(160,199,128,0.18)",
            "ring": "rgba(160,199,128,0.30)",
        },
        "secondary_lilac": {
            "primary": "#BBABDE",
            "primary_2": "#9F8DC6",
            "on_primary": "#1A1429",
            "soft": "rgba(187,171,222,0.12)",
            "fade": "rgba(187,171,222,0.18)",
        },
        "status": {
            "danger": "#DC7E72",
            "danger_soft": "rgba(220,126,114,0.13)",
            "warn": "#DDA962",
            "warn_soft": "rgba(221,169,98,0.15)",
            "info": "#BBABDE",
            "info_soft": "rgba(187,171,222,0.12)",
            "success": "#A0C780",
        },
        "scrollbar": {
            "track": "transparent",
            "thumb": "#3E372E",
            "thumb_hover": "#4F483D",
        },
    },
    "light": {
        "label": "Light — paper and ink",
        "surfaces": {
            "bg_0": "#F5F1E6",
            "bg_1": "#FFFFFF",
            "bg_2": "#EFEBE0",
            "bg_3": "#E5E0D1",
            "bg_4": "#D5D0BE",
            "border": "#E2DDCD",
            "border_strong": "#CCC6B3",
            "root_bg": "#EAE5D6",
        },
        "text": {
            "t_1": "#18170F",
            "t_2": "#55524A",
            "t_3": "#8A877B",
            "t_4": "#B7B3A4",
        },
        "accent": {
            "primary": "#648C4F",
            "primary_2": "#517438",
            "on_primary": "#FFFFFF",
            "soft_10": "rgba(100,140,79,0.08)",
            "soft_16": "rgba(100,140,79,0.14)",
            "ring": "rgba(100,140,79,0.25)",
        },
        "secondary_lilac": {
            "primary": "#7869A8",
            "primary_2": "#5F5093",
            "on_primary": "#FFFFFF",
            "soft": "rgba(120,105,168,0.09)",
            "fade": "rgba(120,105,168,0.15)",
        },
        "status": {
            "danger": "#B85043",
            "danger_soft": "rgba(184,80,67,0.10)",
            "warn": "#B07A35",
            "warn_soft": "rgba(176,122,53,0.12)",
            "info": "#7869A8",
            "info_soft": "rgba(120,105,168,0.09)",
            "success": "#648C4F",
        },
        "scrollbar": {
            "track": "transparent",
            "thumb": "#C9C3B0",
            "thumb_hover": "#B5AE99",
        },
    },
}

# ── Status colors mapping (manga status → token path) ──
STATUS_TOKEN = {
    "reading": "accent.primary",
    "plan": "status.info",
    "on-hold": "status.warn",
    "paused": "status.warn",
    "completed": "secondary_lilac.primary",
    "dropped": "status.danger",
}

# ── Typography (theme-independent) ──
TYPOGRAPHY = {
    "family_sans": "Geist, Inter, 'Segoe UI', sans-serif",
    "family_mono": "'Geist Mono', 'JetBrains Mono', Consolas, monospace",
    "size_h1": 26,
    "size_detail_title": 30,
    "size_section_label": 13,
    "size_card_title": 15,
    "size_body": 13,
    "size_body_strong": 13,
    "size_label": 13,
    "size_hint": 12,
    "size_meta": 12,
    "size_small": 11,
    "size_micro": 11,
    "size_kbd": 11,
    "size_badge": 10,
    "size_tag": 10,
    "size_brand": 17,
    "size_brand_version": 10,
}

# ── Radii ──
RADII = {"xs": 4, "sm": 6, "md": 8, "lg": 12, "xl": 16, "pill": 999}

# ── Spacing ──
SPACING = {
    "page_body_padding": (20, 32, 32, 32),
    "page_header_padding": (24, 32, 18, 32),
    "card_padding": (14, 16, 14, 16),
    "section_gap": 24,
    "input_v": 8,
    "input_h": 12,
}

# ── Shell sizes ──
SHELL = {
    "sidebar_width": 232,
    "title_bar_height": 36,
    "min_window": (1100, 720),
    "default_window": (1440, 900),
}


def flat(theme_dict: dict, prefix: str = "") -> dict:
    """Flatten nested dict into {dotted.key: value}.

    e.g. {"surfaces": {"bg_0": "#000"}} → {"surfaces.bg_0": "#000"}.
    Used by both qss_builder and any widget that needs a single lookup.
    """
    out = {}
    for k, v in theme_dict.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flat(v, key + "."))
        else:
            out[key] = v
    return out


def get(token_path: str, theme_name: str = None) -> str:
    """Look up a single dotted-key token in a given theme."""
    name = theme_name or DEFAULT_THEME
    f = flat(THEMES.get(name, THEMES[DEFAULT_THEME]))
    return f.get(token_path, "")
