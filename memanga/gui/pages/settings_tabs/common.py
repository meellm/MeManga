"""Shared form helpers for the Settings tabs."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit

from ... import theme as T


class SettingsFormMixin:
    """Section headings and labeled entries shared by every tab."""

    def _section(self, parent_layout, text):
        label = QLabel(text)
        label.setStyleSheet(f"font-size: {T.FONT_SIZE_LG}pt; font-weight: bold;")
        label.setContentsMargins(0, T.PAD_LG, 0, T.PAD_SM)
        parent_layout.addWidget(label)

    def _labeled_entry(self, parent_layout, label_text, value, placeholder="", password=False):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        lbl.setFixedWidth(120)
        row.addWidget(lbl)

        entry = QLineEdit()
        # Narrow enough for the Email tab to fit the 900 px minimum
        # window width; the entry still stretches when there is room.
        entry.setMinimumWidth(160)
        if placeholder:
            entry.setPlaceholderText(placeholder)
        if password:
            entry.setEchoMode(QLineEdit.EchoMode.Password)
        if value:
            entry.setText(str(value))
        row.addWidget(entry, 1)
        parent_layout.addLayout(row)
        return entry
