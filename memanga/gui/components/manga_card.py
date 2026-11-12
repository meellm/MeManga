"""
Manga cover card — grid item.

Matches memanga-pyside6-spec.json `components.manga_cover_card`:
- 2:3 aspect ratio cover, radius md, shadow md
- Hover translate-y -2px over 180ms
- Overlays:
    - linear-gradient(180deg, transparent 55%, rgba(0,0,0,0.85)) for text
    - if newCount > 0 → corner_badge top-right '+N NEW' (accent on accent.on_primary)
    - status_pill bottom-left (rgba(0,0,0,0.6) + blur with leading colored dot)
    - if 0 < progress < 100 → 3px progress bar at the very bottom, accent fill
- Below cover: title (clamp 2 lines) + sub (mono small)
- Placeholder paint: gradient + halftone dots + the manga's own title
  when there's no real cover image.
"""

import zlib

from PySide6.QtCore import (
    Qt, QRectF, QSize, QPoint, QPropertyAnimation, QEasingCurve, Property,
    QPointF,
)
from PySide6.QtGui import (
    QPixmap, QMouseEvent, QPainter, QColor, QLinearGradient, QBrush, QPen,
    QFont, QFontMetrics,
)
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget

from .. import theme as T
from ..theme.tokens import TYPOGRAPHY, status_label
from .keyboard import is_activation, is_context_menu, menu_anchor


CARD_W = 170
COVER_H = int(CARD_W * 1.5)  # 2:3 ratio → 255
# cover (255) + 4px spacing + title max 2 lines (~46) + 4px spacing
# + sub line (~18) + 4px bottom padding = 331. Use 332 so descenders
# on the second title line never spill onto the card below.
CARD_H = COVER_H + 77


# A small rotation of gradients for the placeholder paint, all dark
# enough for the white title drawn on them (4.5:1 or better on every
# stop). Mirrors memanga-pyside6-spec.json svg_assets.cover_paint_examples.
_PALETTES = [
    {"top": "#2A3441", "mid": "#4A3A56", "bot": "#6E4458"},
    {"top": "#8F3312", "mid": "#A03D18", "bot": "#B0481C"},
    {"top": "#9E2828", "mid": "#7A2020", "bot": "#5A1717"},
    {"top": "#8A5A1C", "mid": "#7A4E1A", "bot": "#6A4116"},
    {"top": "#1E3A5F", "mid": "#2C4A72", "bot": "#3A5A85"},
    {"top": "#5A2D5F", "mid": "#6A3672", "bot": "#7A3F84"},
]

# Longest title drawn on a placeholder; the full one is under the cover.
_PLACEHOLDER_TITLE_CHARS = 60


def _palette_for(title: str) -> dict:
    """Palette for a title, the same on every launch. (The built-in
    ``hash`` of a string changes from one run to the next.)"""
    return _PALETTES[zlib.crc32(title.encode("utf-8")) % len(_PALETTES)]


class _CoverArea(QWidget):
    """Custom-painted cover area: real image (if present) or paint-gradient
    placeholder. Renders all overlays on top via paintEvent so the cover
    composition stays pixel-exact regardless of theme.
    """

    def __init__(self, parent, *, cover_image: QPixmap, manga: dict, new_count: int,
                 read_count: int = 0, total_count: int = 0):
        super().__init__(parent)
        self.setFixedSize(CARD_W, COVER_H)
        self._cover = cover_image if cover_image and not cover_image.isNull() else None
        self._manga = manga
        self._new_count = new_count
        self._read_count = int(read_count or 0)
        self._total_count = int(total_count or 0)
        # The placeholder is painted once and kept: its halftone is over
        # a thousand dots, too many to redo on every hover repaint.
        self._placeholder_cache: QPixmap | None = None
        # Repaint when theme switches (status pill / NEW badge colors change).
        T.on_theme_change(self.update)

    def paintEvent(self, _ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            rect = QRectF(0, 0, self.width(), self.height())
            radius = 8

            # Path clipping so all overlays + image are clipped to the rounded card
            path = self._rounded_path(rect, radius)
            p.setClipPath(path)

            # 1. Cover image OR paint placeholder
            if self._cover is not None:
                # The cover cache hands out the pixmap already cropped to
                # this shape, at the screen's pixel density; drawing it
                # into the widget's rectangle keeps it sharp there.
                p.drawPixmap(self.rect(), self._cover)
            else:
                p.drawPixmap(self.rect(), self._placeholder_pixmap())

            # 2. Gradient overlay (bottom-half dim) for text legibility
            grad = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(0.55, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 217))  # 0.85 alpha
            p.fillRect(rect, QBrush(grad))

            # 3. Top-right corner "+N NEW" badge
            if self._new_count > 0:
                self._paint_new_badge(p)

            # 4. Bottom-left status pill (dot + status text)
            self._paint_status_pill(p)

            # 5. Progress bar (3px at very bottom) if progress > 0 < 100
            progress = self._get_progress()
            if 0 < progress < 100:
                self._paint_progress_bar(p, progress)

            # 6. Border on top so it isn't hidden by overlays. A card
            # with keyboard focus gets a 2px accent ring instead
            # (issue #396).
            p.setClipping(False)
            p.setBrush(Qt.BrushStyle.NoBrush)
            parent = self.parentWidget()
            if parent is not None and parent.hasFocus():
                p.setPen(QPen(QColor(T.tokens()["accent.primary"]), 2))
                p.drawPath(self._rounded_path(rect.adjusted(1, 1, -1, -1),
                                              radius - 1))
            else:
                p.setPen(QPen(QColor(T.tokens()["surfaces.border"]), 1))
                p.drawPath(path)
        finally:
            # Always end() — otherwise an exception leaves the QPainter
            # active and Qt floods the log with QBackingStore::endPaint
            # warnings (and may crash on the next paint pass).
            p.end()

    # ── helpers ──

    @staticmethod
    def _rounded_path(rect: QRectF, radius: float):
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _placeholder_pixmap(self) -> QPixmap:
        """The painted placeholder, rendered once per pixel density."""
        ratio = self.devicePixelRatioF() or 1.0
        cached = self._placeholder_cache
        if cached is not None and cached.devicePixelRatio() == ratio:
            return cached
        pm = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        pm.setDevicePixelRatio(ratio)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_placeholder(
                painter, QRectF(0, 0, self.width(), self.height()))
        finally:
            painter.end()
        self._placeholder_cache = pm
        return pm

    def _paint_placeholder(self, p: QPainter, rect: QRectF):
        title = (self._manga.get("title") or "?").strip() or "?"
        pal = _palette_for(title)

        # gradient bg
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, QColor(pal["top"]))
        g.setColorAt(0.5, QColor(pal["mid"]))
        g.setColorAt(1.0, QColor(pal["bot"]))
        p.fillRect(rect, g)

        # halftone dot pattern overlay (6px grid, 1px dots at 18% opacity)
        dot = QColor(255, 255, 255, 46)  # ~0.18 alpha
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        step = 6
        for y in range(2, int(rect.height()), step):
            for x in range(2, int(rect.width()), step):
                p.drawEllipse(QPointF(x, y), 0.7, 0.7)

        # The manga's own title, centered and wrapped, so a card without
        # a cover still says what it is.
        if len(title) > _PLACEHOLDER_TITLE_CHARS:
            title = title[:_PLACEHOLDER_TITLE_CHARS - 1].rstrip() + "…"
        font = QFont()
        font.setPointSizeF(15)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        text_rect = rect.adjusted(12, 12, -12, -COVER_H * 0.30)
        # Two different flag enums; drawText takes their combined value.
        flags = (Qt.AlignmentFlag.AlignCenter.value
                 | Qt.TextFlag.TextWordWrap.value)
        p.drawText(text_rect, flags, title)

    def _paint_new_badge(self, p: QPainter):
        """Subtle NEW-chapter badge top-right of the cover.

        Refined per HTML CSS: tiny accent-on-translucent pill instead of
        a chunky solid green oval. Accent fill is alpha 78% so it sits
        on the cover image without blocking the art behind it.
        """
        accent = QColor(T.tokens()["accent.primary"])
        on_accent = QColor(T.tokens()["accent.on_primary"])
        # Solid fill: a translucent one let a bright cover wash it out
        # until the label was hard to read (issue #395).
        accent_bg = QColor(accent)
        label = f"+{self._new_count} NEW"

        font = QFont()
        font.setFamilies(["Geist Mono", "JetBrains Mono", "Consolas", "monospace"])
        font.setPointSizeF(TYPOGRAPHY["size_min"])
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        p.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        pad_h, pad_v = 6, 1
        badge_w = text_w + pad_h * 2
        badge_h = fm.height() + pad_v * 2
        x = self.width() - badge_w - 6
        y = 6
        badge_rect = QRectF(x, y, badge_w, badge_h)
        p.setBrush(accent_bg)
        p.setPen(Qt.PenStyle.NoPen)
        # Tight rounded rect (not full pill) to read as a tag, not an oval.
        p.drawRoundedRect(badge_rect, 4, 4)
        p.setPen(on_accent)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_status_pill(self, p: QPainter):
        """Tiny uppercase pill — matches HTML/CSS `.manga-card .status-pill`:
            padding: 2px 8px;
            font-size: 10px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.06em;
            background: rgba(0,0,0,0.6);
            border-radius: 10px (true pill at this height);
        """
        status = (self._manga.get("status") or "reading").lower()
        from ..theme.tokens import STATUS_TOKEN
        dot_token = STATUS_TOKEN.get(status, "accent.primary")
        dot_color = QColor(T.tokens()[dot_token])

        # The shared status wording, uppercase: "ON HOLD", "PLAN TO READ".
        label = status_label(status).upper()

        # The smallest text size the app uses (issue #395); the design's
        # 7.5pt was too small to read.
        font = QFont()
        font.setPointSizeF(TYPOGRAPHY["size_min"])
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        p.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        dot_size = 5            # CSS: 5px
        dot_gap = 5             # CSS: margin-right: 5px
        pad_h = 8               # CSS: padding 2px 8px
        pad_v = 2
        # Use cap_height-style measurement: tighter than fm.height() so
        # the pill stays slim — that's what makes it read as a tiny chip
        # instead of a chunky badge.
        text_h = fm.ascent()
        pill_h = text_h + pad_v * 2 + 2   # +2 for breathing room
        pill_w = dot_size + dot_gap + text_w + pad_h * 2

        # Bottom-left, matching CSS bottom:10px left:10px.
        x = 10
        y = self.height() - pill_h - 10
        pill_rect = QRectF(x, y, pill_w, pill_h)

        # Translucent black with subtle white border (CSS:
        # background rgba(0,0,0,0.6) + border rgba(255,255,255,0.08))
        p.setBrush(QColor(0, 0, 0, 153))
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        # True pill — radius = half-height.
        p.drawRoundedRect(pill_rect, pill_h / 2, pill_h / 2)

        # Status dot — vertically centered.
        p.setBrush(dot_color)
        p.setPen(Qt.PenStyle.NoPen)
        dot_x = x + pad_h
        dot_y = y + (pill_h - dot_size) / 2
        p.drawEllipse(QRectF(dot_x, dot_y, dot_size, dot_size))

        # Label — bright white, vertically centered.
        p.setPen(QColor(255, 255, 255, 242))   # CSS rgba(255,255,255,0.95)
        text_rect = QRectF(dot_x + dot_size + dot_gap, y, text_w, pill_h)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, label)

    def _paint_progress_bar(self, p: QPainter, progress: float):
        accent = QColor(T.tokens()["accent.primary"])
        bar_h = 3
        full_w = self.width() * (progress / 100.0)
        rect = QRectF(0, self.height() - bar_h, full_w, bar_h)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(rect)

    def _get_progress(self) -> float:
        """Return READ-progress as % (issue #18). Falls back to the
        downloaded ratio when no read tracking exists yet. 0 means
        none/unknown; 100 means fully read (caller hides the bar at
        extremes).
        """
        try:
            if self._total_count > 0:
                return min(100, (self._read_count / self._total_count) * 100)
            total = int(self._manga.get("chapters_total") or 0)
            done = int(self._manga.get("chapters_downloaded") or 0)
            if total <= 0:
                return 0.0
            return min(100, (done / total) * 100)
        except Exception:
            return 0.0


class MangaCard(QFrame):
    """Clickable manga card with painted cover area + below-cover labels.

    Hover translates the whole card up by 2px (animated 180ms).
    """

    def __init__(self, parent, manga: dict, cover_image: QPixmap = None,
                 on_click=None, on_right_click=None, new_count: int = 0,
                 read_count: int = 0, total_count: int = 0):
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Tab reaches the card; a click still opens it without moving
        # focus, so the ring shows for keyboard use only (issue #396).
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click
        self._hover_offset = 0
        # Issue #18: per-chapter read counts (passed in by Library so the
        # card doesn't need to reach into State).
        self._read_count = int(read_count or 0)
        self._total_count = int(total_count or 0)
        self.setMouseTracking(True)
        # The cover and its badges are painted, so screen readers get the
        # title and what the overlays show from here (issue #394).
        self.setAccessibleName(manga.get("title", "Unknown"))
        self.setAccessibleDescription(self._accessible_text(
            manga, new_count, self._read_count, self._total_count))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Cover area ──
        # Pass read/total so the paint code can render the bottom
        # progress bar based on READ progress (more useful to the user
        # than downloaded progress for tracking what's left to read).
        self._cover_area = _CoverArea(
            self, cover_image=cover_image, manga=manga, new_count=new_count,
            read_count=self._read_count, total_count=self._total_count,
        )
        layout.addWidget(self._cover_area)

        # ── Below cover: title + sub ──
        title_text = manga.get("title", "Unknown")
        title_lbl = QLabel(title_text)
        # Titles come from source sites; show them literally.
        title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        title_lbl.setWordWrap(True)
        # Two-line clamp + headroom for descenders ('g', 'y', 'p', 'q')
        # on the SECOND line. 11pt × 1.45 line-height = ~21px per line;
        # 48px gives 2 lines + ~6px breathing room so the bottom of 'g'
        # / 'y' never spills onto the card below it.
        title_lbl.setMaximumHeight(48)
        title_lbl.setMinimumHeight(48)
        layout.addWidget(title_lbl)

        sub_text = self._sub_text(manga, new_count,
                                    read_count=self._read_count,
                                    total_count=self._total_count)
        sub_lbl = QLabel(sub_text)
        layout.addWidget(sub_lbl)

        # Label colours follow the theme. A method, not a lambda: the
        # subscription is then dropped with the card, which is rebuilt
        # on every Library refresh.
        self._title_lbl = title_lbl
        self._sub_lbl = sub_lbl
        self._apply_label_theme()
        T.on_theme_change(self._apply_label_theme)

        # Hover translate animation.
        self._anim = QPropertyAnimation(self, b"_offset", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── Hover animation ──
    #
    # The animation needs to lift the card 2 px up without fighting the
    # layout. Earlier impl snapshotted self.pos().y() ONCE on first
    # show and used self.move() during animation — that snapshot went
    # stale on fullscreen toggle or window resize, causing cards to
    # jump to phantom coordinates and (on Windows) sometimes crash the
    # paint pass mid-relayout.
    #
    # Fix: track the layout's current Y via moveEvent whenever we're
    # not mid-animation. enterEvent re-snapshots from the live pos.
    # Resize / fullscreen now correctly resets the baseline.

    def get_offset(self):
        return self._hover_offset

    def set_offset(self, val):
        self._hover_offset = val
        if hasattr(self, "_initial_y"):
            self.move(self.pos().x(), self._initial_y + val)

    _offset = Property(int, get_offset, set_offset)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not hasattr(self, "_initial_y"):
            self._initial_y = self.pos().y()

    def moveEvent(self, ev):
        """Re-anchor the hover-animation baseline when the layout
        repositions us (window resize, fullscreen toggle, grid reflow).
        We only update when there's no active animation, otherwise the
        animator's interpolated moves would feed back into themselves.
        """
        super().moveEvent(ev)
        if self._hover_offset == 0 and (
            not self._anim or self._anim.state() != QPropertyAnimation.State.Running
        ):
            self._initial_y = self.pos().y()

    def enterEvent(self, ev):
        # Always re-snapshot from the live pos so layout reflows
        # (fullscreen toggle, window resize) can't make the snapshot
        # stale between hovers.
        self._initial_y = self.pos().y() - self._hover_offset
        self._anim.stop()
        self._anim.setStartValue(self._hover_offset)
        self._anim.setEndValue(-2)
        self._anim.start()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if hasattr(self, "_initial_y"):
            self._anim.stop()
            self._anim.setStartValue(self._hover_offset)
            self._anim.setEndValue(0)
            self._anim.start()
        super().leaveEvent(ev)

    # ── Click handling ──

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._manga)
        elif event.button() == Qt.MouseButton.RightButton and self._on_right_click:
            pos = event.globalPosition().toPoint()
            self._on_right_click(self._manga, pos.x(), pos.y())

    # ── Keyboard (issue #396) ──

    def keyPressEvent(self, event):
        if is_activation(event) and self._on_click:
            self._on_click(self._manga)
        elif is_context_menu(event) and self._on_right_click:
            pos = menu_anchor(self)
            self._on_right_click(self._manga, pos.x(), pos.y())
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self._cover_area.update()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self._cover_area.update()

    # ── Helpers ──

    @staticmethod
    def _sub_text(manga: dict, new_count: int,
                  read_count: int = 0, total_count: int = 0) -> str:
        """Sub-line shown under the title.

        Prefers READ progress (issue #18). Falls back to downloaded
        progress when read tracking isn't populated yet.
        """
        if total_count > 0:
            base = f"Read {read_count}/{total_count}"
        else:
            ch_total = manga.get("chapters_total") or "?"
            ch_done = manga.get("chapters_downloaded") or 0
            base = f"Ch.{ch_done}/{ch_total}"
        if new_count > 0:
            return f"{base} · +{new_count}"
        return base

    @staticmethod
    def _accessible_text(manga: dict, new_count: int,
                         read_count: int = 0, total_count: int = 0) -> str:
        """Spoken summary of the painted status pill, progress and NEW
        badge, plus what activating the card does."""
        parts = [status_label(manga.get("status"))]
        if total_count > 0:
            parts.append(f"read {read_count} of {total_count} chapters")
        else:
            ch_total = manga.get("chapters_total") or "?"
            ch_done = manga.get("chapters_downloaded") or 0
            parts.append(f"{ch_done} of {ch_total} chapters downloaded")
        if new_count > 0:
            parts.append(f"{new_count} new")
        parts.append("opens details")
        return ", ".join(parts)

    def _apply_label_theme(self):
        self._title_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 11pt; font-weight: 600;"
            f"padding: 4px 2px 0 2px;"
        )
        self._sub_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 10pt;"
            f"font-family: 'Geist Mono', monospace; padding: 0 2px;"
        )

    # Back-compat for callers that update cover after construction.
    def update_cover(self, cover_image: QPixmap):
        self._cover_area._cover = (
            cover_image if cover_image and not cover_image.isNull() else None
        )
        self._cover_area.update()
