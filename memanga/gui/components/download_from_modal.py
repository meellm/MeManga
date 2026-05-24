"""
"Download from chapter" modal — matches memanga-pyside6-spec.json
`modals.download_from_chapter`.

Small modal (440px) with:
  - mono input centered, 15px, padding 12px
  - hint with code-styled `0` example
  - "Skip chapters already downloaded" checkbox
  - foot: Cancel + primary "Start download" (download icon)

Backend: caller passes a `manga` dict + `on_confirm(start_chapter, skip_existing)`
callback. The modal validates the start-chapter number and closes on confirm.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QPushButton, QCheckBox, QLabel

from .. import theme as T
from .modal import ModalDialog, field_label, field_hint
from ..assets.icons import icon


class DownloadFromModal(ModalDialog):
    """Prompts for a start chapter + skip-existing flag."""

    def __init__(self, parent, manga: dict, on_confirm):
        self._manga = manga
        self._on_confirm = on_confirm
        super().__init__(parent, title="Download from chapter", width=440)

    def build_body(self):
        bl = self.body_layout

        bl.addWidget(field_label("Start downloading from chapter"))
        self._chapter_input = QLineEdit("1")
        self._chapter_input.setStyleSheet(
            f"font-family: 'Geist Mono', monospace; font-size: 15pt;"
            f"padding: 12px; text-align: center;"
        )
        self._chapter_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(self._chapter_input)

        # Hint with code-styled "0"
        hint = QLabel(
            f"Use <code style='font-family:\"Geist Mono\",monospace;"
            f"background:{T.tokens()['surfaces.bg_3']};padding:1px 5px;"
            f"border-radius:3px;color:{T.tokens()['text.t_1']}'>0</code> "
            f"to download all chapters from the beginning."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        bl.addWidget(hint)

        self._skip_check = QCheckBox("Skip chapters already downloaded")
        self._skip_check.setChecked(False)
        bl.addWidget(self._skip_check)

        # Foot: replace cancel + add primary "Start download"
        start_btn = QPushButton("  Start download")
        start_btn.setProperty("variant", "primary")
        start_btn.setIcon(icon("download", T.tokens()["accent.on_primary"], 14))
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.clicked.connect(self._do_confirm)
        self.foot_layout.addWidget(start_btn)

        self._chapter_input.setFocus()
        self._chapter_input.selectAll()

    def _do_confirm(self):
        raw = self._chapter_input.text().strip() or "1"
        try:
            start = float(raw)
        except ValueError:
            from .toast import Toast
            Toast(self, "Chapter must be a number", kind="warning")
            return
        if self._on_confirm:
            try:
                self._on_confirm(start, self._skip_check.isChecked())
            except Exception:
                pass
        self.accept()
