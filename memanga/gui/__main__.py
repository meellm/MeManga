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


def _verify_playwright() -> int:
    """End-to-end Playwright self-test. Returns a process exit code.

    Invoked via ``--verify-playwright``, primarily by the release
    pipeline: after building the windowed executable, CI runs it with
    this flag on a pristine runner — the same "fresh machine, first
    session" conditions issue #28 kept reproducing under. The test
    installs Firefox through the bundled driver (exactly like the
    first-launch dialog), launches it through the regular Playwright
    transport, and loads a page. A release cannot ship unless this
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
        print(f"[Verify] installing firefox via bundled driver…", flush=True)
        result = subprocess.run(
            [str(node), str(cli), "install", "firefox"],
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
            print(f"[Verify] firefox expected at: {pw.firefox.executable_path}",
                  flush=True)
            browser = pw.firefox.launch(headless=True)
            page = browser.new_page()
            page.goto("data:text/html,<title>memanga-verify</title>",
                      wait_until="domcontentloaded")
            title = page.title()
            browser.close()
        if title != "memanga-verify":
            print(f"[Verify] FAIL: unexpected page title {title!r}", flush=True)
            return 1
        print("[Verify] PASS: driver started, firefox launched, page loaded",
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
    # Pin the browser cache location unconditionally; see
    # _configure_playwright_browsers for why "only if it exists" broke
    # every Playwright source on a fresh machine's first session.
    pw_browsers = _configure_playwright_browsers()
    if pw_browsers.exists():
        print(f"[Playwright] Browsers: {pw_browsers}", flush=True)
    else:
        print(f"[Playwright] Browser dir not present yet "
              f"(first-launch install creates it): {pw_browsers}", flush=True)

    # Quick SSL test
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        print("[SSL] HTTPS test passed", flush=True)
    except Exception as e:
        print(f"[SSL] HTTPS test FAILED: {e}", flush=True)
else:
    print("[Init] Running from source", flush=True)

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
