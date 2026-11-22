"""
Safe file persistence shared by Config and State (issue #243).

Durability: file contents are fsynced before they are published with
os.replace, and the directory is fsynced afterwards where the platform
allows it (_fsync_dir). That is best effort: Windows and some filesystems
do not support it, and then a power loss right after a save can still
bring back the previous file (never a torn one).

A process killed hard inside a save can leave a ``*.tmp`` file next to
the config files. Such files are never read; they are not swept up
automatically because a temp of a save running in another process looks
the same.
"""

import errno
import hashlib
import os
import secrets
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


class SaveError(OSError):
    """A file could not be saved. The file and its backup were left as
    they were. An OSError, so existing ``except OSError`` handlers still
    apply; ``error`` is the underlying OSError."""

    def __init__(self, path: Path, error: OSError):
        self.path = Path(path)
        self.error = error
        super().__init__(
            f"could not save {self.path}: {error.strerror or error}")
        self.errno = error.errno


def atomic_write_text(path: Path, text: str, backup_path: Optional[Path] = None):
    """Write ``text`` to ``path`` atomically.

    The data goes to a temp file in the same directory, is flushed to disk,
    then replaces ``path`` with os.replace, so a crash leaves either the old
    or the new file, never a torn one.

    With ``backup_path`` the current file becomes the backup (one
    generation). The new backup is prepared at a temp path before anything
    is replaced; if that fails the save raises OSError and both the file
    and the existing backup are left as they were. The existing backup is
    only replaced once the new file is in place, so a failed save never
    costs the previous backup. Storage errors are raised as SaveError.
    """
    path = Path(path)
    backup_tmp = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    except OSError as e:
        raise SaveError(path, e) from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if backup_path is not None:
            backup_tmp = _prepare_backup(path, Path(backup_path))
        os.replace(tmp_path, path)
    except BaseException as e:
        for leftover in (tmp_path, backup_tmp):
            if leftover is None:
                continue
            try:
                os.unlink(leftover)
            except OSError:
                pass
        if isinstance(e, OSError) and not isinstance(e, SaveError):
            raise SaveError(path, e) from e
        raise
    try:
        if backup_tmp is not None:
            try:
                os.replace(backup_tmp, backup_path)
            except BaseException as e:
                # The new file is already saved. Keep the existing backup
                # (one generation older, still valid) rather than lose it.
                try:
                    os.unlink(backup_tmp)
                except OSError:
                    pass
                if not isinstance(e, OSError):
                    raise
    finally:
        # Also when interrupted here: the new file is already in place.
        _fsync_dir(path.parent)


def _fsync_dir(directory: Path):
    """Flush a directory entry change (rename, create) to disk.

    Best effort: Windows cannot open a directory for this and some
    filesystems reject fsync on a directory; the save itself has already
    succeeded, so failures are ignored.
    """
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _copy_durable(src: Path, dst: Path):
    """Copy ``src`` to a new file ``dst`` and fsync it.

    ``dst`` is created exclusively (an existing file is never replaced)
    with ``src``'s permission bits from the start, so a copy of a private
    file (config may hold secrets) is never readable by others, not even
    while it is written. Raises OSError; a partial ``dst`` is removed.
    """
    mode = stat.S_IMODE(os.stat(src).st_mode)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_BINARY", 0), mode)
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as source:
            shutil.copyfileobj(source, out)
            out.flush()
            os.fsync(out.fileno())
        # Exact bits even if the umask narrowed them at creation.
        shutil.copymode(src, dst)
    except BaseException:
        try:
            os.unlink(dst)
        except OSError:
            pass
        raise


def _prepare_backup(path: Path, backup_path: Path) -> Optional[Path]:
    """Put a copy of the current ``path`` at a temp name next to
    ``backup_path`` and return that name, or None when there is no file
    to back up yet. Raises OSError if the copy cannot be made; a partial
    copy is removed.

    A hard link is free and keeps the old file once os.replace swaps in the
    new one; filesystems without hard links get a copy instead.
    """
    if not path.exists():
        return None
    tmp = backup_path.with_name(
        f"{backup_path.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")
    try:
        os.link(path, tmp)
    except OSError:
        # No hard links here: a durable copy (removed again on failure).
        _copy_durable(path, tmp)
    return tmp


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _open_regular(path: Path, not_inode=None):
    """Open ``path`` read-only if it is a regular file itself (not a
    symlink) and not the file identified by ``not_inode`` (st_dev,
    st_ino). Returns ``(fd, stat_result)`` or None.

    The checks run on the open descriptor (fstat), so the file cannot be
    swapped between the check and the read. O_NOFOLLOW refuses a symlink
    where the platform has it; elsewhere the lstat/fstat identity
    comparison catches one.
    """
    try:
        before = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode):
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    same_entry = (st.st_dev, st.st_ino) == (before.st_dev, before.st_ino)
    if (not stat.S_ISREG(st.st_mode) or not same_entry
            or (not_inode is not None and (st.st_dev, st.st_ino) == not_inode)):
        os.close(fd)
        return None
    return fd, st


def _identical_copy(path: Path) -> Optional[Path]:
    """An existing preserved copy (``<name>.corrupt-*``) with the same
    bytes as ``path``, or None. Only reads.

    Accepted only if it is an independent regular file: not a symlink
    and not another name for ``path`` itself (same inode), because the
    caller may delete ``path`` once it has a copy. Copies are only ever
    published under this name complete and are never removed by
    MeManga afterwards (see preserve_corrupt), so a match is a durable
    copy, not one still being written.
    """
    # The primary itself may legitimately be a symlink (dotfile setups),
    # so it is opened normally; its real inode is what candidates must
    # not share.
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        primary = os.fstat(fd)
        digest = None
        for candidate in sorted(path.parent.glob(f"{path.name}.corrupt-*")):
            found = _open_regular(candidate, (primary.st_dev, primary.st_ino))
            if found is None:
                continue
            cfd, cst = found
            try:
                if cst.st_size != primary.st_size:
                    continue
                if digest is None:
                    digest = _sha256_fd(fd)
                if _sha256_fd(cfd) == digest:
                    return candidate
            except OSError:
                continue
            finally:
                os.close(cfd)
    except OSError:
        return None
    finally:
        os.close(fd)
    return None


def preserve_corrupt(path: Path) -> Path:
    """Copy a damaged ``path`` to ``<name>.corrupt-<timestamp>-<random>``
    and return the copy's path. ``path`` itself is left in place, so the
    caller only replaces or removes it once whatever comes next has
    worked.

    A real copy, not a hard link: an in-place edit of ``path`` must not
    change the preserved copy. If one already holds exactly these bytes
    (a restore that keeps failing on every start), that copy is returned
    instead of adding another.

    The copy is written and fsynced under a private temp name that does
    not match ``<name>.corrupt-*`` (Maildir-style tmp, then publish), so
    another process never sees, and never reuses, a copy that is still
    being written. It is published under a name nobody else uses (random
    suffix) by a hard link, which never replaces an existing entry
    (POSIX link(): EEXIST); where hard links are not supported, by a
    rename (never replaces on Windows; elsewhere the name is unique and
    checked first). Once published a copy is never removed again: on
    failure only the private temp is deleted. Raises OSError.
    """
    path = Path(path)
    existing = _identical_copy(path)
    if existing is not None:
        return existing
    token = secrets.token_hex(8)
    tmp = path.with_name(f"{path.name}.preserving-{token}.tmp")
    _copy_durable(path, tmp)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}-{token}")
    try:
        try:
            os.link(tmp, target)
            linked = True
        except FileExistsError:
            raise
        except OSError:
            linked = False  # no hard links on this filesystem
        if not linked:
            if os.path.lexists(target):
                raise FileExistsError(
                    errno.EEXIST, "preserved copy name in use", str(target))
            os.rename(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if linked:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # an inert extra name for the published copy
    _fsync_dir(path.parent)
    return target
