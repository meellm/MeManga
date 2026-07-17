"""
Downloader for MeManga

Handles:
1. Checking sources for new chapters using scrapers
2. Downloading chapter images
3. Converting to PDF, EPUB, or CBZ
4. Cleanup
5. Backup source fallback (wait N days before using backup)
"""

import io
import os
import re
import signal
import shlex
import time
import atexit
import subprocess
import tempfile
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict, Any, Literal, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse

import img2pdf
from PIL import Image
from ebooklib import epub

from .state import State
from .scrapers import get_scraper, list_supported_sources
from .scrapers.base import Chapter


def restart_browsers():
    """Restart any browser instances to free memory."""
    try:
        from .scrapers.mangafire import VRFGenerator
        VRFGenerator().restart()
    except Exception:
        pass

    try:
        from .scrapers.playwright_base import PlaywrightScraper
        PlaywrightScraper.cleanup()
    except Exception:
        pass


def _cleanup_at_exit():
    """Clean up browser resources on exit."""
    restart_browsers()


atexit.register(_cleanup_at_exit)

OutputFormat = Literal["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"]

# Default days to wait before falling back to backup source
DEFAULT_FALLBACK_DELAY_DAYS = 2

# How long a post-processing command may run before it's killed (seconds).
POST_PROCESSING_TIMEOUT = 600


class DownloaderError(Exception):
    """Base exception for downloader errors.

    Incomplete-download failures carry structured detail so callers can
    record/act on them without parsing the message string:
    ``failed_pages`` (1-indexed page numbers) and ``total_pages``.
    Both are ``None`` for errors unrelated to per-page failures.
    """

    def __init__(self, message, failed_pages=None, total_pages=None):
        super().__init__(message)
        self.failed_pages = failed_pages
        self.total_pages = total_pages


class ChapterWithSource(Chapter):
    """Chapter with source info for multi-source support."""
    
    def __init__(self, chapter: Chapter, source: str, source_url: str, is_backup: bool = False):
        super().__init__(
            number=chapter.number,
            title=chapter.title,
            url=chapter.url,
            date=chapter.date,
        )
        self.source = source
        self.source_url = source_url
        self.is_backup = is_backup


def _extract_source(url: str) -> str:
    """Extract source domain from URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _get_sources_from_manga(manga: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Get list of sources from manga config.
    Supports both old format (single source) and new format (sources array).
    
    Returns: List of dicts with 'source' and 'url' keys
    """
    # New format: sources array
    if "sources" in manga:
        sources = []
        for s in manga["sources"]:
            if isinstance(s, dict):
                url = s.get("url", "")
                if not url:
                    # Skip blank-URL entries — they'd crash downstream
                    # in get_chapters("") with no useful error.
                    continue
                source = s.get("source") or _extract_source(url)
                sources.append({"source": source, "url": url})
            elif isinstance(s, str):
                if not s:
                    continue
                # Just a URL string
                sources.append({"source": _extract_source(s), "url": s})
        return sources
    
    # Old format: single source/url
    return [{
        "source": manga.get("source", ""),
        "url": manga.get("url", ""),
    }]


def _max_cached_chapter(cached: List[Dict[str, Any]]) -> float:
    """Highest numeric chapter number in a cached available-chapters list.

    Used to bootstrap the catalogue baseline for manga that predate the
    stored ``catalogue_baseline`` field (#102). Entries are the dicts the
    GUI persists via ``set_available_chapters`` (``{"number": ...}``).
    Returns 0.0 when nothing usable is present.
    """
    best = 0.0
    for entry in cached or []:
        if not isinstance(entry, dict):
            continue
        num = entry.get("number")
        if num is None:
            continue
        try:
            best = max(best, float(num))
        except (TypeError, ValueError):
            # Fall back to the leading number in strings like "12 Part 1".
            match = re.search(r"\d+\.?\d*", str(num))
            if match:
                best = max(best, float(match.group()))
    return best


def check_for_updates(
    manga: Dict[str, Any],
    state: State,
    from_chapter: Optional[float] = None,
    return_all: bool = False,
    force_suspicious: bool = False,
):
    """
    Check if a manga has new chapters, with backup source support.

    Logic:
    1. Check primary source first
    2. If new chapter on primary → return it
    3. If no new chapter → check backup source(s)
    4. If backup has new chapter:
       - Already in pending_backup? Check if fallback_delay passed
         - Yes → return it (download from backup)
         - No → skip (still waiting)
       - Not in pending_backup? Add it, skip (start waiting)
    5. If primary gets the chapter later, we prefer primary

    Suspicious batches: when the primary source suddenly exposes a batch
    of "new" chapters that doesn't fit the manga's history (huge count,
    big numeric jump, gappy numbering), the batch is verified against
    backup sources. If no backup confirms it, the chapters are withheld,
    recorded via ``state.set_suspicious_batch``, and a warning notification
    is added. Nothing is downloaded or delivered until the user re-runs
    with ``force_suspicious=True``.

    Args:
        manga: Manga entry from config with title, sources (or url/source)
        state: State manager to check last downloaded chapter
        from_chapter: Override starting chapter (for downloading from scratch)
        return_all: If True, return a tuple ``(new_chapters, all_chapters)``
            where ``all_chapters`` is the full chapter list from the primary
            source wrapped as :class:`ChapterWithSource` (used by the GUI
            Detail page to show every chapter as Read/Download). When False
            (default), returns just the filtered new-chapter list, preserving
            the original CLI signature.
        force_suspicious: Accept a batch even if it looks suspicious
            (``memanga check --force-suspicious``).

    Returns:
        ``List[ChapterWithSource]`` (default) or
        ``Tuple[List[ChapterWithSource], List[ChapterWithSource]]`` when
        ``return_all=True``.
    """
    title = manga["title"]
    sources = _get_sources_from_manga(manga)
    fallback_delay_days = manga.get("fallback_delay_days", DEFAULT_FALLBACK_DELAY_DAYS)
    
    if not sources:
        raise DownloaderError(f"No sources configured for '{title}'")
    
    # Get starting chapter - use from_chapter if provided, else last downloaded
    if from_chapter is not None:
        # Subtract small amount so --from 1 includes chapter 1
        last_num = from_chapter - 0.001
    else:
        last_chapter = state.get_last_chapter(title)
        last_num = float(last_chapter) if last_chapter else 0.0
    
    # Results to return
    chapters_to_download: List[ChapterWithSource] = []

    # Track what we found on each source
    primary_chapters: Dict[str, Chapter] = {}  # chapter_num -> Chapter
    backup_chapters: Dict[str, Tuple[Chapter, str, str]] = {}  # chapter_num -> (Chapter, source, url)

    # Every chapter number seen on any backup source (full list, not just
    # new ones). Used to verify suspicious primary batches.
    backup_all_numbers: set = set()
    backup_sources_checked = 0
    primary_checked = False

    # Full chapter list from the primary source (every chapter, downloaded or not).
    # Used by the GUI Detail page when return_all=True so it can render every
    # chapter as Read or Download without re-scraping.
    primary_all: List[ChapterWithSource] = []

    # Check each source
    source_errors = []
    sources_checked = 0
    for i, src in enumerate(sources):
        source = src["source"]
        url = src["url"]
        is_primary = (i == 0)

        try:
            scraper = get_scraper(source)
            all_chapters = scraper.get_chapters(url)
            sources_checked += 1
        except ValueError as e:
            # Unsupported source - skip but warn
            source_errors.append(f"{source}: {e}")
            print(f"  [Warning] Unsupported source '{source}': {e}")
            continue
        except Exception as e:
            # Failed to fetch - skip but warn
            source_errors.append(f"{source}: {e}")
            print(f"  [Warning] Failed to fetch from {source}: {e}")
            continue

        # Capture the full chapter list from the primary source for the
        # Detail-page cache. Backup sources are intentionally skipped here —
        # we don't want backup-only chapters polluting the canonical list.
        if is_primary:
            primary_checked = True
            primary_all = [
                ChapterWithSource(ch, source, url, is_backup=False)
                for ch in all_chapters
            ]
        else:
            backup_sources_checked += 1
            backup_all_numbers.update(round(ch.numeric, 3) for ch in all_chapters)

        # Filter to new chapters
        new_chapters = [
            ch for ch in all_chapters
            if ch.numeric > last_num and not state.is_chapter_downloaded(title, ch.number)
        ]

        for ch in new_chapters:
            ch_num = ch.number

            if is_primary:
                primary_chapters[ch_num] = ch
            else:
                # Only track if not already on primary
                if ch_num not in primary_chapters:
                    backup_chapters[ch_num] = (ch, source, url)
    
    # If ALL sources failed, raise so the caller knows
    if sources_checked == 0 and source_errors:
        raise DownloaderError(
            f"All sources failed for '{title}': " + "; ".join(source_errors)
        )

    # Suspicious-batch guard.
    #
    # The batch is scored against the source's *catalogue baseline* — the
    # highest chapter the source has legitimately exposed before — not the
    # last downloaded chapter. Scoring against the last download makes a
    # manual-mode backlog (only an early chapter grabbed from an
    # already-large catalogue) look like a giant source jump on every check
    # (#102). Only chapters that appear beyond the known catalogue are
    # candidates for suspicion; anything at or below it is an existing,
    # still-undownloaded backlog and stays freely downloadable.
    if primary_checked:
        primary_high = max((ch.numeric for ch in primary_all), default=0.0)

        get_suspicious_batch = getattr(state, "get_suspicious_batch", None)
        active_suspicious = (
            get_suspicious_batch(title)
            if callable(get_suspicious_batch)
            else None
        )
        get_catalogue_baseline = getattr(state, "get_catalogue_baseline", None)
        baseline = (
            get_catalogue_baseline(title)
            if callable(get_catalogue_baseline)
            else None
        )
        if baseline is None and not active_suspicious:
            # No trusted snapshot yet (manga predates this field, or was
            # never checked). Bootstrap from the last cached catalogue so an
            # existing large backlog isn't mistaken for a jump.
            get_available_chapters = getattr(state, "get_available_chapters", None)
            cached = (
                get_available_chapters(title)
                if callable(get_available_chapters)
                else []
            )
            baseline = _max_cached_chapter(cached)
        if baseline is None:
            baseline = 0.0
        bootstrapped_manual_baseline = False
        if baseline <= 0 and manga.get("mode") == "manual" and from_chapter is None:
            # First manual-mode check after adding/importing a manga. Manual
            # mode only surfaces Download buttons, so this snapshot is not an
            # auto-delivery risk; use it as the initial catalogue baseline
            # instead of scoring the whole undownloaded backlog against the
            # user's last downloaded/read chapter (#102).
            baseline = primary_high
            bootstrapped_manual_baseline = True

        catalogue_trusted = True
        # Only score when we have a download baseline and the user isn't
        # explicitly bulk-downloading with from_chapter.
        if from_chapter is None and last_num > 0:
            from .suspicion import evaluate_new_chapters

            guard_from = max(last_num, baseline)
            scored = {
                num: ch for num, ch in primary_chapters.items()
                if ch.numeric > guard_from
            }
            suspicion = (
                evaluate_new_chapters(
                    state, title,
                    [ch.numeric for ch in scored.values()],
                    guard_from,
                )
                if scored else None
            )
            if suspicion is not None and suspicion.suspicious and not force_suspicious:
                suspect = sorted(scored.values())
                suspect_numbers = [round(ch.numeric, 3) for ch in suspect]

                # Verify against backup sources before withholding anything.
                confirmed = sum(1 for n in suspect_numbers if n in backup_all_numbers)
                if backup_sources_checked and confirmed / len(suspect_numbers) >= 0.5:
                    # Backup largely agrees with the primary, so accept the batch.
                    state.clear_suspicious_batch(title)
                else:
                    if backup_sources_checked:
                        backup_status = (
                            f"backup confirmed only {confirmed}/{len(suspect_numbers)} chapters"
                        )
                    else:
                        backup_status = "no backup source available to verify"
                    state.set_suspicious_batch(title, {
                        "detected_at": datetime.now().isoformat(),
                        "chapters": [ch.number for ch in suspect],
                        "count": len(suspect),
                        "last_chapter": guard_from,
                        "highest": max(suspect_numbers),
                        "score": suspicion.score,
                        "reasons": suspicion.reasons,
                        "backup_status": backup_status,
                    })
                    state.add_notification(
                        "warn",
                        f"Suspicious chapter batch for '{title}': "
                        f"{len(suspect)} chapter(s) up to {max(suspect_numbers):g} "
                        f"({backup_status}). Skipped auto-delivery.",
                    )
                    # Withhold only the suspicious newly-appeared chapters;
                    # the known backlog stays downloadable. Don't advance the
                    # trusted baseline past an unverified jump.
                    for num in scored:
                        primary_chapters.pop(num, None)
                    catalogue_trusted = False
            else:
                # Batch is normal, forced, or backup-confirmed. Drop any
                # stale suspicious record so warnings don't linger.
                state.clear_suspicious_batch(title)

        # Advance the trusted catalogue high-water mark unless we just held
        # back an unverified jump. Recording it even when the guard didn't
        # run (fresh manga, explicit from_chapter) gives later checks a
        # baseline so a big existing backlog is never re-scored as a jump.
        if catalogue_trusted and (primary_high > baseline or bootstrapped_manual_baseline):
            set_catalogue_baseline = getattr(state, "set_catalogue_baseline", None)
            if callable(set_catalogue_baseline):
                set_catalogue_baseline(title, primary_high)

    # Process primary chapters first (always download these)
    for ch_num, ch in primary_chapters.items():
        primary_src = sources[0]
        chapters_to_download.append(
            ChapterWithSource(ch, primary_src["source"], primary_src["url"], is_backup=False)
        )
        # Clear any pending backup for this chapter (primary caught up)
        state.clear_pending_backup(title, ch_num)
    
    # Process backup chapters
    now = datetime.now()
    for ch_num, (ch, backup_source, backup_url) in backup_chapters.items():
        # Skip if we're already downloading from primary
        if ch_num in primary_chapters:
            continue
        
        pending = state.get_pending_backup(title, ch_num)
        
        if pending:
            # Check if fallback delay has passed
            first_seen = datetime.fromisoformat(pending["first_seen"])
            days_waiting = (now - first_seen).days
            
            if days_waiting >= fallback_delay_days:
                # Delay passed, download from backup
                chapters_to_download.append(
                    ChapterWithSource(ch, backup_source, backup_url, is_backup=True)
                )
                # Note: We'll clear pending_backup after successful download
            # else: still waiting, do nothing
        else:
            # First time seeing this on backup, start waiting
            state.set_pending_backup(title, ch_num, backup_source, ch.url)

    new_sorted = sorted(chapters_to_download)
    if return_all:
        return new_sorted, sorted(primary_all)
    return new_sorted


def _find_chapter_on_backup(
    manga: Dict[str, Any],
    chapter_num_str: str,
) -> Optional["ChapterWithSource"]:
    """
    Find a chapter on backup sources.

    Used when the primary source download fails — looks up the same chapter
    number on any configured backup sources and returns it ready to download.
    """
    sources = _get_sources_from_manga(manga)
    backup_sources = sources[1:]  # Everything after primary

    for src in backup_sources:
        source = src["source"]
        url = src["url"]
        try:
            scraper = get_scraper(source)
            all_chapters = scraper.get_chapters(url)
        except Exception:
            continue

        for ch in all_chapters:
            if ch.number == chapter_num_str:
                return ChapterWithSource(ch, source, url, is_backup=True)

    return None


def download_chapter(
    manga: Dict[str, Any],
    chapter: Chapter,
    output_dir: Path,
    output_format: OutputFormat = "pdf",
    state: Optional[State] = None,
    progress_callback=None,
    naming_template: Optional[str] = None,
    cancel_event=None,
    max_retries: int = 3,
    post_processing: Optional[Dict[str, Any]] = None,
    allow_partial: bool = False,
    partial_threshold: float = 0.0,
    on_partial=None,
) -> Optional[Path]:
    """
    Download a chapter and convert to PDF or EPUB.

    Args:
        manga: Manga entry from config
        chapter: Chapter to download (can be ChapterWithSource)
        output_dir: Directory to save the file
        output_format: "pdf" or "epub"
        state: State manager (for clearing pending backup after download)
        progress_callback: Optional callable(current, total) for progress updates
        cancel_event: Optional threading.Event — when set, raises
            InterruptedError before/during page fetching to abort the download.
        max_retries: Number of times to retry failed page downloads
            (with exponential back-off). 0 to disable.
        post_processing: Optional ``delivery.post_processing`` config dict
            ({"enabled", "command", "fail_on_error"}). When enabled, the
            command is run after the output file/folder is created. If
            ``fail_on_error`` is set, a command failure raises
            :class:`DownloaderError` so normal failed-chapter handling applies;
            otherwise it only prints a warning.
        allow_partial: When True, a chapter that still has missing pages
            after retries is kept as a *partial* download (only the pages
            that succeeded, in order) instead of raising — provided the
            failure rate is within ``partial_threshold``. Off by default,
            so the historical "any failure aborts the chapter" behavior is
            unchanged unless a caller opts in (issue #86).
        partial_threshold: Maximum share of pages allowed to fail, as a
            percentage (0-100). A partial is kept only when
            ``failed_pages / total_pages * 100 <= partial_threshold`` and
            at least one page downloaded. With the default 0, any failure
            still aborts.
        on_partial: Optional callable(failed_page_nums, total_pages) invoked
            when a partial download is accepted, so callers can log/surface
            it and record which pages are missing.

    Returns:
        Path to downloaded file, or None if failed
    """
    title = manga["title"]

    # Defensive: keep the tolerance within [0, 100] even if a caller passes
    # something out of range directly (issue #86). The CLI/config already
    # clamp, but download_chapter is a public entry point.
    try:
        partial_threshold = max(0.0, min(100.0, float(partial_threshold)))
    except (TypeError, ValueError):
        partial_threshold = 0.0

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Download cancelled")

    # Get source from chapter if available (ChapterWithSource), else from manga config
    if isinstance(chapter, ChapterWithSource):
        source = chapter.source
        is_backup = chapter.is_backup
    else:
        sources = _get_sources_from_manga(manga)
        source = sources[0]["source"] if sources else ""
        is_backup = False

    # Get scraper
    try:
        scraper = get_scraper(source)
    except ValueError as e:
        raise DownloaderError(f"Unsupported source: {e}")

    # Bail before kicking off any expensive work if already cancelled.
    _check_cancel()

    # Create temp directory for images
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Get page URLs
        try:
            page_urls = scraper.get_pages(chapter.url)
        except Exception as e:
            raise DownloaderError(f"Failed to get pages: {e}")

        _check_cancel()

        if not page_urls:
            raise DownloaderError("No pages found for chapter")

        # Download images concurrently
        download_tasks = []
        for i, url in enumerate(page_urls):
            ext = _get_extension(url)
            img_path = temp_path / f"page_{i:03d}{ext}"
            download_tasks.append((i, url, img_path))

        results: Dict[int, Path] = {}
        total_pages = len(download_tasks)
        completed_count = 0
        # Manually manage the pool so we can `cancel_futures=True` and bail
        # without waiting for in-flight image fetches when the user cancels.
        executor = ThreadPoolExecutor(max_workers=4)
        cancelled = False
        try:
            futures = {
                executor.submit(scraper.download_image, url, img_path): (idx, url, img_path)
                for idx, url, img_path in download_tasks
            }
            for future in as_completed(futures):
                idx, url, img_path = futures[future]
                try:
                    if future.result():
                        results[idx] = img_path
                except Exception:
                    # Per-page failure — silent; retry loop below decides
                    # whether to give up. Old code printed a warning but
                    # the new failed-chapter handling does that more
                    # usefully via DownloaderError + state.add_failed_chapter.
                    pass
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total_pages)
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
        finally:
            # cancel_futures only ditches futures that haven't started yet;
            # in-flight ones still run to completion but we don't wait on them.
            executor.shutdown(wait=False, cancel_futures=True)

        if cancelled:
            raise InterruptedError("Download cancelled")

        # Retry individually any pages that failed the first pass.
        # Issue #26: silent partial failures used to produce a tiny
        # incomplete CBZ and mark the chapter as "downloaded".
        # Now we retry up to `max_retries` times then raise so the
        # caller can record the failure and try the backup source.
        if max_retries > 0:
            for attempt in range(1, max_retries + 1):
                failed = [(idx, url, img_path)
                          for idx, url, img_path in download_tasks
                          if idx not in results]
                if not failed:
                    break
                print(
                    f"  Retrying {len(failed)} failed page(s), "
                    f"attempt {attempt}/{max_retries}..."
                )
                time.sleep(2 ** (attempt - 1))
                for idx, url, img_path in failed:
                    _check_cancel()
                    try:
                        if scraper.download_image(url, img_path):
                            results[idx] = img_path
                    except Exception:
                        pass

        still_failed = [idx for idx, _, _ in download_tasks if idx not in results]
        if still_failed:
            failed_page_nums = [i + 1 for i in still_failed]
            failed_pct = len(still_failed) / total_pages * 100

            # Partial-chapter tolerance (issue #86): when enabled and the
            # failure rate is within the configured threshold, keep the
            # pages we did get instead of discarding the whole chapter.
            # At least one page must have downloaded — a chapter with zero
            # usable pages is a hard failure regardless of the threshold.
            partial_ok = (
                allow_partial
                and results
                and failed_pct <= partial_threshold
            )
            if not partial_ok:
                raise DownloaderError(
                    f"Incomplete download: {len(still_failed)}/{len(page_urls)} "
                    f"pages failed (pages {failed_page_nums})",
                    failed_pages=failed_page_nums,
                    total_pages=total_pages,
                )

            print(
                f"  Partial chapter kept: {len(still_failed)}/{total_pages} "
                f"page(s) missing ({failed_pct:.0f}% <= "
                f"{partial_threshold:g}% tolerance), pages {failed_page_nums}"
            )
            if on_partial is not None:
                try:
                    on_partial(failed_page_nums, total_pages)
                except Exception:
                    pass

        # Preserve page order
        image_paths = [results[i] for i in sorted(results)]

        # Download cover image for EPUB
        cover_path = None
        if output_format == "epub":
            cover_url = manga.get("cover_url")
            if not cover_url:
                # Try to fetch cover from the manga page
                try:
                    manga_url = manga.get("url", "")
                    if not manga_url:
                        sources = _get_sources_from_manga(manga)
                        manga_url = sources[0]["url"] if sources else ""
                    if manga_url:
                        cover_url = scraper.get_cover_url(manga_url)
                except Exception:
                    pass
            if cover_url:
                cover_path = temp_path / "cover_art.jpg"
                try:
                    if not scraper.download_image(cover_url, cover_path):
                        cover_path = None
                except Exception:
                    cover_path = None

        # Convert to output format
        safe_title = _sanitize_filename(title)
        # Issue #21: every format gets its own per-manga subfolder
        # (<dir>/<manga_name>/…). Image format already did this; the
        # archive/document formats used to land at the dir root, which
        # broke the Reader's file lookup (it searches <dir>/<title>/).
        manga_dir = output_dir / safe_title
        manga_dir.mkdir(parents=True, exist_ok=True)

        # Zero-pad chapter numbers for proper sorting
        chapter_str = _format_chapter_number(chapter.number)

        # Build filename from template
        template = naming_template or "{title} - Chapter {chapter}"
        base_name = _sanitize_filename(
            template.replace("{title}", title)
                    .replace("{chapter}", chapter_str)
                    .replace("{source}", source)
        )

        if output_format == "epub":
            output_path = manga_dir / f"{base_name}.epub"
            try:
                _images_to_epub(image_paths, output_path, title, chapter.number, cover_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create EPUB: {e}")
        elif output_format == "cbz":
            output_path = manga_dir / f"{base_name}.cbz"
            try:
                comicinfo_xml = _build_comicinfo_xml(manga, chapter, len(image_paths))
                _images_to_cbz(image_paths, output_path, comicinfo_xml)
            except Exception as e:
                raise DownloaderError(f"Failed to create CBZ: {e}")
        elif output_format == "zip":
            output_path = manga_dir / f"{base_name}.zip"
            try:
                _images_to_cbz(image_paths, output_path)  # Reuse CBZ logic (same ZIP format)
            except Exception as e:
                raise DownloaderError(f"Failed to create ZIP: {e}")
        elif output_format in ("jpg", "png", "webp"):
            chapter_folder = manga_dir / f"Chapter {chapter_str}"
            try:
                _images_to_folder(image_paths, chapter_folder, output_format)
            except Exception as e:
                raise DownloaderError(f"Failed to save images: {e}")
            output_path = chapter_folder  # Return the directory path
        else:
            output_path = manga_dir / f"{base_name}.pdf"
            try:
                _images_to_pdf(image_paths, output_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create PDF: {e}")

        # Run the user's post-processing hook (if configured) after the
        # output exists but before the caller records the chapter as
        # downloaded, so a fail_on_error failure surfaces normally.
        _run_post_processing(
            post_processing,
            output_path=output_path,
            title=title,
            chapter_num=chapter.number,
            source=source,
            output_format=output_format,
        )

        return output_path


def _run_post_processing(
    post_processing: Optional[Dict[str, Any]],
    output_path: Path,
    title: str,
    chapter_num: str,
    source: str,
    output_format: str,
):
    """Run the optional user post-processing command for a finished chapter.

    The command is split into argv and run directly, not through a shell.
    Useful values are passed both as ``{placeholder}`` substitutions in command
    arguments and as ``MEMANGA_*`` environment variables:

    - ``{output_path}`` / ``MEMANGA_OUTPUT_PATH`` - final file or folder path
    - ``{title}`` / ``MEMANGA_MANGA_TITLE`` - manga title
    - ``{chapter}`` / ``MEMANGA_CHAPTER`` - chapter number
    - ``{source}`` / ``MEMANGA_SOURCE`` - source the chapter came from
    - ``{format}`` / ``MEMANGA_OUTPUT_FORMAT`` - output format
    - ``{is_dir}`` / ``MEMANGA_IS_DIR`` - "1" if output is a folder, else "0"

    Placeholder values are substituted after argv parsing, so metadata cannot
    become shell syntax. For shell features such as pipes or redirects, invoke
    a shell explicitly and prefer the ``MEMANGA_*`` environment variables.

    A non-zero exit, timeout, or launch error is treated as failure: if
    ``fail_on_error`` is set the failure is re-raised as
    :class:`DownloaderError`; otherwise a warning is printed and the download
    stays successful.
    """
    if not post_processing or not post_processing.get("enabled"):
        return

    command = (post_processing.get("command") or "").strip()
    if not command:
        return

    fail_on_error = bool(post_processing.get("fail_on_error"))
    is_dir = "1" if output_path.is_dir() else "0"
    output_path_str = str(output_path)
    title = str(title)
    chapter_num = str(chapter_num)
    source = str(source)
    output_format = str(output_format)

    replacements = {
        "output_path": output_path_str,
        "title": title,
        "chapter": chapter_num,
        "source": source,
        "format": output_format,
        "is_dir": is_dir,
    }

    def _fail(message: str):
        if fail_on_error:
            raise DownloaderError(message)
        print(f"  [Warning] {message}")

    try:
        command_args = _split_post_processing_command(command)
    except ValueError as e:
        _fail(f"Post-processing command could not be parsed: {e}")
        return
    if not command_args:
        return

    resolved_args = [
        _substitute_post_processing_placeholders(arg, replacements)
        for arg in command_args
    ]

    env = os.environ.copy()
    env.update({
        "MEMANGA_OUTPUT_PATH": output_path_str,
        "MEMANGA_MANGA_TITLE": title,
        "MEMANGA_CHAPTER": chapter_num,
        "MEMANGA_SOURCE": source,
        "MEMANGA_OUTPUT_FORMAT": output_format,
        "MEMANGA_IS_DIR": is_dir,
    })

    try:
        result = _run_post_processing_command(
            resolved_args,
            env=env,
            timeout=POST_PROCESSING_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _fail(
            f"Post-processing command timed out after "
            f"{POST_PROCESSING_TIMEOUT}s"
        )
        return
    except Exception as e:
        _fail(f"Post-processing command failed to start: {e}")
        return

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"Post-processing command exited with code {result.returncode}"
        if detail:
            message += f": {detail}"
        _fail(message)


def _run_post_processing_command(
    args: List[str],
    env: Dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess:
    """Run a post-processing command and terminate its process tree on timeout."""
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # The process tree is killed first, then we drain the pipes with a
        # bounded wait. If a surviving grandchild still holds the pipe handles
        # open, communicate() would block forever, so every drain here has its
        # own timeout and we ultimately abandon the output rather than hang.
        _terminate_process_tree(process)
        stdout, stderr = _drain_after_timeout(process)
        exc.output = stdout
        exc.stderr = stderr
        raise exc

    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _drain_after_timeout(
    process: subprocess.Popen,
    drain_timeout: int = 5,
) -> tuple:
    """Read remaining output from a killed process without ever blocking.

    Returns ``(stdout, stderr)``. If the pipes cannot be drained even after a
    second kill, they are force-closed and ``(None, None)`` is returned so the
    caller never waits on a wedged child that inherited the handles.
    """
    try:
        return process.communicate(timeout=drain_timeout)
    except subprocess.TimeoutExpired:
        pass

    process.kill()
    try:
        return process.communicate(timeout=drain_timeout)
    except subprocess.TimeoutExpired:
        pass

    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
    return None, None


_POST_PROCESSING_PLACEHOLDER_RE = re.compile(
    r"\{(output_path|title|chapter|source|format|is_dir)\}"
)


def _substitute_post_processing_placeholders(
    arg: str,
    replacements: Dict[str, str],
) -> str:
    """Replace placeholders once, without expanding placeholder text in values."""
    return _POST_PROCESSING_PLACEHOLDER_RE.sub(
        lambda match: replacements[match.group(1)],
        arg,
    )


def _split_post_processing_command(command: str) -> List[str]:
    """Split a command string into argv without damaging Windows paths."""
    if os.name != "nt":
        return shlex.split(command)

    args: List[str] = []
    current: List[str] = []
    in_quotes = False
    quote_char = ""

    for ch in command:
        if ch in ("'", '"'):
            if in_quotes and ch == quote_char:
                in_quotes = False
                quote_char = ""
            elif not in_quotes:
                in_quotes = True
                quote_char = ch
            else:
                current.append(ch)
        elif ch.isspace() and not in_quotes:
            if current:
                args.append("".join(current))
                current = []
        else:
            current.append(ch)

    if in_quotes:
        raise ValueError("No closing quotation")
    if current:
        args.append("".join(current))
    return args


def _terminate_process_tree(process: subprocess.Popen) -> bool:
    """Terminate a process and its children where the platform supports it."""
    if process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return True
        except Exception:
            pass
    try:
        process.kill()
        return True
    except Exception:
        return False


def _image_to_jpeg_bytes(img_path: Path) -> tuple:
    """Convert any image to JPEG bytes suitable for EPUB/Kindle.

    Returns (jpeg_bytes, width, height).
    """
    img = Image.open(img_path)
    try:
        width, height = img.size
        # Flatten transparency onto white background
        if img.mode in ('RGBA', 'P', 'LA', 'PA'):
            rgba = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[3])
            rgba.close()
            img.close()
            img = bg
        elif img.mode != 'RGB':
            converted = img.convert('RGB')
            img.close()
            img = converted
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=95)
        return buf.getvalue(), width, height
    finally:
        img.close()


def _images_to_epub(
    image_paths: List[Path],
    output_path: Path,
    title: str,
    chapter_num: str,
    cover_image_path: Optional[Path] = None,
):
    """Convert images to a fixed-layout EPUB compatible with Kindle.

    Args:
        image_paths: Ordered list of page image paths.
        output_path: Where to write the .epub file.
        title: Manga title.
        chapter_num: Chapter number string.
        cover_image_path: Optional separate cover image. Falls back to first page.
    """
    book = epub.EpubBook()

    # ── Metadata ──
    book_id = str(uuid.uuid4())
    book.set_identifier(book_id)
    full_title = f"{title} - Chapter {chapter_num}"
    book.set_title(full_title)
    book.set_language('en')
    book.add_author(title)

    # Fixed-layout metadata (required for Kindle to render as image pages)
    book.add_metadata(None, 'meta', 'pre-paginated', {'property': 'rendition:layout'})
    book.add_metadata(None, 'meta', 'auto', {'property': 'rendition:orientation'})
    book.add_metadata(None, 'meta', 'none', {'property': 'rendition:spread'})

    # ── Cover image ──
    cover_src = cover_image_path if cover_image_path and cover_image_path.exists() else (
        image_paths[0] if image_paths else None
    )
    if cover_src:
        cover_data, cw, ch = _image_to_jpeg_bytes(cover_src)
        # Manually add cover item with proper metadata for Kindle
        cover_item = epub.EpubItem(
            uid='cover-image',
            file_name='images/cover.jpg',
            media_type='image/jpeg',
            content=cover_data,
        )
        book.add_item(cover_item)
        # Kindle recognises this meta tag to find the cover
        book.add_metadata('OPF', 'meta', '', {
            'name': 'cover',
            'content': 'cover-image',
        })

        # Cover XHTML page
        cover_html = epub.EpubHtml(
            title='Cover',
            file_name='cover.xhtml',
            lang='en',
        )
        cover_html.content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Cover</title>
<meta name="viewport" content="width={cw}, height={ch}"/>
<style>html,body{{margin:0;padding:0;width:100%;height:100%}}
img{{width:100%;height:auto;display:block}}</style></head>
<body><img src="images/cover.jpg" alt="Cover"/></body></html>'''.encode('utf-8')
        book.add_item(cover_html)

    # ── Page images ──
    spine = []
    if cover_src:
        spine.append(cover_html)

    for i, img_path in enumerate(image_paths):
        img_data, width, height = _image_to_jpeg_bytes(img_path)

        img_name = f"page_{i:03d}.jpg"
        img_item = epub.EpubItem(
            uid=f"img_{i}",
            file_name=f"images/{img_name}",
            media_type='image/jpeg',
            content=img_data,
        )
        book.add_item(img_item)

        page_html = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Page {i + 1}</title>
<meta name="viewport" content="width={width}, height={height}"/>
<style>html,body{{margin:0;padding:0;width:100%;height:100%}}
img{{width:100%;height:auto;display:block}}</style></head>
<body><img src="images/{img_name}" alt="Page {i + 1}"/></body></html>'''

        page = epub.EpubHtml(
            title=f'Page {i + 1}',
            file_name=f'page_{i:03d}.xhtml',
            lang='en',
        )
        page.content = page_html.encode('utf-8')
        book.add_item(page)
        spine.append(page)

    # ── Navigation ──
    book.toc = []
    book.add_item(epub.EpubNcx())
    nav = epub.EpubNav()
    book.add_item(nav)

    # Spine: nav hidden, then pages in order
    book.spine = [nav] + spine

    epub.write_epub(str(output_path), book)


def _images_to_pdf(image_paths: List[Path], output_path: Path):
    """Convert a list of images to a single PDF."""
    processed_images = []

    for img_path in image_paths:
        try:
            jpeg_data, _, _ = _image_to_jpeg_bytes(img_path)
            processed_images.append(jpeg_data)
        except Exception as e:
            print(f"  Warning: Could not process {img_path}: {e}")

    if not processed_images:
        raise DownloaderError("No images could be processed")

    pdf_bytes = img2pdf.convert(processed_images)
    output_path.write_bytes(pdf_bytes)


def _parse_comicinfo_date(date_str: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Best-effort parse of a chapter/source date into (year, month, day).

    Chapter dates arrive in many shapes across scrapers (ISO 8601 from API
    sources like ``publishAt``, free-form text elsewhere). Returns ``None``
    when nothing usable can be extracted so the caller simply omits the
    Year/Month/Day fields.
    """
    if not date_str:
        return None
    text = str(date_str).strip()
    if not text:
        return None

    # ISO 8601 first (covers the trailing "...Z" suffix common to API sources).
    try:
        iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(iso_text)
        return dt.year, dt.month, dt.day
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y",
        "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.year, dt.month, dt.day
        except ValueError:
            continue
    return None


def _build_comicinfo_xml(
    manga: Dict[str, Any],
    chapter: Chapter,
    page_count: int,
) -> bytes:
    """Build a ComicInfo.xml document from already-known metadata.

    Only fields MeManga already has on hand (the tracked manga config and
    the ``Chapter`` object) are written; no extra network requests are
    made. Optional fields with no data are omitted entirely. Serialization
    and XML escaping are handled by ElementTree.
    """
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("ComicInfo", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
    })

    def add(tag: str, value: Any):
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        SubElement(root, tag).text = text

    chapter_title = getattr(chapter, "title", None)
    add("Title", chapter_title or f"Chapter {chapter.number}")
    add("Series", manga.get("title"))
    add("Number", chapter.number)

    add("Summary", manga.get("description"))

    parsed = _parse_comicinfo_date(getattr(chapter, "date", None))
    if parsed:
        year, month, day = parsed
        add("Year", year)
        add("Month", month)
        add("Day", day)

    add("Writer", manga.get("author"))

    # Web: prefer the specific chapter URL, fall back to the manga URL.
    add("Web", getattr(chapter, "url", "") or manga.get("url", ""))
    add("PageCount", page_count)

    return tostring(root, encoding="utf-8", xml_declaration=True)


def _images_to_cbz(
    image_paths: List[Path],
    output_path: Path,
    comicinfo_xml: Optional[bytes] = None,
):
    """Convert a list of images to a CBZ (Comic Book ZIP) archive.

    Images are stored as-is (no re-encoding) with sequential names
    for correct reading order.

    When ``comicinfo_xml`` is provided it is written to the archive root as
    ``ComicInfo.xml`` so offline libraries and e-readers can read chapter
    metadata. Page names and order are unaffected.
    """
    import zipfile

    if not image_paths:
        raise DownloaderError("No images to archive")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as cbz:
        for i, img_path in enumerate(image_paths):
            ext = img_path.suffix.lower() or '.jpg'
            cbz.write(img_path, f"page_{i:03d}{ext}")
        if comicinfo_xml is not None:
            cbz.writestr("ComicInfo.xml", comicinfo_xml)


def _images_to_folder(image_paths: List[Path], output_dir: Path, img_format: str):
    """Save images to a folder, converting to the specified format.

    Args:
        image_paths: Downloaded source images
        output_dir: Chapter folder to save into (e.g., downloads/Manga/Chapter 001/)
        img_format: Target format - "jpg", "png", or "webp"
    """
    if not image_paths:
        raise DownloaderError("No images to save")

    output_dir.mkdir(parents=True, exist_ok=True)

    pillow_format_map = {
        "jpg": ("JPEG", ".jpg", {"quality": 95}),
        "png": ("PNG", ".png", {}),
        "webp": ("WEBP", ".webp", {"quality": 90}),
    }

    pil_format, ext, save_kwargs = pillow_format_map[img_format]

    for i, img_path in enumerate(image_paths):
        img = Image.open(img_path)
        try:
            # JPEG requires RGB (no alpha channel)
            if pil_format == "JPEG" and img.mode in ('RGBA', 'P', 'LA', 'PA'):
                rgba = img.convert('RGBA')
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[3])
                rgba.close()
                img.close()
                img = bg
            elif pil_format == "JPEG" and img.mode != 'RGB':
                converted = img.convert('RGB')
                img.close()
                img = converted
            elif pil_format in ("PNG", "WEBP") and img.mode not in ('RGB', 'RGBA'):
                converted = img.convert('RGB')
                img.close()
                img = converted

            out_path = output_dir / f"{i:03d}{ext}"
            img.save(out_path, format=pil_format, **save_kwargs)
        finally:
            img.close()


def _get_extension(url: str) -> str:
    """Get file extension from URL path (not substring match)."""
    from posixpath import splitext
    path = url.split('?')[0].split('#')[0]
    _, ext = splitext(path)
    ext = ext.lower()
    if ext in ('.webp', '.png', '.jpg', '.jpeg', '.gif'):
        return ext
    return '.jpg'


def _sanitize_filename(name: str) -> str:
    """Make a string safe for use as filename."""
    # Remove/replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '')
    return name.strip()[:100]  # Limit length


def rename_manga_downloads(download_dir, old_title: str, new_title: str) -> bool:
    """Move a manga's downloaded files when the manga is renamed.

    Downloads live under ``<download_dir>/<sanitized title>/`` and the
    default naming template embeds the title in each file
    (``{title} - Chapter N``). The reader derives both the folder and the
    file name from the manga's current title, so a rename leaves the old
    files unreachable — the chapter shows as downloaded but "Read" finds
    nothing.

    This moves the per-manga folder to the new title and rewrites the
    title prefix on any contained file or folder name so the reader's
    lookup matches again. Existing files at the destination are left
    untouched rather than overwritten.

    Returns ``True`` if anything was moved, ``False`` if there was nothing
    to migrate (no prior downloads, or the sanitized title is unchanged).
    """
    old_safe = _sanitize_filename(old_title)
    new_safe = _sanitize_filename(new_title)
    if not old_safe or not new_safe or old_safe == new_safe:
        return False

    base = Path(download_dir)
    old_dir = base / old_safe
    if not old_dir.is_dir():
        return False

    new_dir = base / new_safe
    new_dir.mkdir(parents=True, exist_ok=True)

    moved = False
    for entry in list(old_dir.iterdir()):
        name = entry.name
        # Swap the leading title prefix (e.g. "Old - Chapter 5.cbz" ->
        # "New - Chapter 5.cbz"). Names that don't start with the title
        # (e.g. image-format "Chapter 5" folders) are moved as-is.
        if name.startswith(old_safe):
            name = new_safe + name[len(old_safe):]
        target = new_dir / name
        if target.exists():
            continue
        shutil.move(str(entry), str(target))
        moved = True

    # Drop the old folder if it's now empty; leave it if collisions
    # forced some files to stay behind.
    try:
        old_dir.rmdir()
    except OSError:
        pass

    return moved


def _format_chapter_number(chapter_num: str) -> str:
    """
    Format chapter number for proper alphabetical sorting.
    
    - Regular chapters: stay as is (2, 3, 4...)
    - Part chapters: "2 Part 1" -> "2.01", "2 Part 2" -> "2.02"
    - Decimal chapters: stay as is (2.5 -> 2.5)
    
    Sorting result: 2 < 2.01 < 2.02 < 2.5 < 3 (correct!)
    """
    import re
    
    # Check for "Part X" pattern (case insensitive)
    part_match = re.match(r'^(\d+)\s*[Pp]art\s*(\d+)(.*)$', chapter_num)
    if part_match:
        main_num = part_match.group(1)
        part_num = part_match.group(2).zfill(2)  # Zero-pad to 2 digits
        rest = part_match.group(3)  # Any trailing text
        return f"{main_num}.{part_num}{rest}"
    
    # Return as-is for regular and decimal chapters
    return chapter_num


def get_supported_sources() -> List[str]:
    """Get list of supported source domains."""
    return list_supported_sources()
