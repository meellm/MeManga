#!/usr/bin/env python3
"""Whether a release tag goes to PyPI (#218).

  python scripts/pypi_release_gate.py v1.2.3 <commit> dist

writes `publish=true` or `publish=false` to $GITHUB_OUTPUT.

A tag that is not a canonical stable vX.Y.Z from 0.5.0 on is not published,
and its GitHub release continues. A tag that is must point at a commit on
main, and the folder must hold exactly its sdist and wheel, whose own
metadata carries the project name and version. Anything else, including
anything that cannot be read, exits 1 without writing `publish`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import zipfile
import zlib
from email.parser import BytesHeaderParser
from pathlib import Path

PROJECT = "memanga"
FIRST_VERSION = (0, 5, 0)
MAIN_REF = "refs/remotes/origin/main"
STABLE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def publishable_version(tag: str) -> str | None:
    """The version `tag` publishes, or None when it stays off PyPI."""
    match = STABLE_TAG.fullmatch(tag)
    if match is None or tuple(map(int, match.groups())) < FIRST_VERSION:
        return None
    return ".".join(match.groups())


def main_problem(commit: str) -> str | None:
    """Why `commit` does not count as on main, or None when it does."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, MAIN_REF],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"cannot check that {commit} is on main: {exc}"
    if result.returncode == 0:
        return None
    if result.returncode == 1:
        return f"commit {commit} is not on main"
    return f"cannot check that {commit} is on main: {result.stderr.strip()}"


def _wheel_metadata(path: Path, version: str) -> bytes:
    name = f"{PROJECT}-{version}.dist-info/METADATA"
    with zipfile.ZipFile(path) as wheel:
        entries = [e for e in wheel.infolist() if e.filename == name]
        if len(entries) != 1:
            raise ValueError(f"expected one {name}")
        return wheel.read(entries[0])


def _sdist_metadata(path: Path, version: str) -> bytes:
    name = f"{PROJECT}-{version}/PKG-INFO"
    with tarfile.open(path, "r:gz") as sdist:
        entries = [m for m in sdist.getmembers() if m.name == name]
        if len(entries) != 1 or not entries[0].isreg():
            raise ValueError(f"expected one regular file {name}")
        with sdist.extractfile(entries[0]) as handle:
            return handle.read()


def _metadata_problems(label: str, data: bytes, version: str) -> list[str]:
    headers = BytesHeaderParser().parsebytes(data)
    problems = []
    for field, expected in (("Name", PROJECT), ("Version", version)):
        found = headers.get_all(field, [])
        if found != [expected]:
            problems.append(f"{label} has {field} {found}, expected {expected!r}")
    return problems


def dist_problems(dist: Path, version: str) -> list[str]:
    """What is wrong with the sdist and wheel of `version` in `dist`."""
    sdist = f"{PROJECT}-{version}.tar.gz"
    wheel = f"{PROJECT}-{version}-py3-none-any.whl"
    expected = sorted((sdist, wheel))
    try:
        found = sorted(path.name for path in dist.iterdir())
    except OSError as exc:
        return [f"cannot read {dist}: {exc}"]
    if found != expected:
        return [f"{dist} holds {found}, expected {expected}"]
    problems: list[str] = []
    for name, read in ((sdist, _sdist_metadata), (wheel, _wheel_metadata)):
        path = dist / name
        if path.is_symlink() or not path.is_file():
            problems.append(f"{name} is not a regular file")
            continue
        try:
            data = read(path, version)
        except (OSError, EOFError, ValueError, tarfile.TarError,
                zipfile.BadZipFile, zlib.error) as exc:
            problems.append(f"cannot read the metadata of {name}: {exc}")
            continue
        problems += _metadata_problems(name, data, version)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide whether a release tag goes to PyPI.")
    parser.add_argument("tag", help="the release tag, vX.Y.Z")
    parser.add_argument("commit", help="the commit the tag points at")
    parser.add_argument("dist", type=Path, help="folder with the sdist and wheel")
    args = parser.parse_args(argv)
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        print("error: GITHUB_OUTPUT is not set", file=sys.stderr)
        return 1
    version = publishable_version(args.tag)
    if version is None:
        publish = "false"
        print(f"{args.tag} is not a stable release from "
              f"{'.'.join(map(str, FIRST_VERSION))} on: not publishing to PyPI")
    else:
        problem = main_problem(args.commit)
        problems = ([problem] if problem else []) + dist_problems(args.dist, version)
        if problems:
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1
        publish = "true"
        print(f"OK: {PROJECT} {version} can be published to PyPI")
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"publish={publish}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
