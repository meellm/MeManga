"""Chapter model shared by scrapers, state, the downloader, CLI and GUI.

Chapter identifiers stay strings everywhere ("1", "12.5", "10 Part 1",
"Extra"). Code that needs a number, an order or a display value for one
uses the helpers here, so every caller reads a label the same way:

- a plain number (".5", "12", "12.5", "-1", " 7 ") is its own value;
- any other label counts by its first embedded unsigned number
  ("Chapter 10", "10 Part 1" -> 10);
- a label with no number ("Extra") has no value and sorts as 0.0.

Only finite values are produced, so sort keys always form a total order.
This module imports only the standard library, so State and the CLI can
use it without loading the scrapers or the downloader.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

CHAPTER_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

# A whole identifier that is just a decimal number: optional sign, digits
# with an optional fraction, or a leading-dot fraction (".5"). Exponents,
# "nan" and "inf" are not chapter numbers.
PLAIN_NUMBER_RE = re.compile(r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*")


def chapter_number(label: Any) -> Optional[float]:
    """Return the first unsigned number embedded in a label, or None.

    This is the fallback half of :func:`chapter_value`; use that to read
    a chapter identifier.
    """
    match = CHAPTER_NUMBER_RE.search(str(label))
    if not match:
        return None
    return float(match.group(1))


def chapter_value(label: Any) -> Optional[float]:
    """Numeric value of a chapter identifier, or None when it has none.

    A plain number (".5", "12", "12.5", "-1") is read as is; anything else
    falls back to its first embedded number, so "Chapter 10" and
    "10 Part 1" are 10. The result is always finite.
    """
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        value = float(label)
        return value if math.isfinite(value) else None
    text = str(label)
    if PLAIN_NUMBER_RE.fullmatch(text):
        return float(text)
    return chapter_number(text)


def chapter_sort_key(chapter: Any) -> float:
    """Numeric sort key for a chapter identifier: its chapter_value.

    Plain numbers sort by value and labelled numbers like "2 Part 1" or
    "Chapter 10" by their first embedded number, so labelled chapters land
    after their plain predecessors and the reader's Next controls can reach
    a prefetched "2 Part 1" from chapter "1" (issue #107). Fully
    non-numeric labels sort as 0.0.
    """
    value = chapter_value(chapter)
    return value if value is not None else 0.0


def chapter_order_key(chapter: Any) -> Tuple[float, str, str]:
    """Total order for chapter identifiers: chapter_sort_key, then label.

    Use it where the input order is arbitrary (sets, merged lists) so
    labels with the same number ("10" and "10 Part 1", or several
    non-numeric extras) still come out in a stable order. Labels compare
    case-insensitively first, as backup merges always did.
    """
    label = str(chapter)
    return (chapter_sort_key(chapter), label.casefold(), label)


def format_chapter_value(value: float) -> str:
    """Display a numeric chapter value the way scrapers write it ("47",
    not "47.0"; "12.5" stays "12.5")."""
    return str(int(value)) if value == int(value) else str(value)


@dataclass
class Chapter:
    """Represents a manga chapter."""
    number: str  # Can be "1", "1.5", "Extra", etc.
    title: Optional[str] = None
    url: str = ""
    date: Optional[str] = None

    def __lt__(self, other):
        """Compare chapters by number for sorting."""
        return self.numeric < other.numeric

    @property
    def numeric(self) -> float:
        """Get numeric chapter number (0.0 when the label has none)."""
        value = chapter_value(self.number)
        return value if value is not None else 0.0


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
        self.group_ids = getattr(chapter, "group_ids", [])
        self.group_names = getattr(chapter, "group_names", [])
