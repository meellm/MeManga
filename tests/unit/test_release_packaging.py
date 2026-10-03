"""Static guards for the release packaging (issues #146, #163, and #167).

#146: The release binary's CPU architecture follows PyInstaller's
`target_arch` in `packaging/memanga-release.spec`. Left unset it silently
follows the build host, so a run on an Apple Silicon runner shipped an
arm64-only binary and left Intel Mac users with nothing to run. The fix
pins the arch per-runner via the `MEMANGA_TARGET_ARCH` env var and ships
two distinct macOS assets.

#163: those assets shipped as raw extensionless Mach-O executables, which
GitHub serves as application/octet-stream — a browser download opens them
in TextEdit and drops the exec bit. The fix wraps the binary in a
`MeManga.app` bundle inside a `.zip` via `packaging/macos_app.py`. The
zipped app can still fail Gatekeeper ("MeManga is damaged") because it is
not Developer ID signed or notarized. That needs paid Apple credentials, so
it is optional: when all signing secrets are set the macOS legs sign the
build with a Developer ID identity + hardened runtime, notarize it with
`notarytool`, staple the ticket and gate the upload on `spctl`; otherwise
they warn and still ship a validated, unsigned app zip.

#167: a GitHub release asset is raw bytes with no Unix mode, and browsers
save the download without the executable bit, so a bare Linux ELF lands as
`-rw-r--r--` and fails with "Permission denied" before the app starts. The
fix ships Linux as a `.tar.gz`, which records the +x bit inside the archive
so `tar xzf` restores a runnable binary, and the workflow gates the release
on that bit surviving extraction.

The workflow/spec assertions are cheap text/YAML checks because the real
build only runs on CI runners; Gatekeeper acceptance itself can only be
proven by the macOS workflow gates these tests pin in place. The macOS
helper is pure stdlib and fully exercised here; the Linux round-trip test
proves the archive format itself preserves the executable bit.
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
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
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

# ── issue #163: macOS assets ship as launchable .app packages ───────────
def test_workflow_packages_macos_app_bundle():
    """A macOS-gated step must build the .app via the helper. It is archived
    only after signing + stapling (see the notarization tests below)."""
    step = _step_named("Package macOS app bundle")
    assert step is not None, "macOS .app packaging step missing"
    assert step.get("if") == "runner.os == 'macOS'"
    run = step.get("run", "")
    assert "packaging/macos_app.py build" in run
    # Zipping here would ship the bundle before it is signed and stapled.
    assert "ditto -c" not in run


def test_workflow_validates_packaged_macos_app():
    """A macOS-gated gate must validate the packaged .zip (launchable bundle
    + expected arch) before it can be uploaded — on unsigned builds too, so
    it must not demand a signature or ticket."""
    step = _step_named("Validate packaged macOS app bundle")
    assert step is not None, "macOS app validation gate missing"
    assert step.get("if") == "runner.os == 'macOS'"
    run = step.get("run", "")
    assert "packaging/macos_app.py validate" in run
    assert ARCH_EXPR in run
    assert "--require-signed" not in run and "--require-stapled" not in run


def test_package_step_handles_macos_without_renaming():
    """The unified package step must leave the macOS .zip produced by the
    app-packaging step in place while still renaming Windows/Linux binaries."""
    step = _step_named("Package artifact for upload")
    assert step is not None
    assert step.get("id") == "package"
    run = step.get("run", "")
    assert 'if [ "${{ runner.os }}" = "macOS" ]' in run
    assert 'echo "upload_path=$asset"' in run
    assert 'mv "$bin" "$asset"' in run

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


# ── issue #163: Developer ID signing + notarization (Gatekeeper) ────────
ENTITLEMENTS = REPO_ROOT / "packaging" / "macos-entitlements.plist"
SIGNING_SECRETS = (
    "MACOS_CERTIFICATE_BASE64",
    "MACOS_CERTIFICATE_PASSWORD",
    "MACOS_CODESIGN_IDENTITY",
    "APPLE_ID",
    "APPLE_TEAM_ID",
    "APPLE_APP_SPECIFIC_PASSWORD",
)
MACOS_ONLY = "runner.os == 'macOS'"
NOTARIZED = "steps.notarization.outputs.macos_notarization == 'enabled'"
SIGNED_ONLY_STEPS = (
    "Import Developer ID signing certificate",
    "Sign macOS app bundle",
    "Notarize and staple macOS app bundle",
    "Verify Gatekeeper accepts the macOS app",
    "Verify Playwright works inside the signed macOS app",
    "Verify release zip is signed, stapled and notarized",
)
# The free, unsigned path must keep every one of these gates.
UNSIGNED_PATH_STEPS = (
    "Verify macOS artifact architecture",
    "Verify Playwright works inside the built executable (macOS)",
    "Package macOS app bundle",
    "Archive macOS app bundle",
    "Validate packaged macOS app bundle",
)


def _secret_expr(name):
    return "${{ secrets." + name + " }}"


def test_workflow_detects_optional_notarization_secrets():
    """Notarization needs paid Apple credentials, so a missing secret must
    switch the build to the unsigned path with a warning, not fail it. One
    early step exposes the decision as a step output."""
    step = _step_named("Detect macOS notarization credentials")
    assert step is not None, "notarization detection step missing"
    assert step.get("id") == "notarization"
    assert step.get("if") == MACOS_ONLY
    env = step.get("env", {})
    run = step.get("run", "")
    for name in SIGNING_SECRETS:
        assert env.get(name) == _secret_expr(name), f"{name} not wired in"
        assert name in run, f"{name} not checked"
    assert 'echo "macos_notarization=enabled" >> "$GITHUB_OUTPUT"' in run
    assert 'echo "macos_notarization=disabled" >> "$GITHUB_OUTPUT"' in run
    # Missing secrets are a warning that names the Gatekeeper limitation,
    # never an error or a failing exit.
    assert "::warning::" in run
    assert "unsigned" in run and "Gatekeeper" in run and "unnotarized" in run
    assert "::error::" not in run
    assert "exit" not in run
    # Decided before the slow installs so later steps can branch on it.
    assert _step_index("Detect macOS notarization") < _step_index("Setup Python")


def test_no_step_fails_on_missing_signing_secrets():
    """The old mandatory gate is gone: nothing outside the notarized path
    reads the signing secrets."""
    assert _step_named("Check macOS signing and notarization secrets") is None
    for step in _build_steps():
        name = step.get("name", "")
        if name in ("Detect macOS notarization credentials",
                    "Build release executable"):
            continue
        uses_secret = any("secrets." in str(v)
                          for v in step.get("env", {}).values())
        if uses_secret:
            assert step.get("if") == NOTARIZED, name


def test_signed_only_steps_are_gated_on_notarization_output():
    for name in SIGNED_ONLY_STEPS:
        step = _step_named(name)
        assert step is not None, name
        assert step.get("if") == NOTARIZED, name


def test_unsigned_path_keeps_app_package_gates():
    """Without credentials the leg still builds, self-tests, wraps, zips
    and validates MeManga.app — only the paid-signing steps are skipped."""
    for name in UNSIGNED_PATH_STEPS:
        step = _step_named(name)
        assert step is not None, name
        assert step.get("if") == MACOS_ONLY, name
    validate = _step_named("Validate packaged macOS app bundle").get("run", "")
    assert "packaging/macos_app.py validate" in validate
    assert ARCH_EXPR in validate


def test_workflow_imports_developer_id_certificate():
    step = _step_named("Import Developer ID signing certificate")
    assert step is not None, "certificate import step missing"
    assert step.get("if") == NOTARIZED
    run = step.get("run", "")
    assert "base64 --decode" in run
    assert "security create-keychain" in run
    assert "security import" in run and "-T /usr/bin/codesign" in run
    assert "security set-key-partition-list" in run
    assert "security list-keychains" in run
    # The identity must resolve to a Developer ID Application certificate.
    assert "security find-identity -v -p codesigning" in run
    assert "Developer ID Application" in run


def test_build_step_threads_signing_identity_and_entitlements():
    """PyInstaller can only sign a one-file build's embedded binaries at
    build time, so the identity + entitlements must reach the spec — and
    only when notarization is enabled; unsigned builds get no identity."""
    env = _step_named("Build release executable").get("env", {})
    identity = env.get("MEMANGA_CODESIGN_IDENTITY", "")
    assert NOTARIZED in identity
    assert "secrets.MACOS_CODESIGN_IDENTITY" in identity
    assert identity.rstrip("} ").endswith("|| ''")
    entitlements = env.get("MEMANGA_ENTITLEMENTS_FILE", "")
    assert MACOS_ONLY in entitlements
    assert "packaging/macos-entitlements.plist" in entitlements


def test_spec_parameterizes_codesign_identity_from_env():
    text = SPEC.read_text(encoding="utf-8")
    assert "MEMANGA_CODESIGN_IDENTITY" in text
    assert "MEMANGA_ENTITLEMENTS_FILE" in text
    assert "macos-entitlements.plist" in text
    assert "codesign_identity=_codesign_identity" in text
    assert "entitlements_file=_entitlements_file" in text
    assert "codesign_identity=None" not in text
    # UPX would invalidate the Mach-O signatures.
    assert 'upx=_sys.platform != "darwin"' in text


def test_entitlements_are_minimal_for_hardened_runtime():
    """Only two conservative PyInstaller/PySide6 runtime exceptions; no
    sandbox, no allow-jit, no debug entitlement (notarization rejects
    get-task-allow)."""
    ents = plistlib.loads(ENTITLEMENTS.read_bytes())
    assert ents == {
        "com.apple.security.cs.allow-unsigned-executable-memory": True,
        "com.apple.security.cs.disable-library-validation": True,
    }
    # The comment must not overclaim: these are defensive exceptions, not
    # proven hard requirements of a specific dependency.
    text = ENTITLEMENTS.read_text(encoding="utf-8")
    assert "conservative" in text
    assert "needs:" not in text


def test_workflow_signs_app_bundle_with_hardened_runtime():
    step = _step_named("Sign macOS app bundle")
    assert step is not None, "app bundle signing step missing"
    assert step.get("if") == NOTARIZED
    run = step.get("run", "")
    assert "codesign --force --options runtime --timestamp" in run
    assert "--entitlements packaging/macos-entitlements.plist" in run
    assert '--sign "$MACOS_CODESIGN_IDENTITY"' in run
    assert "codesign --verify --deep --strict" in run
    assert "Authority=Developer ID Application" in run
    assert "TeamIdentifier=$APPLE_TEAM_ID" in run
    assert "runtime" in run and "::error::" in run


def test_workflow_notarizes_and_staples_app_bundle():
    step = _step_named("Notarize and staple macOS app bundle")
    assert step is not None, "notarization step missing"
    assert step.get("if") == NOTARIZED
    env = step.get("env", {})
    for name in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_SPECIFIC_PASSWORD"):
        assert env.get(name) == _secret_expr(name)
    run = step.get("run", "")
    assert "ditto -c -k --keepParent" in run
    assert "xcrun notarytool submit" in run and "--wait" in run
    # Anything but Accepted must fail the release (and print the log).
    assert '"Accepted"' in run
    assert "xcrun notarytool log" in run
    assert "exit 1" in run
    assert 'xcrun stapler staple "release/MeManga.app"' in run
    assert 'xcrun stapler validate "release/MeManga.app"' in run


def _assert_gatekeeper_enabled_before_assess(run):
    """Runners may have Gatekeeper off, which makes spctl answer
    "accepted (override=security disabled)"; it must be enabled, its status
    logged and proven before the assessment."""
    assert "spctl --status" in run
    assert "sudo spctl --global-enable" in run
    assert "sudo spctl --master-enable" in run  # older macOS fallback
    assert "assessments enabled" in run
    assert run.index("--global-enable") < run.index("spctl --assess")
    assert run.rindex("spctl --status") < run.index("spctl --assess")


def test_workflow_runs_gatekeeper_assessment():
    step = _step_named("Verify Gatekeeper accepts the macOS app")
    assert step is not None, "spctl Gatekeeper gate missing"
    assert step.get("if") == NOTARIZED
    run = step.get("run", "")
    assert "spctl --assess --type execute" in run
    assert "source=Notarized Developer ID" in run
    assert "::error::" in run
    _assert_gatekeeper_enabled_before_assess(run)


def test_workflow_launches_final_signed_app():
    """The bundle re-sign rewrites the launcher's signature, so the final
    stapled MeManga.app launcher must itself pass the Playwright self-test
    under the hardened runtime before it is zipped."""
    step = _step_named("Verify Playwright works inside the signed macOS app")
    assert step is not None, "post-staple app self-test missing"
    assert step.get("if") == NOTARIZED
    run = step.get("run", "")
    assert '"release/MeManga.app/Contents/MacOS/MeManga" --verify-playwright' in run
    assert "runtime.log" in run and "exit 1" in run
    assert (_step_index("Notarize and staple macOS app bundle")
            < _step_index("Verify Playwright works inside the signed macOS app")
            < _step_index("Archive macOS app bundle"))
    # The earlier raw-binary gate is kept as well.
    assert _step_named(
        "Verify Playwright works inside the built executable (macOS)") is not None


def test_workflow_zips_stapled_app_for_release():
    """The release .zip is built after stapling (when enabled) and on the
    unsigned path alike."""
    step = _step_named("Archive macOS app bundle")
    assert step is not None, "post-staple archive step missing"
    assert (_step_index("Notarize and staple macOS app bundle")
            < _step_index("Archive macOS app bundle"))
    assert step.get("if") == MACOS_ONLY
    run = step.get("run", "")
    assert "ditto -c -k --keepParent" in run
    assert '"${{ matrix.asset_name }}"' in run


def test_workflow_validates_signed_stapled_zip_after_notarization():
    """When notarization is enabled the uploaded zip itself must pass the
    signed/stapled shape check and, once extracted, codesign + stapler +
    Gatekeeper."""
    step = _step_named("Verify release zip is signed, stapled and notarized")
    assert step is not None, "signed zip gate missing"
    assert step.get("if") == NOTARIZED
    run = step.get("run", "")
    assert "packaging/macos_app.py validate" in run and ARCH_EXPR in run
    assert "--require-signed" in run and "--require-stapled" in run
    assert "ditto -x -k" in run
    assert 'codesign --verify --deep --strict --verbose=2 "$extracted"' in run
    assert 'xcrun stapler validate "$extracted"' in run
    assert 'spctl --assess --type execute --verbose=4 "$extracted"' in run
    assert "source=Notarized Developer ID" in run
    _assert_gatekeeper_enabled_before_assess(run)


def test_macos_signing_steps_are_ordered_before_upload():
    order = [
        "Detect macOS notarization credentials",
        "Install dependencies",
        "Import Developer ID signing certificate",
        "Build release executable",
        "Verify Playwright works inside the built executable (macOS)",
        "Package macOS app bundle",
        "Sign macOS app bundle",
        "Notarize and staple macOS app bundle",
        "Verify Gatekeeper accepts the macOS app",
        "Verify Playwright works inside the signed macOS app",
        "Archive macOS app bundle",
        "Validate packaged macOS app bundle",
        "Verify release zip is signed, stapled and notarized",
        "Package artifact for upload",
        "Upload artifact",
    ]
    idx = [_step_index(name) for name in order]
    assert -1 not in idx, dict(zip(order, idx))
    assert idx == sorted(idx), dict(zip(order, idx))


def test_signing_steps_leave_windows_and_linux_alone():
    """Every signing/notarization step is macOS-only (the detection step
    only runs on macOS, so its output is empty elsewhere), and the Windows
    and Linux gates are still in place."""
    assert _step_named("Detect macOS notarization credentials").get("if") \
        == MACOS_ONLY
    for name in SIGNED_ONLY_STEPS:
        assert _step_named(name).get("if") == NOTARIZED, name
    win = _step_named("Verify Playwright works inside the built executable (Windows)")
    assert win is not None and win.get("if") == "runner.os == 'Windows'"
    linux = _step_named("Verify Linux archive preserves the executable bit")
    assert linux is not None and linux.get("if") == "runner.os == 'Linux'"
    by_asset = {e["asset_name"]: e for e in _build_matrix()}
    assert "MeManga-windows-x64.exe" in by_asset
    assert by_asset["MeManga-windows-x64.exe"]["os"] == "windows-latest"


def test_workflow_removes_signing_keychain():
    step = _step_named("Remove macOS signing keychain")
    assert step is not None
    assert step.get("if") == f"always() && {NOTARIZED}"
    assert "security delete-keychain" in step.get("run", "")
    assert _step_index("Remove macOS signing keychain") > _step_index("Upload artifact")


def test_readme_describes_unsigned_mac_app_workaround():
    """Notarization is optional and the published app may be unsigned, so
    the README must not promise a notarized app and must keep the fix for
    the "damaged" dialog."""
    text = README.read_text(encoding="utf-8")
    assert "not code-signed or notarized" in text
    assert "paid Apple Developer account" in text
    assert "starting with the next release" not in text
    assert "The Mac app is signed with a Developer ID" not in text
    assert "is damaged and can't be opened" in text
    assert "xattr -dr com.apple.quarantine" in text
    # The old Gatekeeper bypass doesn't clear the "damaged" dialog.
    assert "right-click → Open the first time" not in text


def test_changelog_163_entry_describes_optional_notarization():
    """The entry must say notarization is optional and paid, that unsigned
    zips still publish, and must not claim the free path fixes the
    "damaged" dialog."""
    text = CHANGELOG.read_text(encoding="utf-8")
    if "- #163" in text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]:
        section = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    else:
        section = text.split("\n## [", 2)[2].split("\n## [", 1)[0]
    entry = section.split("- #163", 1)[1].split("\n- #", 1)[0]
    assert "optionally" in entry and "paid" in entry
    assert "unsigned" in entry and "xattr" in entry
    assert "so Gatekeeper opens\n  them normally" not in entry
    assert "no longer fail" not in entry
    assert "self-test" in entry


def test_contributing_documents_optional_notarization():
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    section = text.split("### macOS signing and notarization", 1)[1]
    section = section.split("\n### ", 1)[0]
    assert "optional" in section and "paid Apple Developer" in section
    for name in SIGNING_SECRETS:
        assert f"`{name}`" in section
    assert "still\npublishes unsigned" in section
    assert "fails if any of these repository secrets is\nmissing" not in section


# ── issue #163: signed / stapled shape checks in macos_app.py ───────────
def _fake_signed_macho(arch: str) -> bytes:
    """64-bit little-endian Mach-O header with a single LC_CODE_SIGNATURE
    load command (cmd 0x1D, cmdsize 16)."""
    cpu = {"x86_64": macos_app._CPU_TYPE_X86_64,
           "arm64": macos_app._CPU_TYPE_ARM64}[arch]
    header = struct.pack("<IIIIIIII", 0xFEEDFACF, cpu, 0, 2, 1, 16, 0, 0)
    lc = struct.pack("<IIII", 0x1D, 16, 0, 0)
    return header + lc + b"\x00" * 32


def _signed_app(tmp_path, arch="arm64", *, stapled=True):
    exe = tmp_path / "MeManga"
    exe.write_bytes(_fake_signed_macho(arch))
    app = macos_app.build_app_bundle(exe, tmp_path / "out", version="1.0.0")
    seal = app / macos_app.SIGNATURE_SEAL_REL
    seal.parent.mkdir(parents=True)
    seal.write_bytes(b"<plist/>")
    if stapled:
        (app / macos_app.STAPLED_TICKET_REL).write_bytes(b"ticket")
    return app


def test_has_code_signature_reads_load_commands():
    assert macos_app.has_code_signature(_fake_signed_macho("arm64"))
    assert macos_app.has_code_signature(_fake_signed_macho("x86_64"))
    # The plain fake header has ncmds == 0: no signature.
    assert not macos_app.has_code_signature(_fake_macho("arm64"))
    assert not macos_app.has_code_signature(b"not a mach-o at all")
    assert not macos_app.has_code_signature(b"")


def test_has_code_signature_reads_first_fat_slice():
    thin = _fake_signed_macho("arm64")
    offset = 64
    fat = struct.pack(">II", 0xCAFEBABE, 1)
    fat += struct.pack(">IIIII", macos_app._CPU_TYPE_ARM64, 0, offset,
                       len(thin), 14)
    fat = fat.ljust(offset, b"\x00") + thin
    assert macos_app.has_code_signature(fat)


def test_unsigned_bundle_fails_require_signed(tmp_path):
    """The exact v0.4.3 shape (no _CodeSignature, no ticket) must be
    rejected once signing is required — it passed the old gate."""
    app, zip_path = _build_and_zip(tmp_path, "arm64")
    for path in (app, zip_path):
        assert macos_app.validate_app_bundle(path, expected_arch="arm64") == []
        problems = macos_app.validate_app_bundle(
            path, expected_arch="arm64",
            require_signed=True, require_stapled=True)
        assert any("not code-signed" in p for p in problems), problems
        assert any("no embedded code signature" in p for p in problems), problems
        assert any("notarization ticket" in p for p in problems), problems


def test_signed_stapled_bundle_passes_dir_and_zip(tmp_path):
    app = _signed_app(tmp_path, "x86_64")
    zip_path = macos_app.zip_app_bundle(app, tmp_path / "signed.zip")
    for path in (app, zip_path):
        assert macos_app.validate_app_bundle(
            path, expected_arch="x86_64",
            require_signed=True, require_stapled=True) == []


def test_signed_but_unstapled_bundle_fails_require_stapled(tmp_path):
    app = _signed_app(tmp_path, "arm64", stapled=False)
    zip_path = macos_app.zip_app_bundle(app, tmp_path / "unstapled.zip")
    for path in (app, zip_path):
        assert macos_app.validate_app_bundle(
            path, expected_arch="arm64", require_signed=True) == []
        problems = macos_app.validate_app_bundle(
            path, expected_arch="arm64",
            require_signed=True, require_stapled=True)
        assert problems and all("notarization ticket" in p for p in problems)


def test_sealed_bundle_with_unsigned_binary_fails(tmp_path):
    app = _signed_app(tmp_path, "arm64")
    (app / "Contents" / "MacOS" / "MeManga").write_bytes(_fake_macho("arm64"))
    problems = macos_app.validate_app_bundle(app, require_signed=True)
    assert any("no embedded code signature" in p for p in problems), problems


def test_validate_cli_require_flags(tmp_path, capsys):
    unsigned_dir = tmp_path / "unsigned"
    unsigned_dir.mkdir()
    _, unsigned_zip = _build_and_zip(unsigned_dir, "arm64")
    args = ["validate", "--path", str(unsigned_zip), "--arch", "arm64",
            "--require-signed", "--require-stapled"]
    assert macos_app.main(args) == 1
    assert "INVALID" in capsys.readouterr().out

    signed = _signed_app(tmp_path, "arm64")
    signed_zip = macos_app.zip_app_bundle(signed, tmp_path / "ok.zip")
    args[2] = str(signed_zip)
    assert macos_app.main(args) == 0
    assert "signed, stapled" in capsys.readouterr().out
