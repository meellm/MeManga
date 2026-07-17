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

from typing import Any, Callable, Dict

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
