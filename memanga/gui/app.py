"""
MeManga GUI Application - PySide6 MainWindow with sidebar + QStackedWidget.
"""

from datetime import datetime

from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QShortcut, QKeySequence

from .. import __version__
from ..config import Config
from ..state import State
from .events import EventBus
from .workers import BackgroundWorker
from .cache import CoverCache
from .network_status import NetworkMonitor
from . import theme as T
from .components.sidebar import Sidebar
from .components.offline_banner import OfflineBanner
from .pages.base import BasePage


class MeMangaApp(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Shared state
        self.config = Config()
        self.app_state = State()
        self._seed_default_sources_if_first_launch()
        self.events = EventBus()
        self.worker = BackgroundWorker(self.events)
        # Honor the persisted concurrency setting on startup so the slider
        # in Settings → General actually takes effect across launches.
        try:
            self.worker._max_concurrent_downloads = int(
                self.config.get("gui.max_concurrent_downloads", 2)
            )
        except Exception:
            pass
        self.cover_cache = CoverCache(self.config.config_dir, self.events)
        # Cover URLs we already tried to replace after a failed fetch —
        # once per URL per session, see _on_cover_load_failed.
        self._cover_fallback_attempted: set = set()

        # Centralised network status — probes connectivity in a daemon
        # thread, publishes `network_online` / `network_offline` events.
        # Workers and pages subscribe to short-circuit / disable
        # network-bound actions while offline.
        self.network = NetworkMonitor(self.events)
        # Hand the same monitor to the worker so its entry points
        # (search, check, download, cover fetch) can bail fast when
        # offline instead of timing out per-source.
        self.worker.network = self.network
        self.network.start()

        # Wire up event handlers
        self.events.subscribe("cover_fetch_request", self._on_cover_fetch_request)
        self.events.subscribe("cover_loaded", self._on_cover_load_failed)
        self.events.subscribe("download_complete", self._on_download_complete)
        self.events.subscribe("download_error", self._on_download_error)
        self.events.subscribe("check_complete", self._on_check_complete)
        self.events.subscribe("check_error", self._on_check_error)
        self.events.subscribe("kindle_sent", self._on_kindle_sent)

        # Window setup
        self.setWindowTitle(f"MeManga v{__version__}")
        self.resize(1100, 750)
        self.setMinimumSize(900, 600)

        # Explicit window icon — QApplication.setWindowIcon is the
        # global default but on Windows individual top-level windows
        # sometimes don't inherit it (Qt quirk around HICON vs
        # taskbar icon), so set it on this window directly too.
        try:
            from . import _load_app_icon
            _icon = _load_app_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            pass

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

        # Main column = offline banner (top, hidden when online) +
        # page stack. We wrap them in a vertical QWidget so the banner
        # can sit above the stack without disturbing the sidebar.
        from PySide6.QtWidgets import QVBoxLayout
        main_col = QWidget()
        main_col.setObjectName("main_area")
        col_layout = QVBoxLayout(main_col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)

        self._offline_banner = OfflineBanner(
            main_col, events=self.events,
            on_retry=self.network.force_recheck,
        )
        col_layout.addWidget(self._offline_banner)

        # Page stack (instant page switching — no destroy/rebuild)
        self._stack = QStackedWidget()
        col_layout.addWidget(self._stack, 1)
        main_layout.addWidget(main_col, 1)

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

        # When connectivity returns after a drop, retry the things we
        # would have done on startup — silently kick off another
        # auto-check + cover backfill so the library catches up.
        self.events.subscribe("network_online",
                                lambda _d: self._on_network_recovered())

        # ── Global shortcuts ──
        # Ctrl/Cmd+K from anywhere → focus the Search input.
        # QKeySequence("Ctrl+K") maps to ⌘K on macOS automatically.
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._search_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._search_shortcut.activated.connect(self._focus_search)

    def _focus_search(self):
        """Jump to the Search page and put focus in its input."""
        self.show_page("search")
        page = self._pages.get("search")
        if page and hasattr(page, "_search_entry"):
            page._search_entry.setFocus()
            page._search_entry.selectAll()

    def _register_pages(self):
        from .pages.library import LibraryPage
        from .pages.search import SearchPage
        from .pages.downloads import DownloadsPage
        from .pages.settings import SettingsPage
        from .pages.detail import DetailPage
        from .pages.reader import ReaderPage
        from .pages.sources import SourcesPage
        from .pages.notifications import NotificationsPage

        page_classes = {
            "library":       LibraryPage,
            "search":        SearchPage,
            "downloads":     DownloadsPage,
            "notifications": NotificationsPage,
            "sources":       SourcesPage,
            "settings":      SettingsPage,
            "detail":        DetailPage,
            "reader":        ReaderPage,
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

    def _on_cover_load_failed(self, data):
        """A stored cover URL no longer downloads (dead CDN link,
        hotlink block we can't satisfy, non-image response). Try to
        replace it via the MangaDex fallback so the card doesn't keep
        a permanent placeholder — `_backfill_missing_covers` only
        handles entries with no URL at all. Tried at most once per
        URL per session; repeated paints of the same broken cover
        shouldn't re-query MangaDex.
        """
        if not data.get("error") or data.get("offline"):
            return
        url = data.get("url") or ""
        if not url or url in self._cover_fallback_attempted:
            return
        self._cover_fallback_attempted.add(url)
        titles = [
            m.get("title") for m in self.config.get("manga", [])
            if m.get("title") and m.get("cover_url") == url
        ]
        if not titles:
            return  # transient cover (search result) — nothing to repair

        def _task():
            from .cover_fallback import fetch_mangadex_cover
            for t in titles:
                try:
                    cover = fetch_mangadex_cover(t)
                except Exception:
                    cover = None
                if not cover or cover == url:
                    continue

                def _mutate(entry, _cover=cover):
                    if entry.get("cover_url") != url:
                        return False  # someone else already replaced it
                    entry["cover_url"] = _cover
                    return True

                if self.config.update_manga(t, _mutate):
                    self.events.publish(
                        "library_updated", {"title": t, "action": "cover"}
                    )

        self.worker.submit_task(_task)

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
            self.events.publish("notification_added", {})
        # No-news checks are silent — adding a "No new chapters found"
        # notification on every auto-check makes the sidebar bell badge
        # bounce back to "1" right after Mark all read.
        self.app_state.update_last_check(new_chapters=total_new)
        # Still nudge the sidebar so the "Synced just now" timestamp
        # refreshes even when there's nothing new.
        self.events.publish("check_complete_silent", {})

    def _on_kindle_sent(self, data):
        self.app_state.add_notification("kindle", f"Sent to Kindle: {data.get('path', '').split('/')[-1]}")
        self.events.publish("notification_added", {})

    # ---- First-launch source seeding ----

    def _seed_default_sources_if_first_launch(self):
        """Pre-tick only the 15 most popular working sources on a
        fresh install.

        Without this, a brand-new user opens the app and every supported
        source is enabled — so the first multi-source search probes
        100+ sites and takes minutes. Seeding ships with a curated
        working subset enabled and leaves the long tail disabled but
        toggleable from the Sources tab.

        Guarded by `sources.first_run_seeded` so we ONLY run once,
        ever. Existing users with their own selection (or veteran
        users who liked the everything-on default) never get their
        config overwritten by a future re-launch.
        """
        if self.config.get("sources.first_run_seeded"):
            return
        try:
            from ..scrapers import (
                SCRAPERS, DEFAULT_ENABLED_SOURCES,
            )
            from ..scrapers.registry import TEMPLATE_SCRAPERS
        except Exception:
            # If anything goes wrong loading the curated list, just
            # mark seeded so we don't keep retrying forever — the
            # app stays in the "everything enabled" legacy mode.
            self.config.set("sources.first_run_seeded", True)
            self.config.save()
            return

        # We disable everything that isn't in DEFAULT_ENABLED_SOURCES,
        # but we also keep TEMPLATE single-manga sites enabled. Those
        # are excluded from the multi-source search sweep anyway and
        # users add them by URL — disabling them would only show
        # confusing red dots all over the Sources tab for sources
        # the user never sees in search.
        enabled = set(DEFAULT_ENABLED_SOURCES)
        template_domains = set(TEMPLATE_SCRAPERS.keys())
        disabled = sorted(
            d for d in SCRAPERS.keys()
            if d not in enabled and d not in template_domains
        )
        self.config.set("sources.disabled", disabled)
        self.config.set("sources.first_run_seeded", True)
        self.config.save()

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
        # Bail when offline — we'd just mark every title as failed,
        # which the on-recovery hook then has to clean up. The
        # `network_online` subscriber re-runs this when we come back.
        if hasattr(self, "network") and not self.network.is_online:
            return
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

    def _on_network_recovered(self):
        """Connectivity came back — silently retry the startup-time
        actions the user would otherwise have to trigger manually.

        Notifies the rest of the app via existing events so library /
        sources pages re-render.
        """
        # Toast so the user knows the app picked up the recovery.
        try:
            from .components.toast import Toast
            page = self._stack.currentWidget() if hasattr(self, "_stack") else None
            if page is not None:
                Toast(page, "Back online", kind="success")
        except Exception:
            pass
        # Re-run the deferred startup actions.
        QTimer.singleShot(500, self._backfill_missing_covers)
        if self.config.get("gui.auto_check", True):
            QTimer.singleShot(800, self._auto_check)

    def _auto_check(self):
        # Network gate — the worker would also short-circuit, but
        # bailing here avoids advancing last_check and creating an
        # empty "0 new chapters" event.
        if hasattr(self, "network") and not self.network.is_online:
            return
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
        if hasattr(self, "network"):
            self.network.stop()
        super().closeEvent(event)
