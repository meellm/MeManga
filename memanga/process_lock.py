"""
One state-changing MeManga process per config directory (issue #244).

Config and State serialize threads with their own locks, but each process
loads config.yaml and state.json, works for a while and then writes full
snapshots, so two processes on one directory lose each other's updates.
ConfigDirLock is taken before anything is loaded and held until the last
write.

The lock is an OS advisory lock on ``<config dir>/memanga.lock``:
``fcntl.flock`` on Linux and macOS, ``msvcrt.locking`` on Windows. The OS
owns it and drops it when the process exits or is killed, so a crash never
leaves a stale lock behind and nothing ever has to be cleaned up. The file
itself is left in place: deleting it while another process holds it would
let a third process lock a new file next to it. Python opens the file
non-inheritable, so child processes (browsers, post-process commands) never
keep the lock alive.

Acquiring never waits. A lock held by another process raises
ConfigDirBusy; a lock that cannot be taken at all (a file system without
lock support) raises ConfigDirLockError, so callers never continue
unprotected.
"""

import errno
import os
import threading
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

LOCK_FILENAME = "memanga.lock"

# errno values for "locked by someone else": flock(LOCK_NB) reports
# EWOULDBLOCK/EAGAIN; msvcrt.locking(LK_NBLCK) reports EACCES or EDEADLOCK.
_BUSY_ERRNOS = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES,
                getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK}

# Locks this process holds, by normalized directory: [fd, holders]. A
# second acquire for the same directory (``memanga --gui`` hands the CLI's
# lock to the GUI) only counts up instead of locking against itself.
_held = {}
_held_guard = threading.Lock()


class ConfigDirBusy(Exception):
    """Another process holds the lock for this config directory."""

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        super().__init__(f"{self.config_dir} is in use by another MeManga process")


class ConfigDirLockError(OSError):
    """The lock could not be taken for a reason other than another holder."""

    def __init__(self, config_dir: Path, error: OSError):
        self.config_dir = Path(config_dir)
        self.error = error
        super().__init__(
            f"cannot lock {self.config_dir}: {error.strerror or error}")
        self.errno = error.errno


def _key(config_dir: Path) -> str:
    return os.path.normcase(os.path.realpath(config_dir))


def _lock_fd(fd: int):
    if os.name == "nt":
        # Byte 0; a range past the end of the file may be locked.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int):
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass  # closing the descriptor below releases it anyway
    finally:
        os.close(fd)


class ConfigDirLock:
    """Exclusive inter-process lock for one config directory.

    Use as a context manager or call acquire()/release(). One instance
    holds the lock at most once; release() without a matching acquire()
    does nothing.
    """

    def __init__(self, config_dir):
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / LOCK_FILENAME
        self._key = _key(self.config_dir)
        self._acquired = False
        self._joined = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    @property
    def joined(self) -> bool:
        """True when acquire() joined a lock this process already held."""
        return self._acquired and self._joined

    def acquire(self) -> "ConfigDirLock":
        if self._acquired:
            return self
        with _held_guard:
            entry = _held.get(self._key)
            if entry is not None:
                entry[1] += 1
                self._acquired = True
                self._joined = True
                return self
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as e:
                raise ConfigDirLockError(self.config_dir, e) from e
            try:
                _lock_fd(fd)
            except OSError as e:
                os.close(fd)
                if e.errno in _BUSY_ERRNOS:
                    raise ConfigDirBusy(self.config_dir) from e
                raise ConfigDirLockError(self.config_dir, e) from e
            except BaseException:
                os.close(fd)
                raise
            _held[self._key] = [fd, 1]
            self._acquired = True
            self._joined = False
            return self

    def release(self):
        if not self._acquired:
            return
        with _held_guard:
            self._acquired = False
            entry = _held.get(self._key)
            if entry is None:
                return
            entry[1] -= 1
            if entry[1] > 0:
                return
            del _held[self._key]
            _unlock_fd(entry[0])

    def __enter__(self) -> "ConfigDirLock":
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
