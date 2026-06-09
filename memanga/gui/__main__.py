#!/usr/bin/env python3
"""
Entry point for MeManga GUI (.exe / standalone).
Sets up SSL certificates and Playwright browser path for frozen builds.
"""

import os
import sys
from pathlib import Path


def _config_dir() -> Path:
    """Directory the app uses for state, logs and crash reports."""
    return Path.home() / ".config" / "memanga"


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
    the scraper layer's ``print``/traceback output then lands in
    ``runtime.log`` instead of vanishing, which is what makes a frozen
    Playwright failure diagnosable at all.

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

    if need_out or need_err:
        log = None
        try:
            config_dir = _config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            # Truncate per launch — this is a "last session" diagnostic
            # log, not an append-forever file that grows unbounded.
            log = open(config_dir / "runtime.log", "w",
                       encoding="utf-8", buffering=1)
        except OSError:
            # No writable config dir — fall back to the null device.
            # It still provides a valid fd, which is all the Playwright
            # driver needs; the output is simply discarded.
            try:
                log = open(os.devnull, "w", encoding="utf-8")
            except OSError:
                log = None
        if log is not None:
            if need_out:
                sys.stdout = log
            if need_err:
                sys.stderr = log
            # Also point the process's OS-level standard handles at the
            # log. Playwright's Node driver is a child process: on
            # Windows a windowed build leaves the real stdout/stderr
            # handles invalid, and a child that inherits those handles
            # — rather than reading ``sys.stderr.fileno()`` — gets broken
            # ones and the driver fails to start. ``dup2`` makes the
            # inherited descriptors valid too.
            try:
                _fd = log.fileno()
                if need_out:
                    os.dup2(_fd, 1)
                if need_err:
                    os.dup2(_fd, 2)
            except (OSError, ValueError, AttributeError):
                pass

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


if getattr(sys, 'frozen', False):
    # Must run before anything else in the frozen build: a windowed
    # (console=False) exe has null std streams, and Playwright's driver
    # reads sys.stderr.fileno() the moment a scraper starts.
    _windowed = _ensure_valid_std_streams()
    if _windowed:
        # Windowed build only: keep Windows from allocating a console for
        # the Playwright Node driver, which otherwise fails to start.
        _install_windowed_subprocess_defaults()

    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))

    # --- SSL certificates ---
    ca_bundle = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
    if os.path.exists(ca_bundle):
        os.environ['SSL_CERT_FILE'] = ca_bundle
        os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
        print(f"[SSL] CA bundle: {ca_bundle}", flush=True)
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
                print("[SSL] WARNING: No CA bundle found!", flush=True)

    # --- Playwright browsers ---
    # Playwright installs browsers to ~\AppData\Local\ms-playwright (Windows)
    # or ~/.cache/ms-playwright (Linux/Mac). Inside a PyInstaller bundle,
    # Playwright's bundled driver looks for browsers relative to itself
    # (.local-browsers/) which is wrong. Point it to the real install location.
    if os.name == 'nt':
        pw_browsers = Path.home() / "AppData" / "Local" / "ms-playwright"
    else:
        pw_browsers = Path.home() / ".cache" / "ms-playwright"

    if pw_browsers.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(pw_browsers)
        print(f"[Playwright] Browsers: {pw_browsers}", flush=True)
    else:
        print(f"[Playwright] WARNING: Browser dir not found at {pw_browsers}", flush=True)

    # Quick SSL test
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        print("[SSL] HTTPS test passed", flush=True)
    except Exception as e:
        print(f"[SSL] HTTPS test FAILED: {e}", flush=True)
else:
    print("[Init] Running from source", flush=True)

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
