"""
Runtime diagnostics behind `memanga doctor` (issue #250).

Each check is a small function that inspects one area and returns a
`CheckResult`. Checks never raise: anything unexpected becomes a
``fail`` result, so a broken environment still gets a full report.

Default checks only touch the local machine. Checks that hit the
network or start real browsers are opt-in:

- ``smtp`` logs in to the configured SMTP server only with ``--smtp``.
- ``browsers`` confirms the Playwright builds are installed; launching
  them headless (a stronger smoke test, e.g. for Docker images) needs
  ``--launch-browsers``.

The JSON report shape is a stable contract for scripts; bump
`SCHEMA_VERSION` on incompatible changes.
"""

import json
import os
import platform
import shlex
import smtplib
import ssl
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from . import __version__
from .config import get_app_password

SCHEMA_VERSION = 1

OK = "ok"
WARNING = "warning"
FAIL = "fail"
SKIP = "skip"

# Stable check names, in report order. `--check` accepts these.
CHECK_NAMES = (
    "runtime",
    "config",
    "state",
    "download_dir",
    "email",
    "keyring",
    "smtp",
    "scheduler",
    "sources",
    "browsers",
)

# Browsers the Playwright scrapers launch. Mirrors
# memanga.gui._REQUIRED_BROWSERS; kept here because the CLI-only Docker
# image ships without the gui package.
REQUIRED_BROWSERS = ("firefox", "chromium")

WINDOWS_TASK_NAME = "MeManga_AutoCheck"

SMTP_TIMEOUT_SECONDS = 20


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Helpers
# ============================================================================

def _probe_writable(directory: Path) -> Optional[str]:
    """Return None if a file can be created in ``directory``, else the error.

    Creates and removes a temp file instead of trusting os.access(),
    which is wrong for root, ACLs and read-only mounts.
    """
    try:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".memanga-doctor-")
    except OSError as e:
        return e.strerror or str(e)
    os.close(fd)
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return None


def _nearest_existing(path: Path) -> Path:
    """Closest existing ancestor of ``path`` (or the path itself)."""
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _tracked_domains(config) -> List[str]:
    from .downloader import _get_sources_from_manga

    domains = set()
    for manga in config.get("manga", []) or []:
        if not isinstance(manga, dict):
            continue
        for src in _get_sources_from_manga(manga):
            if src.get("source"):
                domains.add(src["source"])
    return sorted(domains)


def _parse_hhmm(value) -> bool:
    try:
        hour, minute = str(value).split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (TypeError, ValueError):
        return False


# ============================================================================
# Checks
# ============================================================================

def _same_path(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _distribution_info(package_dir: Path) -> Dict[str, Any]:
    """Installed ``memanga`` distribution metadata, if any.

    ``editable`` comes from the PEP 610 ``direct_url.json`` that pip
    writes for ``pip install -e``; it is None when that is unknown.
    ``matches`` says whether the metadata describes the imported package
    in ``package_dir``: a source checkout can shadow an unrelated
    site-packages install, and that metadata says nothing about the code
    actually running.
    """
    from importlib import metadata
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    try:
        dist = metadata.distribution("memanga")
    except metadata.PackageNotFoundError:
        return {"version": None, "editable": None, "matches": False,
                "location": None, "metadata_path": None}
    editable = None
    source_dir = None
    try:
        raw = dist.read_text("direct_url.json")
        if raw:
            direct_url = json.loads(raw)
            editable = bool(direct_url.get("dir_info", {}).get("editable"))
            url = urlparse(direct_url.get("url") or "")
            if url.scheme == "file":
                source_dir = url2pathname(url.path)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        location = str(dist.locate_file(""))
        located = dist.locate_file("memanga")
    except (OSError, TypeError, ValueError):
        location = located = None
    # A regular install keeps the package next to its metadata; an
    # editable one points direct_url.json at the checkout holding it.
    matches = (located is not None and _same_path(located, package_dir)) or bool(
        editable and source_dir and _same_path(source_dir, package_dir.parent))
    metadata_path = getattr(dist, "_path", None)
    return {
        "version": dist.version,
        "editable": editable,
        "matches": matches,
        "location": location,
        "metadata_path": str(metadata_path) if metadata_path else None,
    }


def _install_mode(package_dir: Path, dist: Dict[str, Any]) -> str:
    """Best-effort guess: frozen, editable, source, installed or unknown.

    Only metadata that matches the imported package counts; unrelated
    metadata (e.g. an older site-packages install shadowed by a source
    checkout) is ignored. In a source checkout only editable metadata
    counts: non-editable metadata there is a stale local
    egg-info/dist-info left over from a build, not an install.
    """
    if getattr(sys, "frozen", False):
        return "frozen"
    if dist.get("matches") and dist.get("editable"):
        return "editable"
    if (package_dir.parent / "pyproject.toml").is_file():
        return "source"
    if dist.get("matches"):
        return "installed"
    return "unknown"


def check_runtime(config=None, state=None) -> CheckResult:
    package_dir = Path(__file__).resolve().parent
    dist = _distribution_info(package_dir)
    mode = _install_mode(package_dir, dist)
    details = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "version": __version__,
        "dist_version": dist["version"],
        "dist_matches": dist["matches"],
        "dist_location": dist["location"],
        "dist_metadata_path": dist["metadata_path"],
        "package_path": str(package_dir),
        "install_mode": mode,
    }
    python = f"Python {details['python_version']}"
    # Stale local metadata in a source checkout ("source") is not an install.
    if (dist["matches"] and mode != "source" and dist["version"]
            and dist["version"] != __version__):
        return CheckResult("runtime", WARNING,
                           f"Installed package metadata is {dist['version']} but the imported "
                           f"code is {__version__}; reinstall MeManga", details)
    return CheckResult("runtime", OK, f"MeManga {__version__} ({mode}) on {python}", details)


def check_config(config, state=None) -> CheckResult:
    path = Path(config.config_path)
    config_dir = Path(config.config_dir)
    details = {"path": str(path), "dir": str(config_dir), "exists": path.exists()}

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, UnicodeDecodeError) as e:
            return CheckResult("config", FAIL, f"Config file is not readable: {e}", details)
        except yaml.YAMLError as e:
            return CheckResult("config", FAIL, f"Config file is not valid YAML: {e}", details)
        if data is not None and not isinstance(data, dict):
            return CheckResult("config", FAIL, "Config file does not contain a YAML mapping", details)

    error = _probe_writable(config_dir) if config_dir.is_dir() else "directory is missing"
    if error:
        return CheckResult("config", FAIL, f"Config directory is not writable: {error}", details)
    if not path.exists():
        return CheckResult("config", OK, "No config file yet; defaults are in use", details)
    return CheckResult("config", OK, "Config file is readable and its directory is writable", details)


def check_state(config, state) -> CheckResult:
    path = Path(state.state_path)
    details = {"path": str(path), "exists": path.exists()}

    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except OSError as e:
            return CheckResult("state", FAIL, f"State file is not readable: {e}", details)
        except ValueError as e:
            # State() silently falls back to an empty state on bad JSON,
            # so the next save would drop the download history.
            return CheckResult("state", FAIL, f"State file is not valid JSON: {e}", details)
        if not isinstance(data, dict):
            return CheckResult("state", FAIL, "State file does not contain a JSON object", details)

    error = _probe_writable(path.parent) if path.parent.is_dir() else "directory is missing"
    if error:
        return CheckResult("state", FAIL, f"State directory is not writable: {error}", details)
    if not path.exists():
        return CheckResult("state", OK, "No state file yet; it will be created on first save", details)
    return CheckResult("state", OK, "State file is readable and writable", details)


def check_download_dir(config, state=None) -> CheckResult:
    """Chapters are written here in both delivery modes (email mode
    sends them from this directory), so it is always checked."""
    directory = Path(config.download_dir)
    details = {
        "path": str(directory),
        "exists": directory.exists(),
        "delivery_mode": config.delivery_mode,
    }
    if directory.exists():
        if not directory.is_dir():
            return CheckResult("download_dir", FAIL, f"Download path is not a directory: {directory}", details)
        error = _probe_writable(directory)
        if error:
            return CheckResult("download_dir", FAIL, f"Download directory is not writable: {error}", details)
        return CheckResult("download_dir", OK, "Download directory is writable", details)

    parent = _nearest_existing(directory)
    details["nearest_existing"] = str(parent)
    if parent.is_dir() and _probe_writable(parent) is None:
        return CheckResult("download_dir", OK, "Download directory will be created on first download", details)
    return CheckResult(
        "download_dir", FAIL,
        f"Download directory does not exist and cannot be created under {parent}", details,
    )


def check_email(config, state=None) -> CheckResult:
    mode = config.delivery_mode
    if mode != "email":
        return CheckResult("email", SKIP, f"Delivery mode is {mode}; email is not used",
                           {"delivery_mode": mode})

    details = {
        "delivery_mode": mode,
        "kindle_email_set": bool(config.get("email.kindle_email")),
        "sender_email_set": bool(config.get("email.sender_email")),
        "smtp_server": config.get("email.smtp_server", "smtp.gmail.com"),
        "smtp_port": config.get("email.smtp_port", 587),
        "app_password_set": bool(get_app_password(config)),
    }
    missing = [
        label for label, key in (
            ("Kindle email", "kindle_email_set"),
            ("sender email", "sender_email_set"),
            ("app password", "app_password_set"),
        ) if not details[key]
    ]
    if missing:
        return CheckResult("email", FAIL, "Email delivery is missing: " + ", ".join(missing), details)
    return CheckResult("email", OK, "Email delivery is configured", details)


def _keyring_backend() -> Dict[str, Any]:
    """Describe the active keyring backend without reading any secret."""
    try:
        import keyring
        backend = keyring.get_keyring()
    except Exception as e:
        return {"available": False, "backend": None, "plaintext": False, "error": str(e)}

    cls = type(backend)
    unusable = cls.__module__.startswith(("keyring.backends.fail", "keyring.backends.null"))
    if getattr(backend, "backends", None) == []:
        # A chainer with nothing to chain behaves like the fail backend.
        unusable = True
    return {
        "available": not unusable,
        "backend": f"{cls.__module__}.{cls.__qualname__}",
        "plaintext": cls.__name__ == "PlaintextKeyring",
    }


def check_keyring(config, state=None) -> CheckResult:
    info = _keyring_backend()
    details = dict(info)
    details["password_in_config"] = bool(config.get("email.app_password"))
    backend = info["backend"] or "none"

    if details["password_in_config"]:
        return CheckResult("keyring", WARNING,
                           "App password is stored in plaintext in config.yaml", details)
    if config.delivery_mode != "email":
        return CheckResult("keyring", SKIP,
                           f"Not needed for local delivery (backend: {backend})", details)
    if not info["available"]:
        return CheckResult("keyring", WARNING,
                           "No usable keyring backend; the app password would be saved "
                           "in plaintext in config.yaml", details)
    if info["plaintext"]:
        return CheckResult("keyring", WARNING,
                           f"Keyring backend stores secrets unencrypted ({backend})", details)
    return CheckResult("keyring", OK, f"Using keyring backend {backend}", details)


def _smtp_login(server: str, port: int, user: str, password: str) -> None:
    """Log in the way delivery does (SMTP + STARTTLS). Raises on failure."""
    context = ssl.create_default_context()
    with smtplib.SMTP(server, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.starttls(context=context)
        smtp.login(user, password)


def check_smtp(config, state=None, live: bool = False) -> CheckResult:
    server = config.get("email.smtp_server", "smtp.gmail.com")
    port = config.get("email.smtp_port", 587)
    details = {"smtp_server": server, "smtp_port": port, "live": live}

    if not live:
        return CheckResult("smtp", SKIP, "Login test not run; pass --smtp to try it", details)
    sender = config.get("email.sender_email")
    password = get_app_password(config)
    if not sender or not password:
        return CheckResult("smtp", FAIL,
                           "Sender email and app password are required for the login test", details)

    try:
        _smtp_login(server, int(port), sender, password)
    except smtplib.SMTPAuthenticationError:
        return CheckResult("smtp", FAIL,
                           "SMTP authentication failed; check the sender email and app password",
                           details)
    except Exception as e:
        message = (str(e) or type(e).__name__).replace(password, "****")
        return CheckResult("smtp", FAIL, f"SMTP login failed: {message}", details)
    return CheckResult("smtp", OK, f"Logged in to {server}:{port}", details)


def _read_crontab(runner) -> Optional[str]:
    """Current user's crontab, "" when there is none, None when crontab is unavailable."""
    try:
        result = runner(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        # `crontab -l` exits non-zero when the user has no crontab.
        return ""
    return result.stdout or ""


def _find_interpreter(tokens: List[str]) -> Optional[str]:
    """Interpreter token before ``-m memanga``, looking inside wrapper
    strings such as ``bash -lc '... python3 -m memanga check'``."""
    for i, token in enumerate(tokens):
        if token == "-m" and i > 0 and tokens[i + 1:i + 2] == ["memanga"]:
            return tokens[i - 1]
        if " -m memanga" in token:
            try:
                found = _find_interpreter(shlex.split(token))
            except ValueError:
                found = None
            if found:
                return found
    return None


def _cron_entry_sane(line: str) -> bool:
    """Loose sanity check for a MeManga crontab line: five schedule fields,
    a `memanga check` command and, when the interpreter can be located,
    an interpreter path that still exists. Hand-written wrappers (flock,
    bash -lc) are accepted."""
    fields = line.split(None, 5)
    if len(fields) < 6 or "memanga check" not in fields[5]:
        return False
    try:
        interpreter = _find_interpreter(shlex.split(fields[5]))
    except ValueError:
        return False
    if interpreter and os.sep in interpreter:
        return Path(interpreter).exists()
    return True


def check_scheduler(config, state=None, runner: Callable = subprocess.run,
                    system: Optional[str] = None) -> CheckResult:
    system = system or platform.system()
    enabled = bool(config.get("cron.enabled"))
    cron_time = config.get("cron.time", "06:00")
    details: Dict[str, Any] = {"enabled": enabled, "time": cron_time, "platform": system}

    if enabled and not _parse_hhmm(cron_time):
        return CheckResult("scheduler", FAIL,
                           f"Invalid scheduled time {cron_time!r}; expected HH:MM", details)

    entries_ok = True
    if system == "Windows":
        details["task_name"] = WINDOWS_TASK_NAME
        try:
            result = runner(["schtasks", "/query", "/tn", WINDOWS_TASK_NAME],
                            capture_output=True, text=True, timeout=10)
            installed = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            installed = None
    else:
        text = _read_crontab(runner)
        if text is None:
            installed = None
        else:
            entries = [line for line in text.splitlines()
                       if "memanga" in line.lower() and not line.lstrip().startswith("#")]
            details["entries"] = entries
            installed = bool(entries)
            entries_ok = len(entries) <= 1 and all(_cron_entry_sane(e) for e in entries)
    details["installed"] = installed

    if installed is None:
        if enabled:
            return CheckResult("scheduler", WARNING,
                               "Scheduled checks are enabled but the system scheduler "
                               "could not be queried", details)
        return CheckResult("scheduler", SKIP,
                           "System scheduler is not available; scheduled checks are off", details)
    if enabled and not installed:
        return CheckResult("scheduler", WARNING,
                           "Scheduled checks are enabled in config but no entry is installed; "
                           "run 'memanga cron install'", details)
    if installed and not enabled:
        return CheckResult("scheduler", WARNING,
                           "A MeManga scheduler entry is installed but disabled in config", details)
    if installed and not entries_ok:
        return CheckResult("scheduler", WARNING,
                           "MeManga crontab entries look wrong (duplicate, unexpected command, "
                           "or missing interpreter); reinstall with 'memanga cron install'", details)
    if installed:
        return CheckResult("scheduler", OK, f"Daily check scheduled at {cron_time}", details)
    return CheckResult("scheduler", OK, "No scheduled checks configured", details)


def check_sources(config, state) -> CheckResult:
    """Summarise cached source health. No network: this only reads what
    earlier checks and GUI probes recorded in state."""
    health = state.get_all_source_health()
    counts = {"ok": 0, "warning": 0, "error": 0}
    for info in health.values():
        status = info.get("status")
        if status in counts:
            counts[status] += 1

    tracked = _tracked_domains(config)
    tracked_errors = [d for d in tracked if health.get(d, {}).get("status") == "error"]
    details = {
        "cached": len(health),
        **counts,
        "tracked": tracked,
        "tracked_errors": tracked_errors,
        "tracked_unknown": [d for d in tracked if d not in health],
    }

    if not health:
        return CheckResult("sources", SKIP, "No cached source health yet", details)
    summary = (f"{counts['ok']} ok, {counts['warning']} warning, "
               f"{counts['error']} error (cached)")
    if tracked_errors:
        return CheckResult("sources", WARNING,
                           "Tracked source(s) failing: " + ", ".join(tracked_errors), details)
    return CheckResult("sources", OK, summary, details)


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _probe_browsers(launch: bool) -> Dict[str, Dict[str, Any]]:
    """Per-browser install (and optionally launch) status via Playwright.

    Launching only loads a ``data:`` URL, so it never touches the network.
    Raises ImportError when Playwright itself is missing.
    """
    from playwright.sync_api import sync_playwright

    results: Dict[str, Dict[str, Any]] = {}
    with sync_playwright() as pw:
        for name in REQUIRED_BROWSERS:
            info: Dict[str, Any] = {
                "installed": False, "executable": None, "launched": None, "error": None,
            }
            results[name] = info
            browser_type = getattr(pw, name)
            try:
                executable = browser_type.executable_path
            except Exception as e:
                info["error"] = _first_line(e)
                continue
            info["executable"] = executable
            info["installed"] = bool(executable) and Path(executable).exists()
            if not info["installed"] or not launch:
                continue
            try:
                browser = browser_type.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto("data:text/html,<title>memanga-doctor</title>",
                              wait_until="domcontentloaded")
                    info["launched"] = page.title() == "memanga-doctor"
                    if not info["launched"]:
                        info["error"] = "unexpected page title"
                finally:
                    browser.close()
            except Exception as e:
                info["launched"] = False
                info["error"] = _first_line(e)
    return results


def check_browsers(config=None, state=None, launch: bool = False) -> CheckResult:
    details: Dict[str, Any] = {
        "launch": launch,
        "required": list(REQUIRED_BROWSERS),
        "browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    }
    try:
        browsers = _probe_browsers(launch)
    except ImportError:
        return CheckResult("browsers", FAIL, "Playwright is not installed", details)
    except Exception as e:
        return CheckResult("browsers", FAIL, f"Playwright could not start: {_first_line(e)}", details)

    details["browsers"] = browsers
    missing = [n for n in REQUIRED_BROWSERS if not browsers.get(n, {}).get("installed")]
    if missing:
        install = "python -m playwright install " + " ".join(REQUIRED_BROWSERS)
        return CheckResult("browsers", FAIL,
                           "Missing Playwright browser(s): " + ", ".join(missing)
                           + f"; run '{install}'", details)
    names = ", ".join(REQUIRED_BROWSERS)
    if launch:
        broken = [n for n in REQUIRED_BROWSERS if not browsers[n].get("launched")]
        if broken:
            return CheckResult("browsers", FAIL, "Browser launch failed: " + ", ".join(broken), details)
        return CheckResult("browsers", OK, f"Launched {names}", details)
    return CheckResult("browsers", OK, f"Installed: {names}", details)


# ============================================================================
# Runner / report
# ============================================================================

def run_checks(config, state, only=None, smtp: bool = False,
               launch_browsers: bool = False) -> List[CheckResult]:
    """Run the selected checks (all by default) in `CHECK_NAMES` order."""
    checks = {
        "runtime": check_runtime,
        "config": check_config,
        "state": check_state,
        "download_dir": check_download_dir,
        "email": check_email,
        "keyring": check_keyring,
        "smtp": lambda c, s: check_smtp(c, s, live=smtp),
        "scheduler": check_scheduler,
        "sources": check_sources,
        "browsers": lambda c, s: check_browsers(c, s, launch=launch_browsers),
    }
    results = []
    for name in CHECK_NAMES:
        if only and name not in only:
            continue
        try:
            results.append(checks[name](config, state))
        except Exception as e:
            results.append(CheckResult(name, FAIL, f"Check crashed: {type(e).__name__}: {e}"))
    return results


def overall_status(results: List[CheckResult]) -> str:
    """Worst status across results; skipped checks don't count."""
    statuses = {r.status for r in results}
    if FAIL in statuses:
        return FAIL
    if WARNING in statuses:
        return WARNING
    return OK


def build_report(results: List[CheckResult]) -> Dict[str, Any]:
    summary = {OK: 0, WARNING: 0, FAIL: 0, SKIP: 0}
    for r in results:
        summary[r.status] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall_status(results),
        "summary": summary,
        "checks": [r.to_dict() for r in results],
    }


def exit_code(results: List[CheckResult], strict: bool = False) -> int:
    """0 when healthy, 1 when any check failed (or warned, with strict)."""
    status = overall_status(results)
    if status == FAIL or (strict and status == WARNING):
        return 1
    return 0
