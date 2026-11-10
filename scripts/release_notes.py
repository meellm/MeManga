#!/usr/bin/env python3
"""The GitHub release notes of a tag: its CHANGELOG.md section (#285).

  python scripts/release_notes.py v1.2.3 [--changelog CHANGELOG.md]
                                         [--output notes.md]

prints (or writes) the body of the `## [1.2.3]` section, without its
heading. It exits 1 when the tag is not v<version> or CHANGELOG.md has
no section for that version, or an empty one, so a release is not
published without its notes. The release workflow runs it before it
creates the release.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"v(\d[0-9A-Za-z.+-]*)")
# A version section, `## [1.2.3] - 2026-01-31`; any other `## ` heading
# ends the section before it too.
SECTION = re.compile(r"^## (?:\[([^\]]+)\])?")


def section(text: str, version: str) -> str | None:
    """The body of the `## [version]` section of `text`, stripped, or
    None when there is no such section."""
    body = None
    for line in text.splitlines():
        match = SECTION.match(line)
        if match:
            if body is not None:
                break
            if match.group(1) == version:
                body = []
            continue
        if body is not None:
            body.append(line)
    if body is None:
        return None
    return "\n".join(body).strip()


def release_notes(tag: str, changelog: Path) -> tuple[str | None, str | None]:
    """(notes, None) for `tag`, or (None, the problem)."""
    match = TAG.fullmatch(tag)
    if not match:
        return None, f"release tag {tag!r} is not v<version>"
    version = match.group(1)
    try:
        text = changelog.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {changelog}: {exc}"
    notes = section(text, version)
    if notes is None:
        return None, f"{changelog.name} has no '## [{version}]' section"
    if not notes:
        return None, f"the '## [{version}]' section of {changelog.name} is empty"
    return notes, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the CHANGELOG.md section of a release tag.")
    parser.add_argument("tag", help="the release tag, v<version>")
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument("--output", type=Path,
                        help="write the notes to this file instead of printing them")
    args = parser.parse_args(argv)
    notes, problem = release_notes(args.tag, args.changelog)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(notes + "\n", encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
