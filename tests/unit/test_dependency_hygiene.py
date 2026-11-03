"""#214: the Docker image installs its CLI dependencies from a lock that
pins every package it pulls in, Linux-only ones included (#315: that lock
is requirements/cli.txt, generated from pyproject.toml), and cloudscraper
sessions are built in one place."""
import ast
import re
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parents[2]
# The Docker image: python:3.12-slim on Linux.
DOCKER_ENV = {"sys_platform": "linux", "platform_system": "Linux",
              "os_name": "posix", "python_version": "3.12",
              "python_full_version": "3.12.0",
              "implementation_name": "cpython",
              "platform_python_implementation": "CPython"}
DOCKER_LOCK = "requirements/cli.txt"


def _applies(req):
    return req.marker is None or req.marker.evaluate({**DOCKER_ENV, "extra": ""})


def _dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return [Requirement(r) for r in project["project"]["dependencies"]]


def _docker_pins():
    """The version the image installs of each package in the lock."""
    pins = {}
    for line in (ROOT / DOCKER_LOCK).read_text(encoding="utf-8").splitlines():
        if not line or line[0] in "# ":
            continue
        req = Requirement(line.rstrip("\\ "))
        if _applies(req):
            (spec,) = req.specifier
            assert spec.operator == "==", line
            name = canonicalize_name(req.name)
            assert name not in pins, f"{req.name} pinned twice for the image"
            pins[name] = spec.version
    return pins


def test_dockerfile_installs_the_cli_lock_with_hashes():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    flat = " ".join(text.replace("\\\n", " ").split())
    assert re.search(r"^COPY requirements/cli\.txt \./requirements/$", text, re.M)
    assert "pip install --require-hashes -r requirements/cli.txt" in flat
    ignored = {line.strip().rstrip("/") for line in
               (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    assert not ignored & {"requirements", DOCKER_LOCK}


def test_lock_satisfies_every_docker_requirement():
    # A floor raised in pyproject.toml without a lock refresh would
    # otherwise only fail during `docker build`.
    pins = _docker_pins()
    for req in _dependencies():
        if not _applies(req):
            continue
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is not pinned in {DOCKER_LOCK}"
        assert req.specifier.contains(pins[name], prereleases=True), (
            f"{DOCKER_LOCK} gives {req.name}=={pins[name]}, "
            f"pyproject.toml needs {req.specifier}")


def test_every_linux_dependency_of_the_docker_set_is_pinned():
    # Walks the dependency metadata of the installed packages from
    # pyproject.toml, evaluated for the Linux image, so a package only
    # Linux pulls in (keyring's Secret Service backend) cannot slip in
    # unpinned. Packages not installed here are still checked for a pin,
    # just not walked further.
    pins = _docker_pins()
    todo = [r for r in _dependencies() if _applies(r)]
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


def test_docker_lock_pins_the_linux_keyring_backend():
    # The lock covers every platform, so the Linux-only packages keyring
    # adds there have rows the image uses.
    pins = _docker_pins()
    assert {"jeepney", "secretstorage", "cryptography", "cffi", "pycparser"} <= set(pins)


def test_docker_lock_holds_only_cli_packages():
    pins = _docker_pins()
    for name in ("pyside6", "shiboken6", "pyinstaller"):
        assert name not in pins, name


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
