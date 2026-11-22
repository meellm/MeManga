"""Tests for the frozen-entry helpers in memanga/gui/__main__.py.

The module body is gated on ``sys.frozen`` and imports the GUI at the
bottom, so the helper functions are exec'd from the file header instead
of imported.

Core regression (issue #28): ``PLAYWRIGHT_BROWSERS_PATH`` must be pinned
unconditionally. Playwright's driver transport forces the variable to
``"0"`` (browsers inside the application bundle) for frozen builds when
it is unset, and no browsers ship in the bundle — so the old "set it
only if the directory already exists" logic broke every Playwright
source for the entire first session on a fresh machine.
"""

from __future__ import annotations

import ast
import os
import socket
import sys
from pathlib import Path

import pytest

import memanga


def _entry_helpers() -> dict:
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    header = src.split("if getattr(sys")[0]
    ns: dict = {}
    exec(header, ns)
    return ns


def test_playwright_verifier_uses_absolute_required_browsers_import():
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    verifier = src.split("def _verify_playwright", 1)[1].split(
        "def main", 1,
    )[0]

    assert "from memanga.gui import _REQUIRED_BROWSERS" in verifier
    assert "from . import _REQUIRED_BROWSERS" not in verifier


class TestConfigurePlaywrightBrowsers:
    def test_env_pinned_even_when_dir_missing(self, monkeypatch, tmp_path):
        ns = _entry_helpers()
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        # Point every platform cache root at an empty location so the
        # computed browsers dir definitely does not exist yet (a fresh
        # machine before the first-launch install).
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "nope"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nope"))
        monkeypatch.setattr(
            ns["Path"], "home", classmethod(lambda cls: tmp_path / "home"),
        )

        result = ns["_configure_playwright_browsers"]()

        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(result)
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] != "0"
        assert result.name == "ms-playwright"
        # The whole point: pinned before the directory exists, so the
        # transport's frozen setdefault("0") can never engage.
        assert not result.exists()

    def test_explicit_user_value_is_honoured(self, monkeypatch, tmp_path):
        ns = _entry_helpers()
        custom = tmp_path / "my-browsers"
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(custom))

        result = ns["_configure_playwright_browsers"]()

        assert result == custom
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(custom)

    def test_bundle_sentinel_is_replaced(self, monkeypatch):
        # "0" means "inside the bundle" — never valid for this app, the
        # bundle ships no browsers. It must be replaced with a real dir.
        ns = _entry_helpers()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")

        result = ns["_configure_playwright_browsers"]()

        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] != "0"
        assert result.name == "ms-playwright"

    def test_browsers_dir_matches_playwright_default_layout(self):
        ns = _entry_helpers()
        d = ns["_playwright_browsers_dir"]()
        assert d.name == "ms-playwright"
        assert d.is_absolute()


def _cacert(root: Path) -> Path:
    pem = root / "certifi" / "cacert.pem"
    pem.parent.mkdir(parents=True)
    pem.write_text("bundle\n")
    return pem


class TestConfigureCaBundle:
    """Issue #300: certificate setup stays local; no request is made."""

    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch, tmp_path):
        def no_network(*args, **kwargs):
            raise AssertionError("startup made a network connection")
        monkeypatch.setattr(socket, "create_connection", no_network)
        monkeypatch.setattr(socket.socket, "connect", no_network)
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "MeManga"))

    def test_bundled_certifi_wins(self, tmp_path):
        pem = _cacert(tmp_path / "bundle")
        _cacert(tmp_path / "app" / "_internal")

        result = _entry_helpers()["_configure_ca_bundle"](
            str(tmp_path / "bundle"))

        assert result == str(pem)
        assert os.environ["SSL_CERT_FILE"] == str(pem)
        assert os.environ["REQUESTS_CA_BUNDLE"] == str(pem)

    def test_internal_dir_next_to_executable(self, tmp_path):
        pem = _cacert(tmp_path / "app" / "_internal")

        result = _entry_helpers()["_configure_ca_bundle"](
            str(tmp_path / "bundle"))

        assert result == str(pem)
        assert os.environ["SSL_CERT_FILE"] == str(pem)
        assert os.environ["REQUESTS_CA_BUNDLE"] == str(pem)

    def test_falls_back_to_certifi(self, tmp_path):
        import certifi

        result = _entry_helpers()["_configure_ca_bundle"](
            str(tmp_path / "bundle"))

        assert result == certifi.where()
        assert os.environ["SSL_CERT_FILE"] == certifi.where()
        assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()

    def test_no_bundle_leaves_environment_alone(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "certifi", None)

        result = _entry_helpers()["_configure_ca_bundle"](
            str(tmp_path / "bundle"))

        assert result is None
        assert "SSL_CERT_FILE" not in os.environ
        assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_entry_module_makes_no_network_request():
    """Issue #300: the frozen startup used to block on an HTTPS request
    to a third-party host before the window could open. The entry module
    must not import an HTTP/socket client or contact any host."""
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    network = {"urllib.request", "http.client", "socket", "ssl",
               "requests", "httpx", "aiohttp", "curl_cffi", "cloudscraper"}
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}"
                            for alias in node.names)

    assert not imported & network
    assert "urlopen" not in src
    assert "httpbin" not in src


def test_log_dir_is_the_shared_default_config_dir(isolated_home, monkeypatch):
    """Issue #249: runtime.log and crash.log go to the folder the GUI and
    CLI use, after a legacy ~/.config/memanga was moved there."""
    from memanga import config as config_mod
    legacy = isolated_home / ".config" / "memanga"
    native = isolated_home / "platform" / "memanga"
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    (legacy / "state.json").write_text("{}", encoding="utf-8")

    assert _entry_helpers()["_config_dir"]() == native
    assert (native / "state.json").exists()


def test_log_dir_follows_env_config_dir(isolated_home, monkeypatch, tmp_path):
    """Issue #249: with $MEMANGA_CONFIG_DIR the logs go to that directory,
    like Config and State, and the legacy folder is not moved."""
    from memanga import config as config_mod
    legacy = isolated_home / ".config" / "memanga"
    native = isolated_home / "platform" / "memanga"
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    (legacy / "state.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "from-env"
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))

    assert _entry_helpers()["_config_dir"]() == root
    assert (legacy / "state.json").exists()
    assert not native.exists()


def _end_session(ns, log):
    """End one launch: close its runtime.log and release the config
    directory lock it took."""
    log.close()
    lock = ns["_runtime_log_lock"]
    if lock is not None:
        lock.release()
    ns["_runtime_log_lock"] = None


def test_runtime_log_rotates_instead_of_truncating(tmp_path):
    """Issue #226: each launch keeps the earlier sessions' runtime.log
    (newest in .1) rather than wiping the only diagnostic trail."""
    ns = _entry_helpers()
    for session in ("first", "second", "third", "fourth", "fifth"):
        log = ns["_open_runtime_log"](tmp_path)
        assert ns["_runtime_log_lock"].acquired
        log.write(f"{session}\n")
        _end_session(ns, log)

    assert (tmp_path / "runtime.log").read_text() == "fifth\n"
    assert (tmp_path / "runtime.log.1").read_text() == "fourth\n"
    assert (tmp_path / "runtime.log.2").read_text() == "third\n"
    assert (tmp_path / "runtime.log.3").read_text() == "second\n"
    assert not (tmp_path / "runtime.log.4").exists()


def test_second_launch_does_not_touch_running_instance_log(tmp_path,
                                                           lock_holder):
    """Issue #226: a launch while another instance holds the config
    directory (it then stops at the "already running" dialog) appends
    instead of rotating or truncating the running instance's log."""
    (tmp_path / "runtime.log").write_text("running instance\n")
    lock_holder.hold(tmp_path)
    ns = _entry_helpers()

    log = ns["_open_runtime_log"](tmp_path)
    log.write("second launch\n")
    _end_session(ns, log)

    assert (tmp_path / "runtime.log").read_text() == (
        "running instance\nsecond launch\n")
    assert not (tmp_path / "runtime.log.1").exists()


def test_runtime_log_appends_when_rotation_fails(tmp_path, monkeypatch):
    """A log that could not be moved aside (open elsewhere on Windows) is
    appended to, never truncated."""
    from memanga import output

    (tmp_path / "runtime.log").write_text("earlier\n")
    monkeypatch.setattr(output, "rotate_log_file", lambda *a, **k: False)
    ns = _entry_helpers()

    log = ns["_open_runtime_log"](tmp_path)
    log.write("this session\n")
    _end_session(ns, log)

    assert (tmp_path / "runtime.log").read_text() == "earlier\nthis session\n"


def test_runtime_log_appends_when_lock_cannot_be_taken(tmp_path, monkeypatch):
    """Issue #226: without the lock (a file system without lock support)
    nothing proves no other instance is writing runtime.log, so it is
    appended to, never rotated or truncated."""
    import errno

    from memanga import output, process_lock

    (tmp_path / "runtime.log").write_text("running instance\n")

    def no_lock(self):
        raise process_lock.ConfigDirLockError(
            self.config_dir, OSError(errno.ENOLCK, "No locks available"))
    monkeypatch.setattr(process_lock.ConfigDirLock, "acquire", no_lock)
    rotated = []
    monkeypatch.setattr(output, "rotate_log_file",
                        lambda *a, **k: rotated.append(a) or True)
    ns = _entry_helpers()

    log = ns["_open_runtime_log"](tmp_path)
    log.write("this launch\n")
    _end_session(ns, log)

    assert rotated == []
    assert ns["_runtime_log_lock"] is None
    assert (tmp_path / "runtime.log").read_text() == (
        "running instance\nthis launch\n")
    assert not (tmp_path / "runtime.log.1").exists()


def test_runtime_log_stays_when_window_uses_its_folder(tmp_path, monkeypatch):
    """launch_gui() locking the folder the entry chose changes nothing."""
    import sys

    ns = _entry_helpers()
    log = ns["_open_runtime_log"](tmp_path)
    monkeypatch.setattr(sys, "stderr", log)

    ns["_move_runtime_log"](tmp_path)

    assert sys.stderr is log
    assert ns["_runtime_log_lock"].acquired
    assert ns["_runtime_log_lock"].config_dir == tmp_path
    _end_session(ns, log)


def _fail_open_in(ns, folder):
    """Make the entry's open() of a runtime.log in ``folder`` fail."""
    import builtins

    def _open(path, *args, **kwargs):
        if Path(path).parent == folder:
            raise PermissionError(13, "Permission denied", str(path))
        return builtins.open(path, *args, **kwargs)
    ns["open"] = _open


def _runtime_log_session(ns, folder, monkeypatch):
    """Start a session whose stdout and stderr write to runtime.log in
    ``folder``; returns the log and the os.dup2 targets used later."""
    import sys

    log = ns["_open_runtime_log"](folder)
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(sys, "stderr", log)
    dup2 = []
    monkeypatch.setattr(os, "dup2", lambda fd, target: dup2.append(target))
    return log, dup2


def test_failed_runtime_log_move_keeps_old_log_locked(tmp_path, monkeypatch,
                                                      lock_holder):
    """Issue #226: when runtime.log cannot be opened in the window's
    folder, the old log stays in use, so its folder stays locked; another
    launch there must not rotate a file this session still writes."""
    import sys

    old, new = tmp_path / "old", tmp_path / "new"
    ns = _entry_helpers()
    log, dup2 = _runtime_log_session(ns, old, monkeypatch)
    old_lock = ns["_runtime_log_lock"]
    _fail_open_in(ns, new)

    ns["_move_runtime_log"](new)

    assert sys.stdout is log and sys.stderr is log
    assert dup2 == []
    assert ns["_runtime_log_file"] is log
    assert ns["_runtime_log_lock"] is old_lock and old_lock.acquired
    assert not lock_holder.can_lock(old)
    assert lock_holder.can_lock(new)
    log.write("still here\n")

    _end_session(ns, log)
    assert lock_holder.can_lock(old)
    assert (old / "runtime.log").read_text().endswith("still here\n")
    assert not (old / "runtime.log.1").exists()


def test_runtime_log_move_after_failed_one_hands_over_lock(tmp_path,
                                                           monkeypatch,
                                                           lock_holder):
    """The lock kept after a failed move is let go once a later move
    switches the streams to the new folder's runtime.log."""
    import sys

    old, new = tmp_path / "old", tmp_path / "new"
    ns = _entry_helpers()
    log, dup2 = _runtime_log_session(ns, old, monkeypatch)
    _fail_open_in(ns, new)
    ns["_move_runtime_log"](new)
    del ns["open"]

    ns["_move_runtime_log"](new)

    new_log = sys.stderr
    try:
        assert new_log is not log and sys.stdout is new_log
        assert dup2 == [1, 2]
        assert lock_holder.can_lock(old)
        assert not lock_holder.can_lock(new)
        assert ns["_runtime_log_lock"].config_dir == new
        new_log.write("window\n")
    finally:
        log.close()
    _end_session(ns, new_log)
    assert lock_holder.can_lock(new)
    assert (new / "runtime.log").read_text().endswith("window\n")


# A windowed start: standard descriptors closed and sys streams None.
# Repairs the streams like the frozen entry, writes to runtime.log, then
# stays alive until the test is done with it.
_WINDOWED_SESSION = """
import os, sys, time, traceback
from pathlib import Path
entry, cfg = Path(sys.argv[1]), Path(sys.argv[2])
os.close(0); os.close(1); os.close(2)
sys.stdin = sys.stdout = sys.stderr = None
try:
    ns = {}
    exec(entry.read_text().split("if getattr(sys")[0], ns)
    ns["_ensure_valid_std_streams"]()
    print("first session", flush=True)
    (cfg / "ready").write_text("ok")
except BaseException:
    (cfg / "error").write_text(traceback.format_exc())
    raise
deadline = time.monotonic() + 60
while not (cfg / "done").exists() and time.monotonic() < deadline:
    time.sleep(0.05)
"""


def test_std_stream_repair_keeps_config_dir_lock(tmp_path, lock_holder):
    """Issue #226: with descriptors 0-2 closed, the lock taken for
    runtime.log used to land on descriptor 0 and the stdin repair closed
    it. The folder must stay locked, so a second launch appends to the
    running session's log instead of rotating it."""
    import subprocess
    import sys
    import time

    entry = Path(memanga.__file__).parent / "gui" / "__main__.py"
    env = dict(os.environ, MEMANGA_CONFIG_DIR=str(tmp_path))
    proc = subprocess.Popen(
        [sys.executable, "-c", _WINDOWED_SESSION, str(entry), str(tmp_path)],
        cwd=str(Path(memanga.__file__).parent.parent), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while not (tmp_path / "ready").exists():
            assert not (tmp_path / "error").exists(), (
                (tmp_path / "error").read_text())
            assert proc.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)

        assert not lock_holder.can_lock(tmp_path)
        ns = _entry_helpers()
        log = ns["_open_runtime_log"](tmp_path)
        assert ns["_runtime_log_lock"] is None
        log.write("second launch\n")
        log.close()
    finally:
        (tmp_path / "done").write_text("ok")
        proc.wait(timeout=60)

    assert proc.returncode == 0
    assert not (tmp_path / "runtime.log.1").exists()
    text = (tmp_path / "runtime.log").read_text()
    assert "first session\n" in text and text.endswith("second launch\n")
