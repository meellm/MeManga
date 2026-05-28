"""Modal first-run dialog for downloading Playwright's Firefox build.

The Playwright Firefox build is ~90 MB and download time is dominated
by network speed (anywhere from 20 s to several minutes). A blank
"please wait" message during that window looks like the app is hung.
This dialog streams the subprocess output, parses the percentage out
of the progress line Playwright already prints, and surfaces both a
progress bar and the raw log (collapsible) so failures are
diagnosable.

Used by :func:`memanga.gui._ensure_browsers` when a QApplication
exists. Falls back to the legacy QMessageBox flow if Qt isn't
available at the call site (CLI-driven fallback path).
"""

from __future__ import annotations

import re
import threading
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QPlainTextEdit,
)


# Playwright's install CLI prints lines like
#   "91 MiB [====================] 100% 0.0s"
# during the download. Match any "<n>%" token — works whether the
# percentage is the only thing on the line or embedded in a progress bar.
_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _parse_percent(line: str) -> Optional[int]:
    """Return an int 0..100 if `line` contains a percentage, else None."""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    try:
        pct = int(float(m.group(1)))
    except ValueError:
        return None
    return max(0, min(100, pct))


class _InstallSignals(QObject):
    """Worker → UI bridge. All slots run on the main thread."""

    progress = Signal(int)        # 0..100
    status = Signal(str)          # current status line
    raw_line = Signal(str)        # raw subprocess line
    finished = Signal(bool, str)  # ok, error_detail


class FirefoxInstallDialog(QDialog):
    """Modal dialog that drives Playwright's Firefox install.

    Construction does not start the install — call :meth:`run_install`
    to spin the dialog (blocking) and run the install in a worker
    thread. ``run_install`` returns ``(ok, error_text)``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MeManga — First-time setup")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._signals = _InstallSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.status.connect(self._on_status)
        self._signals.raw_line.connect(self._on_raw_line)
        self._signals.finished.connect(self._on_finished)
        self._cancelled = False
        self._ok: Optional[bool] = None
        self._error: str = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        title = QLabel("Setting up MeManga")
        title.setStyleSheet("font-size: 16pt; font-weight: 600;")
        layout.addWidget(title)

        self._subtitle = QLabel(
            "Downloading Firefox browser components (~90 MB). This runs "
            "once per machine and is required to scrape sites that need "
            "a real browser."
        )
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._bar = QProgressBar()
        # Start indeterminate (busy stripe) until a percentage arrives.
        self._bar.setRange(0, 0)
        layout.addWidget(self._bar)

        self._status_label = QLabel("Connecting…")
        self._status_label.setStyleSheet("color: #888;")
        layout.addWidget(self._status_label)

        # Collapsible log block — hidden by default, auto-shown on error.
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(140)
        self._log.setStyleSheet("font-family: monospace; font-size: 9pt;")
        self._log.hide()
        layout.addWidget(self._log)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._show_log_btn = QPushButton("Show log")
        self._show_log_btn.clicked.connect(self._toggle_log)
        btn_row.addWidget(self._show_log_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_install(self) -> Tuple[bool, str]:
        """Start the install on a worker thread and block until done.

        Safe to call from the GUI thread — the dialog runs its own
        Qt event loop via ``exec()`` so the parent window stays
        responsive.
        """
        threading.Thread(target=self._install_worker, daemon=True).start()
        self.exec()
        return bool(self._ok), self._error

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _install_worker(self):
        # Imported lazily so unit tests that only construct the dialog
        # don't trigger a Playwright import at module load.
        from .. import _install_playwright_browsers_stream
        try:
            ok, error = _install_playwright_browsers_stream(
                on_line=self._handle_line,
                cancelled=lambda: self._cancelled,
            )
        except Exception as exc:  # pragma: no cover - defensive
            ok, error = False, f"{type(exc).__name__}: {exc}"
        self._signals.finished.emit(ok, error)

    def _handle_line(self, line: str):
        line = line.rstrip("\r\n")
        if not line:
            return
        self._signals.raw_line.emit(line)
        pct = _parse_percent(line)
        if pct is not None:
            self._signals.progress.emit(pct)
        low = line.lower()
        if "downloading" in low:
            self._signals.status.emit("Downloading Firefox…")
        elif "extracting" in low:
            self._signals.status.emit("Extracting…")
        elif "downloaded to" in low or "installed" in low:
            self._signals.status.emit("Finalizing…")

    # ------------------------------------------------------------------
    # Slots (main thread)
    # ------------------------------------------------------------------

    def _on_progress(self, pct: int):
        if self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._bar.setValue(pct)

    def _on_status(self, status: str):
        self._status_label.setText(status)

    def _on_raw_line(self, line: str):
        self._log.appendPlainText(line)

    def _on_finished(self, ok: bool, error: str):
        self._ok = ok
        self._error = error
        if ok:
            self._status_label.setText("Installation complete.")
            self._bar.setRange(0, 100)
            self._bar.setValue(100)
            # Brief pause so the filled bar is visible before the
            # dialog disappears.
            QTimer.singleShot(400, self.accept)
            return

        self._status_label.setText(
            "Installation failed — see log for details."
        )
        self._subtitle.setText(
            "Firefox install failed. Check your internet connection and "
            "try again. You can also install manually with:\n"
            "    playwright install firefox"
        )
        if self._log.isHidden():
            self._log.show()
            self._show_log_btn.setText("Hide log")
        self._log.appendPlainText("")
        self._log.appendPlainText("--- summary ---")
        self._log.appendPlainText(error or "(no detail)")
        # Swap Cancel → Close so the dialog can be dismissed without
        # kicking off a second install attempt.
        self._cancel_btn.setText("Close")
        try:
            self._cancel_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._cancel_btn.clicked.connect(self.reject)
        self.adjustSize()

    def _on_cancel_clicked(self):
        # Best-effort cancel — the worker thread polls this between
        # subprocess output lines.
        self._cancelled = True
        self.reject()

    def _toggle_log(self):
        # `isHidden()` reflects the most-recent explicit hide()/show()
        # call. `isVisible()` is only true once the parent dialog is
        # realised on screen, so it can't drive the toggle.
        if self._log.isHidden():
            self._log.show()
            self._show_log_btn.setText("Hide log")
        else:
            self._log.hide()
            self._show_log_btn.setText("Show log")
        self.adjustSize()
