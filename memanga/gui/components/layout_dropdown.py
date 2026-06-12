"""
Layout dropdown — per-manga reader page layout (issue #32).

Same QToolButton + two-line menu shape as ModeDropdown; only the
option set differs. The selected key is stored on the manga's config
entry as ``reader_mode`` and read by the reader when a chapter opens.
"""

from .mode_dropdown import ModeDropdown


LAYOUT_OPTIONS = [
    ("continuous", "Continuous", "All pages stacked in one vertical scroll."),
    ("single",     "Single page", "One page at a time; arrows turn pages."),
    ("double",     "Two-up",      "Two-page spreads; arrows turn spreads."),
]


class LayoutDropdown(ModeDropdown):
    """Continuous / Single page / Two-up picker for the detail page."""

    def __init__(self, parent=None, initial: str = "continuous"):
        super().__init__(parent, initial=initial, options=LAYOUT_OPTIONS)
