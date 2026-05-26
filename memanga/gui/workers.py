"""
Background worker for long-running operations.
Wraps ThreadPoolExecutor; publishes events to the EventBus.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests

from .events import EventBus


class BackgroundWorker:
    """Runs download/check/search tasks in background threads."""

    def __init__(self, event_bus: EventBus):
        self._events = event_bus
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="memanga-worker")
        self._download_queue: list = []
        self._active_downloads: int = 0
        self._max_concurrent_downloads = 2
        self._lock = threading.Lock()
        self._cancel_flags: Dict[str, threading.Event] = {}

    def shutdown(self):
        """Clean up the thread pool."""
        self._shutdown = True
        self._pool.shutdown(wait=False)

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
        """Download a cover image in the background. Only saves bytes to disk — no CTkImage."""
        def _task():
            try:
                resp = requests.get(url, timeout=15, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                resp.raise_for_status()
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

    def check_updates(self, manga_list: list, state, config):
        """Check for new chapters across manga list."""
        import sys as _sys
        print(f"[Check] check_updates called with {len(manga_list)} manga", flush=True)
        for m in manga_list:
            print(f"[Check]   - '{m.get('title')}' source={m.get('source', '')} status={m.get('status', 'reading')}", flush=True)

        def _task():
            import traceback
            print(f"[Check] Background task started", flush=True)
            try:
                from ..downloader import check_for_updates
            except Exception as e:
                print(f"[Check] FATAL: Failed to import downloader: {e}", flush=True)
                traceback.print_exc()
                _sys.stdout.flush()
                self._events.publish("check_error", {"title": "Import Error", "error": str(e)})
                self._events.publish("check_complete", {"results": []})
                return
            results = []
            _sys.stdout.flush()
            for i, manga in enumerate(manga_list):
                status = manga.get("status", "reading")
                if status != "reading":
                    print(f"[Check] Skipping '{manga.get('title')}' — status={status}", flush=True)
                    continue
                title = manga.get("title", "")
                print(f"[Check] Checking '{title}' ({i+1}/{len(manga_list)})", flush=True)
                self._events.publish("check_progress", {
                    "current": i + 1,
                    "total": len(manga_list),
                    "title": title,
                })

                # Determine source domain for health tracking
                sources = manga.get("sources", [])
                domain = sources[0].get("source", "") if sources else manga.get("source", "")
                print(f"[Check]   Source domain: {domain}", flush=True)

                try:
                    new_chapters, all_chapters = check_for_updates(
                        manga, state, return_all=True,
                    )
                    print(
                        f"[Check]   Found {len(new_chapters)} new chapter(s) "
                        f"(total {len(all_chapters)} available on primary)",
                        flush=True,
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
                    print(f"[Check]   ERROR: {e}", flush=True)
                    traceback.print_exc()
                    _sys.stdout.flush()
                    # Mark source unhealthy
                    if domain:
                        state.update_source_health(domain, success=False, error_msg=str(e))
                    self._events.publish("check_error", {
                        "title": title, "error": str(e),
                    })
            print(f"[Check] Done. Total results: {len(results)} manga with new chapters", flush=True)
            self._events.publish("check_complete", {"results": results})

        self._safe_submit(_task)

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------

    def download_chapter(self, manga, chapter, output_dir, output_format, state,
                         kindle_cfg=None, naming_template=None):
        """Queue a chapter download."""
        task_id = f"{manga['title']}:{chapter.number}"
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
            "cancel": cancel,
        }

        with self._lock:
            paused = getattr(self, "_paused", False)
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

    def cancel_download(self, task_id: str):
        """Signal a download to cancel."""
        if task_id in self._cancel_flags:
            self._cancel_flags[task_id].set()

    def _run_download(self, item):
        """Execute a single download task."""
        import traceback
        try:
            from ..downloader import download_chapter
        except Exception as e:
            print(f"[Download] FATAL: Failed to import downloader: {e}", flush=True)
            traceback.print_exc()
            self._events.publish("download_error", {
                "task_id": item["task_id"], "error": f"Import error: {e}",
                "title": item["manga"]["title"], "chapter": "?",
            })
            return
        task_id = item["task_id"]
        manga = item["manga"]
        chapter = item["chapter"]

        print(f"[Download] Starting: {manga['title']} Ch.{chapter.number}", flush=True)
        print(f"[Download]   Output: {item['output_dir']} format={item['output_format']}", flush=True)
        self._events.publish("download_started", {
            "task_id": task_id,
            "title": manga["title"],
            "chapter": chapter.number,
        })

        def progress_cb(current, total):
            if item["cancel"].is_set():
                raise InterruptedError("Download cancelled")
            try:
                self._events.publish("download_progress", {
                    "task_id": task_id,
                    "current": current,
                    "total": total,
                })
            except Exception:
                pass

        try:
            path = download_chapter(
                manga=manga,
                chapter=chapter,
                output_dir=item["output_dir"],
                output_format=item["output_format"],
                state=item["state"],
                progress_callback=progress_cb,
                naming_template=item.get("naming_template"),
                cancel_event=item["cancel"],
            )

            # Kindle delivery
            if item["kindle_cfg"] and path:
                try:
                    from ..emailer import send_to_kindle
                    from ..config import get_app_password
                    send_to_kindle(
                        pdf_path=path,
                        kindle_email=item["kindle_cfg"]["kindle_email"],
                        sender_email=item["kindle_cfg"]["sender_email"],
                        app_password=item["kindle_cfg"]["app_password"],
                        smtp_server=item["kindle_cfg"].get("smtp_server", "smtp.gmail.com"),
                        smtp_port=item["kindle_cfg"].get("smtp_port", 587),
                    )
                    self._events.publish("kindle_sent", {"task_id": task_id, "path": str(path)})
                except Exception as e:
                    self._events.publish("kindle_error", {"task_id": task_id, "error": str(e)})

            self._events.publish("download_complete", {
                "task_id": task_id,
                "path": str(path) if path else None,
                "title": manga["title"],
                "chapter": chapter.number,
            })
        except InterruptedError:
            self._events.publish("download_cancelled", {"task_id": task_id})
        except Exception as e:
            print(f"[Download] ERROR: {manga['title']} Ch.{chapter.number}: {e}", flush=True)
            traceback.print_exc()
            self._events.publish("download_error", {
                "task_id": task_id, "error": str(e),
                "title": manga["title"], "chapter": chapter.number,
            })
        finally:
            self._cancel_flags.pop(task_id, None)
            self._start_next_download()

    def _start_next_download(self):
        """Finish current download and start next queued one if capacity allows.

        While paused (``pause_all()``) the queue holds — no new jobs are
        dequeued. In-flight jobs continue until completion. ``resume_all()``
        kicks this method again to drain the queue.
        """
        next_item = None
        with self._lock:
            self._active_downloads = max(0, self._active_downloads - 1)
            if getattr(self, "_paused", False):
                # Don't dequeue anything while paused.
                return
            if self._download_queue and self._active_downloads < self._max_concurrent_downloads:
                next_item = self._download_queue.pop(0)
                self._active_downloads += 1
        # Submit outside lock to avoid deadlock
        if next_item:
            self._safe_submit(self._run_download, next_item)

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
        """
        from concurrent.futures import as_completed

        def _search_source(source_domain: str):
            from ..scrapers import get_scraper
            try:
                scraper = get_scraper(source_domain)
            except Exception as e:
                self._events.publish("search_source_failed", {
                    "source": source_domain,
                    "error": f"no scraper: {e}"[:160],
                })
                return 0
            try:
                results = scraper.search(query) or []
            except Exception as e:
                self._events.publish("search_source_failed", {
                    "source": source_domain,
                    "error": f"{type(e).__name__}: {e}"[:160],
                })
                return 0
            count = 0
            for m in results:
                # Tolerate both Manga dataclass (the contract) and plain
                # dict (older scrapers / future variants).
                if hasattr(m, "title") and hasattr(m, "url"):
                    payload = {
                        "title": getattr(m, "title", ""),
                        "url": getattr(m, "url", ""),
                        "cover_url": getattr(m, "cover_url", None),
                        "description": getattr(m, "description", None),
                        "source": source_domain,
                    }
                elif isinstance(m, dict):
                    payload = dict(m)
                    payload["source"] = source_domain
                else:
                    continue
                if not payload.get("title") or not payload.get("url"):
                    continue
                self._events.publish("search_result", payload)
                count += 1
            self._events.publish("search_source_done", {
                "source": source_domain, "count": count,
            })
            return count

        def _task():
            self._events.publish("search_started", {
                "query": query, "total_sources": len(sources),
            })
            # Cap concurrency — 290 supported sources × 1 thread each
            # would saturate the network stack and spin up a flood of
            # Playwright browsers. 8 keeps it responsive without
            # melting the laptop.
            with ThreadPoolExecutor(max_workers=8,
                                     thread_name_prefix="search") as pool:
                futures = {pool.submit(_search_source, src): src for src in sources}
                # as_completed gives each future the full timeout window
                # instead of serializing — one slow source no longer
                # eats every subsequent source's budget.
                for f in as_completed(futures, timeout=None):
                    src = futures[f]
                    try:
                        f.result(timeout=20)
                    except Exception as e:
                        self._events.publish("search_source_failed", {
                            "source": src,
                            "error": f"timeout/{type(e).__name__}",
                        })
            self._events.publish("search_complete", {"query": query})

        self._safe_submit(_task)

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
                    domain, False, error_msg=str(e)[:80], latency_ms=latency,
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
        return getattr(self, "_paused", False)

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
        # Kick the queue.
        self._start_next_download()
