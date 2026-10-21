"""Chapter download orchestration: fetch pages, write the output file and
run the post-processing hook."""

import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from ..chapters import Chapter, ChapterWithSource
from ..scrapers import get_scraper
from ..scrapers.base import is_image_file
from ..state import State
from .errors import DownloaderError
from .formats import (_build_comicinfo_xml, _images_to_cbz, _images_to_epub,
                      _images_to_folder, _images_to_pdf, _manga_language)
from .naming import (DEFAULT_NAMING_TEMPLATE, _chapter_base_name,
                     _format_chapter_number, _get_extension,
                     _sanitize_filename)
from .post_processing import _run_post_processing
from .sources import _configure_mangadex, _get_sources_from_manga

logger = logging.getLogger(__name__)

OutputFormat = Literal["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"]

# Default number of times a failed page download is retried
DEFAULT_PAGE_RETRIES = 3


def download_chapter(
    manga: Dict[str, Any],
    chapter: Chapter,
    output_dir: Path,
    output_format: OutputFormat = "pdf",
    state: Optional[State] = None,
    progress_callback=None,
    naming_template: Optional[str] = None,
    cancel_event=None,
    max_retries: int = DEFAULT_PAGE_RETRIES,
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
        _configure_mangadex(scraper, state)
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

        def _fetch_page(url, img_path) -> bool:
            # A page counts only when the saved bytes are an image, whatever
            # the scraper returned: an HTML block page or empty body is a
            # failed page that goes through retry/partial handling (#229).
            if not scraper.download_image(url, img_path):
                return False
            if is_image_file(img_path):
                return True
            Path(img_path).unlink(missing_ok=True)
            return False

        # Download images concurrently
        download_tasks = []
        for i, url in enumerate(page_urls):
            ext = _get_extension(url)
            img_path = temp_path / f"page_{i:03d}{ext}"
            download_tasks.append((i, url, img_path))

        results: Dict[int, Path] = {}
        total_pages = len(download_tasks)
        completed_count = 0
        # Manually manage the pool so we can `cancel_futures=True` and stop
        # queued page fetches when the user cancels.
        executor = ThreadPoolExecutor(max_workers=4)
        cancelled = False
        try:
            futures = {
                executor.submit(_fetch_page, url, img_path): (idx, url, img_path)
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
            # cancel_futures only ditches futures that haven't started yet.
            # Wait for the in-flight ones (each bounded by the scraper's
            # request timeout): they write into temp_path, which is removed
            # when this block exits, and a worker still writing then would
            # make the cleanup fail (Windows) or recreate the folder and
            # leave it behind (issue #246).
            executor.shutdown(wait=True, cancel_futures=True)

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
                logger.debug(
                    "Retrying %d failed page(s), attempt %d/%d",
                    len(failed), attempt, max_retries,
                )
                time.sleep(2 ** (attempt - 1))
                for idx, url, img_path in failed:
                    _check_cancel()
                    try:
                        if _fetch_page(url, img_path):
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

            # INFO: the chapter pipeline reports the partial as a warning.
            logger.info(
                "Partial chapter kept: %d/%d page(s) missing "
                "(%.0f%% <= %g%% tolerance), pages %s",
                len(still_failed), total_pages, failed_pct,
                partial_threshold, failed_page_nums,
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
                    if not _fetch_page(cover_url, cover_path):
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

        # Zero-pad chapter numbers so file names sort in chapter order
        # ("2" -> "0002.000"); see _format_chapter_number for the rules.
        chapter_str = _format_chapter_number(chapter.number)

        # Build filename from template; long names shorten the title so
        # the chapter text stays whole and distinct.
        template = naming_template or DEFAULT_NAMING_TEMPLATE
        base_name = _chapter_base_name(template, title, chapter_str, source)
        credit = None
        if source in ("mangadex.org", "api.mangadex.org"):
            groups = getattr(chapter, "group_names", [])
            if not groups and state is not None:
                # Chapters rebuilt by the GUI (reader, queue) carry no group
                # names; the cached chapter list from the last check does.
                cached = next((c for c in state.get_available_chapters(title)
                               if c.get("url") == chapter.url), {})
                groups = cached.get("group_names", [])
                chapter.group_names = groups
                if not getattr(chapter, "group_ids", []):
                    chapter.group_ids = cached.get("group_ids", [])
            credit = "MangaDex" + (" · " + ", ".join(groups) if groups else "")

        if output_format == "epub":
            output_path = manga_dir / f"{base_name}.epub"
            try:
                _images_to_epub(image_paths, output_path, title, chapter.number,
                                cover_path, credit=credit,
                                author=manga.get("author"),
                                language=_manga_language(manga, scraper))
            except Exception as e:
                raise DownloaderError(f"Failed to create EPUB: {e}")
        elif output_format == "cbz":
            output_path = manga_dir / f"{base_name}.cbz"
            try:
                comicinfo_xml = _build_comicinfo_xml(manga, chapter, len(image_paths),
                                                     scraper=scraper)
                _images_to_cbz(image_paths, output_path, comicinfo_xml,
                               credit=credit)
            except Exception as e:
                raise DownloaderError(f"Failed to create CBZ: {e}")
        elif output_format == "zip":
            output_path = manga_dir / f"{base_name}.zip"
            try:
                _images_to_cbz(image_paths, output_path, credit=credit)
            except Exception as e:
                raise DownloaderError(f"Failed to create ZIP: {e}")
        elif output_format in ("jpg", "png", "webp"):
            chapter_folder = manga_dir / f"Chapter {chapter_str}"
            try:
                _images_to_folder(image_paths, chapter_folder, output_format)
                if credit:
                    (chapter_folder / "Source.txt").write_text(credit + "\n", encoding="utf-8")
            except Exception as e:
                raise DownloaderError(f"Failed to save images: {e}")
            output_path = chapter_folder  # Return the directory path
        else:
            output_path = manga_dir / f"{base_name}.pdf"
            try:
                _images_to_pdf(image_paths, output_path, credit=credit)
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

        if credit is not None and state is not None:
            # Survives later checks that drop this group's chapters (#400).
            state.set_chapter_groups(
                title, chapter.number, source,
                getattr(chapter, "group_ids", []),
                getattr(chapter, "group_names", []),
            )

        return output_path
