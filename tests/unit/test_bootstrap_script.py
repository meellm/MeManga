"""Installing the package never runs the setup steps (#212).

The one-step setup (venv, requirements, Playwright browsers, `sudo
apt-get` on Linux, config folder) used to live in a root `setup.py`.
`setuptools.build_meta` executes a root `setup.py` as `__main__` for
every build hook, so `pip install .`, `pip install -e ".[dev]"` and
`pip wheel .` ran the whole setup. It now lives in
`scripts/bootstrap.py`, outside the build, and `pyproject.toml` is the
only packaging config.

The setup itself downloads browsers and installs system packages, so
its commands are recorded here instead of being run.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.py"
# Where users are told how to set up a checkout.
SETUP_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "docs" / "Guide.md",
    REPO_ROOT / "scripts" / "windows" / "setup.bat",
    REPO_ROOT / "scripts" / "windows" / "run.bat",
    REPO_ROOT / "scripts" / "linux" / "setup.sh",
]


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("memanga_bootstrap", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_root_setup_py_for_the_build_backend_to_run():
    assert not (REPO_ROOT / "setup.py").exists()


def test_pyproject_is_the_only_packaging_config():
    tomllib = pytest.importorskip("tomllib")
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    assert "backend-path" not in data["build-system"]
    assert data["project"]["name"] == "memanga"
    assert data["project"]["scripts"]["memanga"] == "memanga.cli:main"
    # scripts/ (with bootstrap.py) never ends up in a wheel.
    assert data["tool"]["setuptools"]["packages"]["find"]["include"] == ["memanga*"]


def test_importing_bootstrap_runs_nothing(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"ran on import: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr("os.chdir", refuse)

    bootstrap = _load_bootstrap()

    assert bootstrap.PROJECT_DIR == REPO_ROOT


def test_bootstrap_runs_from_project_root(monkeypatch, capsys):
    bootstrap = _load_bootstrap()
    commands = []
    chdirs = []

    def record(cmd, *args, **kwargs):
        commands.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="cfg\n", stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", record)
    monkeypatch.setattr(bootstrap.os, "chdir", chdirs.append)
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")

    bootstrap.main()

    assert chdirs == [REPO_ROOT]
    assert (REPO_ROOT / "requirements" / "gui.txt").is_file()
    assert any("install -r requirements/gui.txt" in c for c in commands)
    assert any("-m playwright install chromium firefox" in c for c in commands)
    assert not [c for c in commands if "sudo" in c or "install-deps" in c]
    assert "Setup complete" in capsys.readouterr().out


@pytest.mark.parametrize("path", SETUP_DOCS, ids=lambda p: p.name)
def test_setup_instructions_name_bootstrap_not_setup_py(path):
    assert "setup.py" not in path.read_text(encoding="utf-8")
