#!/usr/bin/env python3
"""macOS `.app` packaging for the MeManga RELEASE build (issue #163).

`build_app.py` + PyInstaller produce a single-file Mach-O executable
(`release/MeManga`). GitHub serves that extensionless file as
`application/octet-stream`, so a browser download lands as a raw document
that opens in TextEdit instead of a runnable app — and the executable bit
is lost over the download (mode 0644). This module turns that verified
binary into a normal, double-clickable macOS app:

    release/MeManga            (one-file exe from build_app.py)
      -> release/MeManga.app   (minimal bundle wrapping the exe)
      -> MeManga-macos-<arch>.zip

The bundle is intentionally the smallest thing Launch Services accepts as
an application:

    MeManga.app/
      Contents/
        Info.plist             (CFBundleExecutable = MeManga, APPL)
        PkgInfo                 ("APPL????")
        MacOS/MeManga           (the one-file exe, mode 0755)
        Resources/icon.icns     (optional app icon)

We wrap the already-built binary rather than switching the PyInstaller
spec to a BUNDLE target: the one-file exe is the artifact the release
already verifies (arch via `lipo`, Playwright self-test), so wrapping it
keeps the launch behaviour identical and adds nothing that only a real
macOS run could prove.

Everything here is pure stdlib and platform-independent so the whole
`build -> zip -> validate` pipeline is exercised by the unit tests on the
Linux CI leg — the arch check reads the Mach-O header directly instead of
shelling out to `lipo`. On the macOS release leg the workflow archives the
bundle with Apple's `ditto` (bulletproof permission/layout fidelity) and
then runs `validate` on the real `.zip` as a release gate.

Downloaded apps that are not Developer ID signed and notarized may be
reported by Gatekeeper as "damaged". When the optional Apple credentials
are configured, the release workflow signs the bundle with `codesign`,
notarizes it with `notarytool`, staples the ticket with `stapler`, and
assesses it with `spctl` — those Apple tools are the real trust check.
`validate --require-signed --require-stapled` adds a platform-independent
shape check on top for those builds: the bundle must carry its code
signature seal and stapled ticket, and the launcher must embed a Mach-O
code signature, so a notarized build cannot upload an unsigned or
unstapled zip. Without the credentials the zip is validated without the
`--require-*` flags and ships unsigned.

CLI:
    python packaging/macos_app.py build    --exe release/MeManga --dest release
    python packaging/macos_app.py zip      --app release/MeManga.app --out out.zip
    python packaging/macos_app.py validate --path out.zip --arch x86_64
    python packaging/macos_app.py validate --path out.zip --arch arm64 \
        --require-signed --require-stapled
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import stat
import struct
import sys
import zipfile
from pathlib import Path

APP_NAME = "MeManga"
# Reverse-DNS bundle id. `codesign` uses it as the signing identifier and
# notarization records it, so it must stay stable across releases.
BUNDLE_IDENTIFIER = "com.memanga.MeManga"

# Written by `codesign` when it seals the bundle (hashes of every file in
# Contents/), and by `stapler` when it attaches the notarization ticket.
SIGNATURE_SEAL_REL = "Contents/_CodeSignature/CodeResources"
STAPLED_TICKET_REL = "Contents/CodeResources"

# ── Mach-O architecture detection ───────────────────────────────────────
# Parsing the header ourselves keeps the arch check identical on the Linux
# test leg and the macOS release leg (no dependency on `lipo`, which only
# exists on macOS). Only the leading 8 bytes matter: a 4-byte magic that
# encodes 32/64-bit + endianness, followed by the 4-byte CPU type.
_MH_MAGIC = 0xFEEDFACE      # 32-bit, big-endian file
_MH_CIGAM = 0xCEFAEDFE      # 32-bit, little-endian file
_MH_MAGIC_64 = 0xFEEDFACF   # 64-bit, big-endian file
_MH_CIGAM_64 = 0xCFFAEDFE   # 64-bit, little-endian file (normal on x86_64/arm64)
_FAT_MAGIC = 0xCAFEBABE     # universal ("fat") archive
_FAT_CIGAM = 0xBEBAFECA

_CPU_TYPE_X86_64 = 0x01000007
_CPU_TYPE_ARM64 = 0x0100000C
_LC_CODE_SIGNATURE = 0x1D
_CPU_NAMES = {_CPU_TYPE_X86_64: "x86_64", _CPU_TYPE_ARM64: "arm64"}


def read_macho_arch(header: bytes) -> str | None:
    """Return "x86_64", "arm64", "universal", or None for the given Mach-O
    header bytes (the first 8 are enough). None means "not a Mach-O" — i.e.
    something that would not launch as an app at all."""
    if len(header) < 8:
        return None
    # The magic is endianness-defining, so read it big-endian and match the
    # constant; that tells us how to read the CPU type that follows.
    magic = struct.unpack(">I", header[:4])[0]
    if magic in (_FAT_MAGIC, _FAT_CIGAM):
        return "universal"
    if magic in (_MH_MAGIC, _MH_MAGIC_64):
        cputype = struct.unpack(">I", header[4:8])[0]
    elif magic in (_MH_CIGAM, _MH_CIGAM_64):
        cputype = struct.unpack("<I", header[4:8])[0]
    else:
        return None
    return _CPU_NAMES.get(cputype)


def has_code_signature(data: bytes) -> bool:
    """True when the Mach-O `data` carries an LC_CODE_SIGNATURE load command
    (for a universal binary: its first slice). This proves a signature is
    embedded, not that it is a valid Developer ID one — `codesign --verify`
    and `spctl` in the release workflow check that."""
    if len(data) < 8:
        return False
    magic = struct.unpack(">I", data[:4])[0]
    if magic in (_FAT_MAGIC, _FAT_CIGAM):
        # fat_header and fat_arch entries are always big-endian.
        if len(data) < 28 or not struct.unpack(">I", data[4:8])[0]:
            return False
        offset = struct.unpack(">I", data[16:20])[0]
        return has_code_signature(data[offset:])
    if magic in (_MH_MAGIC, _MH_MAGIC_64):
        endian = ">"
    elif magic in (_MH_CIGAM, _MH_CIGAM_64):
        endian = "<"
    else:
        return False
    header_size = 32 if magic in (_MH_MAGIC_64, _MH_CIGAM_64) else 28
    if len(data) < header_size:
        return False
    ncmds = struct.unpack(endian + "I", data[16:20])[0]
    pos = header_size
    for _ in range(ncmds):
        if pos + 8 > len(data):
            return False
        cmd, cmdsize = struct.unpack(endian + "II", data[pos:pos + 8])
        if cmd == _LC_CODE_SIGNATURE:
            return True
        if cmdsize < 8:
            return False
        pos += cmdsize
    return False


# ── Building the .app bundle ────────────────────────────────────────────
def _source_version() -> str:
    """Read `__version__` from memanga/__init__.py — the same string the app
    shows in its title bar — so Finder's "Get Info" matches the release."""
    init = Path(__file__).resolve().parent.parent / "memanga" / "__init__.py"
    try:
        for line in init.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.0.0"


def _info_plist(app_name: str, version: str, has_icon: bool) -> bytes:
    info = {
        "CFBundleName": app_name,
        "CFBundleDisplayName": app_name,
        # The launcher runs Contents/MacOS/<CFBundleExecutable>; it must
        # name the binary we drop in there or the app won't start.
        "CFBundleExecutable": app_name,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "10.13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
    }
    if has_icon:
        info["CFBundleIconFile"] = "icon.icns"
    return plistlib.dumps(info)


def build_app_bundle(
    exe_path,
    dest_dir,
    *,
    icon_path=None,
    version: str | None = None,
    app_name: str = APP_NAME,
) -> Path:
    """Wrap the one-file executable `exe_path` in `<dest_dir>/<app_name>.app`
    and return the bundle path. The inner binary is written mode 0755 — that
    executable bit is the whole point of #163."""
    exe_path = Path(exe_path)
    dest_dir = Path(dest_dir)
    if not exe_path.is_file():
        raise FileNotFoundError(f"executable not found: {exe_path}")

    app = dest_dir / f"{app_name}.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    # Start clean so a rerun never leaves stale files inside the bundle.
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    inner = macos / app_name
    shutil.copyfile(exe_path, inner)
    inner.chmod(0o755)  # rwxr-xr-x — launchable

    has_icon = False
    if icon_path:
        icon_path = Path(icon_path)
        if icon_path.is_file():
            shutil.copyfile(icon_path, resources / "icon.icns")
            has_icon = True

    (contents / "Info.plist").write_bytes(
        _info_plist(app_name, version or _source_version(), has_icon)
    )
    # Legacy 8-byte type/creator record. Modern macOS reads Info.plist, but
    # a well-formed bundle still carries it: 'APPL' type, '????' creator.
    (contents / "PkgInfo").write_bytes(b"APPL????")
    return app


# ── Zipping the bundle ──────────────────────────────────────────────────
# The release leg archives with `ditto` (canonical macOS tool). This
# portable zipper produces an equivalent archive for the unit tests and for
# any host without `ditto`. A one-file wrapper bundle contains no symlinks
# or resource forks, so a plain zip is a faithful representation — the only
# thing that must survive is the exec bit, stored in each entry's Unix mode.
_DIR_MODE = 0o755
_EXEC_MODE = 0o755
_DATA_MODE = 0o644


def _write_entry(zf, arcname, data, mode, *, is_dir=False):
    zi = zipfile.ZipInfo(arcname)
    type_bits = stat.S_IFDIR if is_dir else stat.S_IFREG
    # Unix permission bits live in the top 16 bits of external_attr, and
    # extractors only honour them when "version made by" says Unix (3).
    # Without this the unzipped binary is rw-r--r-- and the app can't
    # launch — exactly the #163 failure mode.
    zi.external_attr = ((type_bits | mode) & 0xFFFF) << 16
    zi.create_system = 3
    if is_dir:
        zi.external_attr |= 0x10  # MS-DOS directory attribute
        zf.writestr(zi, b"")
    else:
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, data)


def zip_app_bundle(app_dir, zip_path, *, app_name: str = APP_NAME) -> Path:
    """Zip `<app_dir>` (a `*.app`) into `zip_path` with the bundle kept as the
    top-level `<app_name>.app/` folder and Unix exec bits preserved."""
    app_dir = Path(app_dir)
    zip_path = Path(zip_path)
    top = f"{app_name}.app"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_entry(zf, top + "/", b"", _DIR_MODE, is_dir=True)
        for path in sorted(app_dir.rglob("*")):
            rel = f"{top}/{path.relative_to(app_dir).as_posix()}"
            if path.is_symlink():
                # A one-file wrapper has no symlinks; refuse to silently
                # flatten one if the layout ever grows to include them.
                raise ValueError(f"unexpected symlink in bundle: {path}")
            if path.is_dir():
                _write_entry(zf, rel + "/", b"", _DIR_MODE, is_dir=True)
            else:
                exec_bit = path.stat().st_mode & stat.S_IXUSR
                _write_entry(zf, rel, path.read_bytes(),
                             _EXEC_MODE if exec_bit else _DATA_MODE)
    return zip_path


# ── Validation (the release gate) ───────────────────────────────────────
def _check_arch(header: bytes, expected_arch: str | None) -> list[str]:
    arch = read_macho_arch(header)
    if arch is None:
        return ["MacOS/{0} is not a Mach-O binary — the app won't launch"
                .format(APP_NAME)]
    if expected_arch and arch != expected_arch:
        return [f"architecture is {arch!r}, expected {expected_arch!r}"]
    return []


def _check_plist(data: bytes | None, app_name: str) -> list[str]:
    if data is None:
        return [f"missing {app_name}.app/Contents/Info.plist"]
    try:
        info = plistlib.loads(data)
    except Exception:
        return [f"{app_name}.app/Contents/Info.plist is not a valid plist"]
    problems = []
    if info.get("CFBundleExecutable") != app_name:
        problems.append(
            "Info.plist CFBundleExecutable is "
            f"{info.get('CFBundleExecutable')!r}, expected {app_name!r}"
        )
    if info.get("CFBundlePackageType") != "APPL":
        problems.append("Info.plist CFBundlePackageType is not 'APPL'")
    return problems


def _check_signed_shape(exe_data: bytes | None, present, app_name: str, *,
                        require_signed: bool,
                        require_stapled: bool) -> list[str]:
    """`present(rel)` reports whether `<app_name>.app/<rel>` exists."""
    problems = []
    if require_signed:
        if not present(SIGNATURE_SEAL_REL):
            problems.append(f"missing {app_name}.app/{SIGNATURE_SEAL_REL} "
                            "— the bundle is not code-signed")
        if exe_data is not None and not has_code_signature(exe_data):
            problems.append(f"{app_name}.app/Contents/MacOS/{app_name} has "
                            "no embedded code signature")
    if require_stapled and not present(STAPLED_TICKET_REL):
        problems.append(f"missing {app_name}.app/{STAPLED_TICKET_REL} "
                        "— no notarization ticket is stapled")
    return problems


def _validate_dir(app: Path, app_name: str, expected_arch, *,
                  require_signed=False, require_stapled=False) -> list[str]:
    problems: list[str] = []
    exe = app / "Contents" / "MacOS" / app_name
    plist = app / "Contents" / "Info.plist"
    exe_data = None

    if not exe.is_file():
        problems.append(f"missing {app_name}.app/Contents/MacOS/{app_name}")
    else:
        if not (exe.stat().st_mode & stat.S_IXUSR):
            problems.append(
                f"{app_name}.app/Contents/MacOS/{app_name} is not executable")
        exe_data = exe.read_bytes()
        problems += _check_arch(exe_data[:8], expected_arch)

    problems += _check_plist(plist.read_bytes() if plist.is_file() else None,
                             app_name)
    problems += _check_signed_shape(
        exe_data, lambda rel: (app / rel).is_file(), app_name,
        require_signed=require_signed, require_stapled=require_stapled)
    return problems


def _validate_zip(zip_path: Path, app_name: str, expected_arch, *,
                  require_signed=False, require_stapled=False) -> list[str]:
    exe_rel = f"{app_name}.app/Contents/MacOS/{app_name}"
    plist_rel = f"{app_name}.app/Contents/Info.plist"
    problems: list[str] = []
    exe_data = None
    with zipfile.ZipFile(zip_path) as zf:
        by_name = {zi.filename: zi for zi in zf.infolist()}

        if exe_rel not in by_name:
            problems.append(f"missing {exe_rel}")
        else:
            # Read the exec bit from the stored Unix mode, not from an
            # extraction — Python's zipfile drops permission bits on
            # extract, so checking the archive entry is what matters.
            mode = (by_name[exe_rel].external_attr >> 16) & 0o7777
            if not (mode & stat.S_IXUSR):
                problems.append(
                    f"{exe_rel} is not executable (mode {mode:04o})")
            exe_data = zf.read(exe_rel)
            problems += _check_arch(exe_data[:8], expected_arch)

        if plist_rel not in by_name:
            problems.append(f"missing {plist_rel}")
        else:
            problems += _check_plist(zf.read(plist_rel), app_name)
    problems += _check_signed_shape(
        exe_data, lambda rel: f"{app_name}.app/{rel}" in by_name, app_name,
        require_signed=require_signed, require_stapled=require_stapled)
    return problems


def validate_app_bundle(path, *, app_name: str = APP_NAME,
                        expected_arch: str | None = None,
                        require_signed: bool = False,
                        require_stapled: bool = False) -> list[str]:
    """Return a list of problems (empty == a launchable app package) for a
    `.app` directory or a `.zip` archive of one. Checks the launcher binary
    exists with its exec bit, the Info.plist names it, and — when
    `expected_arch` is given — the Mach-O architecture matches.

    `require_signed` also demands the bundle's code signature seal and an
    embedded Mach-O signature on the launcher; `require_stapled` demands a
    stapled notarization ticket. These are shape checks only: whether
    Gatekeeper accepts the signature is proven by `codesign`/`spctl` on
    macOS."""
    path = Path(path)
    opts = dict(require_signed=require_signed,
                require_stapled=require_stapled)
    if path.is_dir():
        app = path if path.suffix == ".app" else path / f"{app_name}.app"
        if not app.is_dir():
            return [f"{path} contains no {app_name}.app"]
        return _validate_dir(app, app_name, expected_arch, **opts)
    if zipfile.is_zipfile(path):
        return _validate_zip(path, app_name, expected_arch, **opts)
    return [f"{path} is neither a {app_name}.app bundle nor a zip archive"]


# ── CLI ─────────────────────────────────────────────────────────────────
def _cmd_build(args) -> int:
    app = build_app_bundle(args.exe, args.dest, icon_path=args.icon,
                           version=args.version)
    print(f"built {app}")
    if args.zip:
        zip_app_bundle(app, args.zip)
        print(f"zipped {args.zip}")
    return 0


def _cmd_zip(args) -> int:
    zip_app_bundle(args.app, args.out)
    print(f"zipped {args.out}")
    return 0


def _cmd_validate(args) -> int:
    problems = validate_app_bundle(args.path, expected_arch=args.arch,
                                   require_signed=args.require_signed,
                                   require_stapled=args.require_stapled)
    if problems:
        print(f"INVALID macOS app package: {args.path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    suffix = f" ({args.arch})" if args.arch else ""
    if args.require_signed:
        suffix += ", signed"
    if args.require_stapled:
        suffix += ", stapled"
    print(f"OK: {args.path} is a launchable {APP_NAME}.app{suffix}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Package the MeManga release binary as a macOS .app.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="wrap the one-file exe into MeManga.app")
    b.add_argument("--exe", required=True, help="path to the one-file binary")
    b.add_argument("--dest", required=True, help="dir to create the .app in")
    b.add_argument("--icon", help="optional .icns for Contents/Resources")
    b.add_argument("--version", help="override CFBundleShortVersionString")
    b.add_argument("--zip", help="also write a .zip of the built bundle here")
    b.set_defaults(func=_cmd_build)

    z = sub.add_parser("zip", help="zip an existing .app, preserving exec bits")
    z.add_argument("--app", required=True)
    z.add_argument("--out", required=True)
    z.set_defaults(func=_cmd_zip)

    v = sub.add_parser("validate", help="check a .app or .zip is launchable")
    v.add_argument("--path", required=True)
    v.add_argument("--arch", help="required Mach-O arch, e.g. x86_64 / arm64")
    v.add_argument("--require-signed", action="store_true",
                   help="require a code signature seal + embedded signature")
    v.add_argument("--require-stapled", action="store_true",
                   help="require a stapled notarization ticket")
    v.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
