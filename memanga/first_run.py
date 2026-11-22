"""
First-run setup behind `memanga setup` (issue #217).

Installing the package never runs any of this; the user runs it on
purpose, as often as they like. Each step checks first and only creates
what is missing:

- the config directory and a ``config.yaml`` with the default settings
  (an existing file is never rewritten),
- the download directory,
- the Playwright browser builds the scrapers launch. They are downloaded
  only with consent: ``--install-browsers``, or a yes on a terminal.

System libraries the browsers need are only reported, with the command
that installs them: setup never runs sudo or a package manager.

Steps return :class:`memanga.doctor.CheckResult`, so ``setup`` and
``doctor`` describe problems the same way. This module imports only the
standard library at load time, so the scrapers can use
:func:`browser_launch_error` cheaply.
"""

import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

# Downloads are large and can be slow on small boards; the user can
# still stop earlier with Ctrl-C.
INSTALL_TIMEOUT = 1800

_MISSING_EXECUTABLE = "Executable doesn't exist"
_MISSING_HOST_DEPS = "Host system is missing dependencies"


class BrowserSetupError(RuntimeError):
    """A browser could not start because setup is incomplete."""


def _first_line(text: str) -> str:
    text = text.strip()
    return text.splitlines()[0].strip() if text else ""


def missing_host_dependencies(error) -> bool:
    """True when a Playwright launch error is about missing system libraries."""
    return _MISSING_HOST_DEPS in str(error)


def browser_launch_error(error) -> Optional[BrowserSetupError]:
    """Actionable replacement for a browser launch error, or None.

    Playwright's own text for these cases is a boxed banner that tells
    the user to run ``playwright install``, a command a pip user may not
    have on their PATH. The first line (which names the missing
    executable) is kept.
    """
    text = str(error)
    if _MISSING_EXECUTABLE in text:
        return BrowserSetupError(
            f"{_first_line(text)}. A browser MeManga needs is not installed; "
            "run 'memanga setup' to install it."
        )
    if _MISSING_HOST_DEPS in text:
        return BrowserSetupError(
            "The browser cannot start because system libraries it needs are "
            "missing; run 'memanga setup' to see the command that installs them."
        )
    return None


def _playwright_argv() -> List[str]:
    """Command prefix that runs the Playwright CLI for this interpreter.

    Frozen builds have no ``python -m``; they use the bundled driver, as
    the desktop app's browser installer does.
    """
    if getattr(sys, "frozen", False):
        from playwright._impl._driver import compute_driver_executable
        driver = compute_driver_executable()
        if isinstance(driver, tuple):
            return [str(part) for part in driver]
        return [str(driver)]
    return [sys.executable, "-m", "playwright"]


def install_command(browsers) -> List[str]:
    """argv that downloads the given Playwright browser builds."""
    return _playwright_argv() + ["install", *browsers]


# Arguments that Command Prompt and PowerShell both read as they are.
_WINDOWS_PLAIN = re.compile(r"[\w.:\\/-]+")


def _powershell_quote(arg: str) -> str:
    """``arg`` as one PowerShell argument; single quotes expand nothing."""
    if _WINDOWS_PLAIN.fullmatch(arg):
        return arg
    return "'" + arg.replace("'", "''") + "'"


def manual_install_text(browsers, system: Optional[str] = None) -> str:
    """The install command for this interpreter, ready to paste.

    POSIX shells get ``shlex`` quoting. On Windows a quoted program path
    needs different syntax in Command Prompt (double quotes) and in
    PowerShell (single quotes after the ``&`` call operator), so a path
    that needs quotes gives one indented line per shell, each named. A
    path that needs none gives one command that works in both.
    """
    try:
        argv = install_command(browsers)
    except Exception:
        return "python -m playwright install " + " ".join(browsers)
    if (system or platform.system()) != "Windows":
        return shlex.join(argv)
    if all(_WINDOWS_PLAIN.fullmatch(arg) for arg in argv):
        return " ".join(argv)
    powershell = "& " + " ".join(_powershell_quote(arg) for arg in argv)
    return (f"\n  Command Prompt: {subprocess.list2cmdline(argv)}"
            f"\n  PowerShell:     {powershell}")


def run_installer(argv, timeout=None):
    """Run the browser installer with the terminal attached."""
    return subprocess.run(argv, timeout=timeout)


def deps_command_text(browsers, system: Optional[str] = None) -> Optional[str]:
    """Command that installs the browsers' system libraries, for display.

    Only Linux needs one; Playwright's helper supports Debian and Ubuntu
    based systems and needs root. None elsewhere.
    """
    if (system or platform.system()) != "Linux":
        return None
    try:
        # Frozen builds run the bundled driver, like install_command().
        prefix = _playwright_argv()
    except Exception:
        return None
    return shlex.join(["sudo", *prefix, "install-deps", *browsers])


# ============================================================================
# Steps
# ============================================================================

def setup_config(config):
    """Create ``config.yaml`` with defaults when there is none, then verify it."""
    from . import doctor

    path = Path(config.config_path)
    if getattr(config, "load_error", None):
        return doctor.CheckResult("config", doctor.FAIL,
                                  f"Config file could not be loaded: {config.load_error}",
                                  {"path": str(path)})
    created = False
    if not path.exists():
        try:
            config.save()
            created = True
        except Exception as e:
            reason = getattr(getattr(e, "error", None), "strerror", None) or e
            return doctor.CheckResult("config", doctor.FAIL,
                                      f"Could not create {path}: {reason}",
                                      {"path": str(path)})
    result = doctor.check_config(config)
    if result.status == doctor.OK:
        result.message = (f"Created {path} with default settings" if created
                          else f"Using existing {path}")
    result.details["created"] = created
    return result


def setup_download_dir(config):
    """Create the download directory when missing, then verify it."""
    from . import doctor

    directory = Path(config.download_dir)
    created = False
    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            created = True
        except OSError as e:
            return doctor.CheckResult(
                "download_dir", doctor.FAIL,
                f"Could not create download directory {directory}: {e.strerror or e}",
                {"path": str(directory)})
    result = doctor.check_download_dir(config)
    if result.status == doctor.OK:
        result.message = (f"Created download directory {directory}" if created
                          else f"Download directory {directory} is writable")
    result.details["created"] = created
    return result


def _missing(probe) -> List[str]:
    from .doctor import REQUIRED_BROWSERS
    return [name for name in REQUIRED_BROWSERS
            if not probe.get(name, {}).get("installed")]


def setup_browsers(install: Optional[bool] = None, can_prompt: bool = False,
                   confirm: Optional[Callable[[str], bool]] = None,
                   runner: Optional[Callable] = None,
                   probe: Optional[Callable] = None,
                   notify: Optional[Callable[[str], None]] = None,
                   system: Optional[str] = None):
    """Make sure the Playwright browsers are installed and can start.

    ``install`` is True (download missing builds without asking), False
    (never download) or None (ask when ``can_prompt``; otherwise don't).
    ``notify`` gets progress lines to show before the installer runs.
    """
    from . import doctor

    probe = probe or doctor._probe_browsers
    runner = runner or run_installer
    notify = notify or (lambda text: None)
    names = list(doctor.REQUIRED_BROWSERS)
    location = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "Playwright's default browser folder"
    details = {"required": names, "installed_now": [], "browsers_path": location}

    def fail(message):
        return doctor.CheckResult("browsers", doctor.FAIL, message, details)

    def driver_error(e):
        return fail(f"Playwright could not start: {_first_line(str(e)) or type(e).__name__}")

    def install_missing(missing):
        """Download ``missing``: a failure result, or None once installed.

        Only --install-browsers covers every build. A yes on the terminal
        covers only the builds its question named, so a build found later
        (Chromium's headless shell) is asked about again.
        """
        details["missing"] = missing
        listed = ", ".join(missing)
        manual = manual_install_text(missing, system)
        allowed = install
        if allowed is None and can_prompt and confirm is not None:
            allowed = confirm(
                f"Download the Playwright {listed} build(s) now? This needs "
                f"internet access and several hundred MB in {location}."
            )
        if not allowed:
            return fail(f"Missing browser(s): {listed}; rerun setup with "
                        f"--install-browsers, or install by hand: {manual}")

        try:
            argv = install_command(missing)
        except Exception as e:
            return fail(f"Could not find the browser installer ({e}); "
                        f"install by hand: {manual}")
        notify(f"Downloading {listed}: {shlex.join(argv)}")
        try:
            # Output goes straight to the terminal so download progress
            # shows. The environment is passed on unchanged so a custom
            # PLAYWRIGHT_BROWSERS_PATH is where the builds land.
            completed = runner(argv, timeout=INSTALL_TIMEOUT)
        except subprocess.TimeoutExpired:
            return fail(f"Browser download did not finish within "
                        f"{INSTALL_TIMEOUT // 60} minutes; retry, or install by "
                        f"hand: {manual}")
        except OSError as e:
            return fail(f"Could not run the browser installer ({e.strerror or e}); "
                        f"install by hand: {manual}")
        if completed.returncode != 0:
            return fail(f"Browser installer exited with code {completed.returncode}; "
                        f"check the output above, then run 'memanga setup' again")
        try:
            still_missing = _missing(probe(False))
        except Exception as e:
            return driver_error(e)
        if still_missing:
            return fail("Browser(s) still missing after the download: "
                        + ", ".join(still_missing))
        details["installed_now"] += [n for n in missing if n not in details["installed_now"]]
        return None

    try:
        missing = _missing(probe(False))
    except ImportError:
        return fail("The playwright package is not installed; reinstall MeManga with pip")
    except Exception as e:
        return driver_error(e)
    if missing:
        problem = install_missing(missing)
        if problem:
            return problem

    # Starting each browser on a data: URL (no network) is the only way to
    # learn whether the system has the libraries it needs. Playwright can
    # also find a browser's main build but not the separate one it starts
    # headless (Chromium's headless shell); that is installed once and the
    # launch retried.
    for attempt in range(2):
        try:
            launched = probe(True)
        except Exception as e:
            return driver_error(e)
        details["browsers"] = launched
        broken = [name for name in names if not launched.get(name, {}).get("launched")]
        unbuilt = [name for name in broken
                   if _MISSING_EXECUTABLE in (launched.get(name, {}).get("error") or "")]
        if not unbuilt or attempt:
            break
        problem = install_missing(unbuilt)
        if problem:
            return problem
    if broken:
        if any(launched.get(name, {}).get("missing_dependencies") for name in broken):
            command = deps_command_text(broken, system)
            how = (f"install them with '{command}' (Debian/Ubuntu), or with your "
                   "system's package manager" if command
                   else "install them with your system's package manager")
            return fail("System libraries the browser(s) need are missing ("
                        + ", ".join(broken) + "). MeManga does not install system "
                        f"packages; {how}, then run 'memanga setup' again")
        errors = "; ".join(f"{name}: {launched.get(name, {}).get('error') or 'did not start'}"
                           for name in broken)
        return fail(f"Browser(s) installed but could not start: {errors}")

    verb = "Downloaded" if details["installed_now"] else "Installed"
    return doctor.CheckResult("browsers", doctor.OK,
                              f"{verb} and started headless: {', '.join(names)}", details)


def run_setup(config, report: Optional[Callable] = None, **browser_options):
    """Run every setup step in order; ``report`` gets each result as it is done."""
    report = report or (lambda result: None)
    results = []
    for step in (lambda: setup_config(config),
                 lambda: setup_download_dir(config),
                 lambda: setup_browsers(**browser_options)):
        result = step()
        results.append(result)
        report(result)
    return results
