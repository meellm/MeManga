"""#289: the lint, format and type checks are configured once, in
pyproject.toml, and the commit hooks, the commands run by hand and the CI
lint job use the same versions and scopes."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ("ruff", "mypy", "pre-commit")


@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def hooks():
    """Every hook of .pre-commit-config.yaml by id, with its repository."""
    config = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    found = {}
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            assert hook["id"] not in found, hook["id"]
            found[hook["id"]] = {**hook, "repo": repo["repo"], "rev": repo.get("rev")}
    return config, found


def _names(requirements):
    return {canonicalize_name(Requirement(r).name) for r in requirements}


def _pins(target):
    """Package name -> pinned version of requirements/<target>.txt."""
    text = (ROOT / "requirements" / f"{target}.txt").read_text(encoding="utf-8")
    return {
        canonicalize_name(name): version
        for name, version in re.findall(r"^([A-Za-z0-9._-]+)==(\S+)", text, re.M)
    }


# ─── Dependencies ───────────────────────────────────────────────────────


def test_the_tools_are_dev_dependencies_only(pyproject):
    project = pyproject["project"]
    extras = project["optional-dependencies"]
    assert set(TOOLS) <= _names(extras["dev"])
    for requirements in (project["dependencies"], extras["gui"], extras["build"]):
        assert not set(TOOLS) & _names(requirements)


def test_only_the_dev_lock_pins_the_tools():
    assert set(TOOLS) <= set(_pins("dev"))
    for target in ("cli", "gui", "build"):
        assert not set(TOOLS) & set(_pins(target)), target


# ─── One version of each tool ───────────────────────────────────────────


def test_the_ruff_hook_is_the_locked_ruff(hooks):
    _, found = hooks
    locked = _pins("dev")["ruff"]
    assert found["ruff-check"]["rev"] == f"v{locked}"
    assert found["ruff-format"]["rev"] == f"v{locked}"


def test_ci_lints_with_the_locked_ruff_and_the_configured_rules(pyproject):
    ci = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    (run,) = [
        step["run"]
        for step in ci["jobs"]["lint"]["steps"]
        if "ruff check" in step.get("run", "")
    ]
    assert re.search(r"ruff==([\d.]+) ", run).group(1) == _pins("dev")["ruff"]
    ruff = pyproject["tool"]["ruff"]
    selected = re.search(r"--select (\S+)", run).group(1).split(",")
    assert sorted(selected) == sorted(ruff["lint"]["select"])
    assert f"--target-version {ruff['target-version']}" in run


def test_mypy_runs_from_the_dev_install_on_its_configured_files(hooks):
    # A hook environment of its own would bring a second mypy version and
    # would not see the installed packages.
    _, found = hooks
    mypy = found["mypy"]
    assert mypy["repo"] == "local"
    assert mypy["language"] == "system"
    assert mypy["entry"] == "python -m mypy"
    assert mypy["pass_filenames"] is False
    for changed in ("memanga/state.py", "pyproject.toml"):
        assert re.search(mypy["files"], changed), changed


# ─── Scopes ─────────────────────────────────────────────────────────────


def test_the_hooks_have_no_settings_of_their_own(hooks):
    # Rules, excluded paths and checked files come from pyproject.toml, so
    # a hook and the same command run by hand agree.
    _, found = hooks
    for hook_id in ("ruff-check", "ruff-format", "mypy"):
        assert "args" not in found[hook_id], hook_id


def test_every_configured_path_exists(pyproject):
    # A renamed or removed file would otherwise stay listed.
    tool = pyproject["tool"]
    unformatted = tool["ruff"]["format"]["exclude"]
    checked = tool["mypy"]["files"]
    # A file may be in both lists: type checked and not formatted yet.
    for paths in (unformatted, checked):
        assert len(paths) == len(set(paths))
        for path in paths:
            assert (ROOT / path.removesuffix("/**")).exists(), path
    # Ruff matches a pattern against each file, not the folders above it:
    # a directory named without `/**` would exclude nothing.
    for path in unformatted:
        assert path.endswith("/**") == (ROOT / path.removesuffix("/**")).is_dir(), path
    for pattern in tool["mypy"]["exclude"]:
        tracked = pattern.removeprefix("^").removesuffix("$").replace("\\.", ".")
        assert (ROOT / tracked).is_file(), pattern


def test_some_code_is_formatted_and_type_checked(pyproject):
    tool = pyproject["tool"]
    unformatted = tool["ruff"]["format"]["exclude"]
    assert "memanga/**" not in unformatted
    assert (ROOT / "memanga" / "__init__.py").is_file()
    assert "memanga/__init__.py" not in unformatted
    assert tool["mypy"]["files"]


def test_mypy_reports_every_error_of_the_files_it_checks(pyproject):
    mypy = pyproject["tool"]["mypy"]
    sections = [mypy, *mypy.get("overrides", [])]
    for section in sections:
        assert "ignore_errors" not in section
        assert "disable_error_code" not in section
        assert section.get("follow_imports", "normal") in ("normal", "silent")
    assert "ignore_missing_imports" not in mypy
    assert mypy["check_untyped_defs"] is True


@pytest.mark.parametrize("path", ["README.md", "docs/README.md", "tests/README.md"])
def test_no_hook_touches_a_readme(hooks, path):
    config, _ = hooks
    assert (ROOT / path).is_file()
    assert re.search(config["exclude"], path)


def test_ruff_leaves_markdown_files_alone(pyproject):
    # Ruff's own default includes Markdown files, whose Python code blocks
    # `ruff format .` would rewrite. The exclusion also holds for a file
    # named on the command line.
    ruff = pyproject["tool"]["ruff"]
    assert "*.md" in ruff["extend-exclude"]
    assert ruff["force-exclude"] is True
    assert "include" not in ruff and "extend-include" not in ruff


def test_the_ruff_hooks_take_python_files_only(hooks):
    # The format hook's own default includes Markdown, whose Python code
    # blocks it rewrites.
    _, found = hooks
    for hook_id in ("ruff-check", "ruff-format"):
        assert found[hook_id]["types_or"] == ["python", "pyi"], hook_id


@pytest.mark.parametrize(
    "path, fixed",
    [
        ("memanga/cli.py", True),
        ("docs/developer/contributing.md", True),
        ("LICENSE", False),
        ("packaging/licenses/GPL-3.0.txt", False),
        ("tests/unit/fixtures/schema/config-v0.yaml", False),
        ("tests/scrapers/fixtures/page.html", False),
    ],
)
def test_end_of_file_fixer_leaves_licenses_and_fixtures(hooks, path, fixed):
    _, found = hooks
    excluded = re.search(found["end-of-file-fixer"]["exclude"], path)
    assert bool(excluded) is not fixed
