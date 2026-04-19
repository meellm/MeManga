"""
Settings page - Tabbed: General, Email, Sources, Advanced.
"""

import json
import platform
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QComboBox, QCheckBox, QRadioButton,
    QLineEdit, QFileDialog, QButtonGroup,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T
from ..components.toast import Toast


class SettingsPage(BasePage):
    """Tabbed settings: General, Email, Sources, Advanced."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._current_tab = "general"
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_SM)
        layout.setSpacing(T.PAD_SM)

        # Header
        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: {T.FONT_SIZE_XL}pt; font-weight: bold;")
        layout.addWidget(title)

        # Tab bar
        tab_bar = QHBoxLayout()
        self._tab_buttons: dict[str, QPushButton] = {}
        for name in ["General", "Email", "Advanced"]:
            btn = QPushButton(name)
            btn.setProperty("class", "tab")
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=name.lower(): self._switch_tab(t))
            tab_bar.addWidget(btn)
            self._tab_buttons[name.lower()] = btn
        tab_bar.addStretch()
        layout.addLayout(tab_bar)

        # ── General tab ──
        self._general_scroll = QScrollArea()
        self._general_scroll.setWidgetResizable(True)
        self._general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        general_content = QWidget()
        self._general_layout = QVBoxLayout(general_content)
        self._general_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._general_layout.setSpacing(T.PAD_SM)
        self._general_scroll.setWidget(general_content)
        self._build_general()

        # ── Email tab ──
        self._email_scroll = QScrollArea()
        self._email_scroll.setWidgetResizable(True)
        self._email_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        email_content = QWidget()
        self._email_layout = QVBoxLayout(email_content)
        self._email_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._email_layout.setSpacing(T.PAD_SM)
        self._email_scroll.setWidget(email_content)
        self._build_email()

        # ── Advanced tab ──
        self._advanced_scroll = QScrollArea()
        self._advanced_scroll.setWidgetResizable(True)
        self._advanced_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        advanced_content = QWidget()
        self._advanced_layout = QVBoxLayout(advanced_content)
        self._advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._advanced_layout.setSpacing(T.PAD_SM)
        self._advanced_scroll.setWidget(advanced_content)
        self._build_advanced()

        # Add all tab scrolls
        layout.addWidget(self._general_scroll, 1)
        layout.addWidget(self._email_scroll, 1)
        layout.addWidget(self._advanced_scroll, 1)

        self._switch_tab("general")

    def _switch_tab(self, tab_name):
        self._current_tab = tab_name

        self._general_scroll.setVisible(tab_name == "general")
        self._email_scroll.setVisible(tab_name == "email")
        self._advanced_scroll.setVisible(tab_name == "advanced")

        for name, btn in self._tab_buttons.items():
            is_active = (name == tab_name)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Helpers ──

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
        entry.setFixedHeight(30)
        entry.setFixedWidth(220)
        if placeholder:
            entry.setPlaceholderText(placeholder)
        if password:
            entry.setEchoMode(QLineEdit.EchoMode.Password)
        if value:
            entry.setText(str(value))
        row.addWidget(entry)
        row.addStretch()
        parent_layout.addLayout(row)
        return entry

    # ── General Tab ──

    def _build_general(self):
        f = self._general_layout

        # Delivery mode
        self._section(f, "Delivery Mode")
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._radio_local = QRadioButton("Local (save to disk)")
        self._radio_email = QRadioButton("Email (send to Kindle)")
        self._mode_group.addButton(self._radio_local)
        self._mode_group.addButton(self._radio_email)
        if self.app.config.delivery_mode == "email":
            self._radio_email.setChecked(True)
        else:
            self._radio_local.setChecked(True)
        mode_row.addWidget(self._radio_local)
        mode_row.addSpacing(T.PAD_XL)
        mode_row.addWidget(self._radio_email)
        mode_row.addStretch()
        f.addLayout(mode_row)

        # Download directory
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("Download Directory:")
        dir_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        dir_row.addWidget(dir_lbl)

        self._dir_entry = QLineEdit(str(self.app.config.download_dir))
        self._dir_entry.setFixedHeight(30)
        self._dir_entry.setMinimumWidth(300)
        dir_row.addWidget(self._dir_entry, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(30)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        f.addLayout(dir_row)

        # Output format
        self._section(f, "Output Format")
        format_row = QHBoxLayout()
        self._format_combo = QComboBox()
        self._format_combo.addItems(["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"])
        self._format_combo.setCurrentText(self.app.config.output_format)
        self._format_combo.setFixedHeight(30)
        self._format_combo.setFixedWidth(120)
        format_row.addWidget(self._format_combo)

        hint = QLabel("pdf/epub = e-reader | cbz/zip = archive")
        hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        format_row.addWidget(hint)
        format_row.addStretch()
        f.addLayout(format_row)

        # Naming template
        self._section(f, "File Naming")
        naming_row = QHBoxLayout()
        naming_lbl = QLabel("Template:")
        naming_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        naming_row.addWidget(naming_lbl)

        self._naming_entry = QLineEdit(
            self.app.config.get("delivery.naming_template", "{title} - Chapter {chapter}")
        )
        self._naming_entry.setFixedHeight(30)
        self._naming_entry.setMinimumWidth(280)
        naming_row.addWidget(self._naming_entry, 1)
        f.addLayout(naming_row)

        vars_label = QLabel("Variables: {title}, {chapter}, {source}")
        vars_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        f.addWidget(vars_label)

        f.addSpacing(T.PAD_LG)

        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.setProperty("class", "accent")
        save_btn.setFixedHeight(38)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        f.addWidget(save_btn)

    # ── Email Tab ──

    def _build_email(self):
        f = self._email_layout

        self._section(f, "Kindle / SMTP")

        self._entry_kindle_email = self._labeled_entry(
            f, "Kindle Email:", self.app.config.get("email.kindle_email", ""), "your-kindle@kindle.com"
        )
        self._entry_sender_email = self._labeled_entry(
            f, "Sender Email:", self.app.config.get("email.sender_email", ""), "your-email@gmail.com"
        )
        self._entry_smtp_server = self._labeled_entry(
            f, "SMTP Server:", self.app.config.get("email.smtp_server", "smtp.gmail.com")
        )
        self._entry_smtp_port = self._labeled_entry(
            f, "SMTP Port:", str(self.app.config.get("email.smtp_port", 587))
        )

        # Password row
        pw_row = QHBoxLayout()
        pw_lbl = QLabel("App Password:")
        pw_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        pw_lbl.setFixedWidth(120)
        pw_row.addWidget(pw_lbl)

        self._password_entry = QLineEdit()
        self._password_entry.setFixedHeight(30)
        self._password_entry.setFixedWidth(220)
        self._password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        pw_row.addWidget(self._password_entry)

        pw_hint = QLabel("(leave blank to keep)")
        pw_hint.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        pw_row.addWidget(pw_hint)
        pw_row.addStretch()
        f.addLayout(pw_row)

        # Delete after send
        self._delete_after_check = QCheckBox("Delete file after sending")
        self._delete_after_check.setChecked(self.app.config.get("delivery.delete_after_send", False))
        f.addWidget(self._delete_after_check)

        f.addSpacing(T.PAD_SM)

        # Test connection
        test_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.setFixedHeight(30)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.clicked.connect(self._test_email)
        test_row.addWidget(test_btn)

        self._test_label = QLabel("")
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt;")
        test_row.addWidget(self._test_label)
        test_row.addStretch()
        f.addLayout(test_row)

        f.addSpacing(T.PAD_LG)

        # Save button
        save_btn = QPushButton("Save Email Settings")
        save_btn.setProperty("class", "accent")
        save_btn.setFixedHeight(38)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        f.addWidget(save_btn)

    # ── Advanced Tab ──

    def _build_advanced(self):
        f = self._advanced_layout

        # Scheduled checks
        self._section(f, "Scheduled Checks")
        cron_row = QHBoxLayout()

        self._cron_check = QCheckBox("Enable daily auto-check")
        self._cron_check.setChecked(self.app.config.get("cron.enabled", False))
        cron_row.addWidget(self._cron_check)

        time_lbl = QLabel("Time:")
        time_lbl.setStyleSheet(f"font-size: {T.FONT_SIZE_SM}pt;")
        cron_row.addWidget(time_lbl)

        self._cron_time = QLineEdit(self.app.config.get("cron.time", "06:00"))
        self._cron_time.setFixedHeight(28)
        self._cron_time.setFixedWidth(60)
        cron_row.addWidget(self._cron_time)
        cron_row.addStretch()
        f.addLayout(cron_row)

        cron_btns = QHBoxLayout()
        install_btn = QPushButton("Install")
        install_btn.setProperty("class", "accent")
        install_btn.setFixedHeight(28)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self._install_cron)
        cron_btns.addWidget(install_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setFixedHeight(28)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._remove_cron)
        cron_btns.addWidget(remove_btn)

        status_btn = QPushButton("Status")
        status_btn.setFixedHeight(28)
        status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        status_btn.clicked.connect(self._check_cron_status)
        cron_btns.addWidget(status_btn)

        cron_btns.addStretch()
        f.addLayout(cron_btns)

        self._cron_status_label = QLabel("")
        self._cron_status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        f.addWidget(self._cron_status_label)

        f.addSpacing(T.PAD_XL)

        # Import/Export
        self._section(f, "Import / Export")
        ie_row = QHBoxLayout()

        export_btn = QPushButton("Export")
        export_btn.setFixedHeight(30)
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self._export)
        ie_row.addWidget(export_btn)

        import_merge_btn = QPushButton("Import (Merge)")
        import_merge_btn.setFixedHeight(30)
        import_merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_merge_btn.clicked.connect(lambda: self._import(replace=False))
        ie_row.addWidget(import_merge_btn)

        import_replace_btn = QPushButton("Import (Replace)")
        import_replace_btn.setProperty("class", "danger")
        import_replace_btn.setFixedHeight(30)
        import_replace_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_replace_btn.clicked.connect(lambda: self._import(replace=True))
        ie_row.addWidget(import_replace_btn)

        ie_row.addStretch()
        f.addLayout(ie_row)

    # ── Actions ──

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if path:
            self._dir_entry.setText(path)

    def _validate_time(self, time_str):
        try:
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                return False
            h, m = int(parts[0]), int(parts[1])
            return 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, IndexError):
            return False

    def _save(self):
        cfg = self.app.config
        mode = "email" if self._radio_email.isChecked() else "local"
        cfg.set("delivery.mode", mode)
        cfg.set("delivery.download_dir", self._dir_entry.text().strip())
        cfg.set("delivery.output_format", self._format_combo.currentText())
        cfg.set("delivery.delete_after_send", self._delete_after_check.isChecked())

        template = self._naming_entry.text().strip()
        if not template or ("{title}" not in template and "{chapter}" not in template):
            template = "{title} - Chapter {chapter}"
        cfg.set("delivery.naming_template", template)

        cfg.set("email.kindle_email", self._entry_kindle_email.text().strip())
        cfg.set("email.sender_email", self._entry_sender_email.text().strip())
        cfg.set("email.smtp_server", self._entry_smtp_server.text().strip())

        port_str = self._entry_smtp_port.text().strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
            cfg.set("email.smtp_port", port)
        except ValueError:
            cfg.set("email.smtp_port", 587)

        pw = self._password_entry.text().strip()
        if pw:
            from ...config import set_app_password
            set_app_password(cfg, pw)

        cron_time = self._cron_time.text().strip()
        if not self._validate_time(cron_time):
            cron_time = "06:00"
        cfg.set("cron.enabled", self._cron_check.isChecked())
        cfg.set("cron.time", cron_time)

        cfg.save()
        Toast(self, "Settings saved", kind="success")

    def _test_email(self):
        self._test_label.setText("Testing...")
        self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")

        sender = self._entry_sender_email.text().strip()
        smtp_server = self._entry_smtp_server.text().strip()
        smtp_port = self._entry_smtp_port.text().strip()
        pw = self._password_entry.text().strip()

        if not sender or not smtp_server:
            self._test_label.setText("Fill sender + server")
            self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            return
        if not pw:
            from ...config import get_app_password
            pw = get_app_password(self.app.config)
        if not pw:
            self._test_label.setText("No password")
            self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            return

        def _test():
            import smtplib
            try:
                server = smtplib.SMTP(smtp_server, int(smtp_port), timeout=10)
                server.ehlo()
                server.starttls()
                server.login(sender, pw)
                server.quit()
                self._test_label.setText("Success!")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.SUCCESS};")
            except smtplib.SMTPAuthenticationError:
                self._test_label.setText("Auth failed")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")
            except Exception as e:
                msg = str(e)[:30]
                self._test_label.setText(f"Failed: {msg}")
                self._test_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.ERROR};")

        threading.Thread(target=_test, daemon=True).start()

    # ── Cron ──

    def _install_cron(self):
        cron_time = self._cron_time.text().strip()
        if not self._validate_time(cron_time):
            Toast(self, "Invalid time", kind="error")
            return
        hour, minute = cron_time.split(":")
        project_dir = Path(__file__).resolve().parent.parent.parent.parent

        if platform.system() == "Windows":
            self._install_cron_windows(project_dir, cron_time)
        else:
            self._install_cron_unix(project_dir, hour, minute)

    def _install_cron_unix(self, project_dir, hour, minute):
        python_path = sys.executable
        venv_python = project_dir / "venv" / "bin" / "python3"
        if venv_python.exists():
            python_path = str(venv_python)
        cron_cmd = (
            f'{minute} {hour} * * * cd {project_dir} && {python_path} '
            f'-m memanga check --auto --quiet >> {project_dir}/memanga.log 2>&1'
        )
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            lines = [line for line in existing.strip().split("\n") if line and "memanga" not in line]
            lines.append(cron_cmd)
            proc = subprocess.run(
                ["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True
            )
            if proc.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", f"{hour}:{minute}")
                self.app.config.save()
                Toast(self, f"Cron: daily at {hour}:{minute}", kind="success")
            else:
                Toast(self, f"Failed: {proc.stderr[:40]}", kind="error")
        except Exception as e:
            Toast(self, f"Error: {str(e)[:40]}", kind="error")

    def _install_cron_windows(self, project_dir, cron_time):
        python_path = sys.executable
        venv_python = project_dir / "venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            python_path = str(venv_python)
        task_name = "MeManga_AutoCheck"
        cmd = f'"{python_path}" -m memanga check --auto --quiet'
        try:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True, text=True,
            )
            result = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/SC", "DAILY",
                 "/ST", cron_time, "/TR", cmd, "/F"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", cron_time)
                self.app.config.save()
                Toast(self, f"Task: daily at {cron_time}", kind="success")
            else:
                Toast(self, f"Failed: {result.stderr[:40]}", kind="error")
        except Exception as e:
            Toast(self, f"Error: {str(e)[:40]}", kind="error")

    def _remove_cron(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(
                    ["schtasks", "/Delete", "/TN", "MeManga_AutoCheck", "/F"],
                    capture_output=True, text=True,
                )
                Toast(self, "Task removed", kind="success")
            except Exception:
                Toast(self, "Failed", kind="error")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                lines = [line for line in existing.strip().split("\n") if line and "memanga" not in line]
                subprocess.run(
                    ["crontab", "-"],
                    input=("\n".join(lines) + "\n") if lines else "",
                    capture_output=True, text=True,
                )
                Toast(self, "Cron removed", kind="success")
            except Exception:
                Toast(self, "Failed", kind="error")
        self.app.config.set("cron.enabled", False)
        self.app.config.save()

    def _check_cron_status(self):
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", "MeManga_AutoCheck"],
                    capture_output=True, text=True,
                )
                text = "Task installed" if result.returncode == 0 else "No task found"
                color = T.SUCCESS if result.returncode == 0 else T.WARNING
            except Exception:
                text, color = "Check failed", T.ERROR
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                found = result.returncode == 0 and "memanga" in result.stdout
                text = "Cron installed" if found else "No cron found"
                color = T.SUCCESS if found else T.WARNING
            except Exception:
                text, color = "Check failed", T.ERROR
        self._cron_status_label.setText(text)
        self._cron_status_label.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {color};")

    # ── Import/Export ──

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "memanga_export.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = {
                "version": 1,
                "exported_at": datetime.now().isoformat(),
                "manga": self.app.config.get("manga", []),
                "state": self.app.app_state._data.get("manga", {}),
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            Toast(self, f"Exported {len(data['manga'])} manga", kind="success")
        except Exception as e:
            Toast(self, f"Export failed: {str(e)[:40]}", kind="error")

    def _import(self, replace=False):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            manga_list = data.get("manga", [])
            if not isinstance(manga_list, list):
                Toast(self, "Invalid file", kind="error")
                return
            if replace:
                self.app.config.set("manga", manga_list)
                self.app.config.save()
                self.app.app_state._data["manga"] = data.get("state", {})
                self.app.app_state.save()
                Toast(self, f"Replaced with {len(manga_list)} manga", kind="success")
            else:
                existing = self.app.config.get("manga", [])
                existing_titles = {m.get("title", "").lower() for m in existing}
                added = sum(
                    1 for m in manga_list if m.get("title", "").lower() not in existing_titles
                )
                for m in manga_list:
                    if m.get("title", "").lower() not in existing_titles:
                        existing.append(m)
                self.app.config.set("manga", existing)
                self.app.config.save()
                for t, sdata in data.get("state", {}).items():
                    if not self.app.app_state.get_manga_state(t):
                        self.app.app_state._data.setdefault("manga", {})[t] = sdata
                self.app.app_state.save()
                Toast(self, f"Imported {added} manga", kind="success")
        except json.JSONDecodeError:
            Toast(self, "Invalid JSON", kind="error")
        except Exception as e:
            Toast(self, f"Failed: {str(e)[:40]}", kind="error")
