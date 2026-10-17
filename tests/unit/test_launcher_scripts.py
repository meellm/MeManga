"""Launcher scripts keep the caller's working directory (#406).

`scripts/run.sh` and `scripts/memanga_launcher.py` are run for real
against a throwaway checkout whose `memanga` package only reports what
it sees. The Windows batch files cannot run here, so they get static
checks.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = REPO_ROOT / "scripts" / "run.sh"
LAUNCHER = REPO_ROOT / "scripts" / "memanga_launcher.py"
RUN_BAT = REPO_ROOT / "scripts" / "windows" / "run.bat"
SETUP_BAT = REPO_ROOT / "scripts" / "windows" / "setup.bat"
# How both wrappers start the launcher.
LAUNCH = (sys.executable, "-I")

FAKE_MAIN = """\
import json, os, sys
try:
    import fakedep
    dep = os.path.dirname(os.path.abspath(fakedep.__file__))
except ImportError:
    dep = None
args = sys.argv[1:]
cwd = os.path.realpath(os.getcwd())
print(json.dumps({
    "cwd": os.getcwd(),
    "args": args,
    "resolved": [os.path.abspath(a) for a in args],
    "package": os.path.dirname(os.path.abspath(__file__)),
    "venv": os.environ.get("FAKE_VENV_PYTHON"),
    "activated": os.environ.get("FAKE_VENV_ACTIVATED"),
    "pythonpath": os.environ.get("PYTHONPATH"),
    "dep": dep,
    "cwd_on_path": any(os.path.realpath(p or ".") == cwd for p in sys.path),
}))
sys.exit(3 if "fail" in args else 0)
"""

needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="run.sh needs bash",
)


def _checkout(tmp_path, with_venv=True):
    """A minimal checkout: scripts/run.sh plus a fake memanga package."""
    root = tmp_path / "My Checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(RUN_SH, root / "scripts" / "run.sh")
    shutil.copy2(LAUNCHER, root / "scripts" / "memanga_launcher.py")
    (root / "scripts" / "run.sh").chmod(0o755)
    (root / "memanga").mkdir()
    (root / "memanga" / "__init__.py").write_text("")
    (root / "memanga" / "__main__.py").write_text(FAKE_MAIN)
    if with_venv:
        bin_dir = root / "venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "activate").write_text("export FAKE_VENV_ACTIVATED=1\n")
        python = bin_dir / "python"
        python.write_text(
            "#!/bin/sh\n"
            "export FAKE_VENV_PYTHON=1\n"
            f'exec "{sys.executable}" "$@"\n'
        )
        python.chmod(0o755)
    return root


def _shadowing_setup(tmp_path):
    """A checkout, a dependency dir, and a caller dir full of look-alikes."""
    root = _checkout(tmp_path)
    deps = tmp_path / "deps"
    deps.mkdir()
    (deps / "fakedep.py").write_text("")
    caller = tmp_path / "caller"
    (caller / "memanga").mkdir(parents=True)
    (caller / "memanga" / "__init__.py").write_text("")
    (caller / "memanga" / "__main__.py").write_text("raise SystemExit(96)\n")
    (caller / "json.py").write_text("raise SystemExit(97)\n")
    (caller / "fakedep.py").write_text("raise SystemExit(98)\n")
    # Loaded while the interpreter or the launcher itself starts up.
    (caller / "sitecustomize.py").write_text("raise SystemExit(94)\n")
    (caller / "runpy.py").write_text("raise SystemExit(95)\n")
    return root, caller, deps


def _caller_dir_entry(form, caller, tmp_path):
    """A PYTHONPATH entry that points at the caller's directory."""
    if form == "dot":
        return "."
    if form == "empty":
        return ""
    if form == "absolute":
        return str(caller)
    alias = tmp_path / "alias"
    try:
        os.symlink(caller, alias, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create a directory symlink here")
    return str(alias)


CALLER_DIR_FORMS = ["dot", "empty", "absolute", "symlink"]


def _check_caller_dir_dropped(script, prefix, form, tmp_path):
    root, caller, deps = _shadowing_setup(tmp_path)
    deps2 = tmp_path / "deps2"
    deps2.mkdir()
    entry = _caller_dir_entry(form, caller, tmp_path)
    pythonpath = os.pathsep.join([str(deps), entry, str(deps2)])

    result, seen = _run(script(root), caller, "import", "backup.json",
                        prefix=prefix, env_extra={"PYTHONPATH": pythonpath})

    assert result.returncode == 0
    assert Path(seen["package"]) == (root / "memanga").resolve()
    assert Path(seen["dep"]) == deps.resolve()
    assert seen["cwd_on_path"] is False
    assert seen["pythonpath"] == os.pathsep.join([str(deps), str(deps2)])
    assert Path(seen["resolved"][1]) == caller.resolve() / "backup.json"


def _run(script, cwd, *args, env_extra=None, prefix=("bash",)):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONSAFEPATH")}
    env.pop("FAKE_VENV_PYTHON", None)
    env.pop("FAKE_VENV_ACTIVATED", None)
    env.update(env_extra or {})
    result = subprocess.run(
        [*prefix, str(script), *args], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


@needs_bash
class TestRunSh:
    def test_keeps_caller_cwd_for_relative_paths(self, tmp_path):
        root = _checkout(tmp_path)
        caller = tmp_path / "caller dir"
        caller.mkdir()

        result, seen = _run(root / "scripts" / "run.sh", caller,
                            "export", "backup.json")

        assert result.returncode == 0
        assert Path(seen["cwd"]) == caller.resolve()
        assert seen["args"] == ["export", "backup.json"]
        assert Path(seen["resolved"][1]) == caller.resolve() / "backup.json"
        assert Path(seen["package"]) == (root / "memanga").resolve()
        assert seen["cwd_on_path"] is False
        assert seen["pythonpath"] is None

    def test_caller_modules_cannot_shadow_imports(self, tmp_path):
        root, caller, deps = _shadowing_setup(tmp_path)

        result, seen = _run(root / "scripts" / "run.sh", caller,
                            "import", "backup.json",
                            env_extra={"PYTHONPATH": str(deps)})

        assert result.returncode == 0
        assert Path(seen["package"]) == (root / "memanga").resolve()
        assert Path(seen["dep"]) == deps.resolve()
        assert Path(seen["resolved"][1]) == caller.resolve() / "backup.json"
        assert seen["cwd_on_path"] is False

    @pytest.mark.parametrize("form", CALLER_DIR_FORMS)
    def test_caller_dir_in_pythonpath_is_dropped(self, form, tmp_path):
        _check_caller_dir_dropped(lambda root: root / "scripts" / "run.sh",
                                  ("bash",), form, tmp_path)

    def test_uses_venv_python_by_absolute_path(self, tmp_path):
        root = _checkout(tmp_path)

        _, seen = _run(root / "scripts" / "run.sh", tmp_path, "list")

        assert seen["venv"] == "1"
        assert seen["activated"] == "1"

    def test_relative_script_path_from_another_dir(self, tmp_path):
        root = _checkout(tmp_path)
        caller = tmp_path / "elsewhere"
        caller.mkdir()

        _, seen = _run(os.path.relpath(root / "scripts" / "run.sh", caller),
                       caller, "import", "in.json")

        assert Path(seen["cwd"]) == caller.resolve()
        assert Path(seen["package"]) == (root / "memanga").resolve()

    def test_arguments_with_spaces_pass_through(self, tmp_path):
        root = _checkout(tmp_path)

        _, seen = _run(root / "scripts" / "run.sh", tmp_path,
                       "export", "my backup.json")

        assert seen["args"] == ["export", "my backup.json"]

    def test_existing_pythonpath_is_untouched(self, tmp_path):
        root = _checkout(tmp_path)
        extra = str(tmp_path / "extra")

        _, seen = _run(root / "scripts" / "run.sh", tmp_path, "list",
                       env_extra={"PYTHONPATH": extra})

        assert seen["pythonpath"] == extra

    def test_exit_code_propagates(self, tmp_path):
        root = _checkout(tmp_path)

        result, _ = _run(root / "scripts" / "run.sh", tmp_path, "fail")

        assert result.returncode == 3

    @pytest.mark.skipif(shutil.which("python3") is None,
                        reason="needs python3 on PATH")
    def test_without_venv_falls_back_to_python3(self, tmp_path):
        root = _checkout(tmp_path, with_venv=False)
        caller = tmp_path / "caller"
        caller.mkdir()

        result, seen = _run(root / "scripts" / "run.sh", caller, "list")

        assert result.returncode == 0
        assert seen["venv"] is None
        assert Path(seen["cwd"]) == caller.resolve()
        assert Path(seen["package"]) == (root / "memanga").resolve()


class TestLauncher:
    """The Python part of both wrappers, run with the current interpreter."""

    def test_keeps_caller_cwd_and_args(self, tmp_path):
        root = _checkout(tmp_path, with_venv=False)
        caller = tmp_path / "caller"
        caller.mkdir()

        result, seen = _run(root / "scripts" / "memanga_launcher.py", caller,
                            "export", "my backup.json", prefix=LAUNCH)

        assert result.returncode == 0
        assert Path(seen["cwd"]) == caller.resolve()
        assert seen["args"] == ["export", "my backup.json"]
        assert Path(seen["resolved"][1]) == caller.resolve() / "my backup.json"
        assert Path(seen["package"]) == (root / "memanga").resolve()

    def test_caller_modules_cannot_shadow_imports(self, tmp_path):
        root, caller, deps = _shadowing_setup(tmp_path)

        result, seen = _run(root / "scripts" / "memanga_launcher.py", caller,
                            "list", prefix=LAUNCH,
                            env_extra={"PYTHONPATH": str(deps)})

        assert result.returncode == 0
        assert Path(seen["package"]) == (root / "memanga").resolve()
        assert Path(seen["dep"]) == deps.resolve()
        assert seen["cwd_on_path"] is False
        assert seen["pythonpath"] == str(deps)

    @pytest.mark.parametrize("form", CALLER_DIR_FORMS)
    def test_caller_dir_in_pythonpath_is_dropped(self, form, tmp_path):
        _check_caller_dir_dropped(
            lambda root: root / "scripts" / "memanga_launcher.py",
            LAUNCH, form, tmp_path)

    def test_exit_code_propagates(self, tmp_path):
        root = _checkout(tmp_path, with_venv=False)

        result, _ = _run(root / "scripts" / "memanga_launcher.py", tmp_path,
                         "fail", prefix=LAUNCH)

        assert result.returncode == 3


def _commands(path):
    """Batch file lines without comments, lower-cased."""
    lines = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not re.match(r"(?i)^(rem\b|::|@echo off$)", line):
            lines.append(line.lower())
    return lines


CHANGES_DIR = re.compile(r"^(cd|chdir|pushd)\b|[(&|]\s*(cd|chdir|pushd)\b")


@pytest.mark.parametrize("bat", [RUN_BAT, SETUP_BAT], ids=lambda p: p.name)
def test_batch_files_do_not_change_directory(bat):
    commands = _commands(bat)

    assert commands[0] == "setlocal"
    assert not [c for c in commands if CHANGES_DIR.search(c)]


def test_run_bat_runs_launcher_isolated_with_absolute_venv_python():
    text = RUN_BAT.read_text()
    commands = _commands(RUN_BAT)

    assert 'set "PROJECT_DIR=%%~fI"' in text
    assert 'set "PYTHON=%PROJECT_DIR%\\venv\\Scripts\\python.exe"' in text
    assert commands[-1] == (
        '"%python%" -i "%project_dir%\\scripts\\memanga_launcher.py" %*')
    assert not [c for c in commands if "-m memanga" in c or "pythonpath" in c]


def test_setup_bat_runs_setup_py_by_script_path():
    assert 'python "%~dp0..\\..\\setup.py"' in SETUP_BAT.read_text()
