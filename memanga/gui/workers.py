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
        self._pool.shutdown(wait=False)

    def submit_task(self, fn):
        """Run a fire-and-forget callable on the shared worker pool.

        Use this for one-off background work (e.g. cover backfill) so
        callers don't have to reach into ``_pool`` directly.
        """
        return self._pool.submit(fn)

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

        self._pool.submit(_task)

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

        self._pool.submit(_task)

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
            if self._active_downloads < self._max_concurrent_downloads:
                self._active_downloads += 1
                self._pool.submit(self._run_download, item)
            else:
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
        """Finish current download and start next queued one if capacity allows."""
        next_item = None
        with self._lock:
            self._active_downloads = max(0, self._active_downloads - 1)
            if self._download_queue and self._active_downloads < self._max_concurrent_downloads:
                next_item = self._download_queue.pop(0)
                self._active_downloads += 1
        # Submit outside lock to avoid deadlock
        if next_item:
            self._pool.submit(self._run_download, next_item)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_manga(self, query: str, sources: List[str]):
        """Search across multiple sources in parallel."""
        def _search_source(source_domain):
            from ..scrapers import get_scraper
            try:
                scraper = get_scraper(source_domain)
                results = scraper.search(query)
                for r in results:
                    r["source"] = source_domain
                    self._events.publish("search_result", r)
            except Exception:
                pass

        def _task():
            self._events.publish("search_started", {"query": query})
            futures = []
            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="search") as pool:
                for src in sources:
                    futures.append(pool.submit(_search_source, src))
                for f in futures:
                    try:
                        f.result(timeout=30)
                    except Exception:
                        pass
            self._events.publish("search_complete", {"query": query})

        self._pool.submit(_task)

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

        self._pool.submit(_task)
