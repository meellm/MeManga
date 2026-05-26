"""
Search page - Search across multiple manga sources.
"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QWidget,
)
from PySide6.QtCore import Qt
from .base import BasePage
from .. import theme as T
from ..components.search_result import SearchResultRow
from ..components.toast import Toast


# Sources we know are broken or dead — skip them in search so we don't
# waste a worker slot waiting for a timeout. Verified 2026-05 via the
# live probe in /tmp/probe_search.py.
#
# Reasons:
#   - SHUTDOWN:     site shows a "shutdown" page (mangasee123)
#   - DEAD_DNS:     domain resolves nowhere, every request times out
#   - REPLACED:     domain forwards to an unrelated site (mangakakalot →
#                   spinzywheel.com gambling page)
#   - NEEDS_JS_API: site has an SPA + client-side search API that the
#                   plain HTML doesn't expose (asurascans, mgeko.cc)
BROKEN_SEARCH_SOURCES = {
    # SHUTDOWN
    "mangasee123.com",            # serves a "shutdown" image
    # DEAD_DNS / unreachable
    "mangareader.to",
    "chapmanganato.to",
    "readmanganato.com",
    "manganato.com",
    "mangakakalot.com",           # → spinzywheel.com
    "mangakakalot.to",
    "manga4life.com",             # ex-mangasee mirror, also dead
    "mangalife.us",
    # REPLACED / regional block / chronic timeout
    "mangatown.com", "www.mangatown.com",
    "manhwa18.cc",
    "mangafreak.me", "mangafreak.ws", "ww2.mangafreak.me",
    "bato.to", "batoto.to",
    # NEEDS_JS_API — static HTML returns 0 hits, real search is client-side
    "asuracomic.net", "asurascans.com", "asuratoon.com",
    "mgeko.cc",
    "mangabolt.com",
    "truemanga.com", "mangamonk.com",
    "mangahub.us",                # search endpoint requires headless JS
    "hivetoons.org", "hivetoon.com",
    "isekaiscan.com",
    "zinmanga.com",
    "kunmanga.com",
    "flamecomics.xyz",            # SPA, search via API only
    # Strong Cloudflare interactive challenge — even cloudscraper gets a
    # 403. Would need a real headless browser. Drops them from search;
    # user can still add manga from these by URL.
    "manhuafast.com",
    "manhuaus.org",
    # Manganato.gg also serves the Cloudflare "Just a moment..." page
    # to plain requests + Playwright without a deep wait. Its existing
    # Playwright scraper times out at the 60s mark in practice.
    "manganato.gg",
}


def _compute_search_sources(app) -> list[str]:
    """Build the source list for the search worker.

    The previous behaviour searched every supported source (~290), most
    of which are template-based single-manga sites (dddmanga.com,
    chainsawdevil.com, …). Their `search()` is hard-wired to their one
    manga's keywords, so searching "Blue Lock" against them is pure
    wasted network. We now restrict by default to:

      1. Real aggregators (general-purpose sources, hand-curated list).
      2. Every source the user has in their library — they've proven
         useful for this user already.
      3. Minus anything disabled on the Sources page.
      4. Minus sites that are known dead / not searchable from plain
         HTML (BROKEN_SEARCH_SOURCES — verified against the live
         probe; updating that set is the supported way to re-enable a
         source once its scraper is fixed).
    """
    from memanga.scrapers import SCRAPERS
    try:
        from memanga.scrapers.registry import TEMPLATE_SCRAPERS
    except Exception:
        TEMPLATE_SCRAPERS = {}

    disabled = set(app.config.get("sources.disabled", []) or [])
    library: set[str] = set()
    for m in app.config.get("manga", []):
        for s in m.get("sources", []) or []:
            d = s.get("source", "")
            if d:
                library.add(d)
        d = m.get("source", "")
        if d:
            library.add(d)

    # Real aggregators: anything in SCRAPERS that's NOT a template-based
    # single-manga site. Template scrapers' search() only matches their
    # configured keywords, so we'd just be probing the network for no
    # reason.
    template_domains = set(TEMPLATE_SCRAPERS.keys())
    aggregators = {d for d in SCRAPERS.keys() if d not in template_domains}

    # De-dupe canonical hostnames — many aliases map to the same scraper
    # class (e.g. tcbscans.com / tcbscans.me / tcbonepiecechapters.com
    # all hit the same TCBScansScraper). We can just collapse via
    # set-of-classes lookup keyed on identity.
    canonical: dict = {}
    for d in (library | aggregators):
        if d in disabled:
            continue
        if d in BROKEN_SEARCH_SOURCES:
            continue
        cls = SCRAPERS.get(d)
        if cls is None:
            continue
        key = id(cls)
        # Prefer library domain over alias domain when both exist.
        if key not in canonical or d in library:
            canonical[key] = d
    return sorted(canonical.values())


class SearchPage(BasePage):
    """Multi-source manga search."""

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._results = []
        self._result_widgets = []
        # Per-source progress counters reset on each new search.
        self._sources_total = 0
        self._sources_done = 0
        self._sources_failed: list[tuple[str, str]] = []
        self._build()

        self.app.events.subscribe("search_result", self._on_result)
        self.app.events.subscribe("search_complete", self._on_complete)
        self.app.events.subscribe("search_started", self._on_started)
        self.app.events.subscribe("search_source_done", self._on_source_done)
        self.app.events.subscribe("search_source_failed", self._on_source_failed)
        self.app.events.subscribe("search_chapter_count", self._on_chapter_count)
        # Reflect connectivity in the status line so the user always
        # knows why the search button does nothing.
        self.app.events.subscribe("network_offline", lambda _d: self._on_offline())
        self.app.events.subscribe("network_online", lambda _d: self._on_online())

    def _on_offline(self):
        if hasattr(self, "_status_label"):
            self._status_label.setText(
                "You're offline — search resumes when the connection comes back."
            )

    def _on_online(self):
        if hasattr(self, "_status_label"):
            self._status_label.setText("Type a title and press Enter to search.")

    def _build(self):
        from PySide6.QtWidgets import QFrame
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        header_w = QWidget()
        h_layout = QVBoxLayout(header_w)
        h_layout.setContentsMargins(32, 24, 32, 18)
        h_layout.setSpacing(4)

        top_row = QHBoxLayout()
        title = QLabel("Search")
        title.setProperty("role", "h1")
        top_row.addWidget(title)
        top_row.addStretch(1)
        h_layout.addLayout(top_row)

        meta = QLabel("Searching across enabled sources")
        meta.setProperty("role", "meta")
        h_layout.addWidget(meta)
        root.addWidget(header_w)

        sep = QFrame()
        sep.setObjectName("page_header_divider")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # Body wrapper
        body_w = QWidget()
        layout = QVBoxLayout(body_w)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.setSpacing(T.PAD_SM)
        root.addWidget(body_w, 1)

        # ── Hero card with search input (matches HTML spec.screens.search.hero)
        hero = QFrame()
        hero.setProperty("role", "card")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(22, 22, 22, 22)
        hero_l.setSpacing(14)

        # Inner search bar: bg_0 container, leading magnifier icon,
        # accent Search button on the right. (⌘K kbd-hint chip removed
        # per user request — Ctrl/Cmd+K still focuses this input,
        # it's just no longer surfaced visually.)
        bar_wrap = QFrame()
        bar_wrap.setProperty("role", "card_2")
        bar = QHBoxLayout(bar_wrap)
        bar.setContentsMargins(16, 4, 4, 4)
        bar.setSpacing(8)

        from ..assets.icons import icon as _ic
        from PySide6.QtCore import QSize
        mag_lbl = QLabel()
        mag_lbl.setPixmap(_ic("search", T.tokens()["text.t_3"], 18).pixmap(QSize(18, 18)))
        bar.addWidget(mag_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Search for manga across enabled sources…")
        self._search_entry.setFixedHeight(40)
        self._search_entry.setStyleSheet("border: none; background: transparent; font-size: 13pt;")
        self._search_entry.returnPressed.connect(self._do_search)
        bar.addWidget(self._search_entry, 1)

        self._search_btn = QPushButton("Search")
        self._search_btn.setProperty("variant", "primary")
        self._search_btn.setFixedHeight(34)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.clicked.connect(self._do_search)
        bar.addWidget(self._search_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        hero_l.addWidget(bar_wrap)

        # Status / hint under the input
        self._status_label = QLabel("Type a title and press Enter to search.")
        self._status_label.setProperty("role", "hint")
        hero_l.addWidget(self._status_label)

        # (Recent searches chip row removed per user request.)

        layout.addWidget(hero)
        layout.addSpacing(8)

        # Results area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._results_layout = QVBoxLayout(self._scroll_content)
        self._results_layout.setSpacing(2)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

    def on_show(self, **kwargs):
        # No-op — recent searches chip row was removed.
        pass

    def _do_search(self):
        query = self._search_entry.text().strip()
        if not query:
            return

        # Clear old results
        for w in self._result_widgets:
            try:
                w.deleteLater()
            except Exception:
                pass
        self._result_widgets.clear()
        self._results.clear()
        self._sources_done = 0
        self._sources_failed = []

        # Refuse the request locally when we know we're offline,
        # rather than handing it to the worker just to have it
        # publish search_complete with no results. Gives the user
        # an immediate reason.
        net = getattr(self.app, "network", None)
        if net is not None and not net.is_online:
            self._status_label.setText(
                "You're offline — connect to the internet to search."
            )
            return

        sources = _compute_search_sources(self.app)
        self._sources_total = len(sources)
        if not sources:
            self._status_label.setText(
                "No sources enabled — enable some on the Sources tab."
            )
            return
        self._status_label.setText(
            f"Searching {len(sources)} source(s)…  0 done · 0 results"
        )
        self.app.worker.search_manga(query, sources)

    def _on_started(self, data):
        total = data.get("total_sources", self._sources_total)
        self._status_label.setText(
            f"Searching '{data['query']}' across {total} sources…  0 done"
        )
        self._search_btn.setEnabled(False)

    def _on_result(self, data):
        self._results.append(data)
        row = SearchResultRow(self._scroll_content, result=data, on_add=self._add_result)
        # Insert at the correct popularity-sorted position so MangaDex
        # results stay above WeebCentral results regardless of which
        # source's network was fastest. The list is built incrementally
        # so most cases are O(n) anyway — no perf concern below 1000
        # results.
        from ..workers import source_rank
        new_rank = source_rank(data.get("source", ""))
        insert_at = self._results_layout.count()
        for i, existing in enumerate(self._result_widgets):
            if source_rank(existing._result.get("source", "")) > new_rank:
                insert_at = i
                break
        self._results_layout.insertWidget(insert_at, row)
        self._result_widgets.insert(insert_at, row)
        self._update_progress_label()

        # Fire-and-forget chapter-count probe so the chip can replace
        # the "—" once the scraper finishes get_chapters(). The worker
        # uses a 3-slot pool so these naturally serialise behind any
        # active download.
        try:
            self.app.worker.count_chapters(data.get("source", ""),
                                             data.get("url", ""))
        except Exception:
            pass

    def _on_chapter_count(self, data):
        """search_chapter_count → find the matching row + update its chip."""
        url = data.get("url", "")
        count = data.get("count", -1)
        if not url:
            return
        for row in self._result_widgets:
            if row.url == url:
                row.set_chapter_count(count)
                break

    def _on_source_done(self, data):
        self._sources_done += 1
        self._update_progress_label()

    def _on_source_failed(self, data):
        self._sources_done += 1
        self._sources_failed.append(
            (data.get("source", "?"), data.get("error", "")[:80])
        )
        self._update_progress_label()

    def _update_progress_label(self):
        done = self._sources_done
        total = self._sources_total or 1
        ok = done - len(self._sources_failed)
        n = len(self._results)
        parts = [f"{done}/{total} sources",
                 f"{n} result{'s' if n != 1 else ''}"]
        if self._sources_failed:
            parts.append(f"{len(self._sources_failed)} failed")
        self._status_label.setText("  ·  ".join(parts))

    def _on_complete(self, data):
        self._search_btn.setEnabled(True)
        # Worker tagged the response as offline → tell the user that's
        # why nothing came back, not "no results".
        if data.get("offline"):
            self._status_label.setText(
                "You're offline — search resumes when the connection comes back."
            )
            return
        count = len(self._results)
        if count == 0:
            msg = "No results found. Try a different query."
            if self._sources_failed:
                # Surface the first couple of failed source names so the
                # user knows which scrapers are broken.
                preview = ", ".join(s for s, _ in self._sources_failed[:5])
                more = (f" (+{len(self._sources_failed) - 5} more)"
                        if len(self._sources_failed) > 5 else "")
                msg += f"\nFailed: {preview}{more}"
            self._status_label.setText(msg)
        else:
            failed_n = len(self._sources_failed)
            ok_n = self._sources_done - failed_n
            suffix = f"  ·  {failed_n} failed" if failed_n else ""
            self._status_label.setText(
                f"{count} results from {ok_n} source(s){suffix}"
            )

    def _add_result(self, result):
        """Open Add Manga dialog with prefilled data from search result."""
        from .add_manga import AddMangaDialog
        dialog = AddMangaDialog(self, self.app, prefill={
            "title": result.get("title", ""),
            "url": result.get("url", ""),
        })
        dialog.exec()
