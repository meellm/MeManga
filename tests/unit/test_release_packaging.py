"""Static guards for the macOS release packaging (issues #146 and #163).

#146: The release binary's CPU architecture follows PyInstaller's
`target_arch` in `packaging/memanga-release.spec`. Left unset it silently
follows the build host, so a run on an Apple Silicon runner shipped an
arm64-only binary and left Intel Mac users with nothing to run. The fix
pins the arch per-runner via the `MEMANGA_TARGET_ARCH` env var and ships
two distinct macOS assets.

#163: those assets shipped as raw extensionless Mach-O executables, which
GitHub serves as application/octet-stream — a browser download opens them
in TextEdit and drops the exec bit. The fix wraps the binary in a
`MeManga.app` bundle inside a `.zip` via `packaging/macos_app.py`.

The workflow/spec assertions are cheap text/YAML checks because the real
build only runs on a macOS CI runner. The `packaging/macos_app.py` helper,
by contrast, is pure stdlib and fully exercised here — its whole reason for
existing that way is to make the #163 fix verifiable off macOS.
"""

from __future__ import annotations

import importlib.util
import plistlib
import stat
import struct
import zipfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "memanga-release.spec"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
MACOS_APP = REPO_ROOT / "packaging" / "macos_app.py"

# The GitHub Actions expression the workflow uses to thread the matrix
# arch into both the build env and the verification step.
ARCH_EXPR = '${{ matrix.target_arch }}'


def _load_macos_app():
    """Import packaging/macos_app.py by path — `packaging/` is a scripts dir,
    not an importable package."""
    spec = importlib.util.spec_from_file_location("memanga_macos_app", MACOS_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


macos_app = _load_macos_app()


def _fake_macho(arch: str) -> bytes:
    """Minimal little-endian 64-bit Mach-O header (magic + cputype) padded
    out, enough for the header-only arch check."""
    cpu = {"x86_64": macos_app._CPU_TYPE_X86_64,
           "arm64": macos_app._CPU_TYPE_ARM64}[arch]
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", cpu) + b"\x00" * 64


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
    each pinned to its own architecture and shipped as a .zip app package
    (issue #163) rather than a raw extensionless Mach-O."""
    include = _build_matrix()
    by_asset = {e["asset_name"]: e for e in include}

    assert "MeManga-macos-arm64.zip" in by_asset, "Apple Silicon asset dropped"
    assert "MeManga-macos-x64.zip" in by_asset, "Intel macOS asset missing"

    arm = by_asset["MeManga-macos-arm64.zip"]
    intel = by_asset["MeManga-macos-x64.zip"]
    assert arm["target_arch"] == "arm64"
    assert intel["target_arch"] == "x86_64"
    # Intel slice must be built natively on an Intel runner image
    # (macos-26-intel is GitHub's current standard x64 macOS runner),
    # not cross-compiled from Apple Silicon.
    assert intel["os"] == "macos-26-intel"


def test_macos_assets_are_zip_app_packages():
    """Every macOS asset must be a .zip (an app package), and no macOS asset
    may ship as a bare extensionless binary — the #163 regression."""
    macos = [e for e in _build_matrix()
             if str(e.get("os", "")).startswith("macos")]
    assert macos, "no macOS build legs found"
    for leg in macos:
        assert leg["asset_name"].endswith(".zip"), \
            f"macOS asset {leg['asset_name']} is not a .zip app package"


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


# ── issue #163: macOS assets ship as launchable .app packages ───────────
def test_workflow_packages_macos_app_bundle():
    """A macOS-gated step must build the .app via the helper and archive it
    into the .zip asset with `ditto` (preserves the exec bit + layout)."""
    step = _step_named("Package macOS app bundle")
    assert step is not None, "macOS .app packaging step missing"
    assert step.get("if") == "runner.os == 'macOS'"
    run = step.get("run", "")
    assert "packaging/macos_app.py build" in run
    assert "ditto -c -k --keepParent" in run
    # The archived asset is the matrix's .zip asset_name.
    assert '"${{ matrix.asset_name }}"' in run


def test_workflow_validates_packaged_macos_app():
    """A macOS-gated gate must validate the packaged .zip (launchable bundle
    + expected arch) before it can be uploaded."""
    step = _step_named("Validate packaged macOS app bundle")
    assert step is not None, "macOS app validation gate missing"
    assert step.get("if") == "runner.os == 'macOS'"
    run = step.get("run", "")
    assert "packaging/macos_app.py validate" in run
    assert ARCH_EXPR in run


def test_rename_step_skips_macos():
    """The raw-binary rename is Windows/Linux only; macOS produces its .zip
    in the packaging step, so renaming would clobber or miss it."""
    step = _step_named("Rename artifact for upload")
    assert step is not None
    assert step.get("if") == "runner.os != 'macOS'"


# ── issue #163: packaging/macos_app.py behaviour (runs off macOS) ────────
def test_read_macho_arch_identifies_slices():
    assert macos_app.read_macho_arch(_fake_macho("x86_64")) == "x86_64"
    assert macos_app.read_macho_arch(_fake_macho("arm64")) == "arm64"
    # Big-endian FAT magic -> universal.
    assert macos_app.read_macho_arch(b"\xca\xfe\xba\xbe" + b"\x00" * 8) \
        == "universal"
    # Not a Mach-O at all (e.g. a text file opened in TextEdit).
    assert macos_app.read_macho_arch(b"hello world!!") is None
    assert macos_app.read_macho_arch(b"\x00\x00") is None


def test_build_app_bundle_layout(tmp_path):
    exe = tmp_path / "MeManga"
    exe.write_bytes(_fake_macho("arm64"))
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icns-bytes")

    app = macos_app.build_app_bundle(exe, tmp_path / "out", icon_path=icon,
                                     version="9.9.9")

    inner = app / "Contents" / "MacOS" / "MeManga"
    assert inner.is_file()
    assert inner.stat().st_mode & stat.S_IXUSR, "inner binary not executable"
    assert (app / "Contents" / "PkgInfo").read_bytes() == b"APPL????"
    assert (app / "Contents" / "Resources" / "icon.icns").is_file()

    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "MeManga"
    assert info["CFBundlePackageType"] == "APPL"
    assert info["CFBundleShortVersionString"] == "9.9.9"
    assert info["CFBundleIconFile"] == "icon.icns"


def test_build_app_bundle_without_icon_omits_icon_key(tmp_path):
    exe = tmp_path / "MeManga"
    exe.write_bytes(_fake_macho("x86_64"))

    app = macos_app.build_app_bundle(exe, tmp_path / "out")

    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert "CFBundleIconFile" not in info
    assert not (app / "Contents" / "Resources" / "icon.icns").exists()
    # Default version falls back to the source __version__ (non-empty).
    assert info["CFBundleShortVersionString"]


def test_build_app_bundle_missing_exe_raises(tmp_path):
    try:
        macos_app.build_app_bundle(tmp_path / "nope", tmp_path / "out")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for a missing exe")


def _build_and_zip(tmp_path, arch="x86_64"):
    exe = tmp_path / "MeManga"
    exe.write_bytes(_fake_macho(arch))
    app = macos_app.build_app_bundle(exe, tmp_path / "out", version="1.0.0")
    zip_path = tmp_path / f"MeManga-macos-{arch}.zip"
    macos_app.zip_app_bundle(app, zip_path)
    return app, zip_path


def test_validate_roundtrip_dir_and_zip(tmp_path):
    app, zip_path = _build_and_zip(tmp_path, "x86_64")
    assert macos_app.validate_app_bundle(app, expected_arch="x86_64") == []
    assert macos_app.validate_app_bundle(zip_path, expected_arch="x86_64") == []


def test_zip_preserves_executable_bit(tmp_path):
    """The exec bit must survive into the archive — its loss is the #163
    failure mode. Read it from the stored Unix mode, as macOS does."""
    _, zip_path = _build_and_zip(tmp_path, "arm64")
    with zipfile.ZipFile(zip_path) as zf:
        zi = zf.getinfo("MeManga.app/Contents/MacOS/MeManga")
    mode = (zi.external_attr >> 16) & 0o777
    assert mode & stat.S_IXUSR, f"inner binary archived without exec bit ({mode:04o})"


def test_validate_flags_wrong_architecture(tmp_path):
    _, zip_path = _build_and_zip(tmp_path, "arm64")
    problems = macos_app.validate_app_bundle(zip_path, expected_arch="x86_64")
    assert any("architecture" in p for p in problems), problems


def test_validate_flags_missing_exec_bit(tmp_path):
    """A zip that stores the binary as rw-r--r-- (the raw-download bug) must
    be rejected by the release gate."""
    app, _ = _build_and_zip(tmp_path, "x86_64")
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                rel = f"MeManga.app/{path.relative_to(app).as_posix()}"
                zi = zipfile.ZipInfo(rel)
                zi.external_attr = (0o644 & 0xFFFF) << 16  # no exec bit
                zi.create_system = 3
                zf.writestr(zi, path.read_bytes())
    problems = macos_app.validate_app_bundle(bad_zip, expected_arch="x86_64")
    assert any("not executable" in p for p in problems), problems


def test_validate_flags_non_macho_binary(tmp_path):
    """A wrapper around a non-Mach-O file (e.g. a text doc) is not a
    launchable app and must be flagged."""
    exe = tmp_path / "MeManga"
    exe.write_bytes(b"this is not a mach-o binary\n")
    app = macos_app.build_app_bundle(exe, tmp_path / "out")
    problems = macos_app.validate_app_bundle(app, expected_arch="x86_64")
    assert any("Mach-O" in p for p in problems), problems


def test_validate_rejects_raw_binary(tmp_path):
    """Passing the bare executable (not an app package) must fail — this is
    literally the shape of the v0.4.2 asset that broke."""
    raw = tmp_path / "MeManga-macos-x64"
    raw.write_bytes(_fake_macho("x86_64"))
    problems = macos_app.validate_app_bundle(raw)
    assert problems  # non-empty == rejected
