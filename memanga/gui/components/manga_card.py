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
- Placeholder paint: gradient + halftone dots + JP serif title text
  when there's no real cover image.
"""

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


CARD_W = 170
COVER_H = int(CARD_W * 1.5)  # 2:3 ratio → 255
CARD_H = COVER_H + 50         # cover + title + sub


# A small rotation of gradient + JP text combos for the placeholder paint.
# Mirrors memanga-pyside6-spec.json svg_assets.cover_paint_examples.
_PALETTES = [
    {"top": "#2A3441", "mid": "#5A4666", "bot": "#A3677E", "jp": "恋愛\nマニュアル"},
    {"top": "#D44A1A", "mid": "#E55F30", "bot": "#F47438", "jp": ".A\nDOT ALICE"},
    {"top": "#BD3030", "mid": "#8A2424", "bot": "#5A1717", "jp": "殺戮\nロボト"},
    {"top": "#E8A23D", "mid": "#C77E2E", "bot": "#9E5C1D", "jp": "チェンソー"},
    {"top": "#1E3A5F", "mid": "#3A5F8A", "bot": "#5F8AB5", "jp": "君に\n言いたい\n事がある"},
    {"top": "#5A2D5F", "mid": "#7E3F88", "bot": "#A35BAE", "jp": "魔女"},
]


def _palette_for(title: str) -> dict:
    """Deterministic palette pick from a title hash."""
    return _PALETTES[abs(hash(title)) % len(_PALETTES)]


class _CoverArea(QWidget):
    """Custom-painted cover area: real image (if present) or paint-gradient
    placeholder. Renders all overlays on top via paintEvent so the cover
    composition stays pixel-exact regardless of theme.
    """

    def __init__(self, parent, *, cover_image: QPixmap, manga: dict, new_count: int):
        super().__init__(parent)
        self.setFixedSize(CARD_W, COVER_H)
        self._cover = cover_image if cover_image and not cover_image.isNull() else None
        self._manga = manga
        self._new_count = new_count
        # cached pixmap of placeholder paint per palette to avoid re-painting.
        self._placeholder_cache: QPixmap | None = None
        # Repaint when theme switches (status pill / NEW badge colors change).
        T.on_theme_change(self.update)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(0, 0, self.width(), self.height())
        radius = 8

        # Path clipping so all overlays + image are clipped to the rounded card
        path = self._rounded_path(rect, radius)
        p.setClipPath(path)

        # 1. Cover image OR paint placeholder
        if self._cover is not None:
            scaled = self._cover.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Centered crop
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            p.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
        else:
            self._paint_placeholder(p, rect)

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

        # 6. Border on top so it isn't hidden by overlays
        p.setClipping(False)
        p.setPen(QPen(QColor(T.tokens()["surfaces.border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()

    # ── helpers ──

    @staticmethod
    def _rounded_path(rect: QRectF, radius: float):
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _paint_placeholder(self, p: QPainter, rect: QRectF):
        title = self._manga.get("title", "?")
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

        # JP-style title text, centered
        jp_text = pal["jp"]
        font = QFont("Noto Serif JP", 22, QFont.Weight.Bold)
        font.setFamilies(["Noto Serif JP", "Hiragino Mincho ProN",
                          "Yu Mincho", "Songti SC", "serif"])
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 235))
        text_rect = rect.adjusted(8, 8, -8, -COVER_H * 0.35)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, jp_text)

    def _paint_new_badge(self, p: QPainter):
        accent = QColor(T.tokens()["accent.primary"])
        on_accent = QColor(T.tokens()["accent.on_primary"])
        label = f"+{self._new_count} NEW"

        font = QFont("Geist Mono", 9, QFont.Weight.Bold)
        font.setFamilies(["Geist Mono", "JetBrains Mono", "Consolas", "monospace"])
        p.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        pad_h, pad_v = 7, 3
        badge_w = text_w + pad_h * 2
        badge_h = fm.height() + pad_v
        x = self.width() - badge_w - 8
        y = 8
        badge_rect = QRectF(x, y, badge_w, badge_h)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(badge_rect, 999, 999)
        p.setPen(on_accent)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_status_pill(self, p: QPainter):
        status = (self._manga.get("status") or "reading").lower()
        from ..theme.tokens import STATUS_TOKEN
        dot_token = STATUS_TOKEN.get(status, "accent.primary")
        dot_color = QColor(T.tokens()[dot_token])

        label = status.replace("-", " ").title()
        font = QFont()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(label)
        dot_size = 6
        gap = 6
        pad_h, pad_v = 9, 3
        pill_w = dot_size + gap + text_w + pad_h * 2
        pill_h = fm.height() + pad_v

        # Pill bg (semi-transparent black)
        x = 8
        y = self.height() - pill_h - 12
        pill_rect = QRectF(x, y, pill_w, pill_h)
        p.setBrush(QColor(0, 0, 0, 153))  # 0.6 alpha
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill_rect, 999, 999)

        # Status dot
        p.setBrush(dot_color)
        dot_x = x + pad_h
        dot_y = y + (pill_h - dot_size) / 2
        p.drawEllipse(QRectF(dot_x, dot_y, dot_size, dot_size))

        # Label
        p.setPen(QColor("#FFFFFF"))
        text_rect = QRectF(dot_x + dot_size + gap, y, text_w, pill_h)
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
        """Return chapter-read progress as %. 0 means none/unknown,
        100 means fully read (caller hides the bar at extremes)."""
        try:
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
                 on_click=None, on_right_click=None, new_count: int = 0):
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manga = manga
        self._on_click = on_click
        self._on_right_click = on_right_click
        self._hover_offset = 0
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Cover area ──
        self._cover_area = _CoverArea(
            self, cover_image=cover_image, manga=manga, new_count=new_count,
        )
        layout.addWidget(self._cover_area)

        # ── Below cover: title + sub ──
        title_text = manga.get("title", "Unknown")
        title_lbl = QLabel(title_text)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 11pt; font-weight: 600;"
            f"padding: 4px 2px 0 2px;"
        )
        # Two-line clamp via fixed height + ellipsis
        title_lbl.setMaximumHeight(34)
        layout.addWidget(title_lbl)

        sub_text = self._sub_text(manga, new_count)
        sub_lbl = QLabel(sub_text)
        sub_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 9pt;"
            f"font-family: 'Geist Mono', monospace; padding: 0 2px;"
        )
        layout.addWidget(sub_lbl)

        # Refresh theme-aware label colors on theme switch.
        T.on_theme_change(lambda: self._on_theme(title_lbl, sub_lbl))

        # Hover translate animation.
        self._anim = QPropertyAnimation(self, b"_offset", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── Hover animation ──

    def get_offset(self):
        return self._hover_offset

    def set_offset(self, val):
        self._hover_offset = val
        self.move(self.pos().x(), self._initial_y + val if hasattr(self, "_initial_y") else self.pos().y())

    _offset = Property(int, get_offset, set_offset)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not hasattr(self, "_initial_y"):
            self._initial_y = self.pos().y()

    def enterEvent(self, ev):
        if hasattr(self, "_initial_y"):
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

    # ── Helpers ──

    @staticmethod
    def _sub_text(manga: dict, new_count: int) -> str:
        ch_total = manga.get("chapters_total") or "?"
        ch_done = manga.get("chapters_downloaded") or 0
        if new_count > 0:
            return f"Ch.{ch_done}/{ch_total} · +{new_count}"
        return f"Ch.{ch_done}/{ch_total}"

    @staticmethod
    def _on_theme(title_lbl: QLabel, sub_lbl: QLabel):
        title_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_1']}; font-size: 11pt; font-weight: 600;"
            f"padding: 4px 2px 0 2px;"
        )
        sub_lbl.setStyleSheet(
            f"color: {T.tokens()['text.t_3']}; font-size: 9pt;"
            f"font-family: 'Geist Mono', monospace; padding: 0 2px;"
        )

    # Back-compat for callers that update cover after construction.
    def update_cover(self, cover_image: QPixmap):
        self._cover_area._cover = (
            cover_image if cover_image and not cover_image.isNull() else None
        )
        self._cover_area.update()
