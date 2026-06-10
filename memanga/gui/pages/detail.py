"""
Detail page - Manga info, edit, chapters, download from chapter, and actions.
"""

from pathlib import Path
from urllib.parse import urlparse
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QComboBox, QCheckBox, QLineEdit,
)
from PySide6.QtCore import Qt, QSize
from .base import BasePage
from .. import theme as T
from ..components.toast import Toast
from ..components.dialogs import ConfirmDialog, InputDialog


class DetailPage(BasePage):
    """Manga detail view with info, edit, chapters, and actions."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._editing = False
        # Container for the merged chapter list — rebuilt independently of the
        # rest of the page when a single download completes.
        self._chapters_container = None
        # task_ids of in-flight per-chapter Download buttons → button widget,
        # so we can flip them to "Read" when their download completes.
        self._pending_downloads: dict = {}
        # Chapter filter state (HTML chip row: All/Downloaded/Not downloaded/Unread)
        self._chapter_filter = "all"
        self._chapter_chips: dict = {}
        self._chapter_sort = "Newest first"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        self._scroll_content = QWidget()
        self._layout = QVBoxLayout(self._scroll_content)
        self._layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_XL)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._scroll_content)

        # Refresh the chapter list when a single download completes for the
        # currently displayed manga (manual-mode per-chapter Download flow).
        self.app.events.subscribe("download_complete", self._on_any_download_complete)
        # Also refresh after a check completes — newly discovered chapters
        # surface as Download rows immediately, no navigation needed.
        self.app.events.subscribe("check_complete", self._on_any_check_complete)

    def on_show(self, **kwargs):
        manga = kwargs.get("manga")
        if manga:
            self._manga = manga
        self._editing = False
        if self._manga:
            self._rebuild()

    def _get_source_display(self, manga):
        """Extract primary and backup source domains from manga config."""
        sources = manga.get("sources", [])
        if sources:
            primary = sources[0].get("source", sources[0].get("url", ""))
            backup = sources[1].get("source", "") if len(sources) > 1 else ""
            primary_url = sources[0].get("url", "")
            backup_url = sources[1].get("url", "") if len(sources) > 1 else ""
        else:
            primary = manga.get("source", "")
            primary_url = manga.get("url", "")
            backup = ""
            backup_url = ""
        return primary, primary_url, backup, backup_url

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())

    def _clear_child_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())

    def _rebuild(self):
        self._clear_layout()

        manga = self._manga
        title = manga.get("title", "Unknown")
        state_data = self.app.app_state.get_manga_state(title)
        primary, primary_url, backup, backup_url = self._get_source_display(manga)

        # ── Back button (matches HTML "< Library" ghost) ──
        back_row = QHBoxLayout()
        back_btn = QPushButton("‹  Library")
        back_btn.setProperty("variant", "ghost")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.app.show_page("library"))
        back_row.addWidget(back_btn)
        back_row.addStretch(1)
        self._layout.addLayout(back_row)
        self._layout.addSpacing(T.PAD_MD)

        # ── Main row: cover left + info right (matches HTML spec.screens.manga_detail.hero)
        main_row = QHBoxLayout()
        main_row.setSpacing(28)

        # Cover — 220x330 per spec
        cover_url = manga.get("cover_url")
        cover_pixmap = self.app.cover_cache.get_cover(cover_url, size=(220, 330))
        cover_label = QLabel()
        cover_label.setFixedSize(220, 330)
        cover_label.setPixmap(cover_pixmap.scaled(
            220, 330,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_label.setStyleSheet(
            f"border-radius: 8px; border: 1px solid {T.tokens()['surfaces.border']};"
            f"background-color: {T.tokens()['surfaces.bg_2']};"
        )
        main_row.addWidget(cover_label, alignment=Qt.AlignmentFlag.AlignTop)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # "By Author" line above title — matches HTML
        author = manga.get("author", "")
        if author:
            by_label = QLabel(f"By  <span style='color:{T.tokens()['text.t_1']};font-weight:500'>{author}</span>")
            by_label.setProperty("role", "t2")
            by_label.setStyleSheet(f"color: {T.tokens()['text.t_2']}; font-size: 12pt;")
            info_layout.addWidget(by_label)

        # Title — use the new detail_title typography role.
        title_label = QLabel(title)
        title_label.setProperty("role", "detail_title")
        title_label.setWordWrap(True)
        info_layout.addWidget(title_label)
        info_layout.addSpacing(6)

        # Source pill row (green dot + name) + URL link in mono
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_row.setContentsMargins(0, 0, 0, 0)
        if primary:
            pill = QLabel(f"●  {primary}")
            accent = T.tokens()["accent.primary"]
            soft = T.tokens()["accent.soft_10"]
            pill.setStyleSheet(
                f"background-color: {soft}; color: {accent};"
                f"padding: 4px 10px; border-radius: 999px;"
                f"font-size: 11pt; font-weight: 500;"
            )
            src_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)

        if primary_url:
            url_lbl = QLabel(primary_url)
            url_lbl.setProperty("role", "mono_meta")
            url_lbl.setStyleSheet(
                f"font-family: 'Geist Mono', monospace; color: {T.tokens()['text.t_3']};"
                f"font-size: 10pt;"
            )
            src_row.addWidget(url_lbl, 1, Qt.AlignmentFlag.AlignVCenter)

        src_row.addStretch(1)
        info_layout.addLayout(src_row)

        if backup:
            backup_row = QHBoxLayout()
            backup_row.setSpacing(8)
            bpill = QLabel(f"●  {backup}")
            warn = T.tokens()["status.warn"]
            wsoft = T.tokens()["status.warn_soft"]
            bpill.setStyleSheet(
                f"background-color: {wsoft}; color: {warn};"
                f"padding: 3px 9px; border-radius: 999px; font-size: 10pt;"
            )
            backup_row.addWidget(bpill, 0, Qt.AlignmentFlag.AlignVCenter)
            backup_row.addWidget(QLabel("backup"), 0, Qt.AlignmentFlag.AlignVCenter)
            delay = manga.get("fallback_delay_days", 2)
            delay_lbl = QLabel(f"· {delay}-day fallback")
            delay_lbl.setProperty("role", "hint")
            backup_row.addWidget(delay_lbl)
            backup_row.addStretch(1)
            info_layout.addLayout(backup_row)

        info_layout.addSpacing(12)

        # ── Controls card (matches HTML spec.screens.manga_detail.controls_card)
        # Two left-aligned columns inside a bg_1 card. Each column has a
        # tiny uppercase label sitting directly above its dropdown — the
        # dropdown sizes to a natural width instead of stretching to the
        # full column, which had been making the layout look "ugly" with
        # huge empty space around "Reading" / "Manual".
        controls_card = QFrame()
        controls_card.setProperty("role", "card")
        cc_l = QHBoxLayout(controls_card)
        cc_l.setContentsMargins(16, 12, 16, 12)
        cc_l.setSpacing(28)

        from ..components.status_dropdown import StatusDropdown
        from ..components.mode_dropdown import ModeDropdown

        def _control_column(label_text: str, widget: QWidget) -> QVBoxLayout:
            col = QVBoxLayout()
            col.setSpacing(6)
            col.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setProperty("role", "section")
            col.addWidget(lbl, 0, Qt.AlignmentFlag.AlignLeft)
            # Cap dropdown width so it doesn't float in a sea of whitespace.
            widget.setMaximumWidth(200)
            widget.setMinimumWidth(160)
            col.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
            return col

        self._status_combo = StatusDropdown(initial=manga.get("status", "reading"))
        self._status_combo.value_changed.connect(self._on_status_change)
        cc_l.addLayout(_control_column("STATUS", self._status_combo))

        current_mode = manga.get("mode", "auto")
        self._mode_combo = ModeDropdown(initial=current_mode)
        self._mode_combo.value_changed.connect(self._on_mode_change)
        cc_l.addLayout(_control_column("MODE", self._mode_combo))

        cc_l.addStretch(1)  # push columns left, no centering void

        info_layout.addWidget(controls_card)

        # Mode hint label (below controls card)
        mode_hint = QLabel(
            "Manual: download chapters individually below"
            if current_mode == "manual"
            else "Auto: new chapters download after each check"
        )
        mode_hint.setProperty("role", "hint")
        self._mode_hint = mode_hint
        info_layout.addWidget(mode_hint)

        # Kindle toggle (below controls card)
        global_email_on = (self.app.config.delivery_mode == "email" and self.app.config.email_enabled)
        manga_kindle = manga.get("send_to_kindle", True)
        kindle_row = QHBoxLayout()
        self._kindle_check = QCheckBox("Send to Kindle after download")
        self._kindle_check.setChecked(bool(manga_kindle and global_email_on))
        self._kindle_check.stateChanged.connect(self._on_kindle_toggle)
        kindle_row.addWidget(self._kindle_check)
        if not global_email_on:
            self._kindle_check.setEnabled(False)
            hint = QLabel("— enable email in Settings first")
            hint.setProperty("role", "hint")
            kindle_row.addWidget(hint)
        kindle_row.addStretch(1)
        info_layout.addLayout(kindle_row)

        info_layout.addSpacing(12)

        # Stats
        downloaded = state_data.get("downloaded", [])
        last_ch = state_data.get("last_chapter") or "-"
        last_updated = state_data.get("last_updated") or "Never"
        if last_updated != "Never" and "T" in last_updated:
            last_updated = last_updated.split("T")[0]

        stats_text = f"Downloaded: {len(downloaded)} chapters  |  Last: Ch. {last_ch}  |  Updated: {last_updated}"
        stats_label = QLabel(stats_text)
        stats_label.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_SECONDARY};")
        info_layout.addWidget(stats_label)

        info_layout.addSpacing(T.PAD_MD)

        # Action row: primary "Check updates" + default "Download from…" +
        # default "Download all" + spacer + ghost "Edit" + danger "Remove"
        from ..assets.icons import icon as _ic
        actions = QHBoxLayout()
        actions.setSpacing(T.PAD_SM)

        check_btn = QPushButton("  Check updates")
        check_btn.setProperty("variant", "primary")
        check_btn.setIcon(_ic("refresh", T.tokens()["accent.on_primary"], 14))
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self._check_updates)
        actions.addWidget(check_btn)

        dl_from_btn = QPushButton("  Download from…")
        dl_from_btn.setIcon(_ic("download", T.tokens()["text.t_2"], 14))
        dl_from_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dl_from_btn.clicked.connect(self._download_from_chapter)
        actions.addWidget(dl_from_btn)

        dl_all_btn = QPushButton("  Download all")
        dl_all_btn.setIcon(_ic("download", T.tokens()["text.t_2"], 14))
        dl_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dl_all_btn.clicked.connect(self._download_all)
        actions.addWidget(dl_all_btn)

        actions.addStretch(1)

        edit_btn = QPushButton("Edit")
        edit_btn.setProperty("variant", "ghost")
        edit_btn.setProperty("size", "sm")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(self._show_edit_form)
        actions.addWidget(edit_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("variant", "danger")
        remove_btn.setProperty("size", "sm")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._confirm_remove)
        actions.addWidget(remove_btn)

        info_layout.addLayout(actions)

        main_row.addLayout(info_layout, 1)

        main_wrapper = QWidget()
        main_wrapper.setLayout(main_row)
        self._layout.addWidget(main_wrapper)

        # ── Edit form (hidden by default) ──
        self._edit_frame = QFrame()
        self._edit_frame.setProperty("class", "card")
        edit_inner = QVBoxLayout(self._edit_frame)
        edit_inner.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD_LG)
        edit_inner.setSpacing(T.PAD_SM)

        edit_title_lbl = QLabel("Edit Manga")
        edit_title_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        edit_inner.addWidget(edit_title_lbl)

        edit_inner.addWidget(QLabel("Title:"))
        self._edit_title = QLineEdit(title)
        self._edit_title.setMinimumHeight(38)
        edit_inner.addWidget(self._edit_title)

        edit_inner.addWidget(QLabel("Primary URL:"))
        self._edit_url = QLineEdit(primary_url)
        self._edit_url.setMinimumHeight(38)
        edit_inner.addWidget(self._edit_url)

        edit_inner.addWidget(QLabel("Backup URL (leave empty to remove):"))
        self._edit_backup = QLineEdit(backup_url)
        self._edit_backup.setMinimumHeight(38)
        edit_inner.addWidget(self._edit_backup)

        # Fallback delay — only meaningful with a backup source, but always
        # rendered so users can fill it in alongside adding a backup. Saved
        # only when a backup URL is present (matches Add Manga behavior).
        delay_row = QHBoxLayout()
        delay_lbl = QLabel("Fallback delay (days):")
        delay_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        delay_row.addWidget(delay_lbl)
        self._edit_delay = QLineEdit(str(manga.get("fallback_delay_days", 2)))
        self._edit_delay.setFixedWidth(60)
        self._edit_delay.setMinimumHeight(36)
        delay_row.addWidget(self._edit_delay)
        delay_row.addStretch()
        edit_inner.addLayout(delay_row)

        edit_btns = QHBoxLayout()
        save_edit_btn = QPushButton("Save Changes")
        save_edit_btn.setProperty("class", "accent")
        save_edit_btn.setFixedHeight(34)
        save_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_edit_btn.clicked.connect(self._save_edit)
        edit_btns.addWidget(save_edit_btn)

        cancel_edit_btn = QPushButton("Cancel")
        cancel_edit_btn.setFixedHeight(34)
        cancel_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_edit_btn.clicked.connect(self._hide_edit_form)
        edit_btns.addWidget(cancel_edit_btn)

        edit_btns.addStretch()
        edit_inner.addLayout(edit_btns)

        self._edit_frame.setVisible(False)
        self._layout.addWidget(self._edit_frame)

        # ── Chapter list section ──
        # Wrapped in a refreshable container so individual per-chapter
        # downloads (manual mode) can flip a row from Download → Read
        # without rebuilding the whole detail page.
        self._layout.addSpacing(T.PAD_MD)
        self._chapters_container = QWidget()
        chapters_layout = QVBoxLayout(self._chapters_container)
        chapters_layout.setContentsMargins(0, 0, 0, 0)
        chapters_layout.setSpacing(0)
        self._layout.addWidget(self._chapters_container)
        self._build_chapter_list()

        self._layout.addStretch()

    def _build_chapter_list(self):
        """Render the merged chapter list (downloaded + available).

        - Each row: "Chapter N" + Read button (if downloaded) OR Download button.
        - Sorted descending by numeric chapter number.
        - Falls back to a downloaded-only render when no available_chapters
          are cached yet (e.g. legacy auto manga that haven't been re-checked).
        """
        if not self._chapters_container or not self._manga:
            return

        # Reset the container layout
        layout = self._chapters_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_child_layout(item.layout())
        # Forget any stale download-button references
        self._pending_downloads.clear()

        title = self._manga.get("title", "")
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        available = self.app.app_state.get_available_chapters(title)
        external = self.app.app_state.get_external_chapters(title)

        # Build the merged set, keyed by chapter number string.
        # Available entries provide source/url metadata; downloaded entries
        # without metadata are still rendered (just no Download button is
        # needed because they're already on disk).
        merged: dict = {}
        for entry in available:
            num = str(entry.get("number", ""))
            if num:
                merged[num] = entry
        for ch_num in downloaded:
            num = str(ch_num)
            if num and num not in merged:
                merged[num] = {"number": num}
        # External-only entries (marked as "read elsewhere" before the
        # chapter list has been fetched) — render them too so the recorded
        # state is visible. They get proper source metadata once a check
        # populates available_chapters.
        for ch_num in external:
            num = str(ch_num)
            if num and num not in merged:
                merged[num] = {"number": num}

        if not merged:
            empty = QLabel(
                "No chapters yet. Use 'Check Updates' to see what's available."
            )
            empty.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt; color: {T.FG_MUTED};")
            layout.addWidget(empty)
            return

        # Section header: "Chapters" h3 + "{dl} downloaded · {total} total · {new} new"
        n_dl = len(downloaded)
        n_total = len(merged)
        n_new = self.app.app_state.get_new_chapters(title) or 0
        head_row = QHBoxLayout()
        h_lbl = QLabel("Chapters")
        h_lbl.setProperty("role", "card_title")
        head_row.addWidget(h_lbl)
        head_row.addStretch(1)
        sub = QLabel(
            f"{n_dl} downloaded  ·  {n_total} total  ·  {n_new} new"
        )
        sub.setProperty("role", "mono_meta")
        head_row.addWidget(sub)
        layout.addLayout(head_row)
        layout.addSpacing(8)

        # Filter chip row + sort dropdown (matches HTML)
        filter_row = QHBoxLayout()
        chips_wrap = QFrame()
        chips_wrap.setProperty("role", "card_2")
        chip_l = QHBoxLayout(chips_wrap)
        chip_l.setContentsMargins(3, 3, 3, 3)
        chip_l.setSpacing(0)
        # Real per-chapter read tracking (issue #18). "Unread" now means
        # actually-not-opened-in-Reader, not the "new since last check" badge.
        read_set = set(self.app.app_state.get_read_chapters(title))
        n_read = sum(1 for num in merged.keys() if num in read_set)
        n_unread = n_total - n_read
        # Preserve the user's chip choice across rebuilds — _build_chapter_list
        # runs on every chip click via _set_chapter_filter, so resetting to
        # "all" here would clobber the click before the new chips paint.
        # Same fix-shape as the Newest/Oldest sort combo two sessions ago.
        valid_filters = {"all", "downloaded", "not_downloaded", "unread"}
        current_filter = getattr(self, "_chapter_filter", "all")
        if current_filter not in valid_filters:
            current_filter = "all"
        self._chapter_filter = current_filter
        self._chapter_chips: dict = {}
        for key, label, count in [
            ("all", "All", n_total),
            ("downloaded", "Downloaded", n_dl),
            ("not_downloaded", "Not downloaded", n_total - n_dl),
            ("unread", "Unread", n_unread),
        ]:
            chip = QPushButton(f"{label}  {count}")
            chip.setProperty("variant", "chip")
            chip.setProperty("active", "true" if key == self._chapter_filter else "false")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, k=key: self._set_chapter_filter(k))
            chip_l.addWidget(chip)
            self._chapter_chips[key] = chip
        filter_row.addWidget(chips_wrap)
        filter_row.addStretch(1)
        sort_combo = QComboBox()
        sort_combo.addItems(["Newest first", "Oldest first"])
        # Was 150 — the QSS adds 28px right padding for the caret, so
        # "Newest first" wrapped/clipped the trailing 't'. 180 fits.
        sort_combo.setMinimumWidth(180)
        # Preserve the current sort across rebuilds — _build_chapter_list
        # runs whenever the chapter list refreshes (status flip, download
        # complete, sort change). If we hard-reset to "Newest first"
        # here, clicking "Oldest first" would flip back immediately.
        current_sort = getattr(self, "_chapter_sort", "Newest first")
        if current_sort not in ("Newest first", "Oldest first"):
            current_sort = "Newest first"
        sort_combo.setCurrentText(current_sort)
        self._chapter_sort = current_sort
        sort_combo.currentTextChanged.connect(self._on_chapter_sort_change)
        filter_row.addWidget(sort_combo)
        layout.addLayout(filter_row)
        layout.addSpacing(6)

        def _sort_key(num: str) -> float:
            try:
                return float(num)
            except (ValueError, TypeError):
                return 0.0

        sort_desc = (getattr(self, "_chapter_sort", "Newest first") == "Newest first")
        sorted_nums = sorted(merged.keys(), key=_sort_key, reverse=sort_desc)

        # Single card holds all rows separated by 1px borders.
        list_card = QFrame()
        list_card.setProperty("role", "card")
        list_l = QVBoxLayout(list_card)
        list_l.setContentsMargins(0, 0, 0, 0)
        list_l.setSpacing(0)

        from ..assets.icons import icon as _ic
        for i, num in enumerate(sorted_nums):
            entry = merged[num]
            is_dl = self.app.app_state.is_chapter_downloaded(title, num)
            is_external = (not is_dl and self.app.app_state.is_external_chapter(title, num))

            # Filter
            f = self._chapter_filter
            if f == "downloaded" and not is_dl:
                continue
            if f == "not_downloaded" and is_dl:
                continue
            # Issue #18: Unread = actually not opened in Reader (read_set
            # is the canonical source). is_external means "marked read
            # elsewhere" so those are also excluded from Unread.
            if f == "unread" and (num in read_set or is_external):
                continue

            ch_frame = QFrame()
            if i > 0:
                ch_frame.setStyleSheet(
                    f"border-top: 1px solid {T.tokens()['surfaces.border']};"
                )
            ch_row = QHBoxLayout(ch_frame)
            ch_row.setContentsMargins(16, 10, 16, 10)
            ch_row.setSpacing(12)

            # Status icon column (28x28). Four distinct visual states so
            # the user can scan chapter status at a glance:
            #   * Read       → filled accent bg + on_accent check
            #   * Downloaded → accent.soft bg + accent check-circle
            #   * External   → warn.soft bg + warn external-link
            #   * Not yet    → bg_2 + t_3 download-tray arrow
            # Computed up-front so we can also drive the title style + label.
            is_read = self.app.app_state.is_chapter_read(title, num)
            status_box = QLabel()
            status_box.setFixedSize(28, 28)
            status_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            toks = T.tokens()
            if is_read:
                # Filled bright accent — strongest visual weight.
                status_box.setPixmap(
                    _ic("check", toks["accent.on_primary"], 14).pixmap(QSize(14, 14)))
                status_box.setStyleSheet(
                    f"background-color: {toks['accent.primary']};"
                    f"border-radius: 6px;"
                )
            elif is_dl:
                # Subtle accent — file on disk, not opened yet.
                status_box.setPixmap(
                    _ic("check_circle", toks["accent.primary"], 16).pixmap(QSize(16, 16)))
                status_box.setStyleSheet(
                    f"background-color: {toks['accent.soft_10']};"
                    f"border-radius: 6px;"
                )
            elif is_external:
                status_box.setPixmap(
                    _ic("external", toks["status.warn"], 14).pixmap(QSize(14, 14)))
                status_box.setStyleSheet(
                    f"background-color: {toks['status.warn_soft']};"
                    f"border-radius: 6px;"
                )
            else:
                status_box.setPixmap(
                    _ic("download_tray", toks["text.t_3"], 14).pixmap(QSize(14, 14)))
                status_box.setStyleSheet(
                    f"background-color: {toks['surfaces.bg_2']};"
                    f"border-radius: 6px;"
                )
            ch_row.addWidget(status_box, 0, Qt.AlignmentFlag.AlignVCenter)

            # Vol / Ch column (mono, two-line)
            vol_lbl = QLabel(f"Ch.{num}")
            vol_lbl.setStyleSheet(
                f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                f"color: {T.tokens()['text.t_3']};"
            )
            vol_lbl.setFixedWidth(60)
            ch_row.addWidget(vol_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

            # Title block — issue #18: distinguish "actually read in the
            # Reader" from "just downloaded". Dim read chapters' title so
            # they visually fade like read mail. (`is_read` was computed
            # above next to the status-box selection.)
            ch_title_text = (entry.get("title") or "").strip()
            title_l = QVBoxLayout()
            title_l.setSpacing(2)
            main_title = QLabel(ch_title_text or f"Chapter {num}")
            title_color = T.tokens()["text.t_3"] if is_read else T.tokens()["text.t_1"]
            title_weight = 400 if is_read else 500
            main_title.setStyleSheet(
                f"font-size: 12pt; font-weight: {title_weight}; color: {title_color};"
            )
            title_l.addWidget(main_title)
            if is_read:
                sub_state = "Read"
            elif is_dl:
                sub_state = "Downloaded"
            elif is_external:
                sub_state = "Read elsewhere"
            else:
                sub_state = "Not downloaded"
            sub_lbl = QLabel(sub_state)
            sub_lbl.setProperty("role", "hint")
            title_l.addWidget(sub_lbl)
            ch_row.addLayout(title_l, 1)

            # Date column (mono, t_3)
            date_str = entry.get("date") or ""
            if date_str:
                date_lbl = QLabel(str(date_str).split("T")[0])
                date_lbl.setStyleSheet(
                    f"font-family: 'Geist Mono', monospace; font-size: 10pt;"
                    f"color: {T.tokens()['text.t_3']};"
                )
                date_lbl.setFixedWidth(96)
                ch_row.addWidget(date_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

            # Action column
            if is_dl:
                btn = QPushButton("Read")
                btn.setProperty("variant", "primary")
                btn.setProperty("size", "sm")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _, c=num: self._read_chapter(c))
                ch_row.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                btn = QPushButton("Download")
                btn.setProperty("size", "sm")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda _, e=entry, b=btn: self._download_chapter(e, b)
                )
                ch_row.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

            list_l.addWidget(ch_frame)

        layout.addWidget(list_card)

    def _set_chapter_filter(self, key: str):
        self._chapter_filter = key
        for k, btn in (self._chapter_chips or {}).items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
        self._build_chapter_list()

    def _on_chapter_sort_change(self, val: str):
        self._chapter_sort = val
        self._build_chapter_list()

    def _refresh_chapter_list(self):
        """Public helper to rebuild the chapter list (used after mode change /
        download completion)."""
        self._build_chapter_list()

    # ── Status ──

    def _on_kindle_toggle(self, state):
        if not self._manga:
            return
        val = self._kindle_check.isChecked()
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["send_to_kindle"] = val
                self._manga = m
                break
        self.app.config.save()
        kind = "info" if val else "warning"
        msg = "Kindle delivery enabled" if val else "Kindle delivery disabled"
        Toast(self, msg, kind=kind)

    def _on_status_change(self, new_status):
        if not self._manga:
            return
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["status"] = new_status
                self._manga = m
                break
        self.app.config.save()
        Toast(self, f"Status: {new_status}", kind="info")

    # ── Mode (Auto / Manual) ──

    def _on_mode_change(self, label: str):
        """Persist the new mode for the current manga.

        Accepts either a label ("Auto"/"Manual") or the internal key
        ("auto"/"manual") — the new ModeDropdown emits the latter,
        but the old QComboBox emitted the former.
        """
        if not self._manga:
            return
        norm = (label or "").strip().lower()
        new_mode = "manual" if norm == "manual" else "auto"
        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == self._manga.get("title"):
                m["mode"] = new_mode
                self._manga = m
                break
        self.app.config.set("manga", manga_list)
        self.app.config.save()

        # Update the inline hint text
        if hasattr(self, "_mode_hint") and self._mode_hint:
            self._mode_hint.setText(
                "(Manual: download chapters individually below)"
                if new_mode == "manual"
                else "(Auto: new chapters download after each check)"
            )

        Toast(
            self,
            "Mode: Manual — chapters won't auto-download"
            if new_mode == "manual"
            else "Mode: Auto — new chapters will download on next check",
            kind="info",
        )

    # ── Edit ──

    def _show_edit_form(self):
        """Slide the edit panel down with an animated maximumHeight transition."""
        if self._editing:
            return
        self._editing = True
        self._edit_frame.setVisible(True)
        # Measure target height (use sizeHint to capture the natural height).
        target_h = self._edit_frame.sizeHint().height()
        self._edit_frame.setMaximumHeight(0)
        self._animate_edit_height(0, target_h)

    def _hide_edit_form(self):
        """Slide the edit panel up. Hides the frame when the animation finishes."""
        if not self._editing:
            self._edit_frame.setVisible(False)
            return
        self._editing = False
        current_h = self._edit_frame.maximumHeight()
        if current_h <= 0:
            current_h = self._edit_frame.height() or self._edit_frame.sizeHint().height()
        anim = self._animate_edit_height(current_h, 0)
        # Hide the frame after the slide-up completes so it doesn't linger.
        if anim is not None:
            anim.finished.connect(lambda: self._edit_frame.setVisible(False))

    def _animate_edit_height(self, start: int, end: int):
        """Run a QPropertyAnimation on `_edit_frame.maximumHeight`. Returns
        the animation so callers can attach finished handlers.
        """
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(self._edit_frame, b"maximumHeight", self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(int(start))
        anim.setEndValue(int(end))
        anim.start()
        # Keep a reference so it isn't GC'd mid-animation.
        self._edit_anim = anim
        return anim

    def _refetch_cover(self, title: str, url: str, domain: str):
        """Spawn a background cover lookup (scraper → MangaDex fallback).

        Called after a manga is renamed so the corrected title gets
        another chance to resolve to a cover image. Mirrors the chain
        in ``add_manga.py:_fetch_cover``.
        """
        import threading

        def _task():
            cover = None
            try:
                from ...scrapers import get_scraper
                scraper = get_scraper(domain)
                if hasattr(scraper, "get_cover_url") and url:
                    cover = scraper.get_cover_url(url)
            except Exception:
                cover = None

            if not cover:
                try:
                    from ..cover_fallback import fetch_mangadex_cover
                    cover = fetch_mangadex_cover(title)
                except Exception:
                    cover = None

            if cover:
                def _mutate(entry, _cover=cover):
                    entry["cover_url"] = _cover
                    entry.pop("cover_lookup_failed", None)
                    return True
                if self.app.config.update_manga(title, _mutate):
                    self.app.events.publish(
                        "library_updated", {"title": title, "action": "cover"}
                    )

        threading.Thread(target=_task, daemon=True).start()

    def _save_edit(self):
        if not self._manga:
            return

        new_title = self._edit_title.text().strip()
        new_url = self._edit_url.text().strip()
        new_backup = self._edit_backup.text().strip()
        old_title = self._manga.get("title", "")

        if not new_title:
            Toast(self, "Title cannot be empty", kind="error")
            return

        # Fallback delay — only meaningful with a backup source. Drop the
        # field entirely when the user removes the backup so config stays clean.
        try:
            new_delay = int(self._edit_delay.text().strip())
            if new_delay < 0:
                new_delay = 2
        except (ValueError, AttributeError):
            new_delay = 2

        manga_list = self.app.config.get("manga", [])
        for m in manga_list:
            if m.get("title") == old_title:
                m["title"] = new_title

                if new_url:
                    new_domain = urlparse(new_url).netloc.replace("www.", "")
                    if new_backup:
                        backup_domain = urlparse(new_backup).netloc.replace("www.", "")
                        m.pop("source", None)
                        m.pop("url", None)
                        m["sources"] = [
                            {"url": new_url, "source": new_domain},
                            {"url": new_backup, "source": backup_domain},
                        ]
                    elif "sources" in m:
                        m["sources"][0] = {"url": new_url, "source": new_domain}
                        if not new_backup and len(m.get("sources", [])) > 1:
                            m["sources"] = [m["sources"][0]]
                    else:
                        m["source"] = new_domain
                        m["url"] = new_url

                if new_backup:
                    m["fallback_delay_days"] = new_delay
                else:
                    m.pop("fallback_delay_days", None)

                if new_title != old_title:
                    old_state = self.app.app_state.get_manga_state(old_title)
                    if old_state:
                        self.app.app_state._data.setdefault("manga", {})[new_title] = old_state
                        self.app.app_state.remove_manga(old_title)
                    # Move already-downloaded files to the new title so the
                    # reader can still find them (state migrates above, but
                    # the on-disk folder/filenames are keyed by title too).
                    from ...downloader import rename_manga_downloads
                    try:
                        rename_manga_downloads(
                            self.app.config.download_dir, old_title, new_title,
                        )
                    except Exception:
                        pass

                self._manga = m
                break

        self.app.config.save()
        self._editing = False
        Toast(self, "Manga updated", kind="success")

        # Title rename + missing cover → take another shot at finding one.
        # The MangaDex fallback may now succeed if the prior failure was
        # due to a typo. Clear the negative-lookup flag first so the
        # backfill loop won't skip it on the next launch either.
        if (
            new_title
            and new_title != old_title
            and not self._manga.get("cover_url")
        ):
            primary_url = ""
            primary_domain = ""
            srcs = self._manga.get("sources") or []
            if srcs:
                primary_url = srcs[0].get("url", "")
                primary_domain = srcs[0].get("source", "")
            else:
                primary_url = self._manga.get("url", "")
                primary_domain = self._manga.get("source", "")
            # Pop the failed-flag eagerly so backfill won't skip it.
            self._manga.pop("cover_lookup_failed", None)
            self._refetch_cover(new_title, primary_url, primary_domain)

        # Notify other pages (Library card label, Sources Active list).
        self.app.events.publish(
            "library_updated", {"title": new_title, "action": "edit"}
        )

        self._rebuild()

    # ── Downloads ──

    def _check_updates(self):
        if not self._manga:
            return
        self.app.worker.check_updates(
            [self._manga], self.app.app_state, self.app.config, force=True,
        )
        # For auto-mode manga we follow the user to the Downloads page since
        # something will start queueing. For manual mode we stay put — the
        # Detail page will refresh its chapter list when check_complete fires.
        mode = self._manga.get("mode", "auto")
        if mode == "auto":
            self.app.show_page("downloads")
        Toast(self, "Checking for updates...", kind="info")

    def _download_from_chapter(self):
        if not self._manga:
            return
        # New modal chrome — replaces the old plain InputDialog.
        from ..components.download_from_modal import DownloadFromModal

        def _on_confirm(start: float, skip_existing: bool):
            self._do_download_from(str(start), skip_existing=skip_existing)

        DownloadFromModal(self, self._manga, on_confirm=_on_confirm).exec()

    def _do_download_from_skip(self, value, skip_existing=False):
        """Same as _do_download_from but honors a skip-existing flag.

        When ``skip_existing`` is True we don't reset progress for chapters
        already in the downloaded set, so the worker re-issues just the
        gaps. (Backend doesn't yet expose a per-chapter skip flag — for
        now the value is propagated and ignored downstream, so wiring is
        unblocked once the downloader grows that knob.)
        """
        return self._do_download_from(value)

    def _do_download_from(self, value, skip_existing=False):
        if not value:
            return
        try:
            from_ch = float(value)
        except ValueError:
            Toast(self, "Invalid chapter number", kind="error")
            return

        title = self._manga.get("title", "")

        if from_ch <= 0:
            # "Download all" — preserve `downloaded` (issue #15) and let
            # check_for_updates return every chapter from the source.
            self.app.app_state.set_last_chapter(title, None)
        else:
            if not skip_existing:
                self.app.app_state.reset_manga_progress(title, from_ch)
            # Issue #20: tell check_for_updates to only return chapters
            # >= from_ch. It treats `last_chapter` as a `>` cursor, so
            # subtract 0.001 to make from_ch itself qualify.
            self.app.app_state.set_last_chapter(title, str(from_ch - 0.001))

        self.app.worker.check_updates(
            [self._manga], self.app.app_state, self.app.config,
            force=True, queue_all=True,
        )
        self.app.show_page("downloads")
        ch_display = int(from_ch) if from_ch == int(from_ch) else from_ch
        Toast(self, f"Downloading from chapter {ch_display}...", kind="info")

    def _download_all(self):
        self._do_download_from("0")

    # ── Remove ──

    def _confirm_remove(self):
        if not self._manga:
            return
        title = self._manga.get("title", "Unknown")
        ConfirmDialog(
            self, title="Remove Manga",
            message=f"Remove '{title}' from your library?\nThis also removes download history.",
            on_confirm=self._do_remove,
        )

    def _do_remove(self):
        title = self._manga.get("title", "")
        manga_list = self.app.config.get("manga", [])
        manga_list = [m for m in manga_list if m.get("title") != title]
        self.app.config.set("manga", manga_list)
        self.app.config.save()
        self.app.app_state.remove_manga(title)
        self.app.events.publish(
            "library_updated", {"title": title, "action": "remove"}
        )
        self.app.show_page("library")

    # ── Reader ──

    def _read_chapter(self, chapter_num):
        self.app.show_page("reader", manga=self._manga, chapter=chapter_num)

    # ── Per-chapter manual download ──

    def _download_chapter(self, ch_dict: dict, button=None):
        """Queue a single chapter for download (manual-mode flow).

        Reconstructs a ``ChapterWithSource`` from the cached entry and routes
        through the existing ``BackgroundWorker.download_chapter`` API — same
        2-concurrent queue, same Kindle delivery, same progress events.
        """
        if not self._manga:
            return

        try:
            from ...downloader import ChapterWithSource
            from ...scrapers.base import Chapter
        except Exception as e:
            Toast(self, f"Download unavailable: {e}", kind="error")
            return

        number = str(ch_dict.get("number", ""))
        if not number:
            Toast(self, "Chapter number missing", kind="error")
            return

        url = ch_dict.get("url") or ch_dict.get("source_url") or ""
        source = ch_dict.get("source", "")
        source_url = ch_dict.get("source_url") or url
        is_backup = bool(ch_dict.get("is_backup", False))
        ch_title = ch_dict.get("title") or ""

        if not url:
            Toast(self, "Chapter URL missing — re-run Check Updates", kind="error")
            return

        # Build a Chapter (then promote to ChapterWithSource for source routing)
        base = Chapter(number=number, title=ch_title, url=url, date=None)
        chapter = ChapterWithSource(base, source, source_url, is_backup=is_backup)

        # Optional Kindle delivery, same gating as the auto-queue path
        kindle_cfg = None
        global_email_on = (
            self.app.config.delivery_mode == "email" and self.app.config.email_enabled
        )
        if global_email_on and self._manga.get("send_to_kindle", True):
            try:
                from ...config import get_app_password
                kindle_cfg = {
                    "kindle_email": self.app.config.get("email.kindle_email"),
                    "sender_email": self.app.config.get("email.sender_email"),
                    "app_password": get_app_password(self.app.config),
                    "smtp_server": self.app.config.get("email.smtp_server", "smtp.gmail.com"),
                    "smtp_port": self.app.config.get("email.smtp_port", 587),
                }
            except Exception:
                kindle_cfg = None

        naming_template = self.app.config.get("delivery.naming_template")

        self.app.worker.download_chapter(
            manga=self._manga, chapter=chapter,
            output_dir=self.app.config.download_dir,
            output_format=self.app.config.output_format,
            state=self.app.app_state, kindle_cfg=kindle_cfg,
            naming_template=naming_template,
        )

        # Visual feedback: disable the button and relabel until completion
        if button is not None:
            button.setEnabled(False)
            button.setText("Queued")
            self._pending_downloads[f"{self._manga['title']}:{number}"] = button

        Toast(self, f"Queued Chapter {number}", kind="info")

    def _on_any_download_complete(self, data):
        """Refresh the chapter list when a download for the current manga
        finishes — flips the matching row from Download → Read."""
        if not self._manga:
            return
        if data.get("title") != self._manga.get("title"):
            return
        # Drop the pending button reference (the row will be rebuilt anyway)
        self._pending_downloads.pop(data.get("task_id", ""), None)
        # Only refresh if this page is currently visible to avoid wasted work
        if self.isVisible():
            self._refresh_chapter_list()

    def _on_any_check_complete(self, data):
        """Refresh the chapter list after a check completes — newly discovered
        chapters appear as Download rows without requiring navigation."""
        if not self._manga or not self.isVisible():
            return
        my_title = self._manga.get("title", "")
        for r in data.get("results", []):
            if r.get("manga", {}).get("title") == my_title:
                self._refresh_chapter_list()
                return
