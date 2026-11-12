"""
First-run "where should downloads go?" dialog (issue #370).

The download folder used to be a silent default: a new user only found
out where chapters went by looking for them. A new library is asked
once, with the default filled in, so the folder is seen and can be
changed before the first download. It can be changed again any time in
Settings.

Either way out of the dialog records that it was shown
(`gui.download_dir_confirmed`), so it never comes back; closing it keeps
the folder that was already set.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from .. import theme as T
from .modal import ModalDialog, field_hint, field_label

CONFIRMED_KEY = "gui.download_dir_confirmed"


def needs_download_location(config) -> bool:
    """Whether to ask: a library with no manga that was never asked.
    A library that already has manga has been downloading to its folder
    and is left alone."""
    if config.get(CONFIRMED_KEY):
        return False
    return not (config.get("manga") or [])


def download_dir_problem(config, text: str):
    """Why ``text`` can't be the download folder, or None when it can.

    Uses the same check as `memanga doctor`: an existing folder must be
    writable, a new one must be creatable. Nothing is created here; the
    folder appears with the first download.
    """
    text = (text or "").strip()
    if not text:
        return "Choose a folder for your downloads."
    from ... import doctor
    # The check reads the folder from the config, so the candidate is
    # put there for the length of the check and the old value restored.
    previous = config.get("delivery.download_dir")
    config.set("delivery.download_dir", text)
    try:
        result = doctor.check_download_dir(config)
    except Exception as e:
        return str(e) or type(e).__name__
    finally:
        config.set("delivery.download_dir", previous)
    return result.message if result.status == doctor.FAIL else None


class DownloadLocationDialog(ModalDialog):
    """Shows the download folder of a new library and lets it be changed."""

    def __init__(self, parent, config):
        self._config = config
        super().__init__(parent, title="Where should downloads go?", width=520)

    def build_body(self):
        bl = self.body_layout

        intro = QLabel(
            "MeManga saves the chapters you download in this folder, one "
            "subfolder per manga."
        )
        intro.setWordWrap(True)
        bl.addWidget(intro)

        label = field_label("Download folder")
        bl.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._path_input = QLineEdit(str(self._config.download_dir))
        self._path_input.setMinimumHeight(36)
        self._path_input.setAccessibleName("Download folder")
        label.setBuddy(self._path_input)
        self._path_input.returnPressed.connect(self._confirm)
        row.addWidget(self._path_input, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.setMinimumHeight(36)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setAccessibleDescription("Choose the download folder")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        bl.addLayout(row)

        # Says why a folder can't be used; empty until then.
        self._problem = QLabel("")
        self._problem.setTextFormat(Qt.TextFormat.PlainText)
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet(
            f"color: {T.tokens()['status.danger']};"
            f" font-size: {T.FONT_SIZE_SM}pt;")
        self._problem.hide()
        bl.addWidget(self._problem)

        bl.addWidget(field_hint(
            "You can change it later in Settings → General."))

        self.cancel_btn.setText("Keep current folder")

        confirm_btn = QPushButton("Use this folder")
        confirm_btn.setProperty("variant", "primary")
        confirm_btn.setMinimumHeight(34)
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Set directly as well, as the other modals do: the foot's own
        # sheet would otherwise paint over the accent fill.
        confirm_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {T.tokens()['accent.primary']};"
            f"  color: {T.tokens()['accent.on_primary']};"
            f"  border: 1px solid {T.tokens()['accent.primary']};"
            f"  border-radius: 6px;"
            f"  padding: 6px 14px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {T.tokens()['accent.primary_2']};"
            f"  border-color: {T.tokens()['accent.primary_2']};"
            f"}}"
            # Keyboard focus ring (issue #396), as for app primary buttons.
            f"QPushButton[focusVisible=\"true\"]:focus {{"
            f"  border: 2px solid {T.tokens()['text.t_1']};"
            f"  padding: 5px 13px;"
            f"}}"
        )
        confirm_btn.clicked.connect(self._confirm)
        self.foot_layout.addWidget(confirm_btn)
        self._confirm_btn = confirm_btn

        self._path_input.setFocus()

    # ── actions ──

    def _browse(self):
        start = self._path_input.text().strip()
        # Start in the nearest folder that exists: the default one is
        # only created by the first download.
        folder = Path(start).expanduser() if start else Path.home()
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Download Directory", str(folder))
        if chosen:
            self._path_input.setText(chosen)
            self._show_problem(None)

    def _show_problem(self, problem):
        if problem:
            self._problem.setText(problem)
            self._problem.setAccessibleName(problem)
            self._problem.show()
        else:
            self._problem.hide()

    def _confirm(self):
        text = self._path_input.text().strip()
        problem = download_dir_problem(self._config, text)
        if problem:
            self._show_problem(problem)
            self._path_input.setFocus()
            return
        self._config.set("delivery.download_dir", text)
        self.accept()

    def done(self, result):
        """Every way out (Use this folder, Keep current folder, the
        close button, Esc, a click outside) records that the question
        was asked, so it is asked once."""
        try:
            self._config.set(CONFIRMED_KEY, True)
            self._config.save()
        except Exception:
            pass
        super().done(result)
