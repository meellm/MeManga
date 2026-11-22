"""Config directory lock across processes (issue #244).

The competing holder is a real second Python process (``lock_holder``),
because the lock only means something between processes.
"""

from __future__ import annotations

import errno
import subprocess
import sys

import pytest

from memanga import process_lock
from memanga.process_lock import (LOCK_FILENAME, ConfigDirBusy, ConfigDirLock,
                                  ConfigDirLockError)


@pytest.fixture
def cfg_dir(tmp_path):
    return tmp_path / "cfg"


def test_acquire_creates_dir_and_lock_file(cfg_dir, lock_holder):
    with ConfigDirLock(cfg_dir) as lock:
        assert lock.acquired
        assert (cfg_dir / LOCK_FILENAME).is_file()
        assert not lock_holder.can_lock(cfg_dir)
    assert not lock.acquired
    assert lock_holder.can_lock(cfg_dir)


def test_lock_held_by_another_process_is_busy(cfg_dir, lock_holder):
    proc = lock_holder.hold(cfg_dir)
    lock = ConfigDirLock(cfg_dir)
    with pytest.raises(ConfigDirBusy) as exc:
        lock.acquire()
    assert exc.value.config_dir == cfg_dir
    assert not lock.acquired
    lock_holder.release(proc)
    with lock:
        assert lock.acquired


def test_killed_holder_leaves_no_stale_lock(cfg_dir, lock_holder):
    proc = lock_holder.hold(cfg_dir)
    proc.kill()
    proc.wait(timeout=30)
    # The OS dropped the lock with the process; the file stays and
    # nothing had to be cleaned up.
    assert (cfg_dir / LOCK_FILENAME).is_file()
    with ConfigDirLock(cfg_dir) as lock:
        assert lock.acquired


def test_reacquire_after_release(cfg_dir):
    lock = ConfigDirLock(cfg_dir)
    for _ in range(3):
        lock.acquire()
        lock.release()
    lock.release()  # extra release does nothing
    assert process_lock._key(cfg_dir) not in process_lock._held


def test_same_process_nests_instead_of_locking_itself(cfg_dir, lock_holder):
    outer = ConfigDirLock(cfg_dir).acquire()
    inner = ConfigDirLock(cfg_dir / ".").acquire()
    assert inner.acquired
    inner.release()
    assert not lock_holder.can_lock(cfg_dir)
    outer.release()
    assert lock_holder.can_lock(cfg_dir)


def test_acquire_twice_on_one_instance_holds_once(cfg_dir, lock_holder):
    lock = ConfigDirLock(cfg_dir)
    lock.acquire()
    lock.acquire()
    lock.release()
    assert lock_holder.can_lock(cfg_dir)


def test_child_processes_do_not_inherit_the_lock(cfg_dir, lock_holder):
    lock = ConfigDirLock(cfg_dir).acquire()
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.readline()"],
        stdin=subprocess.PIPE, text=True)
    try:
        lock.release()
        assert lock_holder.can_lock(cfg_dir)
    finally:
        child.stdin.close()
        child.wait(timeout=30)


def test_other_lock_failure_is_an_error_not_busy(cfg_dir, monkeypatch):
    def _unsupported(fd):
        raise OSError(errno.ENOLCK, "No locks available")
    monkeypatch.setattr(process_lock, "_lock_fd", _unsupported)
    lock = ConfigDirLock(cfg_dir)
    with pytest.raises(ConfigDirLockError) as exc:
        lock.acquire()
    assert exc.value.errno == errno.ENOLCK
    assert not lock.acquired
    assert process_lock._key(cfg_dir) not in process_lock._held


def test_unusable_config_dir_is_an_error(tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigDirLockError):
        ConfigDirLock(not_a_dir).acquire()
