"""Schema versions for config.yaml and state.json (issue #409).

Both files carry an integer ``schema_version`` that changes only when
their layout changes, not with every release. Loading upgrades an older
file in memory, one version at a time, with the functions registered in
a ``{old_version: migrate_fn}`` table (the same pattern as backup
imports in :mod:`memanga.backup`); the next normal save writes the
result and keeps the previous file as the ``.bak`` copy. A file written
by a newer MeManga is refused instead of being loaded and overwritten.

Files from before versioning have no ``schema_version`` and count as
version 0.

When a layout changes: bump the owner's version constant and register
``previous_version: migrate_fn`` in its table. A migration receives the
parsed file as a dict and returns it in the next version's layout; the
version field itself is stamped by :func:`migrate`.
"""

from typing import Any, Callable, Dict, Mapping

SCHEMA_VERSION_KEY = "schema_version"

Migration = Callable[[Dict[str, Any]], Dict[str, Any]]


class SchemaVersionError(ValueError):
    """A file's schema version can't be handled. The message is shown to
    the user as-is, so keep it short and self-explanatory."""


def migrate(data: Dict[str, Any], current: int,
            migrations: Mapping[int, Migration], name: str) -> Dict[str, Any]:
    """Return ``data`` upgraded to schema version ``current``.

    ``name`` names the file in error messages. Raises
    :class:`SchemaVersionError` when the version is malformed, newer than
    ``current`` or has no migration registered.
    """
    version = data.get(SCHEMA_VERSION_KEY, 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise SchemaVersionError(f"invalid {name} schema version: {version!r}")
    if version > current:
        raise SchemaVersionError(
            f"{name} schema version {version} is newer than this MeManga "
            f"supports (max {current}); update MeManga"
        )
    while version < current:
        step = migrations.get(version)
        if step is None:
            raise SchemaVersionError(
                f"{name} schema version {version} is not supported")
        data = step(data)
        version += 1
        data[SCHEMA_VERSION_KEY] = version
    return data


def add_schema_version(data: Dict[str, Any]) -> Dict[str, Any]:
    """Version 0 -> 1: the file gains ``schema_version``; nothing else
    changes."""
    return data
