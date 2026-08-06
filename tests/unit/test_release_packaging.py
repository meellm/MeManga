"""Static guards for the macOS release packaging (issue #146).

The release binary's CPU architecture follows PyInstaller's `target_arch`
in `packaging/memanga-release.spec`. Left unset it silently follows the
build host, so a run on an Apple Silicon runner shipped an arm64-only
binary and left Intel Mac users with nothing to run. The fix pins the
arch per-runner via the `MEMANGA_TARGET_ARCH` env var and ships two
distinct macOS assets. These are cheap text/YAML checks because the real
build only runs on a macOS CI runner and can't be exercised here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "memanga-release.spec"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

# The GitHub Actions expression the workflow uses to thread the matrix
# arch into both the build env and the verification step.
ARCH_EXPR = '${{ matrix.target_arch }}'


def test_spec_parameterizes_target_arch_from_env():
    """The spec must read MEMANGA_TARGET_ARCH (macOS only) and feed it to
    the EXE's `target_arch`, rather than hard-coding None."""
    text = SPEC.read_text(encoding="utf-8")
    assert "MEMANGA_TARGET_ARCH" in text, \
        "spec no longer reads the MEMANGA_TARGET_ARCH env var"
    assert "target_arch=_target_arch" in text, \
        "EXE() no longer wired to the parameterized _target_arch"
    # The hard-coded default must be gone so an arm64 runner cannot ship
    # an Apple-Silicon-only binary by accident.
    assert "target_arch=None" not in text


def _build_matrix():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["build"]["strategy"]["matrix"]["include"]


def test_workflow_ships_both_macos_arch_assets():
    """Release must produce clearly named Intel and Apple Silicon assets,
    each pinned to its own architecture."""
    include = _build_matrix()
    by_asset = {e["asset_name"]: e for e in include}

    assert "MeManga-macos-arm64" in by_asset, "Apple Silicon asset dropped"
    assert "MeManga-macos-x64" in by_asset, "Intel macOS asset missing"

    arm = by_asset["MeManga-macos-arm64"]
    intel = by_asset["MeManga-macos-x64"]
    assert arm["target_arch"] == "arm64"
    assert intel["target_arch"] == "x86_64"
    # Intel slice must be built natively on an Intel runner image
    # (macos-26-intel is GitHub's current standard x64 macOS runner),
    # not cross-compiled from Apple Silicon.
    assert intel["os"] == "macos-26-intel"


def _step_named(fragment):
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in data["jobs"]["build"]["steps"]:
        if fragment in step.get("name", ""):
            return step
    return None


def test_build_step_forwards_target_arch_env():
    """The arch only reaches the spec if the build step exports it."""
    step = _step_named("Build release executable")
    assert step is not None
    env = step.get("env", {})
    assert env.get("MEMANGA_TARGET_ARCH") == ARCH_EXPR


def test_workflow_verifies_architecture_before_upload():
    """A macOS-gated step must assert the built slice matches the target
    so a mis-built asset never reaches the release page."""
    step = _step_named("Verify macOS artifact architecture")
    assert step is not None, "architecture verification step missing"
    assert step.get("if") == "runner.os == 'macOS'"
    run = step.get("run", "")
    assert "lipo -archs" in run
    assert ARCH_EXPR in run
