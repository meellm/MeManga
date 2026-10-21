"""Update checking: find new chapters across primary and backup sources."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..chapters import Chapter, ChapterWithSource, chapter_value
from ..scrapers import get_scraper
from ..state import State
from .errors import DownloaderError
from .sources import _configure_mangadex, _get_sources_from_manga

logger = logging.getLogger(__name__)

# Default days to wait before falling back to backup source
DEFAULT_FALLBACK_DELAY_DAYS = 2


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
        # Labels such as "12 Part 1" count by their leading number.
        value = chapter_value(num)
        if value is not None:
            best = max(best, value)
    return best


def check_for_updates(
    manga: Dict[str, Any],
    state: State,
    from_chapter: Optional[float] = None,
    return_all: bool = False,
    force_suspicious: bool = False,
    *,
    dry_run: bool = False,
    report: Optional[Dict[str, Any]] = None,
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
        dry_run: Preview only (``memanga check --dry-run``). Selects the
            same chapters a real check would, but writes nothing to
            ``state``: no pending-backup clock is started or cleared, no
            suspicious record is set or cleared, no notification is added
            and the catalogue baseline is not advanced. A forced or
            ``from_chapter`` preview therefore can't accept a held batch.
        report: Optional dict filled with what this call decided, so a
            caller can describe it without reading persisted state (which a
            dry run leaves untouched). Keys: ``withheld`` (the suspicious
            batch record withheld by this call, or None) and ``forced``
            (chapters included only because of ``force_suspicious``).

    Returns:
        ``List[ChapterWithSource]`` (default) or
        ``Tuple[List[ChapterWithSource], List[ChapterWithSource]]`` when
        ``return_all=True``.
    """
    title = manga["title"]
    sources = _get_sources_from_manga(manga)
    if report is None:
        report = {}
    report["withheld"] = None
    report["forced"] = 0
    fallback_delay_days = manga.get("fallback_delay_days", DEFAULT_FALLBACK_DELAY_DAYS)
    
    if not sources:
        raise DownloaderError(f"No sources configured for '{title}'")
    
    # Get starting chapter - use from_chapter if provided, else last downloaded
    has_last_chapter = False
    if from_chapter is not None:
        # Subtract small amount so --from 1 includes chapter 1
        last_num = from_chapter - 0.001
    else:
        # Stored labels such as "10 Part 1" or "Extra" are parsed the same
        # way as the scraped chapters they are compared against (#228).
        last_chapter = state.get_last_chapter(title)
        has_last_chapter = bool(last_chapter)
        last_num = Chapter(number=str(last_chapter)).numeric if has_last_chapter else 0.0
    
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
            _configure_mangadex(scraper, state)
            all_chapters = scraper.get_chapters(url)
            sources_checked += 1
        except ValueError as e:
            # Unsupported source - skip but warn
            source_errors.append(f"{source}: {e}")
            logger.warning("Unsupported source '%s': %s", source, e)
            continue
        except Exception as e:
            # Failed to fetch - skip but warn
            source_errors.append(f"{source}: {e}")
            logger.warning("Failed to fetch from %s: %s", source, e)
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

        active_suspicious = state.get_suspicious_batch(title)
        baseline = state.get_catalogue_baseline(title)
        if baseline is None and not active_suspicious:
            # No trusted snapshot yet (manga predates this field, or was
            # never checked). Bootstrap from the last cached catalogue so an
            # existing large backlog isn't mistaken for a jump.
            baseline = _max_cached_chapter(state.get_available_chapters(title))
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
        # explicitly bulk-downloading with from_chapter. A stored label with
        # no number ("Extra") parses to 0.0 but is still download history, so
        # it is scored against a known catalogue baseline instead of
        # bypassing the guard (#228).
        if from_chapter is None and (
            last_num > 0 or (has_last_chapter and baseline > 0)
        ):
            from ..suspicion import evaluate_new_chapters

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
                    if not dry_run:
                        state.clear_suspicious_batch(title)
                else:
                    if backup_sources_checked:
                        backup_status = (
                            f"backup confirmed only {confirmed}/{len(suspect_numbers)} chapters"
                        )
                    else:
                        backup_status = "no backup source available to verify"
                    record = {
                        "detected_at": datetime.now().isoformat(),
                        "chapters": [ch.number for ch in suspect],
                        "count": len(suspect),
                        "last_chapter": guard_from,
                        "highest": max(suspect_numbers),
                        "score": suspicion.score,
                        "reasons": suspicion.reasons,
                        "backup_status": backup_status,
                    }
                    report["withheld"] = record
                    if not dry_run:
                        state.set_suspicious_batch(title, record)
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
                if suspicion is not None and suspicion.suspicious:
                    report["forced"] = len(scored)
                # Batch is normal, forced, or backup-confirmed. Drop any
                # stale suspicious record so warnings don't linger.
                if not dry_run:
                    state.clear_suspicious_batch(title)

        # Advance the trusted catalogue high-water mark unless we just held
        # back an unverified jump. Recording it even when the guard didn't
        # run (fresh manga, explicit from_chapter) gives later checks a
        # baseline so a big existing backlog is never re-scored as a jump.
        if not dry_run and catalogue_trusted and (primary_high > baseline or bootstrapped_manual_baseline):
            state.set_catalogue_baseline(title, primary_high)

    # Process primary chapters first (always download these)
    for ch_num, ch in primary_chapters.items():
        primary_src = sources[0]
        chapters_to_download.append(
            ChapterWithSource(ch, primary_src["source"], primary_src["url"], is_backup=False)
        )
        # Clear any pending backup for this chapter (primary caught up)
        if not dry_run:
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
        elif not dry_run:
            # First time seeing this on backup, start waiting
            state.set_pending_backup(title, ch_num, backup_source, ch.url)

    new_sorted = sorted(chapters_to_download)
    if return_all:
        return new_sorted, sorted(primary_all)
    return new_sorted


def _find_chapter_on_backup(
    manga: Dict[str, Any],
    chapter_num_str: str,
    state: Optional[State] = None,
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
            # Skip removed MangaDex groups so an allowed upload is picked.
            _configure_mangadex(scraper, state)
            all_chapters = scraper.get_chapters(url)
        except Exception:
            continue

        for ch in all_chapters:
            if ch.number == chapter_num_str:
                return ChapterWithSource(ch, source, url, is_backup=True)

    return None
