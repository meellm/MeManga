"""Static guards for the release packaging (issues #146 and #167).

macOS (#146): the release binary's CPU architecture follows PyInstaller's
`target_arch` in `packaging/memanga-release.spec`. Left unset it silently
follows the build host, so a run on an Apple Silicon runner shipped an
arm64-only binary and left Intel Mac users with nothing to run. The fix
pins the arch per-runner via the `MEMANGA_TARGET_ARCH` env var and ships
two distinct macOS assets.

Linux (#167): a GitHub release asset is raw bytes with no Unix mode, and
browsers save the download without the executable bit, so a bare ELF
lands as `-rw-r--r--` and fails with "Permission denied" before the app
starts. The fix ships Linux as a `.tar.gz`, which records the +x bit
inside the archive so `tar xzf` restores a runnable binary, and the
workflow gates the release on that bit surviving extraction.

Most of these are cheap text/YAML checks because the real build only runs
on CI runners and can't be exercised here; the one round-trip test proves
the archive format itself preserves the executable bit.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "memanga-release.spec"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
README = REPO_ROOT / "README.md"

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


# ── Linux archive packaging (issue #167) ──────────────────────────────

def _build_steps():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["build"]["steps"]


def _step_index(fragment):
    for i, step in enumerate(_build_steps()):
        if fragment in step.get("name", ""):
            return i
    return -1


def test_workflow_ships_linux_x64_from_ubuntu_runner():
    """The Linux leg must build the x86_64 asset on the Ubuntu runner."""
    by_asset = {e["asset_name"]: e for e in _build_matrix()}
    assert "MeManga-linux-x64" in by_asset, "Linux x64 asset dropped"
    assert by_asset["MeManga-linux-x64"]["os"] == "ubuntu-latest"


def test_linux_binary_is_packaged_as_targz():
    """Linux must upload a gzip tarball, not a bare ELF. The archive is
    what preserves the executable bit through a GitHub release download
    (issue #167); the packaging step marks the binary +x and tars it,
    then exposes the tarball path for the upload step."""
    step = _step_named("Package artifact for upload")
    assert step is not None, "packaging step missing"
    assert step.get("id") == "package", "upload step can't reference the path"
    run = step.get("run", "")
    # Linux-only branch: make it executable, then wrap it in a tarball.
    assert "runner.os" in run and "Linux" in run
    assert "chmod +x" in run
    assert "tar -czf" in run
    assert ".tar.gz" in run
    # The final upload path is threaded out as a step output so a single
    # upload step serves every OS.
    assert 'upload_path=' in run
    assert '"$GITHUB_OUTPUT"' in run or "$GITHUB_OUTPUT" in run


def test_upload_step_uses_packaged_path():
    """The upload must ship whatever the packaging step produced (the
    tarball on Linux, the raw binary elsewhere), not a hard-coded name."""
    step = _step_named("Upload artifact")
    assert step is not None
    path = step.get("with", {}).get("path", "")
    assert path == "${{ steps.package.outputs.upload_path }}", \
        f"upload path not wired to the packaging output: {path!r}"


def test_workflow_gates_linux_executable_bit_before_upload():
    """A Linux-gated step must extract the tarball and assert the binary
    is executable, so a dropped +x bit fails the build instead of
    shipping an unlaunchable download."""
    step = _step_named("Verify Linux archive preserves the executable bit")
    assert step is not None, "Linux executable-bit gate missing"
    assert step.get("if") == "runner.os == 'Linux'"
    run = step.get("run", "")
    assert "tar -xzf" in run, "gate does not extract the shipped tarball"
    # `test -x` (via `[ ! -x ... ]`) is the actual assertion that the
    # extracted file carries the execute bit.
    assert "-x " in run
    assert "::error::" in run, "gate does not fail loudly"


def test_package_and_gate_precede_upload():
    """Ordering guard: the tarball must be built and verified before the
    upload step consumes it."""
    pkg = _step_index("Package artifact for upload")
    gate = _step_index("Verify Linux archive preserves the executable bit")
    upload = _step_index("Upload artifact")
    assert -1 not in (pkg, gate, upload), "a packaging step is missing"
    assert pkg < gate < upload, \
        f"steps out of order: package={pkg} gate={gate} upload={upload}"


def test_targz_roundtrip_preserves_executable_bit(tmp_path):
    """Mechanism check for issue #167: the format the workflow ships
    (`tar czf` / `tar xzf`) records the Unix mode inside the archive, so
    an executable binary extracts back as executable. This is the whole
    reason Linux ships as a tarball instead of a bare ELF — a raw release
    asset carries no mode and downloads as `-rw-r--r--`."""
    import stat
    import tarfile

    binary = tmp_path / "MeManga-linux-x64"
    binary.write_bytes(b"\x7fELF fake binary")
    binary.chmod(0o755)

    archive = tmp_path / "MeManga-linux-x64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(binary, arcname="MeManga-linux-x64")

    # The archived member itself must carry the owner-execute bit — that
    # is the byte-level guarantee a bare release asset cannot make.
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmember("MeManga-linux-x64")
        assert member.mode & stat.S_IXUSR, "tar member lost the +x bit"

    dest = tmp_path / "out"
    dest.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        # `data` is the extraction filter Python 3.14 makes the default;
        # it keeps an executable file at 0o755, so the +x bit survives.
        tar.extractall(dest, filter="data")

    extracted = dest / "MeManga-linux-x64"
    assert extracted.stat().st_mode & stat.S_IXUSR, \
        "extracted binary is not owner-executable"


def test_readme_documents_linux_targz_launch_path():
    """README must point Linux users at the tarball and show how to run
    it, so the download has a clear launch path (issue #167)."""
    text = README.read_text(encoding="utf-8")
    # Download table links to the archive, not the bare binary.
    assert "MeManga-linux-x64.tar.gz" in text
    # Concrete extract + run instructions.
    assert "tar xzf MeManga-linux-x64.tar.gz" in text
    assert "./MeManga-linux-x64" in text
    # The chmod fallback for file managers that still strip the bit.
    assert "chmod +x MeManga-linux-x64" in text
