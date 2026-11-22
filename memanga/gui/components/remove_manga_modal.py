"""
"Remove manga" modal and the shared removal action (issue #392).

Library and Detail both remove a manga through this module, so they show
the same confirmation and change the same data. It follows the CLI rules
from issue #349: removing stops tracking but keeps read progress and
download history unless the user opts in, and downloaded files always
stay on disk.

Small modal (440px) with:
  - body naming the manga and stating exactly what changes
  - "Also delete progress and history" checkbox (off); the effects text
    above it names exactly what that deletes
  - foot: Cancel + danger "Remove"
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QPushButton

from .modal import ModalDialog
from .wrapping_label import WrappingLabel

KEPT_TEXT = ("Read progress and download history are kept. "
             "Add it again to pick up where you left off.")
# Scoped to the title: rows left under a former title by renames made
# before renames moved history can't be matched to it, so they stay.
PURGED_TEXT = ("Read progress and download history saved under '{title}' "
               "are deleted. This can't be undone.")
FILES_TEXT = "Downloaded files stay in your download folder."


def remove_manga(app, title: str, *, purge_history: bool = False) -> None:
    """Stop tracking ``title``; delete its state only if ``purge_history``.

    Never touches downloaded files.
    """
    manga_list = [m for m in app.config.get("manga", []) if m.get("title") != title]
    app.config.set("manga", manga_list)
    app.config.save()
    if purge_history:
        app.app_state.remove_manga(title)
        app.app_state.remove_download_history(title)
    app.events.publish("library_updated", {"title": title, "action": "remove"})


def removed_message(title: str, purge_history: bool) -> str:
    """Toast text after a removal."""
    if purge_history:
        return f"Removed '{title}' and the history saved under that title. Files were kept."
    return f"Removed '{title}'. Its history and files were kept."


class RemoveMangaModal(ModalDialog):
    """Confirms removing a manga; calls ``on_confirm(purge_history)``."""

    def __init__(self, parent, title: str, on_confirm):
        self._manga_title = title
        self._on_confirm = on_confirm
        super().__init__(parent, title="Remove manga", width=440)

    def build_body(self):
        bl = self.body_layout

        # PlainText: titles come from sites and may contain markup.
        # WrappingLabel: the centered panel sizes from sizeHint(), so a
        # plain QLabel's long wrapped text (long titles) would be clipped
        # and the panel would not grow when the text changes.
        question = WrappingLabel(f"Remove '{self._manga_title}' from your library?")
        question.setTextFormat(Qt.TextFormat.PlainText)
        bl.addWidget(question)

        self._effects = WrappingLabel()
        self._effects.setTextFormat(Qt.TextFormat.PlainText)
        self._effects.setProperty("role", "hint")
        bl.addWidget(self._effects)

        # Kept short: a QCheckBox label never wraps, and the effects text
        # above already names what is deleted.
        self._purge_check = QCheckBox("Also delete progress and history")
        self._purge_check.setChecked(False)
        self._purge_check.toggled.connect(self._update_effects)
        bl.addWidget(self._purge_check)
        self._update_effects()

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setProperty("variant", "danger")
        self.remove_btn.setMinimumHeight(34)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(self._do_confirm)
        self.foot_layout.addWidget(self.remove_btn)

        # Enter must not remove by accident: Cancel is the default.
        self.remove_btn.setAutoDefault(False)
        self.cancel_btn.setDefault(True)
        self.cancel_btn.setFocus()

    def _update_effects(self, *_):
        if self._purge_check.isChecked():
            history = PURGED_TEXT.format(title=self._manga_title)
        else:
            history = KEPT_TEXT
        self._effects.setText(f"{history}\n{FILES_TEXT}")
        if self.isVisible():
            self._relayout()

    def _relayout(self):
        """Fit the panel to the new text now. A size change otherwise
        climbs the nested body/panel/dialog layouts one event-loop pass
        at a time, so the panel can show the old, too-short height."""
        layouts = (self.body_layout, self.panel.layout(), self.layout())
        for layout in layouts:
            layout.invalidate()
        # Inner first, so each outer layout reads fresh size hints.
        for layout in layouts:
            layout.activate()

    def _do_confirm(self):
        purge = self._purge_check.isChecked()
        self.accept()
        if self._on_confirm:
            self._on_confirm(purge)
