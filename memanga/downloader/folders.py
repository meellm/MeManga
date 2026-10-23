"""Managed download folders: rename, locate and delete a manga's files."""

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from .naming import (DEFAULT_NAMING_TEMPLATE, _chapter_base_name,
                     _chapter_filename_labels, _sanitize_filename)

# Extensions download_chapter gives one-file chapters.
_CHAPTER_FILE_SUFFIXES = (".pdf", ".epub", ".cbz", ".zip")


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


class UnsafeDownloadPathError(Exception):
    """A manga's download folder can't be deleted safely."""


def find_manga_downloads(download_dir, title: str) -> Optional[Path]:
    """Return the manga's managed download folder, or ``None`` if absent.

    Only ``<download_dir>/<sanitized title>`` is considered — the folder
    ``download_chapter`` writes to. Raises ``UnsafeDownloadPathError``
    when that entry is a symlink, not a directory, or resolves anywhere
    but directly inside the download root (issue #349).
    """
    root = Path(download_dir).expanduser()
    if not root.is_dir():
        return None
    name = _sanitize_filename(title)
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        raise UnsafeDownloadPathError(f"unusable folder name for {title!r}")
    target = root / name
    if not os.path.lexists(target):
        return None
    if target.is_symlink():
        raise UnsafeDownloadPathError(f"{target} is a symlink")
    if not target.is_dir():
        raise UnsafeDownloadPathError(f"{target} is not a directory")
    if target.resolve(strict=True).parent != root.resolve(strict=True):
        raise UnsafeDownloadPathError(f"{target} is outside {root}")
    return target


def _chapter_file_names(title: str, chapter: str, templates: List[str],
                        sources: List[str]) -> List[str]:
    """Names download_chapter writes, or older versions wrote, for
    ``chapter`` with each of ``templates`` and ``sources``."""
    labels = _chapter_filename_labels(str(chapter))
    bases = []
    for label in labels:
        for template in templates:
            for source in sources:
                bases.append(_chapter_base_name(template, title, label, source))
                # Older versions cut the whole name at the length cap.
                bases.append(_sanitize_filename(
                    template.replace("{title}", title)
                            .replace("{chapter}", label)
                            .replace("{source}", source)))
    names = []
    for base in dict.fromkeys(bases):
        names.extend(f"{base}{suffix}" for suffix in _CHAPTER_FILE_SUFFIXES)
    names.extend(f"Chapter {label}" for label in labels)
    return names


def find_chapter_downloads(download_dir, title: str, chapter: str, *,
                           templates: Iterable[str] = (),
                           sources: Iterable[str] = (),
                           recorded: Iterable[str] = (),
                           others: Iterable[str] = (),
                           claimed: Iterable[str] = ()) -> List[Path]:
    """Saved copies of one chapter, best match first (issue #355).

    Only entries directly inside the manga's managed folder count (see
    ``find_manga_downloads``; its ``UnsafeDownloadPathError`` propagates).
    ``recorded`` are paths from the download history, newest first; one
    elsewhere is ignored. Then come the names download_chapter writes for
    this chapter with ``templates`` (the default template is always
    tried) and ``sources`` (for ``{source}``; no source is always
    tried), in the current and older label forms: a file per one-file
    format, or an image format's ``Chapter <label>`` folder.

    A file must belong to this chapter. ``others`` are the manga's other
    chapter labels and ``claimed`` the history paths of those chapters: a
    name another chapter could have been saved under ("2.0" is an older
    name of chapter "2" and of chapter "2.0") is left out unless the
    history records it for this chapter, and a name recorded for another
    chapter is always left out. Nothing is matched loosely, and symlinks
    are never returned.
    """
    folder = find_manga_downloads(download_dir, title)
    if folder is None:
        return []
    resolved_folder = folder.resolve()

    def in_folder(paths):
        names = []
        for path in paths:
            path = Path(path)
            try:
                if path.parent.resolve() == resolved_folder:
                    names.append(path.name)
            except OSError:
                continue
        return names

    chapter = str(chapter)
    templates = list(dict.fromkeys([*templates, DEFAULT_NAMING_TEMPLATE]))
    sources = list(dict.fromkeys([*sources, ""]))
    claimed_names = set(in_folder(claimed))
    shared = set(claimed_names)
    for other in dict.fromkeys(str(o) for o in others):
        if other != chapter:
            shared.update(_chapter_file_names(title, other, templates, sources))
    names = [name for name in in_folder(recorded) if name not in claimed_names]
    names += [name for name in _chapter_file_names(title, chapter, templates, sources)
              if name not in shared]

    found = []
    for name in dict.fromkeys(names):
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        candidate = folder / name
        if candidate.is_symlink() or candidate in found:
            continue
        if candidate.is_file() or candidate.is_dir():
            found.append(candidate)
    return found


def delete_manga_downloads(download_dir, title: str) -> Optional[Path]:
    """Delete the manga's managed download folder; return what was removed.

    Returns ``None`` when there is nothing to delete. Symlinks inside the
    folder are unlinked, never followed.
    """
    target = find_manga_downloads(download_dir, title)
    if target is None:
        return None
    shutil.rmtree(target)
    return target
