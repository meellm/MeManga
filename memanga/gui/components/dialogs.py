"""
Modal dialog windows.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
)
from PySide6.QtCore import Qt
from .. import theme as T


class ConfirmDialog(QDialog):
    def __init__(self, parent, title="Confirm", message="Are you sure?", on_confirm=None, on_cancel=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(380, 160)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_LG)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)
        layout.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(lambda: (on_cancel() if on_cancel else None, self.close()))
        btns.addWidget(cancel_btn)

        confirm_btn = QPushButton("Confirm")
        confirm_btn.setProperty("class", "accent")
        confirm_btn.setFixedWidth(90)
        confirm_btn.clicked.connect(lambda: (on_confirm() if on_confirm else None, self.close()))
        btns.addWidget(confirm_btn)

        layout.addLayout(btns)
        self.exec()


class InputDialog(QDialog):
    def __init__(self, parent, title="Input", prompt="Enter value:", default="", on_submit=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(400, 160)
        self.setModal(True)
        self._on_submit = on_submit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_LG)

        layout.addWidget(QLabel(prompt))

        self._entry = QLineEdit(default)
        self._entry.setFixedHeight(32)
        self._entry.returnPressed.connect(self._submit)
        layout.addWidget(self._entry)
        layout.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setProperty("class", "accent")
        ok_btn.setFixedWidth(80)
        ok_btn.clicked.connect(self._submit)
        btns.addWidget(ok_btn)

        layout.addLayout(btns)
        self._entry.setFocus()
        self.exec()

    def _submit(self):
        val = self._entry.text().strip()
        if val and self._on_submit:
            self._on_submit(val)
        self.close()
