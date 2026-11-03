"""#219: the desktop app's Qt runtime is the ``gui`` extra.

The default install is the CLI, for servers, containers and scheduled
checks. Without the extra the GUI entry points exit with the install
command instead of a ModuleNotFoundError traceback.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parents[2]
QT_PACKAGES = ("PySide6", "shiboken6")
REPO_HOME = "https://example.invalid/home"


@pytest.fixture(scope="module")
def project():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]


def _names(requirements):
    return {canonicalize_name(Requirement(r).name) for r in requirements}


def _locked(name):
    """canonical name -> pinned version for every row of requirements/<name>.txt."""
    pins = {}
    path = ROOT / "requirements" / f"{name}.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and line[0] not in "# ":
            req = Requirement(line.rstrip("\\ "))
            pins[canonicalize_name(req.name)] = next(iter(req.specifier)).version
    return pins


def _block_qt(monkeypatch):
    # A None entry makes both find_spec() and import treat it as absent.
    for name in QT_PACKAGES:
        monkeypatch.setitem(sys.modules, name, None)


# ─── Metadata ────────────────────────────────────────────────────────────

def test_default_dependencies_have_no_gui_packages(project):
    names = _names(project["dependencies"])
    assert not names & {canonicalize_name(n) for n in QT_PACKAGES}


def test_gui_extra_has_pyside6_with_the_desktop_floor(project):
    (req,) = [Requirement(r) for r in project["optional-dependencies"]["gui"]]
    assert canonicalize_name(req.name) == "pyside6"
    # The source setup and the builds install a PySide6 that meets it.
    for lock in ("gui", "dev", "build"):
        assert req.specifier.contains(_locked(lock)["pyside6"]), lock


def test_cli_lock_has_no_qt():
    assert not set(_locked("cli")) & {canonicalize_name(n) for n in QT_PACKAGES}


def test_missing_gui_hint_installs_exactly_the_gui_extra(project):
    import memanga.gui as gui
    assert sorted(gui.GUI_REQUIREMENTS.values()) == sorted(
        project["optional-dependencies"]["gui"])


@pytest.mark.parametrize("extra", ["dev", "build"])
def test_gui_test_and_build_extras_pull_in_the_gui_extra(project, extra):
    # pytest-qt and the PyInstaller desktop build need Qt.
    reqs = [Requirement(r) for r in project["optional-dependencies"][extra]]
    assert any(r.name == "memanga" and r.extras == {"gui"} for r in reqs)


def test_both_scripts_stay_declared(project):
    assert project["scripts"]["memanga"] == "memanga.cli:main"
    assert project["scripts"]["memanga-gui"] == "memanga.gui:launch_gui"


def test_no_module_outside_the_gui_imports_qt_at_import_time():
    # A function-level import (doctor's guarded Qt version lookup) is fine.
    offenders = []
    for path in (ROOT / "memanga").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("memanga", "gui"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        todo = list(tree.body)
        while todo:
            node = todo.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                todo.extend(ast.iter_child_nodes(node))
                continue
            if any(n.split(".")[0] in QT_PACKAGES for n in names):
                offenders.append(str(rel))
    assert offenders == []


# ─── Behavior without the extra ──────────────────────────────────────────

def test_cli_runs_without_qt(tmp_path):
    code = (
        "import sys\n"
        f"for name in {QT_PACKAGES!r}:\n"
        "    sys.modules[name] = None\n"
        "import memanga.api, memanga.doctor, memanga.gui\n"
        "from memanga.cli import main\n"
        "sys.argv = ['memanga', '--version']\n"
        "main()\n"
    )
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(ROOT)}
    env.pop("MEMANGA_CLI_ONLY", None)
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("memanga ")


def test_launch_gui_without_qt_exits_with_install_command(
        monkeypatch, isolated_home, capsys):
    _block_qt(monkeypatch)
    import memanga.gui as gui
    assert gui._missing_gui_dependency() == "PySide6"
    monkeypatch.setattr(gui, "_repository_url",
                        lambda: "https://example.invalid/MeManga")

    with pytest.raises(SystemExit) as exc:
        gui.launch_gui()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "needs PySide6, which is not installed" in err
    assert ('pip install "memanga[gui] @ '
            'git+https://example.invalid/MeManga"') in err
    assert 'pip install -e ".[gui]"' in err
    assert "Traceback" not in err


def test_install_hint_without_package_metadata_is_still_runnable(
        monkeypatch):
    # #219: an install whose metadata has no Repository URL still gets a
    # command that works from any folder, and no placeholder.
    import memanga.gui as gui
    monkeypatch.setattr(gui, "_repository_url", lambda: None)
    monkeypatch.setattr(sys, "executable", "/opt/env/bin/python3")
    hint = gui._gui_install_hint()
    assert ('\n    /opt/env/bin/python3 -m pip install "PySide6>=6.5.0"\n'
            in hint)
    assert "memanga[gui] @" not in hint
    assert "<" not in hint and ">=6.5.0" in hint
    assert 'pip install -e ".[gui]"' in hint


def _hint_for(monkeypatch, executable, windows):
    import memanga.gui as gui
    monkeypatch.setattr(gui, "_repository_url", lambda: None)
    monkeypatch.setattr(gui, "_windows", lambda: windows)
    monkeypatch.setattr(sys, "executable", executable)
    return gui._gui_install_hint()


@pytest.mark.parametrize("executable", [
    "/opt/My Env/bin/python3",
    "/opt/it's $HOME; `x` & (y)/bin/python3",
])
def test_posix_hint_keeps_and_quotes_the_running_python(
        monkeypatch, executable):
    # A bare `python` may be another environment; the quoted path must
    # come back unchanged when the shell splits the line.
    import shlex
    hint = _hint_for(monkeypatch, executable, windows=False)
    (line,) = [ln for ln in hint.splitlines() if "PySide6>=6.5.0" in ln]
    assert shlex.split(line) == [
        executable, "-m", "pip", "install", "PySide6>=6.5.0"]
    (checkout,) = [ln for ln in hint.splitlines() if ".[gui]" in ln]
    assert shlex.split(checkout) == [
        executable, "-m", "pip", "install", "-e", ".[gui]"]


def test_windows_hint_quotes_a_path_with_spaces_for_cmd_and_powershell(
        monkeypatch):
    hint = _hint_for(monkeypatch, r"C:\Program Files\Python312\python.exe",
                     windows=True)
    assert ('\n    "C:\\Program Files\\Python312\\python.exe" '
            '-m pip install "PySide6>=6.5.0"\n') in hint
    assert ("\n    & 'C:\\Program Files\\Python312\\python.exe' "
            '-m pip install "PySide6>=6.5.0"  # PowerShell\n') in hint
    assert "\n    python -m pip" not in hint


def test_windows_hint_escapes_a_quote_for_powershell(monkeypatch):
    hint = _hint_for(monkeypatch, r"C:\Tools\it's here\python.exe",
                     windows=True)
    assert ("& 'C:\\Tools\\it''s here\\python.exe' "
            '-m pip install "PySide6>=6.5.0"  # PowerShell') in hint
    assert '"C:\\Tools\\it\'s here\\python.exe" -m pip' in hint


def test_windows_hint_plain_path_is_one_line_for_both_shells(monkeypatch):
    hint = _hint_for(monkeypatch, r"C:\Py312\python.exe", windows=True)
    assert ('\n    C:\\Py312\\python.exe -m pip install '
            '"PySide6>=6.5.0"\n') in hint
    assert "PowerShell" not in hint


def test_repository_url_comes_from_the_project_urls(monkeypatch, project):
    from importlib import metadata
    import memanga.gui as gui
    expected = project["urls"]["Repository"]
    fake = {"Project-URL": [f"Homepage, {REPO_HOME}",
                            f"Repository, {expected}"]}

    class _Meta:
        def get_all(self, name):
            return fake.get(name)

    monkeypatch.setattr(metadata, "metadata",
                        lambda name: _Meta() if name == "memanga" else None)
    assert gui._repository_url() == expected

    def _missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "metadata", _missing)
    assert gui._repository_url() is None


def test_gui_flag_without_qt_exits_with_install_command(
        monkeypatch, isolated_home, capsys):
    # Installed metadata without a Repository URL (#219): the CLI path
    # still prints a command that installs the gui extra's package.
    monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
    _block_qt(monkeypatch)
    import memanga.gui as gui
    monkeypatch.setattr(gui, "_repository_url", lambda: None)
    monkeypatch.setattr(sys, "argv", ["memanga", "--gui"])
    import memanga.cli as cli

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "needs PySide6" in err
    assert ' -m pip install "PySide6>=6.5.0"\n' in err
    assert 'pip install -e ".[gui]"' in err
    assert "memanga[gui] @" not in err
    assert "<repository URL>" not in err
    assert "Traceback" not in err


def test_help_says_gui_needs_the_extra(monkeypatch, isolated_home, capsys):
    monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
    monkeypatch.setattr(sys, "argv", ["memanga", "--help"])
    import memanga.cli as cli
    with pytest.raises(SystemExit):
        cli.main()
    out = " ".join(capsys.readouterr().out.split())
    assert "(needs the gui extra)" in out


def test_installed_qt_passes_the_check():
    pytest.importorskip("PySide6")
    import memanga.gui as gui
    assert gui._missing_gui_dependency() is None
