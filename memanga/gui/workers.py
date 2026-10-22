"""
Background worker for long-running operations.
Wraps ThreadPoolExecutor; publishes events to the EventBus.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .events import EventBus

logger = logging.getLogger(__name__)


# Relevance filter and popularity ranking are shared with the CLI's
# `memanga search` — single source of truth lives in memanga.search.
# Re-imported under the historical names so existing callers (and
# tests) keep working.
from ..search import (  # noqa: E402
    result_matches_query as _result_matches_query,
    source_rank,
    sort_sources_by_popularity,
)
from ..scrapers import POPULAR_SOURCES as SOURCE_POPULARITY  # noqa: E402,F401

# Same body sniffing the scrapers use before writing an image to disk:
# caching a non-image body (an HTML block page served with 200) would
# leave the cover permanently blank — the disk cache file exists, so
# the URL is never refetched.
from ..scrapers.base import looks_like_image  # noqa: E402,F401


# ─────────────────────────────────────────────────────────────────────
# Cover fetch helpers — some cover CDNs hotlink-protect their images:
# they refuse the request (or answer 200 with an HTML block page)
# unless it carries the source site's Referer. Scrapers send these
# headers in their own download_image(), but the GUI fetches covers
# straight from the stored URL, outside any scraper — so the worker
# needs its own marker → referer table. Keyed on a stable URL
# fragment: MangaPill's CDN hostname rotates
# (cdn.readdetectiveconan.com at the time of writing) but the
# /file/mangapill/ path prefix does not.
# ─────────────────────────────────────────────────────────────────────


_COVER_REFERERS = (
    ("/file/mangapill/", "https://mangapill.com/"),
    ("mangapill.com", "https://mangapill.com/"),
    # MangaHere hotlink-checks its cover CDN: fmcdn.mangahere.com
    # answers a refererless request with a 403 HTML page, so the cover
    # never renders (issue #174). Matched on the CDN host, not on
    # "mangahere", so mangahere.onl (a different site on mghcdn) is
    # unaffected.
    ("fmcdn.mangahere.com", "https://www.mangahere.cc/"),
)

_COVER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def cover_request_headers(url: str) -> Dict[str, str]:
    """Headers for a cover fetch, with a Referer for CDNs known to
    require one."""
    headers = {"User-Agent": _COVER_USER_AGENT}
    for marker, referer in _COVER_REFERERS:
        if marker in url:
            headers["Referer"] = referer
            break
    return headers


class BackgroundWorker:
    """Runs download/check/search tasks in background threads."""

    def __init__(self, event_bus: EventBus):
        self._events = event_bus
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="memanga-worker")
        self._download_queue: list = []
        self._active_downloads: int = 0
        self._max_concurrent_downloads = 2
        self._paused: bool = False
        self._lock = threading.Lock()
        self._cancel_flags: Dict[str, threading.Event] = {}
        # Each call to search_manga() bumps _search_seq. Every event the
        # search task publishes carries that seq, and the UI drops
        # events whose seq doesn't match its current search. Without
        # this, results from "Oshi No Ko" would bleed into a
        # subsequent "One Piece" search because the old worker's
        # scrapers are still running.
        self._search_seq: int = 0
        self._search_cancel: Optional[threading.Event] = None
        self._search_pool: Optional[ThreadPoolExecutor] = None
        self._search_lock = threading.Lock()
        # Dedicated pool for chapter-count probes — separate from
        # the 3-slot shared pool so a busy download queue doesn't
        # block chips from appearing, and they don't serialise
        # excessively behind each other either.
        self._count_pool = ThreadPoolExecutor(
            max_workers=6, thread_name_prefix="chapter-count",
        )
        # Optional NetworkMonitor — wired up by MeMangaApp after both
        # the worker and the monitor exist. When set, network-bound
        # entry points short-circuit (with a friendly event) instead
        # of timing out per-source against an unreachable host.
        self.network = None

    def _is_offline(self) -> bool:
        """True only when we've actively confirmed we're offline.
        Defaults to optimistic (online) if no monitor is wired —
        keeps existing test setups working.
        """
        return self.network is not None and not self.network.is_online

    def shutdown(self):
        """Clean up the thread pool."""
        self._shutdown = True
        self._pool.shutdown(wait=False)
        try:
            self._count_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        # Tear down any in-flight search so its threads don't outlive
        # the app and try to publish into a destroyed event bus.
        with self._search_lock:
            cancel = self._search_cancel
            pool = self._search_pool
            self._search_cancel = None
            self._search_pool = None
        if cancel is not None:
            cancel.set()
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def submit_task(self, fn):
        """Run a fire-and-forget callable on the shared worker pool.

        Use this for one-off background work (e.g. cover backfill) so
        callers don't have to reach into ``_pool`` directly.

        Becomes a no-op after :meth:`shutdown` — guards against
        QTimer-driven callbacks firing during application close (and
        keeps tests that re-use a process across many windows clean).
        """
        return self._safe_submit(fn)

    def _safe_submit(self, fn, *args, **kwargs):
        """Internal pool.submit wrapper that becomes a no-op after
        shutdown instead of raising ``RuntimeError``."""
        if getattr(self, "_shutdown", False):
            return None
        try:
            return self._pool.submit(fn, *args, **kwargs)
        except RuntimeError:
            return None

    # ------------------------------------------------------------------
    # Cover fetching
    # ------------------------------------------------------------------

    def fetch_cover(self, url: str, size=(180, 230), cache=None):
        """Download a cover image in the background and save the raw
        bytes to the cover cache. The GUI promotes them to QPixmap
        lazily, on the main thread, when a card actually paints."""
        # Skip silently when offline — covers are best-effort and we
        # don't want the cover backfill to flood the network as soon
        # as the user opens the library while their wifi is down.
        # When they come back online, the next library refresh kicks
        # off another round.
        if self._is_offline():
            if cache:
                cache.mark_failed(url)
            self._events.publish("cover_loaded", {"url": url, "error": True,
                                                    "offline": True})
            return None

        def _task():
            try:
                resp = requests.get(url, timeout=15,
                                    headers=cover_request_headers(url))
                resp.raise_for_status()
                if not looks_like_image(
                        resp.content, resp.headers.get("Content-Type", "")):
                    raise ValueError("response body is not an image")
                if cache:
                    cache.save_to_disk(url, resp.content)
            except Exception:
                if cache:
                    cache.mark_failed(url)
                self._events.publish("cover_loaded", {"url": url, "error": True})

        self._safe_submit(_task)

    # ------------------------------------------------------------------
    # Chapter checking
    # ------------------------------------------------------------------

    def check_updates(self, manga_list: list, state, config,
                      force: bool = False, queue_all: bool = False,
                      request_id=None):
        """Check for new chapters across a list of manga.

        The library-wide sweep only checks manga whose status is
        ``reading`` — there's no point polling something that is on hold,
        dropped or completed. Explicit per-manga actions (the Detail
        page's "Check updates" button, a context-menu check, a download
        request) pass ``force=True`` so the requested manga is always
        checked regardless of its status.

        ``queue_all`` marks the check as an explicit download request
        ("Download All" / "Download from chapter"). It is echoed on the
        ``check_complete`` event so the Downloads page queues the resolved
        chapters for every manga regardless of mode — manual-mode manga
        are otherwise only surfaced, never auto-queued.
        """
        def _complete_payload(results, **extra):
            payload = {"results": results, **extra}
            if request_id is not None:
                payload["request_id"] = request_id
            return payload

        def _error_payload(title, error):
            # Issue #107: errors carry the caller's request_id too, so a
            # correlated background check (the reader prefetch fallback)
            # can be kept out of the user-facing error surfaces while
            # ordinary checks keep their notifications/toasts.
            payload = {"title": title, "error": error}
            if request_id is not None:
                payload["request_id"] = request_id
            return payload

        def _progress_payload(current, total, title):
            payload = {"current": current, "total": total, "title": title}
            if request_id is not None:
                payload["request_id"] = request_id
            return payload

        # Short-circuit when we know we're offline. Every per-manga
        # check_for_updates() would otherwise burn 30 s × 3 retries
        # against an unreachable host.
        if self._is_offline():
            self._events.publish("check_error", _error_payload(
                "Offline", "Can't check for updates while offline."))
            self._events.publish("check_complete", _complete_payload([]))
            return
        logger.info("Checking %d manga for updates", len(manga_list))
        for m in manga_list:
            logger.debug("  '%s' source=%s status=%s", m.get('title'),
                         m.get('source', ''), m.get('status', 'reading'))

        def _task():
            try:
                from ..downloader import check_for_updates
            except Exception as e:
                logger.exception("Failed to import downloader: %s", e)
                self._events.publish(
                    "check_error", _error_payload("Import Error", str(e)))
                self._events.publish("check_complete", _complete_payload([]))
                return
            results = []
            for i, manga in enumerate(manga_list):
                status = manga.get("status", "reading")
                if not force and status != "reading":
                    logger.debug("Skipping '%s' — status=%s", manga.get('title'), status)
                    continue
                title = manga.get("title", "")
                logger.info("Checking '%s' (%d/%d)", title, i + 1, len(manga_list))
                self._events.publish(
                    "check_progress",
                    _progress_payload(i + 1, len(manga_list), title),
                )

                # Determine source domain for health tracking
                sources = manga.get("sources", [])
                domain = sources[0].get("source", "") if sources else manga.get("source", "")
                logger.debug("Source domain: %s", domain)

                try:
                    new_chapters, all_chapters = check_for_updates(
                        manga, state, return_all=True,
                    )
                    logger.info(
                        "'%s': %d new chapter(s) (total %d available on primary)",
                        title, len(new_chapters), len(all_chapters),
                    )
                    # Always include the result so the GUI can cache the full
                    # chapter list (used by Detail page for Read/Download UI).
                    # Empty `chapters` is fine — auto-queue will simply skip.
                    results.append({
                        "manga": manga,
                        "chapters": new_chapters,
                        "all_chapters": all_chapters,
                    })
                    # Mark source healthy
                    if domain:
                        state.update_source_health(domain, success=True)
                except Exception as e:
                    logger.exception("Check failed for '%s': %s", title, e)
                    # Mark source unhealthy
                    if domain:
                        state.update_source_health(domain, success=False, error_msg=str(e))
                    self._events.publish(
                        "check_error", _error_payload(title, str(e)))
            logger.info("Check done: %d manga checked", len(results))
            self._events.publish(
                "check_complete",
                _complete_payload(results, queue_all=queue_all),
            )

        self._safe_submit(_task)

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------

    def download_chapter(self, manga, chapter, output_dir, output_format, state,
                         kindle_cfg=None, naming_template=None,
                         post_processing=None, allow_partial=False,
                         partial_threshold=0.0, delete_after_send=False):
        """Queue a chapter download.

        ``allow_partial``/``partial_threshold`` carry the partial-chapter
        tolerance settings (issue #86) from config through to the
        downloader. Off by default so behavior is unchanged unless the
        caller opts in. ``delete_after_send`` removes the local file once
        it has been sent to Kindle via ``kindle_cfg``.

        ``state`` receives the chapter's records (downloaded, partial,
        failed) before the matching event is published.
        """
        task_id = f"{manga['title']}:{chapter.number}"
        # Issue #107: drop duplicate requests for a chapter that is
        # already active or queued (its cancel flag stays registered
        # until the job finishes). The reader prefetch, a Detail-page
        # click and quick chapter changes could otherwise race the same
        # title:chapter task id into the queue twice.
        # Refuse to enqueue while offline — the request would just
        # block a worker slot until per-source retries time out.
        # Surfacing `download_error` lets the Downloads page + Toast
        # show the user a clean reason.
        if self._is_offline():
            self._events.publish("download_error", {
                "task_id": task_id,
                "title": manga.get("title", ""),
                "chapter": getattr(chapter, "number", ""),
                "error": "Offline — connect to the internet and try again.",
                "offline": True,
            })
            return
        with self._lock:
            # Check and register under the same lock: reader windows and
            # Detail-page actions can enqueue from separate GUI callbacks,
            # and a check outside the lock leaves a duplicate race.
            existing = self._cancel_flags.get(task_id)
            if existing is not None and not existing.is_set():
                return None
            cancel = threading.Event()
            self._cancel_flags[task_id] = cancel
            item = {
                "task_id": task_id,
                "manga": manga,
                "chapter": chapter,
                "output_dir": output_dir,
                "output_format": output_format,
                "state": state,
                "kindle_cfg": kindle_cfg,
                "naming_template": naming_template,
                "post_processing": post_processing,
                "cancel": cancel,
                "allow_partial": allow_partial,
                "partial_threshold": partial_threshold,
                "delete_after_send": delete_after_send,
            }
            paused = self._paused
            if (not paused) and self._active_downloads < self._max_concurrent_downloads:
                self._active_downloads += 1
                self._safe_submit(self._run_download, item)
            else:
                # While paused or saturated, always queue.
                self._download_queue.append(item)
                self._events.publish("download_queued", {
                    "task_id": task_id,
                    "title": manga["title"],
                    "chapter": chapter.number,
                })
        return task_id

    def cancel_download(self, task_id: str):
        """Signal a download to cancel."""
        if task_id in self._cancel_flags:
            self._cancel_flags[task_id].set()

    def send_pending(self, manga, chapter_number, state, kindle_cfg,
                     delete_after_send=False):
        """Send a saved chapter whose Kindle delivery failed again
        (issue #360).

        Runs :meth:`ChapterPipeline.redeliver`, the step behind `memanga
        send --pending`: the undelivered record is cleared once the
        chapter is sent and kept when it fails again, and
        ``delete_after_send`` only removes a file that was sent. Publishes
        ``kindle_sent`` or ``kindle_error`` like a download, then
        ``kindle_resend_done`` with ``sent``.
        """
        title = manga["title"]
        number = str(chapter_number)
        task_id = f"{title}:{number}"
        if self._is_offline():
            self._events.publish("kindle_error", {
                "task_id": task_id, "title": title, "chapter": number,
                "error": "Offline — connect to the internet and try again.",
            })
            self._events.publish("kindle_resend_done", {
                "task_id": task_id, "title": title, "chapter": number,
                "sent": False,
            })
            return None
        return self._safe_submit(self._run_send_pending, manga, number,
                                 state, dict(kindle_cfg or {}),
                                 delete_after_send)

    def _run_send_pending(self, manga, number, state, kindle_cfg,
                          delete_after_send):
        title = manga["title"]
        task_id = f"{title}:{number}"
        sent = False
        try:
            from .. import emailer
            from ..chapter_pipeline import (
                ChapterPipeline,
                DeliveryStatus,
                PipelineOptions,
            )
            from ..chapters import Chapter
            from .download_events import GuiChapterReporter

            options = PipelineOptions(
                # Nothing is downloaded: the recorded file is sent.
                download_dir=Path(),
                output_format="",
                delivery_mode="email" if kindle_cfg else "local",
                email=kindle_cfg,
                delete_after_send=delete_after_send,
            )
            pipeline = ChapterPipeline(
                options=options,
                state=state,
                reporter=GuiChapterReporter(
                    self._events, task_id, manga, Chapter(number=number),
                    threading.Event(),
                ),
                send=emailer.send_to_kindle,
                app_password=lambda: kindle_cfg.get("app_password"),
            )
            sent = pipeline.redeliver(title, number) is DeliveryStatus.SENT
        except Exception as e:
            logger.exception("Resending %s Ch.%s to Kindle failed: %s",
                             title, number, e)
            self._events.publish("kindle_error", {
                "task_id": task_id, "title": title, "chapter": number,
                "error": str(e),
            })
        finally:
            self._events.publish("kindle_resend_done", {
                "task_id": task_id, "title": title, "chapter": number,
                "sent": sent,
            })

    def _run_download(self, item):
        """Execute a single download task through the shared chapter
        pipeline (issue #295), so recovery, delivery and state records
        match `memanga check` and `failed retry`."""
        try:
            from .. import downloader, emailer
            from ..chapter_pipeline import (
                ChapterPipeline,
                PipelineOptions,
                chapter_source,
            )
            from .download_events import (
                GuiChapterReporter,
                download_complete_payload,
                download_error_payload,
            )
        except Exception as e:
            logger.exception("Failed to import downloader: %s", e)
            self._events.publish("download_error", {
                "task_id": item["task_id"], "error": f"Import error: {e}",
                "title": item["manga"]["title"], "chapter": "?",
            })
            # Release the slot this job held — bailing without it would
            # leak a concurrency slot and eventually stall the queue.
            self._cancel_flags.pop(item["task_id"], None)
            self._start_next_download()
            return
        task_id = item["task_id"]
        manga = item["manga"]
        chapter = item["chapter"]

        logger.info("Downloading %s Ch.%s", manga['title'], chapter.number)
        logger.debug("Output: %s format=%s", item['output_dir'], item['output_format'])

        # Kindle delivery is opted into per job: the page passes a
        # kindle_cfg only when email delivery applies to this manga.
        kindle_cfg = item.get("kindle_cfg") or {}
        options = PipelineOptions(
            download_dir=Path(item["output_dir"]),
            output_format=item["output_format"],
            post_processing=item.get("post_processing"),
            allow_partial=item.get("allow_partial", False),
            partial_threshold=item.get("partial_threshold", 0.0),
            delivery_mode="email" if kindle_cfg else "local",
            email=dict(kindle_cfg),
            delete_after_send=item.get("delete_after_send", False),
            naming_template=item.get("naming_template"),
        )
        # Collaborators are looked up when the job runs, not bound at
        # import, so they can be replaced on their own modules.
        pipeline = ChapterPipeline(
            options=options,
            state=item["state"],
            reporter=GuiChapterReporter(
                self._events, task_id, manga, chapter, item["cancel"],
            ),
            download=downloader.download_chapter,
            find_backup=downloader._find_chapter_on_backup,
            send=emailer.send_to_kindle,
            app_password=lambda: kindle_cfg.get("app_password"),
            cancel_event=item["cancel"],
        )

        try:
            outcome = pipeline.process(manga, chapter)
        except InterruptedError:
            self._events.publish("download_cancelled", {"task_id": task_id})
        except Exception as e:
            # Not a download failure the pipeline knows how to record
            # (those come back as a FAILED outcome): keep a record anyway
            # so the chapter shows up as failed and can be retried.
            logger.exception("Download failed: %s Ch.%s: %s",
                             manga['title'], chapter.number, e)
            state = item.get("state")
            if state is not None:
                try:
                    state.add_failed_chapter(
                        manga["title"],
                        chapter.number,
                        chapter_source(manga, chapter),
                        str(e),
                    )
                except Exception:
                    logger.exception("Could not record the failed chapter")
            self._events.publish("download_error", {
                "task_id": task_id, "error": str(e),
                "title": manga["title"], "chapter": chapter.number,
            })
        else:
            if outcome.saved:
                self._events.publish(
                    "download_complete",
                    download_complete_payload(task_id, manga, outcome),
                )
            else:
                self._events.publish(
                    "download_error",
                    download_error_payload(task_id, manga, outcome),
                )
        finally:
            self._cancel_flags.pop(task_id, None)
            self._start_next_download()

    def _start_next_download(self):
        """Release the finished download's slot, then refill from the queue.

        Called exactly once per finished job (from ``_run_download``'s
        finally block) — the decrement here is the job giving its slot
        back. While paused (``pause_all()``) the queue holds — no new
        jobs are dequeued. In-flight jobs continue until completion.
        ``resume_all()`` refills the freed slots via
        ``_fill_download_slots``.
        """
        with self._lock:
            self._active_downloads = max(0, self._active_downloads - 1)
        self._fill_download_slots()

    def _fill_download_slots(self):
        """Dequeue queued jobs until the concurrency cap is reached.

        No-op while paused. Never touches the slot counter for jobs it
        didn't start, so it's safe to call from anywhere — job
        completion, ``resume_all``, repeated pause/resume toggles —
        without dropping queued items or breaching
        ``_max_concurrent_downloads``.
        """
        to_start = []
        with self._lock:
            if self._paused:
                # Don't dequeue anything while paused.
                return
            while (self._download_queue
                   and self._active_downloads < self._max_concurrent_downloads):
                self._active_downloads += 1
                to_start.append(self._download_queue.pop(0))
        # Submit outside lock to avoid deadlock
        for item in to_start:
            self._safe_submit(self._run_download, item)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_manga(self, query: str, sources: List[str]):
        """Search across multiple sources in parallel.

        Each scraper's `search()` returns a list of `Manga` dataclasses
        — we convert each into a dict the UI can render directly and
        publish it as a `search_result` event. Per-source success and
        failure are published as `search_source_done` /
        `search_source_failed` so the UI can show progress instead of
        silently hiding broken sources.

        Results are filtered for relevance before publishing:
            - Single-manga aggregators (BeastarsManga, TGManga, etc.)
              blindly return their one manga regardless of the query.
              We drop those when the query terms don't appear in the
              returned title — otherwise searching "Blue Lock" returns
              Beastars, Tokyo Ghoul, Akira, …
        """
        # Bail immediately if the network is down — searching 100+
        # sources with 30 s timeouts would freeze the bar for minutes.
        if self._is_offline():
            self._events.publish("search_started", {
                "query": query, "total_sources": 0, "seq": -1,
            })
            self._events.publish("search_complete", {
                "query": query, "offline": True, "seq": -1,
            })
            return
        from concurrent.futures import as_completed

        # ── Generation tagging ──────────────────────────────────────
        # Bump the seq, signal any previous search to abort, then drop
        # the previous pool. cancel_futures=True (Py 3.9+) discards
        # any queued tasks that haven't started; in-flight scraper
        # calls have to finish on their own (we can't interrupt
        # Playwright mid-navigation) but their post-publish work is
        # short-circuited by the cancel event below.
        with self._search_lock:
            self._search_seq += 1
            seq = self._search_seq
            cancel = threading.Event()
            prev_cancel = self._search_cancel
            prev_pool = self._search_pool
            self._search_cancel = cancel
        if prev_cancel is not None:
            prev_cancel.set()
        if prev_pool is not None:
            try:
                prev_pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

        def _search_source(source_domain: str):
            # Pre-flight cancel check so user-issued new search can
            # abandon stale work fast without spamming the bus.
            if cancel.is_set():
                return 0
            from ..scrapers import get_scraper
            try:
                scraper = get_scraper(source_domain)
            except Exception as e:
                if cancel.is_set():
                    return 0
                # Issue #342: the whole cause; the Search page summarises
                # and shows it on request.
                logger.warning("Search on %s failed: no scraper: %s",
                               source_domain, e)
                self._events.publish("search_source_failed", {
                    "source": source_domain, "seq": seq,
                    "error": f"no scraper: {e}",
                })
                return 0
            try:
                results = scraper.search(query) or []
            except Exception as e:
                if cancel.is_set():
                    return 0
                logger.warning("Search on %s failed: %s: %s",
                               source_domain, type(e).__name__, e)
                self._events.publish("search_source_failed", {
                    "source": source_domain, "seq": seq,
                    "error": f"{type(e).__name__}: {e}",
                })
                return 0
            if cancel.is_set():
                return 0
            count = 0
            for m in results:
                if cancel.is_set():
                    return count
                # Tolerate both Manga dataclass (the contract) and plain
                # dict (older scrapers / future variants).
                if hasattr(m, "title") and hasattr(m, "url"):
                    payload = {
                        "title": getattr(m, "title", ""),
                        "url": getattr(m, "url", ""),
                        "cover_url": getattr(m, "cover_url", None),
                        "description": getattr(m, "description", None),
                        "source": source_domain,
                        "seq": seq,
                    }
                elif isinstance(m, dict):
                    payload = dict(m)
                    payload["source"] = source_domain
                    payload["seq"] = seq
                else:
                    continue
                if not payload.get("title") or not payload.get("url"):
                    continue
                if not _result_matches_query(payload.get("title", ""), query):
                    # Single-manga site returned its manga for an
                    # unrelated query. Drop it silently — counted as
                    # source_done with 0 below.
                    continue
                self._events.publish("search_result", payload)
                count += 1
            if not cancel.is_set():
                self._events.publish("search_source_done", {
                    "source": source_domain, "count": count, "seq": seq,
                })
            return count

        def _task():
            # Submit in popularity order so MangaDex / MangaPill /
            # MangaFire etc. always start before the long tail. The
            # search pool has 8 slots, so the 8 most popular sources
            # are running before any unranked one starts. UI sort
            # in SearchPage uses the same rank to keep results in
            # popularity order regardless of which source's network
            # was fastest.
            ordered = sort_sources_by_popularity(sources)
            self._events.publish("search_started", {
                "query": query, "total_sources": len(ordered), "seq": seq,
            })
            # Cap concurrency — 290 supported sources × 1 thread each
            # would saturate the network stack and spin up a flood of
            # Playwright browsers. 8 keeps it responsive without
            # melting the laptop.
            pool = ThreadPoolExecutor(max_workers=8,
                                       thread_name_prefix=f"search-{seq}")
            with self._search_lock:
                # Register so the next search_manga can shut us down.
                # Skip if a newer search has already replaced us.
                if self._search_cancel is cancel:
                    self._search_pool = pool
                else:
                    # We were cancelled before even starting; bail.
                    try:
                        pool.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    return
            try:
                futures = {pool.submit(_search_source, src): src for src in ordered}
                # as_completed gives each future the full timeout window
                # instead of serializing — one slow source no longer
                # eats every subsequent source's budget.
                for f in as_completed(futures, timeout=None):
                    if cancel.is_set():
                        break
                    src = futures[f]
                    try:
                        f.result(timeout=20)
                    except Exception as e:
                        if cancel.is_set():
                            break
                        self._events.publish("search_source_failed", {
                            "source": src, "seq": seq,
                            "error": f"timeout/{type(e).__name__}",
                        })
            finally:
                try:
                    pool.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                if not cancel.is_set():
                    self._events.publish("search_complete", {
                        "query": query, "seq": seq,
                    })

        self._safe_submit(_task)

    # Retries used when a probe returns -1 (network blip / Cloudflare /
    # transient site error). Three attempts spaced 4, 8, 16 seconds —
    # within ~30 s a typical recoverable failure resolves; permanent
    # failures (404, dead site) burn the budget and stay hidden.
    _COUNT_RETRY_DELAYS = (4.0, 8.0, 16.0)

    def count_chapters(self, source_domain: str, manga_url: str):
        """Fetch the chapter count for a single search result in the
        background. Publishes ``search_chapter_count`` with
        ``{source, url, count}`` once known (count = -1 if every retry
        attempt failed; the row drops the chip).

        - Runs on a dedicated 6-slot pool (`_count_pool`) so it doesn't
          compete with downloads for the shared 3-slot worker pool.
        - **Not** tied to the search seq. The UI matches incoming
          events to result rows by URL, so a late-arriving chip for
          a now-removed search just no-ops. Tying it to the seq
          meant a quick second search killed every in-flight probe
          from the first one — which is what made MangaFire chips
          appear to "never load" for users who searched twice.
        - Retries on failure (see _COUNT_RETRY_DELAYS) — as long as
          you stay on the same search, the chip will eventually fill
          in once the source responds.
        """
        if self._is_offline() or not manga_url:
            return

        def _task():
            from ..scrapers import get_scraper
            count = -1
            # Try once + retry deltas defined above. Each attempt does
            # a full scraper.get_chapters() — for plain-requests
            # sources that's ~1 s, for JSON-API sources (Comick/...)
            # usually <1 s, for Playwright browser-driven sources
            # (WeebCentral/MangaKatana) 3-10 s. MangaFire is the odd
            # one out: its API is plain HTTP but each call carries a
            # vrf token minted in a browser, so the first call in a
            # process pays a one-off browser start and later ones are
            # back under a second.
            for i, delay in enumerate((0.0,) + self._COUNT_RETRY_DELAYS):
                if delay > 0:
                    import time as _t
                    _t.sleep(delay)
                if self._is_offline() or getattr(self, "_shutdown", False):
                    return
                try:
                    scraper = get_scraper(source_domain)
                    chapters = scraper.get_chapters(manga_url) or []
                    count = len(chapters)
                    if count > 0:
                        break  # success — publish below
                except Exception:
                    count = -1
            self._events.publish("search_chapter_count", {
                "source": source_domain,
                "url": manga_url,
                "count": count,
            })

        try:
            if not getattr(self, "_shutdown", False):
                self._count_pool.submit(_task)
        except RuntimeError:
            # Pool was shut down between the check and submit.
            pass

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def calculate_storage(self, download_dir):
        """Calculate total storage used by downloads."""
        def _task():
            from pathlib import Path
            total = 0
            try:
                dl_path = Path(download_dir)
                if dl_path.exists():
                    for f in dl_path.rglob("*"):
                        if f.is_file():
                            total += f.stat().st_size
            except Exception:
                pass
            total_mb = total / (1024 * 1024)
            self._events.publish("storage_calculated", {"total_mb": total_mb})

        self._safe_submit(_task)

    # ------------------------------------------------------------------
    # Source health pings
    # ------------------------------------------------------------------

    def ping_sources(self, sources: List[str], state, timeout: float = 3.0):
        """Issue a parallel HEAD against each source's homepage to refresh
        its health entry in :class:`State`. Publishes
        ``sources_health_updated`` for the UI when done.
        """
        # No point pinging individual sources when we can't even reach
        # the open internet — the eventual results would all be
        # "error". Just bounce so the UI doesn't show a frozen
        # "rechecking…" spinner.
        if self._is_offline():
            self._events.publish("sources_health_updated", {
                "count": 0, "offline": True,
            })
            return

        def _ping_one(domain: str):
            url = f"https://{domain}/"
            import time
            t0 = time.perf_counter()
            try:
                resp = requests.head(
                    url, timeout=timeout, allow_redirects=True,
                    headers={"User-Agent": "MeManga/health-check"},
                )
                latency = int((time.perf_counter() - t0) * 1000)
                ok = 200 <= resp.status_code < 500
                state.update_source_health(
                    domain, ok,
                    error_msg=f"HTTP {resp.status_code}" if not ok else "",
                    latency_ms=latency,
                )
            except requests.RequestException as e:
                latency = int((time.perf_counter() - t0) * 1000)
                state.update_source_health(
                    domain, False, error_msg=str(e), latency_ms=latency,
                )

        def _task():
            # Fan out with a small thread pool — bounded so a clean machine
            # doesn't pop hundreds of connections at once.
            from concurrent.futures import ThreadPoolExecutor as _TPE
            with _TPE(max_workers=8) as ex:
                list(ex.map(_ping_one, sources))
            self._events.publish("sources_health_updated", {"count": len(sources)})

        self._safe_submit(_task)

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    @property
    def active_tasks(self) -> Dict[str, threading.Event]:
        """Read-only view of in-flight cancel-flag map. Used by the sidebar
        for the Downloads badge count and by `pause_all` to enumerate jobs.
        """
        return dict(self._cancel_flags)

    def is_paused(self) -> bool:
        return self._paused

    def pause_all(self):
        """Stop dequeuing new downloads. In-flight jobs continue (Playwright
        sessions can't be cleanly interrupted), but the queue drains naturally.
        """
        with self._lock:
            self._paused = True
        self._events.publish("downloads_paused", {})

    def resume_all(self):
        with self._lock:
            self._paused = False
        self._events.publish("downloads_resumed", {})
        # Refill every free download slot from the held queue. (Not
        # _start_next_download — that would release a slot no job ever
        # held, breaching the concurrency cap on each pause/resume.)
        self._fill_download_slots()
