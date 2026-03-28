"""
MeManga GUI Application - Root window and page routing.
"""

from datetime import datetime

import customtkinter as ctk

from .. import __version__
from ..config import Config, get_app_password, set_app_password
from ..state import State
from .events import EventBus
from .workers import BackgroundWorker
from .cache import CoverCache
from .theme import get_palette, SIDEBAR_WIDTH, font, FONT_SIZE_LG
from .components.sidebar import Sidebar
from .pages.base import BasePage


class MeMangaApp(ctk.CTk):
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
        self.events.subscribe("kindle_sent", self._on_kindle_sent)

        # Window setup
        self.title(f"MeManga v{__version__}")
        self.geometry("1100x750")
        self.minsize(900, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        # Layout: sidebar + content
        self._sidebar = Sidebar(self, app=self)
        self._sidebar.pack(side="left", fill="y")

        self._content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._content_frame.pack(side="right", fill="both", expand=True)

        # Pages registry
        self._pages: dict[str, BasePage] = {}
        self._current_page: str = ""

        self._register_pages()

        # Show dashboard as default
        self.show_page("dashboard")

        # Start event polling and periodic state flush
        self._poll_events()
        self._periodic_flush()

        # Auto-check on open (after 3s delay)
        if self.config.get("gui.auto_check", True):
            self.after(3000, self._auto_check)

    def _register_pages(self):
        """Import and register all pages."""
        from .pages.dashboard import DashboardPage
        from .pages.library import LibraryPage
        from .pages.add_manga import AddMangaPage
        from .pages.search import SearchPage
        from .pages.downloads import DownloadsPage
        from .pages.history import HistoryPage
        from .pages.settings import SettingsPage
        from .pages.sources import SourcesPage
        from .pages.detail import DetailPage
        from .pages.reader import ReaderPage

        page_classes = {
            "dashboard": DashboardPage,
            "library": LibraryPage,
            "add": AddMangaPage,
            "search": SearchPage,
            "downloads": DownloadsPage,
            "history": HistoryPage,
            "settings": SettingsPage,
            "sources": SourcesPage,
            "detail": DetailPage,
            "reader": ReaderPage,
        }
        for name, cls in page_classes.items():
            page = cls(self._content_frame, app=self)
            self._pages[name] = page

    def show_page(self, name: str, **kwargs):
        """Switch to a page by name. Extra kwargs passed to on_show."""
        if name == self._current_page and not kwargs:
            return

        if self._current_page and self._current_page in self._pages:
            self._pages[self._current_page].on_hide()
            self._pages[self._current_page].pack_forget()

        page = self._pages.get(name)
        if page:
            page.pack(fill="both", expand=True)
            page.on_show(**kwargs)
            self._current_page = name
            self._sidebar.set_active(name)

    def on_theme_changed(self):
        palette = get_palette(ctk.get_appearance_mode().lower())
        self._sidebar.refresh_colors()
        for page in self._pages.values():
            if hasattr(page, "refresh_colors"):
                page.refresh_colors()

    def _poll_events(self):
        self.events.poll()
        self.after(100, self._poll_events)

    def reload_data(self):
        self.config = Config()
        self.app_state = State()

    # ---- Event Handlers (notifications + state updates) ----

    def _on_cover_fetch_request(self, data):
        self.worker.fetch_cover(data["url"], data.get("size", (180, 230)), self.cover_cache)

    def _on_download_complete(self, data):
        title = data.get("title", "")
        chapter = data.get("chapter", "")
        path = data.get("path", "")

        # Log notification
        self.app_state.add_notification("download", f"Downloaded {title} Ch. {chapter}")
        self.events.publish("notification_added", {})

        # Log download history
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

        # Mark chapter as downloaded in state (prevents re-downloading)
        self.app_state.add_downloaded_chapter(title, str(chapter))

        # Clear "new chapters" badge for this manga
        self.app_state.clear_new_chapters(title)

    def _on_download_error(self, data):
        title = data.get("title", "")
        error = data.get("error", "Unknown")
        self.app_state.add_notification("error", f"Failed: {title} - {error[:50]}")
        self.events.publish("notification_added", {})

    def _on_check_complete(self, data):
        results = data.get("results", [])
        total_new = sum(len(r["chapters"]) for r in results)

        # Update new_chapters badges per manga
        for r in results:
            title = r["manga"].get("title", "")
            count = len(r["chapters"])
            if count > 0:
                self.app_state.set_new_chapters(title, count)

        # Log notification
        if total_new > 0:
            self.app_state.add_notification("check", f"Found {total_new} new chapter(s)")
        else:
            self.app_state.add_notification("check", "No new chapters found")
        self.events.publish("notification_added", {})

        # Update last check
        self.app_state.update_last_check(new_chapters=total_new)

    def _on_kindle_sent(self, data):
        self.app_state.add_notification("kindle", f"Sent to Kindle: {data.get('path', '').split('/')[-1]}")
        self.events.publish("notification_added", {})

    # ---- Auto-Check ----

    def _auto_check(self):
        """Auto-check for updates on app open if enough time has passed."""
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

    def _periodic_flush(self):
        """Flush dirty state to disk every 5 seconds."""
        self.app_state.flush()
        self.after(5000, self._periodic_flush)

    def destroy(self):
        self.app_state.flush()  # Final flush before exit
        self.worker.shutdown()
        super().destroy()
