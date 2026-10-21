#!/usr/bin/env python3
"""
Entry point for MeManga GUI (.exe / standalone).
Sets up SSL certificates and Playwright browser path for frozen builds.
"""

import logging
import os
import sys
from pathlib import Path

# Not __name__: run as a script that is "__main__", which the logging
# setup would treat as a third-party logger.
logger = logging.getLogger("memanga.gui.entry")

# Previous sessions' runtime.log files kept next to the current one.
RUNTIME_LOG_BACKUPS = 3


def _config_dir() -> Path:
    """Directory the app uses for state, logs and crash reports.

    Selected like the CLI and launch_gui() do (issue #249):
    ``$MEMANGA_CONFIG_DIR``, else the platform default. Resolving the
    default here also moves a legacy ~/.config/memanga before any log
    is written.
    """
    from memanga.config import selected_config_dir
    return selected_config_dir()


def _playwright_browsers_dir() -> Path:
    """Per-user browser cache dir, matching Playwright's own defaults.

    Mirrors the driver registry's platform defaults so the path computed
    here is the same one ``playwright install`` writes to when the env
    var is absent: ``%LOCALAPPDATA%\\ms-playwright`` on Windows,
    ``~/Library/Caches/ms-playwright`` on macOS, ``$XDG_CACHE_HOME`` or
    ``~/.cache`` elsewhere.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        root = Path(base) if base else Path.home() / ".cache"
    return root / "ms-playwright"


def _configure_playwright_browsers() -> Path:
    """Pin ``PLAYWRIGHT_BROWSERS_PATH`` to the per-user cache dir.

    Playwright's driver transport forces ``PLAYWRIGHT_BROWSERS_PATH=0``
    ("browsers live inside the application bundle") for frozen builds
    whenever the variable is unset. No browsers ship inside the bundle,
    so every ``firefox.launch()`` then fails with "Executable doesn't
    exist".

    Setting the variable only when the directory already exists — the
    old behaviour — broke the entire first session on a fresh machine:
    the first-launch installer downloads Firefox into the per-user
    cache, but the running process still has no variable set, so the
    driver resolves to the empty bundle for the rest of the session.
    Search, get_chapters and get_pages fail for every Playwright source
    until the app is restarted. Set it unconditionally; the installer
    creates the directory on first run.

    An explicit pre-set value other than the bundle sentinel ``"0"`` is
    honoured so a user-managed browser cache keeps working.
    """
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if existing and existing != "0":
        return Path(existing)
    pw_browsers = _playwright_browsers_dir()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(pw_browsers)
    return pw_browsers


def _ensure_valid_std_streams() -> bool:
    """Guarantee real, file-descriptor-backed standard streams.

    A PyInstaller ``console=False`` (windowed) build starts with
    ``sys.stdout`` / ``sys.stderr`` / ``sys.stdin`` set to ``None`` on
    Windows, because there is no attached console. Two things break as a
    direct result:

      1. Any code that treats the stream as a file object — e.g.
         ``sys.stdout.flush()`` in the update-check worker — raises
         ``AttributeError: 'NoneType' object has no attribute 'flush'``.

      2. Playwright launches its Node driver as a child process and
         wires the child's stderr to ``sys.stderr.fileno()``. With
         ``sys.stderr`` set to ``None`` it instead lets the child
         inherit the parent's stderr handle, which does not exist in a
         windowed process.

    Pointing the missing streams at a real, writable log file restores a
    valid file descriptor and leaves a diagnostic trail for bug reports —
    log records and tracebacks then land in ``runtime.log`` instead of
    vanishing, which is what makes a frozen Playwright failure
    diagnosable at all.

    Returns ``True`` when streams had to be repaired (i.e. this is the
    windowed build), ``False`` when they were already usable (the console
    dev build, or running from source), so the caller can apply the other
    windowed-only workarounds.
    """
    def _is_usable(stream) -> bool:
        if stream is None:
            return False
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            return False
        return isinstance(fd, int) and fd >= 0

    need_out = not _is_usable(sys.stdout)
    need_err = not _is_usable(sys.stderr)
    need_in = not _is_usable(sys.stdin)
    if not (need_out or need_err or need_in):
        return False

    # Before opening anything: the repairs below dup2 onto descriptors
    # 0-2, which would silently close a config directory lock opened on
    # a free one of them.
    _reserve_std_fds()

    if need_out or need_err:
        log = None
        try:
            log = _open_runtime_log(_config_dir())
        except OSError:
            # No writable config dir — fall back to the null device.
            # It still provides a valid fd, which is all the Playwright
            # driver needs; the output is simply discarded.
            try:
                log = open(os.devnull, "w", encoding="utf-8")
            except OSError:
                log = None
        if log is not None:
            _point_std_streams(log, need_out, need_err)
            if log is _runtime_log_file:
                # Issue #226: launch_gui() moves the log along if it
                # switches config directories.
                from memanga.gui import set_runtime_log_mover
                set_runtime_log_mover(_move_runtime_log)

    if need_in:
        try:
            _devnull_in = open(os.devnull, "r", encoding="utf-8")
            sys.stdin = _devnull_in
            try:
                os.dup2(_devnull_in.fileno(), 0)
            except (OSError, ValueError, AttributeError):
                pass
        except OSError:
            pass

    return True


def _reserve_std_fds() -> None:
    """Open the null device on any closed descriptor 0, 1 or 2.

    Files opened later (the config directory lock, runtime.log) then get
    descriptors above 2, so pointing the standard handles at the log or
    the null device cannot close them. Issue #226: with descriptor 0
    free, the lock landed on it and the stdin repair dropped the lock, so
    a second launch rotated this session's runtime.log.
    """
    for fd in (0, 1, 2):
        try:
            os.fstat(fd)
            continue
        except OSError:
            pass
        try:
            null = os.open(os.devnull, os.O_RDWR)
        except OSError:
            return
        if null != fd:
            try:
                os.dup2(null, fd)
            except OSError:
                pass
            os.close(null)
        else:
            os.set_inheritable(fd, True)


def _point_std_streams(log, out: bool, err: bool) -> None:
    """Point ``sys.stdout`` (``out``) and/or ``sys.stderr`` (``err``) at
    ``log``.

    Also point the process's OS-level standard handles at the log.
    Playwright's Node driver is a child process: on Windows a windowed
    build leaves the real stdout/stderr handles invalid, and a child that
    inherits those handles — rather than reading ``sys.stderr.fileno()``
    — gets broken ones and the driver fails to start. ``dup2`` makes the
    inherited descriptors valid too.
    """
    if out:
        sys.stdout = log
    if err:
        sys.stderr = log
    try:
        _fd = log.fileno()
        if out:
            os.dup2(_fd, 1)
        if err:
            os.dup2(_fd, 2)
    except (OSError, ValueError, AttributeError):
        pass


# This session's runtime.log, its config directory, and the lock on that
# directory taken for it; the lock is held until exit (launch_gui() joins
# it) or until launch_gui() switches directories.
_runtime_log_file = None
_runtime_log_dir = None
_runtime_log_lock = None


def _open_runtime_log(config_dir: Path):
    """Open this session's ``runtime.log``, keeping earlier sessions.

    Issue #226: earlier logs rotate to ``runtime.log.1`` (newest) up to
    ``runtime.log.3`` instead of being truncated, so a failure from the
    session before a restart is still there for a bug report. Each file
    holds one session, so the set stays bounded.

    Only the instance holding the config directory lock rotates. A
    second launch while one is running (it stops at the "already
    running" dialog) appends to the running instance's log instead of
    moving or truncating it, as does a launch that could not take the
    lock at all and any launch whose rotation failed because the file is
    still open elsewhere (Windows).
    """
    global _runtime_log_file, _runtime_log_dir, _runtime_log_lock
    from memanga.output import rotate_log_file
    from memanga.process_lock import ConfigDirBusy, ConfigDirLock, ConfigDirLockError

    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "runtime.log"
    lock = ConfigDirLock(config_dir)
    try:
        lock.acquire()
    except (ConfigDirBusy, ConfigDirLockError):
        # Another instance may be writing this log: it holds the lock, or
        # no lock could be taken to rule that out (launch_gui() reports
        # the latter).
        lock = None
        mode = "a"
    else:
        mode = "w" if rotate_log_file(path, RUNTIME_LOG_BACKUPS) else "a"
    try:
        log = open(path, mode, encoding="utf-8", buffering=1)
    except OSError:
        if lock is not None:
            lock.release()
        raise
    _runtime_log_file, _runtime_log_dir = log, config_dir
    if lock is not None:
        _runtime_log_lock = lock
    return log


def _move_runtime_log(new_dir: Path) -> None:
    """Continue this session's ``runtime.log`` in ``new_dir``.

    Called by launch_gui() with the config folder it locked. That is
    the folder this entry opened the log in, unless another process
    moved the legacy folder to the platform folder in between (issue
    #249). Then the log is reopened in ``new_dir`` (rotating that
    folder's earlier sessions under its lock, which this process now
    holds), the standard streams are pointed at it, and the lock on the
    old, recreated folder is let go rather than held for the session.

    The old file object is flushed but not closed: code that kept a
    reference to the old stream must not start failing.

    If the new log cannot be opened, the old one stays in use and keeps
    its lock for the session; without it, another launch on the old
    folder would rotate the file this process is still writing.
    """
    global _runtime_log_lock
    if _runtime_log_file is None or _same_dir(_runtime_log_dir, new_dir):
        return
    old_file, old_lock = _runtime_log_file, _runtime_log_lock
    try:
        new_file = _open_runtime_log(Path(new_dir))
    except OSError:
        logger.warning("Could not move runtime.log to %s", new_dir)
        return
    if _runtime_log_lock is old_lock:
        _runtime_log_lock = None  # no lock was taken on new_dir
    out, err = sys.stdout is old_file, sys.stderr is old_file
    try:
        old_file.flush()
    except (OSError, ValueError):
        pass
    _point_std_streams(new_file, out, err)
    logger.info("Config folder moved; runtime.log continues in %s", new_dir)
    # Only now is the old file no longer the active log.
    if old_lock is not None:
        old_lock.release()


def _same_dir(a, b) -> bool:
    return (os.path.normcase(os.path.realpath(a))
            == os.path.normcase(os.path.realpath(b)))


def _configure_logging() -> None:
    """Log to stderr with timestamps (``runtime.log`` in the windowed
    build). INFO by default; ``MEMANGA_LOG_LEVEL`` overrides it."""
    from memanga.output import configure_logging, resolve_log_level

    configure_logging(resolve_log_level(default=logging.INFO),
                      timestamps=True)


def _install_windowed_subprocess_defaults() -> None:
    """Spawn child processes without a console in the windowed build.

    A ``console=False`` (GUI-subsystem) process has no console to share
    with its children. When it spawns a console program such as
    Playwright's Node driver, Windows allocates a fresh console for the
    child; combined with the ``SW_HIDE`` startup flag Playwright already
    sets, that allocation is what stops the driver from coming up in the
    release exe — so every Playwright source fails (no search results,
    zero chapters, page-fetch errors) while the console dev build, whose
    children inherit its console, works from the identical bundle.

    ``CREATE_NO_WINDOW`` tells Windows not to allocate a console for the
    child, which is exactly what a background driver wants — its stdio
    already travel over the pipes Playwright sets up. Default it on every
    ``subprocess.Popen`` (the API asyncio uses under the hood to spawn the
    driver) that doesn't already request creation flags, so the existing
    ``no_window_kwargs()`` callers are left as-is.
    """
    if os.name != "nt":
        return
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _orig_popen_init = subprocess.Popen.__init__

    def _popen_init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = flags
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _popen_init


def _verify_playwright() -> int:
    """End-to-end Playwright self-test. Returns a process exit code.

    Invoked via ``--verify-playwright``, primarily by the release
    pipeline: after building the windowed executable, CI runs it with
    this flag on a pristine runner — the same "fresh machine, first
    session" conditions issue #28 kept reproducing under. The test
    installs Firefox and Chromium through the bundled driver (exactly
    like the first-launch dialog), launches each through the regular
    Playwright transport, and loads a page. A release cannot ship unless this
    passes, which turns "the windowed exe can drive Playwright" from a
    claim into a release invariant.

    All progress goes through ``print`` so a windowed build writes it
    to ``runtime.log`` via the repaired streams; the exit code is the
    machine-readable verdict either way.
    """
    import subprocess
    import traceback

    print(f"[Verify] platform={sys.platform} frozen={getattr(sys, 'frozen', False)}",
          flush=True)
    print(f"[Verify] PLAYWRIGHT_BROWSERS_PATH="
          f"{os.environ.get('PLAYWRIGHT_BROWSERS_PATH')!r}", flush=True)
    try:
        from playwright._impl._driver import (
            compute_driver_executable, get_driver_env,
        )
        node, cli = compute_driver_executable()
        from memanga.gui import _REQUIRED_BROWSERS
        names = " + ".join(_REQUIRED_BROWSERS)
        print(f"[Verify] installing {names} via bundled driver…", flush=True)
        result = subprocess.run(
            [str(node), str(cli), "install", *_REQUIRED_BROWSERS],
            env=get_driver_env(), capture_output=True, text=True,
            timeout=900,
        )
        if result.returncode != 0:
            print(f"[Verify] FAIL: install exited {result.returncode}:\n"
                  f"{(result.stderr or result.stdout or '')[-2000:]}",
                  flush=True)
            return 1

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for name in _REQUIRED_BROWSERS:
                browser_type = getattr(pw, name)
                print(f"[Verify] {name} expected at: "
                      f"{browser_type.executable_path}", flush=True)
                browser = browser_type.launch(headless=True)
                page = browser.new_page()
                page.goto("data:text/html,<title>memanga-verify</title>",
                          wait_until="domcontentloaded")
                title = page.title()
                browser.close()
                if title != "memanga-verify":
                    print(f"[Verify] FAIL: {name}: unexpected page title "
                          f"{title!r}", flush=True)
                    return 1
        print(f"[Verify] PASS: driver started, {names} launched, pages loaded",
              flush=True)
        return 0
    except Exception:
        print(f"[Verify] FAIL:\n{traceback.format_exc()}", flush=True)
        return 1


if getattr(sys, 'frozen', False):
    # Must run before anything else in the frozen build: a windowed
    # (console=False) exe has null std streams, and Playwright's driver
    # reads sys.stderr.fileno() the moment a scraper starts.
    _windowed = _ensure_valid_std_streams()
    if _windowed:
        # Windowed build only: keep Windows from allocating a console for
        # the Playwright Node driver, which otherwise fails to start.
        _install_windowed_subprocess_defaults()
    _configure_logging()

    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))

    # --- SSL certificates ---
    ca_bundle = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
    if os.path.exists(ca_bundle):
        os.environ['SSL_CERT_FILE'] = ca_bundle
        os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
        logger.info("CA bundle: %s", ca_bundle)
    else:
        ca_bundle_alt = os.path.join(os.path.dirname(sys.executable), '_internal', 'certifi', 'cacert.pem')
        if os.path.exists(ca_bundle_alt):
            os.environ['SSL_CERT_FILE'] = ca_bundle_alt
            os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle_alt
        else:
            try:
                import certifi
                os.environ['SSL_CERT_FILE'] = certifi.where()
                os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
            except Exception:
                logger.warning("No CA bundle found")

    # --- Playwright browsers ---
    # Pin the browser cache location unconditionally; see
    # _configure_playwright_browsers for why "only if it exists" broke
    # every Playwright source on a fresh machine's first session.
    pw_browsers = _configure_playwright_browsers()
    if pw_browsers.exists():
        logger.info("Playwright browsers: %s", pw_browsers)
    else:
        logger.info("Playwright browser dir not present yet "
                    "(first-launch install creates it): %s", pw_browsers)

    # Quick SSL test
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        logger.info("HTTPS test passed")
    except Exception as e:
        logger.warning("HTTPS test failed: %s", e)
else:
    _configure_logging()
    logger.info("Running from source")

# Release-pipeline self-test — must run before the GUI import so the
# verdict is pure Playwright, with no Qt/display dependency.
if "--verify-playwright" in sys.argv:
    sys.exit(_verify_playwright())

from memanga.gui import launch_gui


def _install_crash_logger():
    """Route uncaught exceptions to a log file.

    The release exe is built with `console=False` so a Python traceback
    that escapes `launch_gui()` would otherwise vanish into the void —
    the user sees the window blink shut and has no idea why. Hooking
    sys.excepthook lets us drop a one-file crash log under the same
    config dir we already use for state, which they can attach to a
    bug report.
    """
    import traceback
    from datetime import datetime

    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    log_path = config_dir / "crash.log"

    def _hook(exc_type, exc, tb):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 70}\n{datetime.now().isoformat()}\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        # Still also print to stderr — caught by the dev build's
        # console, ignored in the release build.
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = _hook


if __name__ == "__main__":
    _install_crash_logger()
    launch_gui()
