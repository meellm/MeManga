"""#285: a release's GitHub notes are its CHANGELOG.md section, and a tag
without one fails before anything is published."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_notes.py"

CHANGELOG = """\
# Changelog

Intro text.

## [Unreleased]

### Added
- Something not released yet.

## [1.2.0] - 2026-02-01

### Added
- #10 A new feature.

### Fixed
- #11 A fix.

## [1.1.0] - 2026-01-01

## [1.0.0] - 2025-12-01

### Added
- The first release.

## Earlier versions

See the git tags.
"""


@pytest.fixture(scope="module")
def notes():
    name = "memanga_release_notes"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def changelog(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    return path


def test_section_is_the_body_up_to_the_next_version(notes):
    body = notes.section(CHANGELOG, "1.2.0")
    assert body == ("### Added\n- #10 A new feature.\n\n"
                    "### Fixed\n- #11 A fix.")


def test_last_section_stops_at_a_heading_without_version(notes):
    assert notes.section(CHANGELOG, "1.0.0") == "### Added\n- The first release."


def test_missing_section_is_none_and_an_empty_one_is_empty(notes):
    assert notes.section(CHANGELOG, "9.9.9") is None
    assert notes.section(CHANGELOG, "1.1.0") == ""


def test_version_must_match_exactly(notes):
    assert notes.section(CHANGELOG, "1.2") is None


def test_release_notes_of_a_tag(notes, changelog):
    body, problem = notes.release_notes("v1.2.0", changelog)
    assert problem is None
    assert body.startswith("### Added\n- #10 A new feature.")


@pytest.mark.parametrize("tag,fragment", [
    ("1.2.0", "is not v<version>"),
    ("vnext", "is not v<version>"),
    ("v9.9.9", "no '## [9.9.9]' section"),
    ("v1.1.0", "section of CHANGELOG.md is empty"),
])
def test_release_notes_problems(notes, changelog, tag, fragment):
    body, problem = notes.release_notes(tag, changelog)
    assert body is None
    assert fragment in problem


def test_prerelease_tag_uses_its_own_section(notes, tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## [2.0.0rc1] - 2026-03-01\n\n- Candidate.\n", encoding="utf-8")
    assert notes.release_notes("v2.0.0rc1", path) == ("- Candidate.", None)


def test_cli_writes_the_notes(notes, changelog, tmp_path, capsys):
    out = tmp_path / "notes.md"
    assert notes.main(["v1.0.0", "--changelog", str(changelog),
                       "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "### Added\n- The first release.\n"


def test_cli_fails_without_a_section(notes, changelog, capsys):
    assert notes.main(["v3.0.0", "--changelog", str(changelog)]) == 1
    assert "no '## [3.0.0]' section" in capsys.readouterr().err


def test_repository_changelog_versions_have_notes(notes):
    # Every released version in CHANGELOG.md gives release notes.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = [m.group(1) for line in text.splitlines()
                if (m := notes.SECTION.match(line)) and m.group(1)
                and m.group(1) != "Unreleased"]
    assert versions
    for version in versions:
        body, problem = notes.release_notes(f"v{version}", ROOT / "CHANGELOG.md")
        assert problem is None, problem
        assert "\n## " not in body
