"""The committed command reference matches the argument parser."""

import argparse
from pathlib import Path

import pytest

from memanga import cli_docs
from memanga.cli import build_parser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def reference():
    return cli_docs.render_reference()


def _section(reference, heading):
    """The text under ``heading`` up to the next heading of the same level."""
    level = heading.split(" ", 1)[0]
    lines = reference.splitlines()
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith(level + " ")), len(lines))
    return "\n".join(lines[start:end])


def _subparsers(parser):
    return next(a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction))


def test_reference_is_current():
    for path, expected in cli_docs.generated_files(ROOT).items():
        assert path.read_text(encoding="utf-8") == expected, (
            f"{path.relative_to(ROOT)} is outdated; "
            "run: python -m memanga.cli_docs")


def test_reference_is_marked_as_generated(reference):
    assert reference.startswith(cli_docs.HEADER + "\n")
    assert "python -m memanga.cli_docs" in cli_docs.HEADER


def test_every_command_and_alias_is_listed(reference):
    commands = _subparsers(build_parser())
    primary = {}
    for name, sub in commands.choices.items():
        primary.setdefault(id(sub), name)
    for name, sub in commands.choices.items():
        owner = primary[id(sub)]
        assert f"\n## memanga {owner}\n" in reference
        if name != owner:
            assert f"`memanga {name}`" in _section(reference,
                                                   f"## memanga {owner}")


def test_nested_actions_get_their_own_sections(reference):
    for heading in ("### memanga config set", "### memanga config email",
                    "### memanga failed retry", "### memanga failed clear"):
        assert f"\n{heading}\n" in reference


def test_every_visible_option_of_a_command_is_listed(reference):
    commands = _subparsers(build_parser())
    for name in ("check", "search", "add", "remove", "send"):
        section = _section(reference, f"## memanga {name}")
        for action in commands.choices[name]._actions:
            if action.help is argparse.SUPPRESS or "--help" in action.option_strings:
                continue
            for flag in action.option_strings:
                assert flag in section, (name, flag)


def test_global_options_and_exclusive_groups(reference):
    section = _section(reference, "## Global options")
    assert "- `--config-dir DIR`:" in section
    assert "- `-V, --version`:" in section
    assert "Only one of `--verbose` and `--quiet` can be given." in section
    assert ("Only one of `--allow-partial` and `--no-partial` can be given."
            in _section(reference, "## memanga check"))


def test_value_placeholders(reference):
    check = _section(reference, "## memanga check")
    assert "- `-f, --from FROM_CHAPTER`:" in check
    assert "- `--retries N`:" in check
    assert "- `-n, --dry-run`:" in check
    assert "memanga check [options] [TARGET]" in check
    assert "memanga send [options] [TARGET] [CHAPTER ...]" in reference
    assert "- `--partial {on,off}`:" in _section(reference, "## memanga config")


def test_help_option_and_top_level_examples_are_left_out(reference):
    assert "--help" not in reference
    assert "show this help message" not in reference
    # The parser's epilog holds examples; the reference lists facts only.
    assert "Examples:" not in reference


def test_help_text_is_escaped_for_the_site(reference):
    # Angle brackets outside code would be read as HTML tags by the site.
    remove = _section(reference, "## memanga remove")
    assert "&lt;download dir&gt;/&lt;title&gt;" in remove
    assert "{{" not in reference
    in_code = False
    for line in reference.splitlines()[1:]:
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            assert "<" not in line.replace("`", ""), line


def test_hand_laid_out_descriptions_stay_preformatted(reference):
    check = _section(reference, "## memanga check")
    assert "```text\nCheck tracked manga for new chapters.\n\nModes:\n" in check


def test_output_ignores_environment_and_terminal_width(reference, monkeypatch):
    monkeypatch.setenv("MEMANGA_CLI_ONLY", "1")
    monkeypatch.setenv("COLUMNS", "40")
    assert cli_docs.render_reference() == reference
    assert "- `--gui`:" in reference
    # The variable is only set aside while the parser is built.
    import os
    assert os.environ["MEMANGA_CLI_ONLY"] == "1"


def test_check_reports_a_stale_reference(tmp_path, monkeypatch, capsys):
    stale = tmp_path / cli_docs.REFERENCE_PATH
    stale.parent.mkdir(parents=True)
    stale.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(cli_docs, "generated_files",
                        lambda root: {stale: "new\n"})
    monkeypatch.setattr(cli_docs, "_repo_root", lambda: tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        cli_docs.main(["--check"])
    assert exit_info.value.code == 1
    assert "Outdated command reference" in capsys.readouterr().err
    assert stale.read_text(encoding="utf-8") == "old\n"

    cli_docs.main([])
    assert stale.read_text(encoding="utf-8") == "new\n"


def test_reference_page_includes_the_generated_file():
    page = (ROOT / "docs/reference/cli.md").read_text(encoding="utf-8")
    assert "<!--@include: ./cli-commands.md-->" in page
    config = (ROOT / "docs/.vitepress/config.mts").read_text(encoding="utf-8")
    assert "'reference/cli-commands.md'" in config


def test_reference_is_checked_in_ci():
    workflow = (ROOT / ".github/workflows/source-docs.yml").read_text(
        encoding="utf-8")
    assert "python -m memanga.cli_docs --check" in workflow
