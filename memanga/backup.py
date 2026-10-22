"""Backup (export/import) schema versioning.

The CLI (``memanga export`` / ``memanga import``) and the GUI settings
page write the same JSON payload, stamped with a schema ``version`` so
a future format change can be migrated or rejected instead of imported
blindly::

    {"version": 1, "exported_at": ..., "manga": [...], "state": {...}}

Importers call :func:`validate_backup` before touching the payload and
show :class:`BackupVersionError` messages to the user as-is, so keep
them short and self-explanatory.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .chapters import chapter_order_key

EXPORT_VERSION = 1

# Migrations from an older schema version to the next one. When
# EXPORT_VERSION is bumped, register ``old_version: migrate_fn`` here so
# backups from previous releases keep importing.
_MIGRATIONS: Dict[int, Callable[[dict], dict]] = {}


class BackupVersionError(ValueError):
    """An import payload's schema version can't be handled."""


def validate_backup(data: Any) -> dict:
    """Check an import payload's schema ``version``, migrating if needed.

    Returns the payload, migrated up to :data:`EXPORT_VERSION` when it
    was produced by an older supported schema. Raises
    :class:`BackupVersionError` with a user-facing message when the
    version is missing, malformed, unsupported, or newer than this app
    understands. Exports have stamped ``version`` since the feature
    shipped, so a missing field means the file isn't a MeManga export.
    """
    if not isinstance(data, dict):
        raise BackupVersionError("Not a MeManga backup file")

    version = data.get("version")
    if version is None:
        raise BackupVersionError("Not a MeManga backup: no version field")
    if isinstance(version, bool) or not isinstance(version, int):
        raise BackupVersionError(f"Invalid backup version: {version!r}")
    if version > EXPORT_VERSION:
        raise BackupVersionError(
            f"Backup version {version} is newer than this app supports "
            f"(max {EXPORT_VERSION}); update MeManga"
        )
    if "state" in data and not isinstance(data["state"], dict):
        raise BackupVersionError("Invalid backup: state must be an object")

    while version < EXPORT_VERSION:
        migrate = _MIGRATIONS.get(version)
        if migrate is None:
            raise BackupVersionError(
                f"Backup version {version} is not supported"
            )
        data = migrate(data)
        version += 1

    return data


def validate_backup_contents(data: dict) -> Tuple[List[dict], Dict[str, dict]]:
    """Check a version-validated payload's ``manga`` and ``state`` shapes.

    Issue #354: the CLI import checks the whole payload before it writes
    anything, so a malformed file is rejected instead of crashing halfway
    through or landing in config.yaml as-is. Returns ``(manga, state)``;
    raises :class:`BackupVersionError` with a user-facing message.
    """
    if "manga" not in data:
        raise BackupVersionError("Invalid backup: missing 'manga' key")
    manga = data["manga"]
    if not isinstance(manga, list):
        raise BackupVersionError("Invalid backup: manga must be a list")
    for index, entry in enumerate(manga, 1):
        if not isinstance(entry, dict):
            raise BackupVersionError(
                f"Invalid backup: manga entry {index} must be an object"
            )
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            raise BackupVersionError(
                f"Invalid backup: manga entry {index} has no title"
            )
        # Issue #246: fields the downloader reads must have the shape
        # MeManga writes, or they would land in config.yaml and fail later.
        for key, (expected, ok) in _MANGA_FIELD_CHECKS.items():
            if key in entry and not ok(entry[key]):
                raise BackupVersionError(
                    f"Invalid backup: manga entry {index} ({title!r}): "
                    f"{key} must be {expected}"
                )

    manga_state = data.get("state", {})
    if manga_state is None:
        manga_state = {}
    if not isinstance(manga_state, dict):
        raise BackupVersionError("Invalid backup: state must be an object")
    for title, entry in manga_state.items():
        if not isinstance(entry, dict):
            raise BackupVersionError(
                f"Invalid backup: state for {title!r} must be an object"
            )
        for key, value in entry.items():
            check = _STATE_FIELD_CHECKS.get(key)
            if check is None or (value is None and key not in _NON_NULL_STATE_FIELDS):
                continue
            expected, ok = check
            if not ok(value):
                raise BackupVersionError(
                    f"Invalid backup: state for {title!r}: {key} must be {expected}"
                )

    return manga, manga_state


def _is_chapter_label(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _is_label_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_chapter_label(v) for v in value)


def _is_record_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, dict) for v in value)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_source_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(s, str)
        or (isinstance(s, dict) and isinstance(s.get("url", ""), str)
            and isinstance(s.get("source") or "", str))
        for s in value
    )


# Manga entry fields the downloader and update check read, with the
# shape MeManga writes them (legacy ``source``/``url`` or a ``sources``
# list of URLs or {"url", "source"} objects). Checked only when present;
# other keys pass through as-is.
_MANGA_FIELD_CHECKS: Dict[str, Tuple[str, Callable[[Any], bool]]] = {
    "url": ("text", lambda v: isinstance(v, str)),
    "source": ("text", lambda v: isinstance(v, str)),
    "sources": ("a list of URLs or source objects", _is_source_list),
    "fallback_delay_days": ("a whole number", _is_count),
}


# Per-manga state fields that merge_manga_state and the State readers
# consume, with the shape State itself writes. ``None`` is accepted
# (fresh entries store it) except for _NON_NULL_STATE_FIELDS; unknown
# keys pass through as-is.
_STATE_FIELD_CHECKS: Dict[str, Tuple[str, Callable[[Any], bool]]] = {
    "downloaded": ("a list of chapter numbers", _is_label_list),
    "read_chapters": ("a list of chapter numbers", _is_label_list),
    "external_chapters": ("a list of chapter numbers", _is_label_list),
    "available_chapters": ("a list of objects", _is_record_list),
    "failed_chapters": ("an object", lambda v: isinstance(v, dict)),
    "pending_backup": ("an object", lambda v: isinstance(v, dict)),
    "partial_chapters": ("an object", lambda v: isinstance(v, dict)),
    "undelivered_chapters": ("an object", lambda v: isinstance(v, dict)),
    "resolved_deliveries": ("an object", lambda v: isinstance(v, dict)),
    "saved_chapter_groups": ("an object", lambda v: isinstance(v, dict)),
    "reading_progress": ("an object", lambda v: isinstance(v, dict)),
    "reader_positions": ("an object", lambda v: isinstance(v, dict)),
    "new_chapters_available": ("a whole number", _is_count),
    "last_chapter": ("a chapter number", _is_chapter_label),
    "last_updated": ("a date string", lambda v: isinstance(v, str)),
    "created": ("a date string", lambda v: isinstance(v, str)),
}

# State never stores these as null, and its readers call ``.get`` on
# them directly (State.get_reader_position), so null is malformed too.
_NON_NULL_STATE_FIELDS = frozenset({"reader_positions"})


def _merge_unique_chapters(local: Any, imported: Any) -> list:
    merged = {str(ch) for ch in (local or [])}
    merged.update(str(ch) for ch in (imported or []))
    return sorted(merged, key=chapter_order_key)


def _chapter_record_key(record: Any):
    if not isinstance(record, dict):
        return repr(record)
    return (
        str(record.get("number", "")),
        str(record.get("source_url") or record.get("url") or ""),
        str(record.get("source", "")),
        bool(record.get("is_backup", False)),
    )


def _merge_chapter_records(local: Any, imported: Any) -> list:
    merged = []
    seen = set()
    for record in list(local or []) + list(imported or []):
        key = _chapter_record_key(record)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def _newer_progress(local: Any, imported: Any) -> dict:
    if not isinstance(local, dict):
        return imported if isinstance(imported, dict) else {}
    if not isinstance(imported, dict):
        return local

    local_time = local.get("last_read")
    imported_time = imported.get("last_read")
    if imported_time and (not local_time or str(imported_time) > str(local_time)):
        return {**local, **imported}
    return {**imported, **local}


def _max_value(local: Any, imported: Any):
    if local in (None, ""):
        return imported
    if imported in (None, ""):
        return local
    return max(local, imported)


def _max_chapter(local: Any, imported: Any):
    if local in (None, ""):
        return imported
    if imported in (None, ""):
        return local
    return max((local, imported), key=chapter_order_key)


def _instant(record: Any, key: str) -> Optional[datetime]:
    """The time ``record[key]`` names, or None when it can't be ordered.

    Delivery records written since issue #360 carry UTC times with an
    offset. A legacy naive local time, or anything that doesn't parse,
    names no instant: its order against another machine's or another
    zone's time is unknown.
    """
    if not isinstance(record, dict):
        return None
    try:
        value = datetime.fromisoformat(str(record.get(key) or ""))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def _after(record: Any, record_key: str, other: Any, other_key: str) -> bool:
    """True only when both times are known and ``record`` is later."""
    mine = _instant(record, record_key)
    theirs = _instant(other, other_key)
    return mine is not None and theirs is not None and mine > theirs


def _resolution_instant(resolution: Any) -> Optional[datetime]:
    """When ``resolution`` provably happened, or None when its order is
    unknown: a legacy or unparseable time, or a merged marker that once
    absorbed one (``"unordered": true``)."""
    if isinstance(resolution, dict) and resolution.get("unordered"):
        return None
    return _instant(resolution, "resolved_at")


def _failed_after(record: Any, resolution: Any) -> bool:
    """True only when ``record`` provably failed after ``resolution``."""
    failed = _instant(record, "failed_at")
    resolved = _resolution_instant(resolution)
    return failed is not None and resolved is not None and failed > resolved


def _merge_resolutions(markers: List[Any]) -> Any:
    """One chapter's resolution markers, local first, merged into one.

    The provably latest marker wins, else the first (local) one. If any
    marker can't be ordered, the result is marked ``"unordered": true``
    for good: dropping that marker would let a later import compare a
    pending record against the remaining time alone and queue a
    delivered chapter again. Like a deletion tombstone, the marker
    has to survive every later merge.
    """
    best = markers[0]
    for marker in markers[1:]:
        if _after(marker, "resolved_at", best, "resolved_at"):
            best = marker
    if any(_resolution_instant(m) is None for m in markers):
        best = {**best, "unordered": True} if isinstance(best, dict) else {"unordered": True}
    return best


def _delivery_maps(side: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = side.get(key)
    return value if isinstance(value, dict) else {}


def _merge_deliveries(merged: Dict[str, Any], local: Dict[str, Any],
                      imported: Dict[str, Any]) -> None:
    """Merge Kindle delivery records (issue #360) into ``merged``.

    Each side's pending record of a chapter is checked on its own against
    every resolution (sent, or dismissed) of that chapter, so an older
    record on one side cannot hide a newer failure on the other. A
    record, local or imported, survives only when it is provably later
    than every resolution; a chapter with no resolution keeps its records
    as before.

    "Provably" needs both times to carry a UTC offset; legacy naive or
    unparseable times are unordered. An unordered record is dropped
    rather than kept: losing a retry (the user can still send the file
    from its folder) is preferred to sending a delivered chapter twice.
    When both records survive, the later one wins, else the local one.

    Resolutions merge into one marker per chapter (see
    :func:`_merge_resolutions`) and pending records are checked against
    that stored marker, so a later import sees exactly what this one
    enforced. Only a new local failure or resolution replaces a marker
    (``FailureStore``), since it happens after everything already known.
    """
    imported_pending = _delivery_maps(imported, "undelivered_chapters")
    local_pending = _delivery_maps(local, "undelivered_chapters")
    imported_resolved = _delivery_maps(imported, "resolved_deliveries")
    local_resolved = _delivery_maps(local, "resolved_deliveries")

    resolved: Dict[str, Any] = {
        chapter: _merge_resolutions(
            [side[chapter] for side in (local_resolved, imported_resolved)
             if chapter in side])
        for chapter in set(local_resolved) | set(imported_resolved)
    }

    pending: Dict[str, Any] = {}
    for chapter in set(imported_pending) | set(local_pending):
        resolution = resolved.get(chapter)
        candidates = [
            side[chapter] for side in (imported_pending, local_pending)
            if chapter in side
            and (resolution is None or _failed_after(side[chapter], resolution))
        ]
        if len(candidates) == 2:
            # [imported, local]: the later failure, else the local one.
            pending[chapter] = (candidates[0]
                                if _after(candidates[0], "failed_at",
                                          candidates[1], "failed_at")
                                else candidates[1])
        elif candidates:
            pending[chapter] = candidates[0]

    for key, value in (("undelivered_chapters", pending),
                       ("resolved_deliveries", resolved)):
        if value or key in merged:
            merged[key] = value


def merge_manga_state(local: Dict[str, Any], imported: Dict[str, Any]) -> Dict[str, Any]:
    """Merge one manga's imported backup state into local state.

    The policy is intentionally conservative: never replace the whole
    local record, union list-like chapter state, merge per-chapter maps
    without overwriting local entries, and only take imported scalar
    metadata when the local record is missing it.
    """
    if not isinstance(local, dict):
        local = {}
    if not isinstance(imported, dict):
        imported = {}

    merged = {**imported, **local}

    for key in ("downloaded", "read_chapters", "external_chapters"):
        merged[key] = _merge_unique_chapters(local.get(key), imported.get(key))

    for key in ("available_chapters",):
        merged[key] = _merge_chapter_records(local.get(key), imported.get(key))

    for key in ("failed_chapters", "pending_backup", "partial_chapters",
                "saved_chapter_groups"):
        imported_map = imported.get(key) if isinstance(imported.get(key), dict) else {}
        local_map = local.get(key) if isinstance(local.get(key), dict) else {}
        if imported_map or local_map:
            merged[key] = {**imported_map, **local_map}

    _merge_deliveries(merged, local, imported)

    merged["reading_progress"] = _newer_progress(
        local.get("reading_progress"),
        imported.get("reading_progress"),
    )
    merged["new_chapters_available"] = _max_value(
        local.get("new_chapters_available", 0),
        imported.get("new_chapters_available", 0),
    ) or 0

    if "last_chapter" in imported or "last_chapter" in local:
        merged["last_chapter"] = _max_chapter(
            local.get("last_chapter"),
            imported.get("last_chapter"),
        )
    if "last_updated" in imported or "last_updated" in local:
        merged["last_updated"] = _max_value(
            local.get("last_updated"),
            imported.get("last_updated"),
        )

    if imported.get("created") and not local.get("created"):
        merged["created"] = imported["created"]

    return merged


def merge_backup_state(
    local_state: Dict[str, Dict[str, Any]],
    imported_state: Dict[str, Dict[str, Any]],
    *,
    title_aliases: Optional[Mapping[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Merge all imported manga state entries into local manga state."""
    if not isinstance(local_state, dict):
        local_state = {}
    if not isinstance(imported_state, dict):
        imported_state = {}
    if title_aliases is None:
        title_aliases = {}
    casefolded_aliases = {
        title.casefold(): canonical
        for title, canonical in title_aliases.items()
        if isinstance(title, str)
    }

    merged = dict(local_state)
    for title, imported_entry in imported_state.items():
        alias_title = title_aliases.get(title) if isinstance(title, str) else None
        if alias_title is None and isinstance(title, str):
            alias_title = casefolded_aliases.get(title.casefold())
        if alias_title and alias_title != title:
            merged[alias_title] = merge_manga_state(
                merged.get(alias_title, {}),
                imported_entry,
            )
        elif title in merged:
            merged[title] = merge_manga_state(merged[title], imported_entry)
        else:
            merged[title] = imported_entry
    return merged
