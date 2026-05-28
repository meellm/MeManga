"""
Sidebar — left nav rail.

Layout (per memanga-pyside6-spec.json `global_shell.sidebar`):
    [Brand: 34px mark + "MeManga" + version line]
    [Section: WORKSPACE]
      Library / Downloads / Search / Notifications
    [Section: SYSTEM]
      Sources / Settings
    [Flex spacer]
    [Footer: sync card with auto-check status + progress + next-at]
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor

from .. import theme as T
from .brand_mark import BrandMark
from ..assets.icons import icon
from ... import __version__


# ── Nav structure ── (icon name → matches memanga/gui/assets/icons/__init__.py)
WORKSPACE_NAV = [
    ("library",       "Library",        "library"),
    ("downloads",     "Downloads",      "download"),
    ("search",        "Search",         "search"),
    ("notifications", "Notifications",  "bell"),
]

SYSTEM_NAV = [
    ("sources",  "Sources",  "sources"),
    ("settings", "Settings", "settings"),
]


class _NavButton(QPushButton):
    """Sidebar nav button with leading icon + optional count badge."""

    def __init__(self, label: str, icon_name: str = "", parent=None):
        super().__init__("  " + label, parent)
        self.setProperty("variant", "nav")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 42 — Windows still clipped the 'g' tail in "Settings" at 40
        # with the current font metric rounding. Two more px buys the
        # descender enough room without changing the visual rhythm of
        # the nav list.
        self.setFixedHeight(42)
        self._icon_name = icon_name
        self._refresh_icon()
        # Recolor icon on theme change.
        T.on_theme_change(self._refresh_icon)

        # Count badge label, right-aligned.
        self._badge = QLabel("", self)
        self._badge.setProperty("role", "badge_count")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()
        self._badge.setFixedHeight(18)

    def _refresh_icon(self):
        if not self._icon_name:
            return
        color_tok = "accent.primary" if self.property("active") == "true" else "text.t_2"
        self.setIcon(icon(self._icon_name, T.tokens()[color_tok], size=18))
        from PySide6.QtCore import QSize
        self.setIconSize(QSize(18, 18))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._badge.isVisible():
            self._badge.adjustSize()
            x = self.width() - self._badge.width() - 12
            y = (self.height() - self._badge.height()) // 2
            self._badge.move(x, y)

    def set_count(self, count: int):
        if count > 0:
            self._badge.setText(str(min(count, 99)))
            self._badge.show()
            self._badge.adjustSize()
            x = self.width() - self._badge.width() - 12
            y = (self.height() - self._badge.height()) // 2
            self._badge.move(x, y)
            # Pad the right side of the button text via QSS property
            # selector (defined in qss_builder) so the label can't slide
            # under the badge. Avoids replacing the whole stylesheet,
            # which would nuke the nav variant hover/active rules.
            self.setProperty("hasBadge", "true")
            # Use accent variant when the nav button is active.
            self._badge.setProperty(
                "role",
                "badge_count_active" if self.property("active") == "true"
                else "badge_count",
            )
        else:
            # Clear the text too — set_active() later re-reads it to
            # restore the badge when the active nav item changes, and a
            # stale "1" there would resurrect the badge after Mark
            # all read.
            self._badge.setText("")
            self._badge.hide()
            self.setProperty("hasBadge", "false")
            self._badge.setProperty("role", "badge_count")
        # Re-polish so the selector flip takes effect.
        for w in (self, self._badge):
            w.style().unpolish(w); w.style().polish(w)


class Sidebar(QWidget):
    """Application-wide left navigation."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        # Plain QWidget ignores QSS background-color unless we set this
        # attribute. We pair it with an instance stylesheet so the bg
        # wins over the QApplication palette (which would otherwise
        # leak Window=bg_0 through).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._restyle()
        T.on_theme_change(self._restyle)

        self._buttons: dict[str, _NavButton] = {}
        self._active = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Brand block ──
        brand = self._build_brand()
        root.addWidget(brand)

        # ── Workspace section ──
        root.addWidget(self._section_label("Workspace"))
        ws_wrap = QWidget()
        ws_l = QVBoxLayout(ws_wrap)
        ws_l.setContentsMargins(8, 0, 8, 0)
        ws_l.setSpacing(2)
        for name, label, icon_name in WORKSPACE_NAV:
            btn = self._make_nav(name, label, icon_name)
            ws_l.addWidget(btn)
        root.addWidget(ws_wrap)

        # ── System section ──
        root.addSpacing(6)
        root.addWidget(self._section_label("System"))
        sys_wrap = QWidget()
        sys_l = QVBoxLayout(sys_wrap)
        sys_l.setContentsMargins(8, 0, 8, 0)
        sys_l.setSpacing(2)
        for name, label, icon_name in SYSTEM_NAV:
            btn = self._make_nav(name, label, icon_name)
            sys_l.addWidget(btn)
        root.addWidget(sys_wrap)

        # ── Spacer ──
        root.addStretch(1)

        # ── Footer: sync card ──
        footer = self._build_footer()
        root.addWidget(footer)

        # Wire up all nav count badges (library / downloads / notifications / sources).
        self.app.events.subscribe("notification_added", lambda d: self._refresh_badges())
        self.app.events.subscribe("check_complete", lambda d: self._refresh_badges())
        self.app.events.subscribe("library_updated", lambda d: self._refresh_badges())
        self.app.events.subscribe("download_complete", lambda d: self._refresh_badges())
        # Initial paint.
        self._refresh_badges()

        # Re-evaluate sync card label every 30s so "2m ago" creeps up.
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_sync_card)
        self._tick.start(30_000)

    def _restyle(self):
        """Re-apply theme-aware inline stylesheet. Needed because the
        QApplication-level QSS rule `QWidget#sidebar { bg: bg_1 }`
        doesn't always win over the QApplication palette (Window=bg_0).
        Instance stylesheet has highest precedence."""
        toks = T.tokens()
        self.setStyleSheet(
            f"#sidebar {{"
            f"  background-color: {toks['surfaces.bg_1']};"
            f"  border-right: 1px solid {toks['surfaces.border']};"
            f"}}"
        )

    # ── builders ──

    def _build_brand(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        mark = BrandMark(w, size=34)
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        word = QLabel("MeManga")
        word.setStyleSheet(
            "font-size: 16pt; font-weight: 700; letter-spacing: -0.3px;"
        )
        text_col.addWidget(word)

        version = QLabel(f"v{__version__} · desktop")
        version.setProperty("role", "mono_meta")
        version.setStyleSheet("font-size: 9pt;")
        text_col.addWidget(version)

        layout.addLayout(text_col, 1)
        return w

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setProperty("role", "section")
        lbl.setContentsMargins(20, 14, 20, 6)
        return lbl

    def _make_nav(self, name: str, label: str, icon_name: str = "") -> _NavButton:
        btn = _NavButton(label, icon_name, self)
        btn.clicked.connect(lambda _, p=name: self.app.show_page(p))
        self._buttons[name] = btn
        return btn

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setObjectName("sidebar_footer")
        # Same instance-stylesheet trick as the sidebar parent.
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        def _restyle():
            toks = T.tokens()
            w.setStyleSheet(
                f"#sidebar_footer {{"
                f"  background-color: {toks['surfaces.bg_1']};"
                f"  border-top: 1px solid {toks['surfaces.border']};"
                f"}}"
            )
        _restyle()
        T.on_theme_change(_restyle)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("sync_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Row 1: dot + status text + age
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        self._sync_dot = _PulsingDot(card)
        row1.addWidget(self._sync_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._sync_status = QLabel("Auto-check ready")
        self._sync_status.setStyleSheet("font-size: 11pt; font-weight: 500;")
        row1.addWidget(self._sync_status, 1)

        self._sync_age = QLabel("—")
        self._sync_age.setProperty("role", "mono_meta")
        self._sync_age.setStyleSheet("font-size: 10pt;")
        row1.addWidget(self._sync_age, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(row1)

        # Row 2: progress bar (slim)
        self._sync_progress = QProgressBar()
        self._sync_progress.setRange(0, 100)
        self._sync_progress.setValue(0)
        self._sync_progress.setTextVisible(False)
        self._sync_progress.setFixedHeight(3)
        layout.addWidget(self._sync_progress)

        # Row 3: next + progress text
        row3 = QHBoxLayout()
        row3.setContentsMargins(0, 0, 0, 0)
        self._sync_next = QLabel("Next: idle")
        self._sync_next.setStyleSheet(
            f"font-size: 10pt; color: {T.tokens()['text.t_3']};"
        )
        row3.addWidget(self._sync_next, 1)

        self._sync_counter = QLabel("0/0")
        self._sync_counter.setProperty("role", "mono_meta")
        self._sync_counter.setStyleSheet("font-size: 10pt;")
        row3.addWidget(self._sync_counter, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(row3)

        outer.addWidget(card)

        # Wire to actual check events.
        self.app.events.subscribe("check_progress", self._on_check_progress)
        self.app.events.subscribe("check_complete", lambda d: self._on_check_done())

        return w

    # ── events ──

    def _on_check_progress(self, data):
        done = data.get("done", 0)
        total = data.get("total", 1)
        pct = int(100 * done / max(total, 1))
        self._sync_progress.setValue(pct)
        self._sync_status.setText("Checking…")
        self._sync_counter.setText(f"{done}/{total}")
        self._sync_dot.set_active(True)

    def _on_check_done(self):
        self._sync_progress.setValue(100)
        self._sync_status.setText("All caught up")
        self._sync_dot.set_active(False)
        QTimer.singleShot(2000, lambda: self._sync_progress.setValue(0))
        self._refresh_sync_card()

    def _refresh_sync_card(self):
        from datetime import datetime
        last = self.app.app_state.get("last_check")
        if not last:
            self._sync_age.setText("never")
            self._sync_next.setText("Next: idle")
            return
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            if elapsed < 60:
                self._sync_age.setText("now")
            elif elapsed < 3600:
                self._sync_age.setText(f"{int(elapsed // 60)}m")
            elif elapsed < 86400:
                self._sync_age.setText(f"{int(elapsed // 3600)}h")
            else:
                self._sync_age.setText(f"{int(elapsed // 86400)}d")
        except Exception:
            self._sync_age.setText("?")

        # Next at = last_check + interval (config setting in seconds)
        interval = int(self.app.config.get("gui.auto_check_interval", 3600))
        try:
            next_dt = datetime.fromisoformat(last)
            from datetime import timedelta
            next_dt = next_dt + timedelta(seconds=interval)
            self._sync_next.setText(f"Next at {next_dt.strftime('%H:%M')}")
        except Exception:
            self._sync_next.setText("Next: —")

    def _refresh_badges(self):
        """Populate the right-side count pill on each nav button from live state.

        Library      → total manga in library
        Downloads    → active+queued downloads (worker count)
        Sources      → enabled-source count
        Notifications→ unread notification count
        """
        # Library: count of manga entries
        try:
            lib_count = len(self.app.config.get("manga", []) or [])
        except Exception:
            lib_count = 0
        if (btn := self._buttons.get("library")):
            btn.set_count(lib_count)

        # Downloads: active tasks in the worker pool
        try:
            dl_count = len(getattr(self.app.worker, "active_tasks", {}) or {})
        except Exception:
            dl_count = 0
        if (btn := self._buttons.get("downloads")):
            btn.set_count(dl_count)

        # Sources: count of enabled scrapers
        try:
            from ...downloader import Downloader
            enabled = Downloader().get_supported_sources()
            disabled = set(self.app.config.get("sources.disabled", []) or [])
            src_count = len([s for s in enabled if s not in disabled])
        except Exception:
            src_count = 0
        if (btn := self._buttons.get("sources")):
            btn.set_count(src_count)

        # Notifications: unread
        try:
            notif_count = self.app.app_state.get_unread_count()
        except Exception:
            notif_count = 0
        if (btn := self._buttons.get("notifications")):
            btn.set_count(notif_count)

    def set_active(self, page_name: str):
        # When the user is on a detail/reader screen, keep the parent
        # "Library" entry visually highlighted so they know where they are.
        highlight = page_name
        if page_name in ("detail", ):
            highlight = "library"
        elif page_name == "reader":
            highlight = "library"

        for name, btn in self._buttons.items():
            on = (name == highlight)
            btn.setProperty("active", "true" if on else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            # Recolor leading icon to match active/idle text color.
            btn._refresh_icon()
        self._active = page_name
        # Re-derive every badge from live state — never from the badge's
        # own text, which can be stale right after Mark all read (set_count(0)
        # hides the widget without clearing the text).
        self._refresh_badges()


# ─────────────────────────────────────────────────────────────────────────
# Pulsing dot — small accent-colored circle that fades in/out while
# auto-check is running. Implemented via QPropertyAnimation on a custom
# `_opacity` property + paintEvent.
# ─────────────────────────────────────────────────────────────────────────

from PySide6.QtCore import Property, QObject  # noqa: E402
from PySide6.QtGui import QPainter as _QPainter  # noqa: E402


class _PulsingDot(QWidget):
    """7x7 accent dot. Animates opacity while ``active`` is True."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._opacity = 1.0
        self._anim = QPropertyAnimation(self, b"_pulse_opacity", self)
        self._anim.setDuration(2000)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.4)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._active = False
        T.on_theme_change(self.update)

    def set_active(self, on: bool):
        if on == self._active:
            return
        self._active = on
        if on:
            self._anim.start()
        else:
            self._anim.stop()
            self._opacity = 1.0
            self.update()

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, val):
        self._opacity = val
        self.update()

    _pulse_opacity = Property(float, get_opacity, set_opacity)

    def paintEvent(self, _ev):
        p = _QPainter(self)
        p.setRenderHint(_QPainter.RenderHint.Antialiasing)
        color = QColor(T.tokens()["accent.primary"])
        color.setAlphaF(self._opacity)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.drawEllipse(rect)
        p.end()
