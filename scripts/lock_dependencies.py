#!/usr/bin/env python3
"""Generate the pinned installs in requirements/ from pyproject.toml (#315).

pyproject.toml is the only place dependencies are declared. Each file in
requirements/ is generated from it and pins, with hashes, every package
one install needs, on every platform and Python version MeManga supports:

  cli.txt    the CLI: the Docker image and the source docs check
  gui.txt    the CLI and the desktop app: a source checkout's setup
  dev.txt    gui plus the test tools
  build.txt  gui plus PyInstaller: the dev and release desktop builds

Which versions they pin is set in pyproject.toml too, under
[tool.lock-dependencies]: each package at its newest release that fits
the declared bounds, as PyPI was at `resolve-at`, or at the time listed
for it under `resolve-package-at` (uv's --exclude-newer and
--exclude-newer-package). The locks are therefore a function of
pyproject.toml alone. To update a package, move its time (or
`resolve-at`) and regenerate:

  python scripts/lock_dependencies.py

Generating needs uv 0.13.1 (`python -m pip install "uv==0.13.1"`) and the
network.

  python scripts/lock_dependencies.py --check

exits 1 when a file is missing, was not generated from the current
pyproject.toml, or is not one of the targets, and then when a lock differs
in any way from what generating it again gives. That second part resolves
from pyproject.toml alone, never from the files it checks, so a pin moved
by hand to another version, even one that fits and carries its own valid
hashes, fails as well. It writes no file. `--check --offline` does only
the first part, without uv or the network.

  python scripts/lock_dependencies.py --check-installed build

exits 1 unless the running Python holds exactly the rows of
requirements/build.txt that apply to it, each once, at its pinned version
and installed from the package index, and nothing else besides pip and
the project itself. It compares names and versions, not file contents.
The release workflow runs it after a hash-checked reinstall of the lock
and before it builds (#316).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
LOCK_DIR = "requirements"
COMMAND = "python scripts/lock_dependencies.py"
# Target name -> the extras it installs on top of the dependencies.
TARGETS = {
    "cli": (),
    "gui": ("gui",),
    "dev": ("dev",),
    "build": ("build",),
}
# One lock for every platform and supported Python version, with hashes
# so pip checks every download. --no-config keeps uv settings found on
# the machine (uv.toml, [tool.uv]) out of the result.
UV_OPTIONS = ("--universal", "--generate-hashes", "--no-config")
DIGEST_PREFIX = "# input-digest: sha256:"
# The uv release the locks are made with. Another release may lay
# them out differently, so generating and the full check need exactly
# this one; CI installs it.
UV_VERSION = "0.13.1"
UV_INSTALL = f'python -m pip install "uv=={UV_VERSION}"'
# Installed distributions --check-installed allows besides the lock rows:
# the installer that put them there, the runner Python's own. The project
# being built is allowed too; it is never a row of its own locks.
INSTALLER = ("pip",)


def load_pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_project(path: Path) -> dict:
    return load_pyproject(path)["project"]


def load_policy(path: Path) -> dict:
    """[tool.lock-dependencies]: when PyPI is read for each package."""
    tool = load_pyproject(path).get("tool", {}).get("lock-dependencies", {})
    return {"resolve-at": tool.get("resolve-at", ""),
            "resolve-package-at": dict(tool.get("resolve-package-at", {}))}


def policy_problems(policy: dict) -> list[str]:
    problems = []
    times = {"resolve-at": policy["resolve-at"],
             **{f"resolve-package-at.{name}": when
                for name, when in policy["resolve-package-at"].items()}}
    for key, when in times.items():
        if not (isinstance(when, str) and when.endswith("Z")):
            problems.append(f"[tool.lock-dependencies] {key} must be a UTC time "
                            f"such as 2026-05-25T08:00:00Z, got {when!r}")
            continue
        try:
            datetime.fromisoformat(when[:-1])
        except ValueError:
            problems.append(f"[tool.lock-dependencies] {key} is not a time: {when!r}")
    return problems


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def target_requirements(project: dict, extras) -> list[str]:
    """The requirements a target installs, with the project's references
    to its own extras (`memanga[gui]`) replaced by their contents."""
    own = _normalize(project["name"])
    optional = project.get("optional-dependencies", {})
    reqs = list(project.get("dependencies", []))
    todo, seen = list(extras), set()
    while todo:
        extra = todo.pop()
        if extra in seen:
            continue
        seen.add(extra)
        for req in optional[extra]:
            match = re.fullmatch(r"([A-Za-z0-9._-]+)\[([^\]]+)\]", req.replace(" ", ""))
            if match and _normalize(match.group(1)) == own:
                todo.extend(match.group(2).split(","))
            else:
                reqs.append(req)
    # Spacing does not change a requirement.
    return sorted("".join(r.split()) for r in reqs)


def python_floor(project: dict) -> str:
    match = re.fullmatch(r">=\s*(\d+\.\d+)", project["requires-python"].strip())
    if not match:
        raise SystemExit("requires-python must be a plain floor such as >=3.11, "
                         f"got {project['requires-python']!r}")
    return match.group(1)


def input_digest(project: dict, extras, policy: dict | None = None) -> str:
    """Changes whenever what the target's lock is generated from changes."""
    policy = policy or {}
    payload = {
        "requires-python": project["requires-python"],
        "requirements": target_requirements(project, extras),
        "options": list(UV_OPTIONS),
        "resolve-at": policy.get("resolve-at", ""),
        "resolve-package-at": {_normalize(name): when for name, when
                               in policy.get("resolve-package-at", {}).items()},
    }
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def recorded_digest(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(DIGEST_PREFIX):
            return line[len(DIGEST_PREFIX):].strip()
    return None


def check(root: Path | None = None) -> list[str]:
    """Problems pyproject.toml alone shows with the locks in
    root/requirements: missing, stale or stray files. Empty when none."""
    root = root or ROOT
    project = load_project(root / "pyproject.toml")
    policy = load_policy(root / "pyproject.toml")
    lock_dir = root / LOCK_DIR
    problems = []
    for name, extras in TARGETS.items():
        path = lock_dir / f"{name}.txt"
        rel = f"{LOCK_DIR}/{path.name}"
        if not path.is_file():
            problems.append(f"{rel} is missing")
            continue
        if recorded_digest(path.read_text(encoding="utf-8")) != input_digest(
                project, extras, policy):
            problems.append(f"{rel} is out of date with pyproject.toml")
    if lock_dir.is_dir():
        expected = {f"{name}.txt" for name in TARGETS}
        for path in sorted(lock_dir.iterdir()):
            if path.name not in expected:
                problems.append(f"{LOCK_DIR}/{path.name} is not a generated lock")
    return problems


def _uv() -> list[str] | None:
    if importlib.util.find_spec("uv") is not None:
        return [sys.executable, "-m", "uv"]
    found = shutil.which("uv")
    return [found] if found else None


def _uv_version(uv) -> str | None:
    result = subprocess.run([*uv, "--version"], capture_output=True, text=True)
    parts = result.stdout.split()
    return parts[1] if result.returncode == 0 and len(parts) > 1 else None


def lock_text(name: str, body: str, digest: str) -> str:
    """The file requirements/<name>.txt: this project's own header (what it
    pins, how to remake it, the input digest), then the rows uv printed
    without a header of its own."""
    return (f"# {LOCK_DIR}/{name}.txt: every package of the {name} install,\n"
            "# pinned with hashes. Made from pyproject.toml; to change it,\n"
            "# edit pyproject.toml and run:\n"
            f"#    {COMMAND}\n"
            f"{DIGEST_PREFIX}{digest}\n"
            "# Do not edit by hand.\n"
            + body)


def render(uv, root: Path, name: str) -> str | None:
    """What requirements/<name>.txt must contain, generated from
    root/pyproject.toml alone: uv gets no existing lock to keep versions
    from, and prints the result instead of writing a file. None when uv
    fails."""
    project = load_project(root / "pyproject.toml")
    policy = load_policy(root / "pyproject.toml")
    extras = TARGETS[name]
    cmd = [*uv, "pip", "compile", "pyproject.toml", *UV_OPTIONS,
           "--python-version", python_floor(project),
           *(arg for extra in extras for arg in ("--extra", extra)),
           "--exclude-newer", policy["resolve-at"],
           *(arg for pkg, when in sorted(policy["resolve-package-at"].items())
             for arg in ("--exclude-newer-package", f"{pkg}={when}")),
           "--no-header", "--quiet"]
    result = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, encoding="utf-8")
    if result.returncode != 0:
        return None
    return lock_text(name, result.stdout, input_digest(project, extras, policy))


def check_generated(root: Path | None, uv) -> list[str]:
    """Generate every lock again from pyproject.toml and compare it with
    the committed file. Reads the locks and writes nothing."""
    root = root or ROOT
    problems = []
    for name in TARGETS:
        rel = f"{LOCK_DIR}/{name}.txt"
        fresh = render(uv, root, name)
        if fresh is None:
            problems.append(f"{rel} could not be generated")
        elif fresh.splitlines() != (root / rel).read_text(encoding="utf-8").splitlines():
            problems.append(f"{rel} differs from what pyproject.toml generates")
    return problems


def lock_rows(text: str) -> list[str]:
    """The requirement of every pinned row of a lock, marker included,
    without its hashes and comments."""
    rows = []
    for line in text.splitlines():
        if line[:1] in ("", " ", "#"):
            continue
        rows.append(line.rstrip("\\").strip())
    return rows


def installed_problems(name: str, root: Path | None = None,
                       distributions=None) -> list[str]:
    """Problems with the running environment against requirements/<name>.txt:
    a row for this platform and Python that is missing or at another
    version, rows for this platform that overlap, a distribution that no
    row pins, one installed more than once, or one installed from a URL or
    path rather than the package index. Empty when the environment holds
    exactly the lock."""
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version

    root = root or ROOT
    rel = f"{LOCK_DIR}/{name}.txt"
    if not (root / rel).is_file():
        return [f"{rel} is missing"]
    problems = []
    pinned = {}
    for row in lock_rows((root / rel).read_text(encoding="utf-8")):
        req = Requirement(row)
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        (spec,) = req.specifier
        pkg = canonicalize_name(req.name)
        if pkg in pinned and pinned[pkg] != spec.version:
            problems.append(f"{rel} pins {pkg} at both {pinned[pkg]} and "
                            f"{spec.version} here")
            continue
        pinned[pkg] = spec.version
    allowed = {canonicalize_name(n) for n in INSTALLER}
    allowed.add(canonicalize_name(load_project(root / "pyproject.toml")["name"]))

    def same(version: str, pin: str) -> bool:
        try:
            return Version(version) == Version(pin)
        except InvalidVersion:
            return version == pin

    found = {}
    if distributions is None:
        # Each search path once, so that a copy is counted once.
        distributions = importlib.metadata.distributions(
            path=list(dict.fromkeys(sys.path)))
    for dist in distributions:
        dist_name = dist.metadata["Name"]
        if dist_name:
            found.setdefault(canonicalize_name(dist_name), []).append(dist)

    for pkg, pin in sorted(pinned.items()):
        if pkg not in found:
            problems.append(f"{pkg}=={pin} from {rel} is not installed")
    for pkg, dists in sorted(found.items()):
        if pkg in allowed:
            continue
        versions = sorted(d.version for d in dists)
        if len(dists) > 1:
            # Even at one version: either copy may be the one imported.
            problems.append(f"{pkg} is installed more than once: "
                            + ", ".join(versions))
            continue
        version = versions[0]
        if pkg not in pinned:
            problems.append(f"{pkg} {version} is installed but not pinned in {rel}")
        elif not same(version, pinned[pkg]):
            problems.append(f"{pkg} is installed at {version}, "
                            f"{rel} pins {pinned[pkg]}")
        elif any(d.read_text("direct_url.json") is not None for d in dists):
            # PEP 610: a URL, VCS or local path install, not the hashed
            # download from the index the lock describes.
            problems.append(f"{pkg} {version} was installed from a URL or path, "
                            "not from the package index")
    return problems


def _run_check_installed(name: str) -> int:
    problems = installed_problems(name)
    rel = f"{LOCK_DIR}/{name}.txt"
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"Install only from the lock, in a new environment: python -m pip "
              f"install --require-hashes --only-binary :all: --force-reinstall "
              f"-r {rel}",
              file=sys.stderr)
        return 1
    try:
        pip = f" and pip {importlib.metadata.version('pip')}"
    except importlib.metadata.PackageNotFoundError:
        pip = ""
    print(f"The environment holds exactly {rel}{pip}")
    return 0


def _usable_uv() -> tuple[list[str] | None, str]:
    uv = _uv()
    version = _uv_version(uv) if uv else None
    if version == UV_VERSION:
        return uv, ""
    found = f"found uv {version}" if version else "uv was not found"
    return None, f"This needs uv {UV_VERSION} ({found}): {UV_INSTALL}"


def generate() -> int:
    policy_errors = policy_problems(load_policy(ROOT / "pyproject.toml"))
    if policy_errors:
        return _report(policy_errors, regenerate=False)
    uv, why = _usable_uv()
    if uv is None:
        print(why, file=sys.stderr)
        return 1
    (ROOT / LOCK_DIR).mkdir(exist_ok=True)
    for name in TARGETS:
        rel = f"{LOCK_DIR}/{name}.txt"
        print(f"-> {rel}")
        text = render(uv, ROOT, name)
        if text is None:
            print(f"failed to generate {rel}", file=sys.stderr)
            return 1
        (ROOT / rel).write_text(text, encoding="utf-8", newline="\n")
    return 0


def _report(problems, regenerate=True) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    if regenerate:
        print(f"Regenerate them with: {COMMAND}", file=sys.stderr)
    return 1


def _run_check(offline: bool) -> int:
    problems = policy_problems(load_policy(ROOT / "pyproject.toml"))
    if problems:
        return _report(problems, regenerate=False)
    problems = check(ROOT)
    if problems:
        return _report(problems)
    if offline:
        print("requirements/ was generated from the current pyproject.toml "
              "(inputs only)")
        return 0
    uv, why = _usable_uv()
    if uv is None:
        print(f"{why}\n--check --offline checks only that the inputs are unchanged.",
              file=sys.stderr)
        return 1
    problems = check_generated(ROOT, uv)
    if problems:
        return _report(problems)
    print("requirements/ matches what pyproject.toml generates")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate requirements/*.txt from pyproject.toml.")
    parser.add_argument("--check", action="store_true",
                        help="check that the locks are what pyproject.toml generates")
    parser.add_argument("--offline", action="store_true",
                        help="with --check: only check the inputs, without uv "
                             "or the network")
    parser.add_argument("--check-installed", metavar="TARGET", choices=TARGETS,
                        help="check that this Python holds exactly the lock "
                             "of TARGET, and nothing else besides pip")
    args = parser.parse_args(argv)
    if args.offline and not args.check:
        parser.error("--offline only goes with --check")
    if args.check_installed and args.check:
        parser.error("--check-installed does not go with --check")
    if args.check_installed:
        return _run_check_installed(args.check_installed)
    if args.check:
        return _run_check(args.offline)
    return generate()


if __name__ == "__main__":
    sys.exit(main())
