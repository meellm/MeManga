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

        # Backfill missing covers a few seconds after launch. Many older
        # entries were added before the MangaDex fallback existed and still
        # show blank cards; this pass populates them quietly in the
        # background.
        QTimer.singleShot(5000, self._backfill_missing_covers)

    def _register_pages(self):
        from .pages.library import LibraryPage
        from .pages.search import SearchPage
        from .pages.downloads import DownloadsPage
        from .pages.settings import SettingsPage
        from .pages.detail import DetailPage
        from .pages.reader import ReaderPage
        from .pages.sources import SourcesPage

        page_classes = {
            "library": LibraryPage,
            "search": SearchPage,
            "downloads": DownloadsPage,
            "sources": SourcesPage,
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

        # Badge update depends on mode:
        #   auto   → batch download flushes the whole badge at once
        #   manual → user picked one chapter; just decrement
        if self._get_manga_mode(title) == "manual":
            self.app_state.decrement_new_chapters(title)
        else:
            self.app_state.clear_new_chapters(title)

    def _resolve_external_threshold(self, manga, threshold_raw, all_chapters) -> bool:
        """Walk cached chapters and mark anything below the user's stated
        "I'm on chapter N" as external (read elsewhere). Bumps last_chapter
        so future check_for_updates calls don't surface the same chapters as
        new. Returns True if config was mutated (sentinel popped).
        """
        title = manga.get("title", "")
        try:
            threshold = float(str(threshold_raw))
        except (ValueError, TypeError):
            # Unparseable sentinel — drop it so we don't keep retrying.
            self._pop_external_threshold(title)
            return True

        marked_max = None
        for c in all_chapters:
            try:
                num_f = float(c.number)
            except (ValueError, TypeError):
                continue
            if num_f < threshold:
                self.app_state.mark_external_chapter(title, c.number)
                if marked_max is None or num_f > marked_max:
                    marked_max = num_f

        # Bump last_chapter so subsequent checks treat these as already-seen.
        # Format as int when whole-numbered ("47" not "47.0") to match how
        # chapter numbers come back from scrapers.
        if marked_max is not None:
            if marked_max == int(marked_max):
                last_str = str(int(marked_max))
            else:
                last_str = str(marked_max)
            self.app_state.set_last_chapter(title, last_str)

        # One-shot: pop the sentinel from config so we don't redo this on
        # every subsequent check.
        return self._pop_external_threshold(title)

    def _pop_external_threshold(self, title: str) -> bool:
        manga_list = self.config.get("manga", [])
        mutated = False
        for entry in manga_list:
            if entry.get("title") == title and "external_threshold" in entry:
                entry.pop("external_threshold", None)
                entry.pop("external_threshold_attempts", None)
                mutated = True
        return mutated

    def _increment_threshold_attempts(self, title: str) -> bool:
        """Bump the attempt counter for the external_threshold sentinel.

        Returns True if the config was mutated (caller should save).
        After 2 failed attempts (i.e. checks where the scraper returned
        no chapters), pops the sentinel so we don't keep retrying a
        permanently-broken source.
        """
        if not title:
            return False
        manga_list = self.config.get("manga", [])
        for entry in manga_list:
            if entry.get("title") != title or "external_threshold" not in entry:
                continue
            attempts = int(entry.get("external_threshold_attempts", 0)) + 1
            if attempts >= 2:
                entry.pop("external_threshold", None)
                entry.pop("external_threshold_attempts", None)
            else:
                entry["external_threshold_attempts"] = attempts
            return True
        return False

    def _get_manga_mode(self, title: str) -> str:
        """Look up a manga's mode from config. Defaults to 'auto' for legacy entries."""
        for m in self.config.get("manga", []):
            if m.get("title") == title:
                return m.get("mode", "auto")
        return "auto"

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
        config_dirty = False

        for r in results:
            manga = r["manga"]
            title = manga.get("title", "")
            count = len(r["chapters"])
            if count > 0:
                self.app_state.set_new_chapters(title, count)

            # Cache the full chapter list from the primary source so the
            # Detail page can render every chapter as Read/Download without
            # re-scraping. Done for BOTH modes — lets users freely toggle
            # auto↔manual without losing visibility.
            all_chapters = r.get("all_chapters") or []
            if all_chapters:
                cached = [
                    {
                        "number": c.number,
                        "title": getattr(c, "title", "") or "",
                        "source": getattr(c, "source", ""),
                        "source_url": getattr(c, "source_url", ""),
                        "is_backup": getattr(c, "is_backup", False),
                        "url": c.url,
                    }
                    for c in all_chapters
                ]
                self.app_state.set_available_chapters(title, cached)

            # Resolve "I'm on chapter N" onboarding sentinel. Done after
            # caching available_chapters so we always have something to walk.
            # One-shot: pop the sentinel and re-save config.
            threshold_raw = manga.get("external_threshold")
            if threshold_raw is not None:
                if all_chapters:
                    if self._resolve_external_threshold(manga, threshold_raw, all_chapters):
                        config_dirty = True
                else:
                    # No chapters returned (scrape failure or empty source).
                    # Track attempt count so a permanently-broken scraper
                    # doesn't leave the sentinel forever; pop after the
                    # second failure to keep config clean.
                    if self._increment_threshold_attempts(manga.get("title", "")):
                        config_dirty = True

        if config_dirty:
            # Persist the popped sentinels and the freshly-set last_chapter.
            self.config.set("manga", self.config.get("manga", []))
            self.config.save()

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

    def _backfill_missing_covers(self):
        """Walk the library and try to populate covers for entries that
        don't have one yet, via the MangaDex fallback. One worker thread
        polls titles serially with a small sleep between requests so we
        don't hammer the API.

        Skips entries previously marked ``cover_lookup_failed`` so we
        don't re-query MangaDex on every launch for titles it doesn't
        carry. The flag clears on title rename (Detail → Edit).
        """
        manga_list = self.config.get("manga", [])
        # Skip entries that have a cover OR that we already tried and missed.
        missing = [
            m for m in manga_list
            if not m.get("cover_url") and not m.get("cover_lookup_failed")
        ]
        if not missing:
            return

        titles = [m.get("title", "") for m in missing if m.get("title")]
        if not titles:
            return

        def _task():
            import time
            from .cover_fallback import fetch_mangadex_cover

            for t in titles:
                try:
                    cover = fetch_mangadex_cover(t)
                except Exception:
                    cover = None

                # Mutate + save under the config lock so we don't race
                # with the UI thread editing the same entry.
                def _mutate(entry, _cover=cover):
                    if _cover:
                        if entry.get("cover_url"):
                            return False  # someone else already filled it
                        entry["cover_url"] = _cover
                        entry.pop("cover_lookup_failed", None)
                        return True
                    # Negative result — remember so we don't re-query
                    # this title on every future launch.
                    entry["cover_lookup_failed"] = True
                    return True

                updated = self.config.update_manga(t, _mutate)
                if updated and cover:
                    # Tell the Library page to repaint — otherwise the new
                    # cover URL just sits in config until the user navigates
                    # away and back.
                    self.events.publish("library_updated", {"title": t})

                # Small throttle between API calls.
                time.sleep(1.0)

        self.worker.submit_task(_task)

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
