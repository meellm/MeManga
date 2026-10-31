"""
Reader view modes (issues #24, #32): continuous scroll, single page and
two-up spreads for ReaderPage. Resolves and persists the layout per
manga, turns pages in the paged layouts and lays out the page widgets
for the active layout.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout

from .. import theme as T


class ReaderViewModeMixin:
    """Layout choice, page turning and per-layout page placement.

    ReaderPage initialises the state used here (``_view_mode``,
    ``_current_page``, ``_mode_btns``, ``_images``, ``_scroll``,
    ``_image_layout``, ``_page_labels`` and the lazy-loading fields) and
    provides ``_rebuild_images``, ``_page_width_budget``, ``_page_label``
    and ``_update_page_window``."""

    # Issue #32: the three reader layouts the toolbar toggle cycles
    # between. "double" is the issue-#24 two-up view, now paged.
    VIEW_MODES = ("continuous", "single", "double")
    PAGED_MODES = ("single", "double")

    # ── Page-by-page navigation (issue #32) ───────────────────────────
    # Only active in the "single" and "double" layouts. Up/Down keep
    # their scroll meaning so a zoomed-in page can still be read top to
    # bottom; Left/Right/PageUp/PageDown/Space/Home/End move between
    # pages (or spreads in two-up).

    def _page_step(self, direction: int):
        """Advance one page (single) or one spread (double)."""
        step = 2 if self._view_mode == "double" else 1
        self._go_to_page(self._current_page + direction * step)

    def _go_to_page(self, index: int):
        if not self._images:
            return
        index = max(0, min(len(self._images) - 1, index))
        if self._view_mode == "double":
            index -= index % 2  # spreads stay aligned to fixed pairs
        if index == self._current_page:
            return
        self._current_page = index
        self._rebuild_images()
        # Each new page starts at its top-left corner, like turning a
        # physical page — leftover scroll from a zoomed previous page
        # would otherwise open the new one mid-panel.
        if self._scroll is not None:
            self._scroll.verticalScrollBar().setValue(0)
            self._scroll.horizontalScrollBar().setValue(0)

    # ── Reader layout (issues #24, #32) ───────────────────────────────
    # Three layouts: continuous scroll, single page, two-up spreads.
    # The choice persists per manga so a webtoon can stay continuous
    # while a print manga stays single-page.

    def _resolve_view_mode(self) -> str:
        """Layout for the current manga: its config entry's
        ``reader_mode``, else the global ``gui.reader_view_mode``, else
        the legacy ``gui.reader_dual_page`` boolean (issue #24)."""
        title = (self._manga or {}).get("title", "")
        for entry in self.app.config.get("manga", []) or []:
            if entry.get("title") == title:
                mode = entry.get("reader_mode")
                if mode in self.VIEW_MODES:
                    return mode
                break
        mode = self.app.config.get("gui.reader_view_mode")
        if mode in self.VIEW_MODES:
            return mode
        if self.app.config.get("gui.reader_dual_page", False):
            return "double"
        return "continuous"

    def _set_view_mode(self, mode: str):
        """Switch layout, persist it for this manga, and re-render."""
        if mode not in self.VIEW_MODES or mode == self._view_mode:
            return
        if self._view_mode == "continuous" and self._scroll is not None \
                and self._images:
            # Carry the reading position over: estimate the current page
            # from the scroll ratio, same as the progress bar does.
            sb = self._scroll.verticalScrollBar()
            ratio = sb.value() / max(1, sb.maximum())
            self._current_page = min(len(self._images) - 1,
                                     int(ratio * len(self._images)))
        self._view_mode = mode

        def _store(entry):
            entry["reader_mode"] = mode
        title = (self._manga or {}).get("title", "")
        if not (title and self.app.config.update_manga(title, _store)):
            # Manga not in config (e.g. removed mid-read): fall back to
            # the global default so the choice still sticks.
            self.app.config.set("gui.reader_view_mode", mode)
            self.app.config.save()

        self._refresh_mode_btns()
        self._rebuild_images()
        if self._scroll is not None:
            self._scroll.verticalScrollBar().setValue(0)
            self._scroll.horizontalScrollBar().setValue(0)

    def _refresh_mode_btns(self):
        """Accent-tint the active layout's toolbar button."""
        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        for mode, (btn, icon_name) in self._mode_btns.items():
            color = (T.tokens()["accent.primary"] if mode == self._view_mode
                     else T.tokens()["text.t_2"])
            btn.setIcon(_ic(icon_name, color, 16))
            btn.setIconSize(QSize(16, 16))

    def _render_images(self):
        max_w = self._page_width_budget()

        # Issue #389: labels start as fixed-size placeholders; decoded
        # pages arrive from the loader in _on_page_ready.
        self._page_slots.clear()
        self._shown_pages.clear()
        self._page_offsets = []
        self._page_target_w = max_w

        # Paged layouts center the (short) content in the viewport;
        # continuous keeps everything pinned to the top of the scroll.
        if self._image_layout is not None:
            if self._view_mode in self.PAGED_MODES:
                self._image_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self._image_layout.setAlignment(
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        if self._view_mode == "continuous":
            # ── Continuous (default): all pages stacked vertically ──
            # Every page gets its full-size placeholder so the scroll
            # range, resume position and read threshold behave as if
            # the whole chapter were loaded.
            spacing = max(0, self._image_layout.spacing())
            top = self._image_layout.contentsMargins().top()
            for index in range(len(self._images)):
                lbl = self._page_label(index, max_w)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._image_layout.addWidget(lbl)
                self._page_labels.append(lbl)
                self._page_offsets.append(top)
                top += lbl.height() + spacing
            self._update_page_window()
            return

        # ── Paged layouts (issue #32): only the current page/spread ──
        self._current_page = max(0, min(len(self._images) - 1,
                                        self._current_page))
        if self._view_mode == "double":
            self._current_page -= self._current_page % 2

        if self._view_mode == "single":
            lbl = self._page_label(self._current_page, max_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._image_layout.addWidget(lbl)
            self._page_labels.append(lbl)
            self._update_page_window()
            return

        # ── Two-up (issues #24, #32): one spread, two pages side-by-side
        # (or one if the chapter ends on an odd page). Allocate half
        # max_w per side so the spread as a whole stays inside the
        # viewport.
        per_side = max(120, (max_w - 8) // 2)
        self._page_target_w = per_side
        i = self._current_page
        spread = QHBoxLayout()
        spread.setSpacing(4)
        spread.setContentsMargins(0, 0, 0, 0)
        spread.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for j in (0, 1):
            if i + j >= len(self._images):
                break
            lbl = self._page_label(i + j, per_side)
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop | (
                Qt.AlignmentFlag.AlignRight if j == 0 else Qt.AlignmentFlag.AlignLeft
            ))
            spread.addWidget(lbl)
            self._page_labels.append(lbl)

        self._image_layout.addLayout(spread)
        self._update_page_window()
