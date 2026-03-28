"""
Settings page - Delivery, email, format, cron, appearance, import/export.
"""

import json
import platform
import subprocess
import sys
import customtkinter as ctk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_XS,
    font, get_palette,
)
from ..components.toast import Toast


class SettingsPage(BasePage):
    """All configuration in one page."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._build()

    def _build(self):
        palette = get_palette(ctk.get_appearance_mode().lower())

        # Header
        ctk.CTkLabel(
            self, text="Settings",
            font=font(FONT_SIZE_XL, "bold"),
        ).pack(anchor="w", padx=PAD_XL, pady=(PAD_XL, PAD_LG))

        # Scrollable settings
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_MD))

        # == Delivery Mode ==
        self._section(scroll, "Delivery Mode")

        mode_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mode_frame.pack(fill="x", pady=(0, PAD_MD))

        self._mode_var = ctk.StringVar(value=self.app.config.delivery_mode)
        ctk.CTkRadioButton(
            mode_frame, text="Local (save to disk)", variable=self._mode_var, value="local",
            font=font(FONT_SIZE_SM),
        ).pack(side="left", padx=(0, PAD_XL))
        ctk.CTkRadioButton(
            mode_frame, text="Email (send to Kindle)", variable=self._mode_var, value="email",
            font=font(FONT_SIZE_SM),
        ).pack(side="left")

        # Download directory
        dir_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        dir_frame.pack(fill="x", pady=(0, PAD_MD))

        ctk.CTkLabel(dir_frame, text="Download Directory:", font=font(FONT_SIZE_SM)).pack(side="left")
        self._dir_entry = ctk.CTkEntry(dir_frame, font=font(FONT_SIZE_SM), height=30, width=350)
        self._dir_entry.pack(side="left", padx=PAD_SM)
        self._dir_entry.insert(0, str(self.app.config.download_dir))

        ctk.CTkButton(
            dir_frame, text="Browse", width=70, height=30,
            font=font(FONT_SIZE_SM), corner_radius=4,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._browse_dir,
        ).pack(side="left")

        # == Output Format ==
        self._section(scroll, "Output Format")

        self._format_var = ctk.StringVar(value=self.app.config.output_format)
        format_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        format_frame.pack(fill="x", pady=(0, PAD_LG))

        formats = ["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"]
        self._format_menu = ctk.CTkOptionMenu(
            format_frame, values=formats, variable=self._format_var,
            font=font(FONT_SIZE_SM), height=30, width=120,
        )
        self._format_menu.pack(side="left")

        format_desc = ctk.CTkLabel(
            format_frame,
            text="  pdf/epub = e-reader | cbz/zip = archive | jpg/png/webp = image folder",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"],
        )
        format_desc.pack(side="left", padx=PAD_SM)

        # == File Naming ==
        self._section(scroll, "File Naming")

        naming_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        naming_frame.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkLabel(naming_frame, text="Template:", font=font(FONT_SIZE_SM)).pack(side="left")
        self._naming_entry = ctk.CTkEntry(naming_frame, font=font(FONT_SIZE_SM), height=30, width=300)
        self._naming_entry.pack(side="left", padx=PAD_SM)
        current_template = self.app.config.get("delivery.naming_template", "{title} - Chapter {chapter}")
        self._naming_entry.insert(0, current_template)

        ctk.CTkLabel(
            scroll,
            text="Variables: {title}, {chapter}, {source}    Example: \"One Piece - Chapter 1.pdf\"",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"],
        ).pack(anchor="w", pady=(0, PAD_LG))

        # == Email Settings ==
        self._section(scroll, "Email Settings (Kindle)")

        email_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        email_grid.pack(fill="x", pady=(0, PAD_LG))

        self._entry_kindle_email = self._labeled_entry(
            email_grid, "Kindle Email:", self.app.config.get("email.kindle_email", ""),
            placeholder="your-kindle@kindle.com",
        )
        self._entry_sender_email = self._labeled_entry(
            email_grid, "Sender Email:", self.app.config.get("email.sender_email", ""),
            placeholder="your-email@gmail.com",
        )
        self._entry_smtp_server = self._labeled_entry(
            email_grid, "SMTP Server:", self.app.config.get("email.smtp_server", "smtp.gmail.com"),
        )
        self._entry_smtp_port = self._labeled_entry(
            email_grid, "SMTP Port:", str(self.app.config.get("email.smtp_port", 587)),
        )

        # Password
        pw_frame = ctk.CTkFrame(email_grid, fg_color="transparent")
        pw_frame.pack(fill="x", pady=2)
        ctk.CTkLabel(pw_frame, text="App Password:", font=font(FONT_SIZE_SM), width=130, anchor="w").pack(side="left")
        self._password_entry = ctk.CTkEntry(pw_frame, font=font(FONT_SIZE_SM), height=30, width=250, show="*")
        self._password_entry.pack(side="left", padx=PAD_SM)
        ctk.CTkLabel(pw_frame, text="(leave blank to keep current)", font=font(FONT_SIZE_XS),
                      text_color=palette["fg_muted"]).pack(side="left")

        self._delete_after_var = ctk.BooleanVar(value=self.app.config.get("delivery.delete_after_send", False))
        ctk.CTkCheckBox(
            email_grid, text="Delete file after sending to Kindle",
            font=font(FONT_SIZE_SM), variable=self._delete_after_var,
        ).pack(anchor="w", pady=PAD_SM)

        # Test email button
        test_frame = ctk.CTkFrame(email_grid, fg_color="transparent")
        test_frame.pack(fill="x", pady=(PAD_SM, 0))

        ctk.CTkButton(
            test_frame, text="Test Email Connection", width=170, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._test_email,
        ).pack(side="left")

        self._test_label = ctk.CTkLabel(
            test_frame, text="", font=font(FONT_SIZE_XS),
        )
        self._test_label.pack(side="left", padx=PAD_SM)

        ctk.CTkLabel(
            email_grid,
            text="Note: Per-manga kindle toggle is on each manga's detail page.\n"
                 "If email delivery is set to 'local' above, per-manga toggles are disabled.",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], justify="left",
        ).pack(anchor="w", pady=(PAD_SM, 0))

        # == Cron ==
        self._section(scroll, "Scheduled Checks")

        cron_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        cron_frame.pack(fill="x", pady=(0, PAD_SM))

        self._cron_var = ctk.BooleanVar(value=self.app.config.get("cron.enabled", False))
        ctk.CTkCheckBox(
            cron_frame, text="Enable daily auto-check", font=font(FONT_SIZE_SM),
            variable=self._cron_var,
        ).pack(side="left")

        ctk.CTkLabel(cron_frame, text="  Time (HH:MM):", font=font(FONT_SIZE_SM)).pack(side="left")
        self._cron_time = ctk.CTkEntry(cron_frame, font=font(FONT_SIZE_SM), height=28, width=70)
        self._cron_time.pack(side="left", padx=PAD_SM)
        self._cron_time.insert(0, self.app.config.get("cron.time", "06:00"))

        cron_btns = ctk.CTkFrame(scroll, fg_color="transparent")
        cron_btns.pack(fill="x", pady=(0, PAD_SM))

        ctk.CTkButton(
            cron_btns, text="Install Cron Job", width=130, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._install_cron,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            cron_btns, text="Remove Cron Job", width=130, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._remove_cron,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            cron_btns, text="Check Status", width=110, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._check_cron_status,
        ).pack(side="left")

        self._cron_status_label = ctk.CTkLabel(
            scroll, text="", font=font(FONT_SIZE_XS), text_color=palette["fg_muted"],
        )
        self._cron_status_label.pack(anchor="w", pady=(0, PAD_LG))

        # == Import / Export ==
        self._section(scroll, "Import / Export")

        ie_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        ie_frame.pack(fill="x", pady=(0, PAD_LG))

        ctk.CTkButton(
            ie_frame, text="Export", width=100, height=34,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=self._export,
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            ie_frame, text="Import (Merge)", width=130, height=34,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"],
            command=lambda: self._import(replace=False),
        ).pack(side="left", padx=(0, PAD_SM))

        ctk.CTkButton(
            ie_frame, text="Import (Replace)", width=130, height=34,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color=palette["error"], hover_color="#b91c1c",
            command=lambda: self._import(replace=True),
        ).pack(side="left")

        # == Save Button ==
        ctk.CTkButton(
            scroll, text="Save Settings", height=42,
            font=font(FONT_SIZE_MD, "bold"),
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            command=self._save,
        ).pack(fill="x", pady=PAD_XL)

    def _section(self, parent, title):
        ctk.CTkLabel(
            parent, text=title, font=font(FONT_SIZE_LG, "bold"),
        ).pack(anchor="w", pady=(PAD_LG, PAD_SM))

    def _labeled_entry(self, parent, label, value, placeholder=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, font=font(FONT_SIZE_SM), width=130, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row, font=font(FONT_SIZE_SM), height=30, width=250,
                             placeholder_text=placeholder)
        entry.pack(side="left", padx=PAD_SM)
        if value:
            entry.insert(0, value)
        return entry

    def _browse_dir(self):
        path = filedialog.askdirectory()
        if path:
            self._dir_entry.delete(0, "end")
            self._dir_entry.insert(0, path)

    def _validate_time(self, time_str):
        """Validate HH:MM format."""
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

        cfg.set("delivery.mode", self._mode_var.get())
        cfg.set("delivery.download_dir", self._dir_entry.get().strip())
        cfg.set("delivery.output_format", self._format_var.get())
        cfg.set("delivery.delete_after_send", self._delete_after_var.get())

        # Naming template
        template = self._naming_entry.get().strip()
        if not template or ("{title}" not in template and "{chapter}" not in template):
            template = "{title} - Chapter {chapter}"
            Toast(self, "Invalid template, using default", kind="warning")
        cfg.set("delivery.naming_template", template)

        cfg.set("email.kindle_email", self._entry_kindle_email.get().strip())
        cfg.set("email.sender_email", self._entry_sender_email.get().strip())
        cfg.set("email.smtp_server", self._entry_smtp_server.get().strip())

        port_str = self._entry_smtp_port.get().strip()
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
            cfg.set("email.smtp_port", port)
        except ValueError:
            Toast(self, f"Invalid port '{port_str}', using 587", kind="warning")
            cfg.set("email.smtp_port", 587)

        # Password - only update if user entered something
        pw = self._password_entry.get().strip()
        if pw:
            from ...config import set_app_password
            set_app_password(cfg, pw)

        # Cron time validation
        cron_time = self._cron_time.get().strip()
        if not self._validate_time(cron_time):
            Toast(self, f"Invalid time '{cron_time}', using 06:00", kind="warning")
            cron_time = "06:00"

        cfg.set("cron.enabled", self._cron_var.get())
        cfg.set("cron.time", cron_time)

        cfg.save()
        Toast(self, "Settings saved", kind="success")

    # ---- Email Test ----

    def _test_email(self):
        """Test SMTP connection with current settings."""
        palette = get_palette(ctk.get_appearance_mode().lower())
        self._test_label.configure(text="Testing...", text_color=palette["fg_muted"])

        sender = self._entry_sender_email.get().strip()
        smtp_server = self._entry_smtp_server.get().strip()
        smtp_port = self._entry_smtp_port.get().strip()
        pw = self._password_entry.get().strip()

        if not sender or not smtp_server:
            self._test_label.configure(text="Fill in sender email and SMTP server", text_color=palette["error"])
            return

        if not pw:
            from ...config import get_app_password
            pw = get_app_password(self.app.config)

        if not pw:
            self._test_label.configure(text="No app password configured", text_color=palette["error"])
            return

        def _test():
            import smtplib
            try:
                port = int(smtp_port)
                server = smtplib.SMTP(smtp_server, port, timeout=10)
                server.ehlo()
                server.starttls()
                server.login(sender, pw)
                server.quit()
                self.after(0, lambda: self._test_label.configure(text="Connection successful!", text_color=palette["success"]))
            except smtplib.SMTPAuthenticationError:
                self.after(0, lambda: self._test_label.configure(text="Authentication failed - check password", text_color=palette["error"]))
            except Exception as e:
                msg = str(e)[:40]
                self.after(0, lambda: self._test_label.configure(text=f"Failed: {msg}", text_color=palette["error"]))

        import threading
        threading.Thread(target=_test, daemon=True).start()

    # ---- Cron Management ----

    def _install_cron(self):
        cron_time = self._cron_time.get().strip()
        if not self._validate_time(cron_time):
            Toast(self, "Invalid time format. Use HH:MM", kind="error")
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

        cron_cmd = f'{minute} {hour} * * * cd {project_dir} && {python_path} -m memanga check --auto --quiet >> {project_dir}/memanga.log 2>&1'

        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            lines = [l for l in existing.strip().split("\n") if l and "memanga" not in l]
            lines.append(cron_cmd)
            new_crontab = "\n".join(lines) + "\n"

            proc = subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
            if proc.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", f"{hour}:{minute}")
                self.app.config.save()
                Toast(self, f"Cron job installed: daily at {hour}:{minute}", kind="success")
            else:
                Toast(self, f"Failed to install cron: {proc.stderr[:60]}", kind="error")
        except Exception as e:
            Toast(self, f"Cron error: {str(e)[:60]}", kind="error")

    def _install_cron_windows(self, project_dir, cron_time):
        python_path = sys.executable
        venv_python = project_dir / "venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            python_path = str(venv_python)

        task_name = "MeManga_AutoCheck"
        cmd = f'"{python_path}" -m memanga check --auto --quiet'

        try:
            subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                           capture_output=True, text=True)
            result = subprocess.run([
                "schtasks", "/Create", "/TN", task_name, "/SC", "DAILY",
                "/ST", cron_time, "/TR", cmd, "/F",
            ], capture_output=True, text=True)

            if result.returncode == 0:
                self.app.config.set("cron.enabled", True)
                self.app.config.set("cron.time", cron_time)
                self.app.config.save()
                Toast(self, f"Task scheduled: daily at {cron_time}", kind="success")
            else:
                Toast(self, f"Failed: {result.stderr[:60]}", kind="error")
        except Exception as e:
            Toast(self, f"Scheduler error: {str(e)[:60]}", kind="error")

    def _remove_cron(self):
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["schtasks", "/Delete", "/TN", "MeManga_AutoCheck", "/F"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    Toast(self, "Scheduled task removed", kind="success")
                else:
                    Toast(self, "No scheduled task found", kind="info")
            except Exception:
                Toast(self, "Failed to remove task", kind="error")
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                existing = result.stdout if result.returncode == 0 else ""
                lines = [l for l in existing.strip().split("\n") if l and "memanga" not in l]
                new_crontab = "\n".join(lines) + "\n" if lines else ""

                subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
                Toast(self, "Cron job removed", kind="success")
            except Exception:
                Toast(self, "Failed to remove cron job", kind="error")

        self.app.config.set("cron.enabled", False)
        self.app.config.save()

    def _check_cron_status(self):
        palette = get_palette(ctk.get_appearance_mode().lower())
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", "MeManga_AutoCheck"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    self._cron_status_label.configure(
                        text="Scheduled task is installed", text_color=palette["success"],
                    )
                else:
                    self._cron_status_label.configure(
                        text="No scheduled task found", text_color=palette["warning"],
                    )
            except Exception:
                self._cron_status_label.configure(
                    text="Could not check task status", text_color=palette["error"],
                )
        else:
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                if result.returncode == 0 and "memanga" in result.stdout:
                    self._cron_status_label.configure(
                        text="Cron job is installed", text_color=palette["success"],
                    )
                else:
                    self._cron_status_label.configure(
                        text="No cron job found", text_color=palette["warning"],
                    )
            except Exception:
                self._cron_status_label.configure(
                    text="Could not check cron status", text_color=palette["error"],
                )

    # ---- Export / Import ----

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="memanga_export.json",
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
            count = len(data["manga"])
            Toast(self, f"Exported {count} manga to {Path(path).name}", kind="success")
        except Exception as e:
            Toast(self, f"Export failed: {str(e)[:50]}", kind="error")

    def _import(self, replace=False):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)

            manga_list = data.get("manga", [])
            if not isinstance(manga_list, list):
                Toast(self, "Invalid export file (missing 'manga' key)", kind="error")
                return

            if replace:
                self.app.config.set("manga", manga_list)
                self.app.config.save()
                # Replace state
                state_data = data.get("state", {})
                self.app.app_state._data["manga"] = state_data
                self.app.app_state.save()
                Toast(self, f"Replaced with {len(manga_list)} manga", kind="success")
            else:
                existing = self.app.config.get("manga", [])
                existing_titles = {m.get("title", "").lower() for m in existing}
                added = 0
                for m in manga_list:
                    if m.get("title", "").lower() not in existing_titles:
                        existing.append(m)
                        added += 1
                self.app.config.set("manga", existing)
                self.app.config.save()

                # Merge state
                state_data = data.get("state", {})
                for title, sdata in state_data.items():
                    existing_state = self.app.app_state.get_manga_state(title)
                    if not existing_state:
                        self.app.app_state._data.setdefault("manga", {})[title] = sdata
                    else:
                        # Merge downloaded chapters
                        existing_dl = set(existing_state.get("downloaded", []))
                        new_dl = set(sdata.get("downloaded", []))
                        merged = sorted(existing_dl | new_dl, key=lambda x: float(x) if x.replace(".", "").isdigit() else 0)
                        self.app.app_state._data["manga"][title]["downloaded"] = merged
                self.app.app_state.save()

                skipped = len(manga_list) - added
                Toast(self, f"Imported: {added} added, {skipped} skipped", kind="success")

        except json.JSONDecodeError:
            Toast(self, "Invalid JSON file", kind="error")
        except Exception as e:
            Toast(self, f"Import failed: {str(e)[:50]}", kind="error")
