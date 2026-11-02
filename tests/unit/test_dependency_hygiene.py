"""#214: the Docker image installs its CLI dependency set with the release
lock and a Docker-only constraints file pinning every package, and
cloudscraper sessions are built in one place."""
import ast
import re
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
# The Docker image: python:3.12-slim on Linux.
DOCKER_ENV = {"sys_platform": "linux", "platform_system": "Linux",
              "os_name": "posix", "python_version": "3.12",
              "python_full_version": "3.12.0"}
DOCKER_PINS = ("requirements-lock.txt", "requirements-docker-constraints.txt")


def _requirements(name):
    reqs = []
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            reqs.append(Requirement(line))
    return reqs


def _pins(name):
    pins = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==(\S+)", line)
        if match:
            pins[canonicalize_name(match.group(1))] = match.group(2)
    return pins


def _docker_pins():
    pins = {}
    for name in DOCKER_PINS:
        pins.update(_pins(name))
    return pins


def _applies(req):
    return req.marker is None or req.marker.evaluate({**DOCKER_ENV, "extra": ""})


def test_dockerfile_installs_with_both_constraints_files():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    flat = " ".join(text.replace("\\\n", " ").split())
    assert re.search(r"^COPY requirements-docker\.txt requirements-lock\.txt "
                     r"requirements-docker-constraints\.txt \./$", text, re.M)
    assert ("pip install -r requirements-docker.txt -c requirements-lock.txt "
            "-c requirements-docker-constraints.txt") in flat
    ignored = {line.strip() for line in
               (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    assert not ignored & set(DOCKER_PINS)


def test_lock_satisfies_every_docker_requirement():
    # A floor raised in requirements-docker.txt without a lock refresh
    # would otherwise only fail during `docker build`.
    pins = _docker_pins()
    for req in _requirements("requirements-docker.txt"):
        if not _applies(req):
            continue
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is not pinned in {DOCKER_PINS}"
        assert req.specifier.contains(pins[name], prereleases=True), (
            f"the Docker pins give {req.name}=={pins[name]}, "
            f"requirements-docker.txt needs {req.specifier}")


def test_every_linux_dependency_of_the_docker_set_is_pinned():
    # Walks the dependency metadata of the installed packages from
    # requirements-docker.txt, evaluated for the Linux image, so a
    # package only Linux pulls in (keyring's Secret Service backend)
    # cannot slip in unpinned. Packages not installed here are still
    # checked for a pin, just not walked further.
    pins = _docker_pins()
    todo = [r for r in _requirements("requirements-docker.txt") if _applies(r)]
    seen, unpinned = set(), []
    while todo:
        req = todo.pop()
        name = canonicalize_name(req.name)
        if name in seen:
            continue
        seen.add(name)
        if name not in pins:
            unpinned.append(req.name)
        elif not req.specifier.contains(pins[name], prereleases=True):
            unpinned.append(f"{req.name}=={pins[name]} (needs {req.specifier})")
        try:
            requires = metadata.distribution(req.name).requires or []
        except metadata.PackageNotFoundError:
            continue
        todo.extend(r for r in map(Requirement, requires) if _applies(r))
    assert {"keyring", "jeepney", "secretstorage"} <= seen
    assert unpinned == []


def test_docker_constraints_only_add_exact_pins_the_lock_lacks():
    lock = _pins("requirements-lock.txt")
    extra = _pins("requirements-docker-constraints.txt")
    assert {"jeepney", "secretstorage", "cryptography", "cffi", "pycparser"} <= set(extra)
    assert not set(extra) & set(lock)
    rows = [r for r in _requirements("requirements-docker-constraints.txt")]
    assert len(rows) == len(extra)
    assert all(str(r.specifier).startswith("==") and r.marker is None for r in rows)


def test_docker_requirements_hold_only_linux_cli_packages():
    names = {canonicalize_name(r.name) for r in _requirements("requirements-docker.txt")}
    for name in ("pyside6", "pywin32-ctypes", "certifi", "pyinstaller"):
        assert name not in names, name
    # Every Docker requirement is also a desktop/release requirement, so
    # the lock compiled from requirements.txt covers it.
    desktop = {canonicalize_name(r.name) for r in _requirements("requirements.txt")}
    assert names - desktop <= {"urllib3"}


def test_only_base_imports_cloudscraper():
    allowed = ROOT / "memanga" / "scrapers" / "base.py"
    offenders = []
    for path in (ROOT / "memanga").rglob("*.py"):
        if path == allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "cloudscraper" or n.startswith("cloudscraper.") for n in names):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
