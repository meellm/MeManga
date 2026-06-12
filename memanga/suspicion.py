"""Suspicious chapter-batch detection.

A source can suddenly expose bogus or re-numbered chapters (real case:
MangaFire's AJAX chapter list made a manga tracked at ~52.3 look like it
had 64 new chapters up to 148, then 154/156). If we trust that blindly,
``check`` downloads and emails a large backlog of wrong chapters.

This module scores a candidate batch of new chapters against what is
"normal" for that manga: its historical batch size, how long since it
last updated, and how far the chapter numbers jump, so the downloader
can hold back suspicious batches until a backup source confirms them or
the user forces acceptance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import List, Optional

# A manga with no download history is assumed to release a couple of
# chapters at a time, roughly weekly. These only seed the allowance;
# real history (when available) overrides them.
DEFAULT_TYPICAL_BATCH_SIZE = 2.0
DEFAULT_CADENCE_DAYS = 7.0

# Download-history entries closer together than this belong to the same
# batch (one check run downloads its chapters within minutes/hours).
BATCH_GAP_HOURS = 12.0

# Score at or above which a batch is considered suspicious.
SUSPICION_THRESHOLD = 3


@dataclass
class SuspicionResult:
    """Outcome of evaluating a candidate new-chapter batch."""

    suspicious: bool
    score: int
    reasons: List[str] = field(default_factory=list)


def evaluate_chapter_batch(
    new_numbers: List[float],
    last_number: float,
    typical_batch_size: Optional[float] = None,
    days_since_last_update: Optional[float] = None,
) -> SuspicionResult:
    """Score a batch of candidate new chapter numbers.

    Args:
        new_numbers: Numeric chapter numbers found on the primary source
            that are newer than the last tracked chapter.
        last_number: The manga's last tracked chapter (numeric). 0 or
            negative means no baseline; a fresh manga legitimately
            returns its whole catalogue, so nothing is flagged.
        typical_batch_size: Median chapters-per-update for this manga
            (from download history), if known.
        days_since_last_update: Days since this manga last got a chapter,
            if known. A long-dormant series can plausibly catch up with a
            bigger batch, so this scales the allowance.

    Returns:
        SuspicionResult with the verdict, score, and human-readable reasons.
    """
    nums = sorted(n for n in new_numbers if n is not None and n > 0)
    if not nums or last_number is None or last_number <= 0:
        return SuspicionResult(False, 0)

    score = 0
    reasons: List[str] = []

    baseline = max(typical_batch_size or DEFAULT_TYPICAL_BATCH_SIZE, 1.0)
    elapsed = (
        days_since_last_update
        if days_since_last_update and days_since_last_update > 0
        else DEFAULT_CADENCE_DAYS
    )
    # The longer a series sat idle, the bigger a legitimate catch-up
    # batch can be.
    allowance = baseline * max(1.0, elapsed / DEFAULT_CADENCE_DAYS)

    batch = len(nums)
    if batch >= max(8.0, 4 * allowance):
        score += 2
        reasons.append(
            f"{batch} new chapters at once (typical batch around {baseline:g})"
        )
    elif batch >= max(5.0, 2 * allowance):
        score += 1
        reasons.append(
            f"{batch} new chapters is above this manga's usual batch of around {baseline:g}"
        )

    # Numeric jump from the last tracked chapter. Decimal/split releases
    # (52.3 -> 52.5, "2 Part 1") stay well under the threshold; a
    # re-numbering like 52.3 -> 156 blows past it.
    jump = nums[-1] - last_number
    allowed_jump = max(10.0, last_number * 0.5)
    if jump > 2 * allowed_jump:
        score += 3
        reasons.append(
            f"chapter number jumped from {last_number:g} to {nums[-1]:g}"
        )
    elif jump > allowed_jump:
        score += 2
        reasons.append(
            f"chapter number jumped from {last_number:g} to {nums[-1]:g}"
        )
    elif jump > max(5.0, allowed_jump / 2):
        score += 1
        reasons.append(
            f"chapter number advanced unusually far ({last_number:g} -> {nums[-1]:g})"
        )

    # Real releases are contiguous; bogus lists tend to have holes
    # (53, 55-93, 103-104, ...).
    gaps = sum(1 for a, b in zip(nums, nums[1:]) if b - a > 2)
    if gaps >= 2:
        score += 1
        reasons.append(f"{gaps} numbering gaps inside the batch")

    return SuspicionResult(score >= SUSPICION_THRESHOLD, score, reasons)


def estimate_typical_batch_size(state, manga_title: str) -> Optional[float]:
    """Median batch size for a manga, derived from its download history.

    Downloads recorded within :data:`BATCH_GAP_HOURS` of each other count
    as one batch (a single check run). Returns ``None`` when there is no
    usable history.
    """
    try:
        history = state.get("download_history", []) or []
    except Exception:
        return None

    times = []
    for entry in history:
        if entry.get("title") != manga_title:
            continue
        try:
            times.append(datetime.fromisoformat(entry["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue

    if not times:
        return None

    times.sort()
    batch_sizes = [1]
    for prev, cur in zip(times, times[1:]):
        if (cur - prev).total_seconds() / 3600.0 <= BATCH_GAP_HOURS:
            batch_sizes[-1] += 1
        else:
            batch_sizes.append(1)

    return float(median(batch_sizes))


def get_days_since_last_update(state, manga_title: str) -> Optional[float]:
    """Days since the manga last received a chapter, from state."""
    try:
        last_updated = state.get_manga_state(manga_title).get("last_updated")
    except Exception:
        return None
    if not last_updated:
        return None
    try:
        then = datetime.fromisoformat(last_updated)
    except (TypeError, ValueError):
        return None
    return max((datetime.now() - then).total_seconds() / 86400.0, 0.0)


def evaluate_new_chapters(
    state,
    manga_title: str,
    new_numbers: List[float],
    last_number: float,
) -> SuspicionResult:
    """Convenience wrapper: pull per-manga history from state and score."""
    return evaluate_chapter_batch(
        new_numbers,
        last_number,
        typical_batch_size=estimate_typical_batch_size(state, manga_title),
        days_since_last_update=get_days_since_last_update(state, manga_title),
    )
