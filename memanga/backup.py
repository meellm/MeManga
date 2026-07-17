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

from typing import Any, Callable, Dict, Mapping, Optional

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


def _chapter_sort_key(value: Any):
    try:
        return (0, float(value), str(value))
    except (TypeError, ValueError):
        return (1, str(value).lower())


def _merge_unique_chapters(local: Any, imported: Any) -> list:
    merged = {str(ch) for ch in (local or [])}
    merged.update(str(ch) for ch in (imported or []))
    return sorted(merged, key=_chapter_sort_key)


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
    return max((local, imported), key=_chapter_sort_key)


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

    for key in ("failed_chapters", "pending_backup"):
        imported_map = imported.get(key) if isinstance(imported.get(key), dict) else {}
        local_map = local.get(key) if isinstance(local.get(key), dict) else {}
        if imported_map or local_map:
            merged[key] = {**imported_map, **local_map}

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
