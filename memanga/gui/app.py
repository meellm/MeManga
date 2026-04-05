"""
MeManga GUI Application - PySide6 MainWindow with sidebar + QStackedWidget.
"""

from datetime import datetime

from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget
from PySide6.QtCore import QTimer

from .. import __version__
from ..config import Config, get_app_password, set_app_password
from ..state import State
from .events import EventBus
from .workers import BackgroundWorker
from .cache import CoverCache
from . import theme as T
from .components.sidebar import Sidebar
from .pages.base import BasePage


class MeMangaApp(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Shared state
        self.config = Config()
        self.app_state = State()
        self.events = EventBus()
        self.worker = BackgroundWorker(self.events)
        self.cover_cache = CoverCache(self.config.config_dir, self.events)

        # Wire up event handlers
        self.events.subscribe("cover_fetch_request", self._on_cover_fetch_request)
        self.events.subscribe("download_complete", self._on_download_complete)
        self.events.subscribe("download_error", self._on_download_error)
        self.events.subscribe("check_complete", self._on_check_complete)
        self.events.subscribe("check_error", self._on_check_error)
        self.events.subscribe("kindle_sent", self._on_kindle_sent)

        # Window setup
        self.setWindowTitle(f"MeManga v{__version__}")
        self.resize(1100, 750)
        self.setMinimumSize(900, 600)

        # Central widget
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar(central, app=self)
        main_layout.addWidget(self._sidebar)

        # Page stack (instant page switching — no destroy/rebuild)
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # Pages registry
        self._pages: dict[str, BasePage] = {}
        self._current_page: str = ""
        self._register_pages()

        # Library is home
        self.show_page("library")

        # Event polling via QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.events.poll)
        self._timer.start(100)

        # Periodic state flush
        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self.app_state.flush)
        self._flush_timer.start(5000)

        # Auto-check on open
        if self.config.get("gui.auto_check", True):
            QTimer.singleShot(3000, self._auto_check)

    def _register_pages(self):
        from .pages.library import LibraryPage
        from .pages.search import SearchPage
        from .pages.downloads import DownloadsPage
        from .pages.settings import SettingsPage
        from .pages.detail import DetailPage
        from .pages.reader import ReaderPage

        page_classes = {
            "library": LibraryPage,
            "search": SearchPage,
            "downloads": DownloadsPage,
            "settings": SettingsPage,
            "detail": DetailPage,
            "reader": ReaderPage,
        }
        for name, cls in page_classes.items():
            page = cls(self._stack, app=self)
            self._stack.addWidget(page)
            self._pages[name] = page

    def show_page(self, name: str, **kwargs):
        if name == self._current_page and not kwargs:
            return

        if self._current_page and self._current_page in self._pages:
            self._pages[self._current_page].on_hide()

        page = self._pages.get(name)
        if page:
            self._stack.setCurrentWidget(page)
            page.on_show(**kwargs)
            self._current_page = name
            self._sidebar.set_active(name)

    def apply_theme(self, mode: str):
        """Switch between dark and light mode."""
        from PySide6.QtWidgets import QApplication
        T.apply_theme(mode)
        QApplication.instance().setStyleSheet(T.generate_stylesheet(mode))

    def reload_data(self):
        self.config = Config()
        self.app_state = State()

    # ---- Event Handlers ----

    def _on_cover_fetch_request(self, data):
        self.worker.fetch_cover(data["url"], data.get("size", (170, 210)), self.cover_cache)

    def _on_download_complete(self, data):
        title = data.get("title", "")
        chapter = data.get("chapter", "")
        path = data.get("path", "")

        self.app_state.add_notification("download", f"Downloaded {title} Ch. {chapter}")
        self.events.publish("notification_added", {})

        size_mb = 0
        if path:
            try:
                from pathlib import Path
                size_mb = Path(path).stat().st_size / (1024 * 1024)
            except Exception:
                pass
        self.app_state.add_download_history(
            title=title, chapter=str(chapter),
            fmt=self.config.output_format, path=path, size_mb=size_mb,
        )
        self.app_state.add_downloaded_chapter(title, str(chapter))
        self.app_state.clear_new_chapters(title)

    def _on_check_error(self, data):
        title = data.get("title", "")
        error = data.get("error", "Unknown")
        self.app_state.add_notification("error", f"Check failed: {title} - {error[:80]}")
        self.events.publish("notification_added", {})
        print(f"[Check Error] {title}: {error}", flush=True)

    def _on_download_error(self, data):
        title = data.get("title", "")
        error = data.get("error", "Unknown")
        self.app_state.add_notification("error", f"Failed: {title} - {error[:50]}")
        self.events.publish("notification_added", {})

    def _on_check_complete(self, data):
        results = data.get("results", [])
        total_new = sum(len(r["chapters"]) for r in results)

        for r in results:
            title = r["manga"].get("title", "")
            count = len(r["chapters"])
            if count > 0:
                self.app_state.set_new_chapters(title, count)

        if total_new > 0:
            self.app_state.add_notification("check", f"Found {total_new} new chapter(s)")
        else:
            self.app_state.add_notification("check", "No new chapters found")
        self.events.publish("notification_added", {})
        self.app_state.update_last_check(new_chapters=total_new)

    def _on_kindle_sent(self, data):
        self.app_state.add_notification("kindle", f"Sent to Kindle: {data.get('path', '').split('/')[-1]}")
        self.events.publish("notification_added", {})

    # ---- Auto-Check ----

    def _auto_check(self):
        interval = self.config.get("gui.auto_check_interval", 3600)
        last_check = self.app_state.get("last_check")

        should_check = True
        if last_check:
            try:
                last_dt = datetime.fromisoformat(last_check)
                elapsed = (datetime.now() - last_dt).total_seconds()
                if elapsed < interval:
                    should_check = False
            except (ValueError, TypeError):
                pass

        if should_check:
            manga_list = self.config.get("manga", [])
            if manga_list:
                self.worker.check_updates(manga_list, self.app_state, self.config)

    def closeEvent(self, event):
        self.app_state.flush()
        self.worker.shutdown()
        super().closeEvent(event)
