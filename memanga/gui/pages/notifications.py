"""
Notifications page — full-screen history of app notifications.

Replaces the old modal NotificationPanel for browsing. The panel still
exists for ad-hoc popups; this page is the persistent log.

Data: pulls from app_state.get_notifications() (already wired). Each
notification has `type`, `message`, `timestamp`, `read`.

Filter chips and the per-row "more" action are UI-only stubs — the data
layer doesn't currently support per-category filtering, per-notification
deletion, or click-through to source actions.
"""

from datetime import datetime
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget,
    QFrame,
)
from PySide6.QtCore import Qt

from .base import BasePage
from .. import theme as T


# Map state notification "type" → notification_row icon variant in spec.
TYPE_TO_VARIANT = {
    "check":    "new",
    "download": "ok",
    "kindle":   "ok",
    "warn":     "warn",
    "error":    "err",
}


class NotificationsPage(BasePage):
    """List of notifications, grouped by Today / Yesterday / Earlier."""

    def __init__(self, parent, app):
        super().__init__(parent, app)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Page header ──
        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        row1 = QHBoxLayout()
        title = QLabel("Notifications")
        title.setProperty("role", "h1")
        row1.addWidget(title)
        row1.addStretch(1)

        # Header actions
        from ..assets.icons import icon as _ic
        mark_btn = QPushButton("  Mark all read")
        mark_btn.setProperty("variant", "ghost")
        mark_btn.setIcon(_ic("check", T.tokens()["text.t_2"], 14))
        mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mark_btn.clicked.connect(self._mark_all_read)
        row1.addWidget(mark_btn)

        clear_btn = QPushButton("  Clear all")
        clear_btn.setProperty("variant", "ghost")
        clear_btn.setIcon(_ic("trash", T.tokens()["text.t_2"], 14))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Wipe all notifications (asks for confirmation)")
        clear_btn.clicked.connect(self._clear_all)
        row1.addWidget(clear_btn)
        h_layout.addLayout(row1)

        self._meta = QLabel("")
        self._meta.setProperty("role", "meta")
        h_layout.addWidget(self._meta)

        # Header bottom divider
        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)

        root.addWidget(header)
        root.addWidget(sep)

        # ── Body: scrollable list of notification rows ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll, 1)

        self._scroll_content = QWidget()
        self._body = QVBoxLayout(self._scroll_content)
        self._body.setContentsMargins(32, 20, 32, 32)
        self._body.setSpacing(14)
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)

        # Filter chip row at top of body. Clicks route through
        # _set_filter → _filter_kind → State.filter_notifications which
        # returns just the rows for the selected category.
        self._filter_kind = "all"
        self._chip_buttons: dict[str, QPushButton] = {}
        chips_wrap = QFrame()
        chips_wrap.setProperty("role", "card_2")
        chips_l = QHBoxLayout(chips_wrap)
        chips_l.setContentsMargins(3, 3, 3, 3)
        chips_l.setSpacing(0)
        for key, label in [("all","All"),("new","New chapters"),
                            ("downloads","Downloads"),("system","System")]:
            chip = QPushButton(label)
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "true" if key == self._filter_kind else "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, k=key: self._set_filter(k))
            chips_l.addWidget(chip)
            self._chip_buttons[key] = chip
        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 10)
        chips_row.addWidget(chips_wrap)
        chips_row.addStretch(1)
        self._body.addLayout(chips_row)

        # Refresh when new ones arrive while visible.
        self.app.events.subscribe(
            "notification_added", lambda d: self.isVisible() and self._refresh()
        )

    def on_show(self, **kwargs):
        self._refresh()
        # Drop the unread badge once user views the page. State keeps the
        # raw entries; only their "read" flag flips.
        self.app.app_state.mark_notifications_read()
        # Bell badge in the sidebar updates via the event below.
        self.app.events.publish("notification_added", {})

    def _set_filter(self, kind: str):
        """Notification filter chip clicked. UI-only for now."""
        self._filter_kind = kind
        for k, btn in self._chip_buttons.items():
            btn.setProperty("active", "true" if k == kind else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
        self._refresh()

    def _refresh(self):
        # Preserve the chip row layout — only clear items below index 0.
        while self._body.count() > 1:
            item = self._body.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()

        # Filter by chip selection (None means all).
        if self._filter_kind == "all":
            notifs = self.app.app_state.get_notifications(limit=100)
        else:
            notifs = self.app.app_state.filter_notifications(self._filter_kind, limit=100)
        total = len(self.app.app_state.get_notifications(limit=100))
        unread = sum(1 for n in self.app.app_state.get_notifications(limit=100) if not n.get("read"))
        self._meta.setText(
            f"● {unread} unread  ·  {total} total  ·  Auto-check delivers updates here"
        )

        if not notifs:
            empty = QLabel("All caught up — new chapters and download events appear here.")
            empty.setStyleSheet(
                f"color: {T.tokens()['text.t_3']}; padding: 60px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body.addWidget(empty)
            return

        # Group by Today / Yesterday / Earlier.
        groups = self._group(notifs)
        for label, rows in groups:
            if not rows:
                continue
            self._body.addWidget(self._group_header(label, len(rows)))
            card = self._build_card(rows)
            self._body.addWidget(card)

    @staticmethod
    def _group(notifs):
        today, yesterday, earlier = [], [], []
        now = datetime.now()
        for n in notifs:
            ts = n.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                earlier.append(n)
                continue
            delta = (now.date() - dt.date()).days
            if delta == 0:
                today.append(n)
            elif delta == 1:
                yesterday.append(n)
            else:
                earlier.append(n)
        return [("Today", today), ("Yesterday", yesterday), ("Earlier", earlier)]

    def _group_header(self, label: str, count: int) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 4)

        lbl = QLabel(label.upper())
        lbl.setProperty("role", "section")
        l.addWidget(lbl)

        l.addStretch(1)

        count_lbl = QLabel(f"{count} item{'s' if count != 1 else ''}")
        count_lbl.setProperty("role", "mono_meta")
        l.addWidget(count_lbl)
        return w

    def _build_card(self, rows) -> QFrame:
        card = QFrame()
        card.setProperty("role", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for i, n in enumerate(rows):
            row = NotificationRow(n)
            if i > 0:
                row.setProperty("role", "row")
                row.style().unpolish(row)
                row.style().polish(row)
            layout.addWidget(row)
        return card

    def _mark_all_read(self):
        self.app.app_state.mark_notifications_read()
        # Also force-flush to disk so a quick app restart doesn't show
        # the badge again from stale on-disk state.
        try:
            self.app.app_state.flush()
        except Exception:
            pass
        # Refresh the sidebar bell badge synchronously — don't rely on
        # the EventBus poll loop, which can be 100 ms behind.
        try:
            self.app._sidebar._refresh_badges()
        except Exception:
            pass
        self.app.events.publish("notification_added", {})
        self._refresh()

    def _clear_all(self):
        """Wipe every notification + repaint the page. Backed by
        State.clear_notifications().
        """
        from ..components.toast import Toast
        from ..components.dialogs import ConfirmDialog

        def _do_clear():
            self.app.app_state.clear_notifications()
            self.app.events.publish("notification_added", {})  # refresh badges
            self._refresh()
            Toast(self, "All notifications cleared.", kind="info")

        ConfirmDialog(
            self,
            title="Clear all notifications?",
            message="This removes every notification from history. Continue?",
            on_confirm=_do_clear,
        )


class NotificationRow(QFrame):
    """Single notification row — icon + body + time."""

    def __init__(self, notif: dict):
        super().__init__()
        n_type = notif.get("type", "check")
        variant = TYPE_TO_VARIANT.get(n_type, "new")
        unread = not notif.get("read", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 16, 14)
        layout.setSpacing(12)

        # ── Icon ──
        icon = QLabel(self._glyph(variant))
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_bg, icon_fg = self._icon_colors(variant)
        icon.setStyleSheet(
            f"background-color: {icon_bg}; color: {icon_fg};"
            f"border-radius: 8px; font-weight: 600; font-size: 13pt;"
        )
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        # ── Body ──
        body = QVBoxLayout()
        body.setSpacing(2)
        title = QLabel(self._title_for(notif))
        title.setStyleSheet("font-weight: 600; font-size: 12pt;")
        body.addWidget(title)

        msg = QLabel(notif.get("message", ""))
        msg.setProperty("role", "t2")
        msg.setWordWrap(True)
        body.addWidget(msg)
        layout.addLayout(body, 1)

        # ── Time ──
        time_lbl = QLabel(self._fmt_time(notif.get("timestamp", "")))
        time_lbl.setProperty("role", "mono_meta")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.addWidget(time_lbl)

        # Visual cue for unread state — left rail.
        if unread:
            accent = T.tokens()["accent.primary"]
            self.setStyleSheet(
                f"NotificationRow {{ border-left: 2px solid {accent}; }}"
            )

    @staticmethod
    def _icon_colors(variant: str):
        toks = T.tokens()
        mapping = {
            "new":  (toks["accent.soft_10"], toks["accent.primary"]),
            "ok":   (toks["secondary_lilac.soft"], toks["secondary_lilac.primary"]),
            "warn": (toks["status.warn_soft"], toks["status.warn"]),
            "err":  (toks["status.danger_soft"], toks["status.danger"]),
        }
        return mapping.get(variant, mapping["new"])

    @staticmethod
    def _glyph(variant: str) -> str:
        return {"new": "↓", "ok": "✓", "warn": "!", "err": "✕"}.get(variant, "•")

    @staticmethod
    def _title_for(notif: dict) -> str:
        t = notif.get("type", "")
        return {
            "check":    "Library check",
            "download": "Download complete",
            "kindle":   "Sent to Kindle",
            "error":    "Error",
            "warn":     "Warning",
        }.get(t, t.title() if t else "Notification")

    @staticmethod
    def _fmt_time(ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            return ts
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if (now - dt).days < 7:
            return dt.strftime("%a %H:%M")
        return dt.strftime("%Y-%m-%d")
