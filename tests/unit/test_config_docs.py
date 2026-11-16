"""The settings reference and the example config file match the program
(issues #272 and #303)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from memanga import config_docs
from memanga.config import (CONFIG_KEYS, Config, config_section_problems,
                            config_value_problem)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "memanga"

# String literals that look like setting keys but are not.
NOT_SETTINGS = {
    "gui.library.refresh",  # a timer name
    "mangadex.org",  # a source domain
}


@pytest.fixture(scope="module")
def reference():
    return config_docs.render_reference()


@pytest.fixture(scope="module")
def example():
    return config_docs.render_example()


def _documented():
    return set(config_docs.KEYS)


def _entry(reference, key):
    """A key's entry, from its heading to the next heading."""
    text = reference.split(f"\n### {key}\n", 1)[1]
    return re.split(r"\n##+ ", text, maxsplit=1)[0]


def _key_literals():
    """Every string literal in the package that looks like a setting key."""
    sections = "|".join(s for s in config_docs.SECTIONS if s)
    pattern = re.compile(
        r"[\"']((?:" + sections + r")\.[a-z_]+(?:\.[a-z_]+)*)[\"']")
    found = {}
    for path in PACKAGE.rglob("*.py"):
        if path.name == "config_docs.py":
            continue
        for key in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(key, path.relative_to(ROOT).as_posix())
    return found


# ─── Freshness ──────────────────────────────────────────────────────────

def test_generated_files_are_current():
    for path, expected in config_docs.generated_files(ROOT).items():
        assert path.read_text(encoding="utf-8") == expected, (
            f"{path.relative_to(ROOT)} is outdated; "
            "run: python -m memanga.config_docs")


def test_check_reports_stale_files_and_generation_repairs_them(
        tmp_path, monkeypatch, capsys, reference, example):
    monkeypatch.setattr(config_docs, "_repo_root", lambda: tmp_path)
    page = tmp_path / config_docs.REFERENCE_PATH
    page.parent.mkdir(parents=True)
    page.write_text("outdated\n", encoding="utf-8")
    sample = tmp_path / config_docs.EXAMPLE_PATH

    with pytest.raises(SystemExit) as stopped:
        config_docs.main(["--check"])
    assert stopped.value.code == 1
    err = capsys.readouterr().err
    assert str(Path(config_docs.REFERENCE_PATH)) in err
    assert str(Path(config_docs.EXAMPLE_PATH)) in err
    assert "Run: python -m memanga.config_docs" in err
    # --check only reports: the stale file stays, the missing one too.
    assert page.read_text(encoding="utf-8") == "outdated\n"
    assert not sample.exists()

    config_docs.main([])
    assert "Updated settings reference" in capsys.readouterr().out
    assert page.read_text(encoding="utf-8") == reference
    assert sample.read_text(encoding="utf-8") == example

    config_docs.main(["--check"])  # Current now, so no exit.
    assert capsys.readouterr().out == ""


def test_descriptions_fit_the_program():
    assert config_docs.problems() == []


def test_named_commands_are_checked_against_the_parser():
    from memanga.cli_docs import reference_parser

    root = reference_parser()
    check = config_docs._command_problem
    assert check("memanga cron install --time HH:MM", root) is None
    assert check("memanga config --partial {on,off}", root) is None
    assert check("memanga confg", root) is not None
    assert check("memanga config --no-such-option", root) is not None


def test_generated_files_are_marked(reference, example):
    assert reference.startswith(config_docs.HEADER + "\n")
    assert "python -m memanga.config_docs" in example.splitlines()[2]


def test_headings_are_plain_text(reference):
    # The site reads a heading's source text out as its permalink label,
    # so Markdown or attributes there would be read aloud.
    for line in reference.splitlines():
        if line.startswith("#"):
            assert not re.search(r"[`*<>{}\[\]]", line), line


# ─── Coverage ───────────────────────────────────────────────────────────

def test_every_default_and_settable_key_has_an_entry(reference):
    keys = set(config_docs.default_keys()) | set(CONFIG_KEYS)
    for key in keys:
        assert f"\n### {key}\n" in reference, key
        # The overview links to the anchor the site gives that heading.
        assert f"(#{config_docs.anchor(key)})" in reference, key


def test_code_reads_no_undocumented_key():
    documented = _documented()
    sections = {key.rsplit(".", n)[0] for key in documented
                for n in range(1, key.count(".") + 1)}
    for key, where in _key_literals().items():
        if key in NOT_SETTINGS or key in sections:
            continue
        assert key in documented, f"{key} ({where}) is not in the reference"


def test_documented_keys_outside_the_defaults_are_still_used():
    used = _key_literals()
    defaults = set(config_docs.default_keys())
    for key in _documented() - defaults:
        assert key in used, f"{key} is documented but no code uses it"


def test_keys_outside_the_defaults_are_not_shown_as_defaults(reference):
    defaults = config_docs.default_keys()
    for key in _documented() - set(defaults):
        entry = _entry(reference, key)
        assert "**Default:** not in a new config file." in entry, key


def test_secret_is_marked(reference):
    for key, spec in CONFIG_KEYS.items():
        entry = _entry(reference, key)
        assert ("**Secret:**" in entry) == bool(spec.get("secret")), key


def test_anchors_follow_the_site():
    # How the site turns a heading into an anchor.
    assert config_docs.anchor("delivery.post_processing.enabled") == (
        "delivery-post-processing-enabled")
    assert config_docs.slug("Email and Kindle") == "email-and-kindle"


# ─── The example file ───────────────────────────────────────────────────

def test_example_holds_every_default(example):
    data = yaml.safe_load(example)
    assert config_section_problems(data) == []
    for key, value in config_docs.default_keys().items():
        node = data
        parts = key.split(".")
        for part in parts[:-1]:
            node = node[part]
        if config_docs._home_relative(value) is not None:
            # Left out on purpose: see test_home_folder_is_never_written.
            assert parts[-1] not in node, key
            continue
        assert node[parts[-1]] == value, key
        if key in CONFIG_KEYS:
            assert config_value_problem(key, node[parts[-1]]) is None, key


def test_example_loads_as_a_config_with_the_defaults(tmp_path, example):
    (tmp_path / "config.yaml").write_text(example, encoding="utf-8")
    config = Config(config_dir=tmp_path)
    assert config.load_error is None
    for key, value in config_docs.default_keys().items():
        assert config.get(key) == value, key


def test_example_has_no_personal_values(example):
    data = yaml.safe_load(example)
    assert data["manga"] == []
    for key, spec in CONFIG_KEYS.items():
        if spec.get("secret"):
            section, name = key.split(".", 1)
            assert data[section][name] == "", key
    assert data["email"]["kindle_email"] == ""
    assert data["email"]["sender_email"] == ""


def test_home_folder_is_never_written(monkeypatch, reference, example):
    # The default download folder is inside the home folder of whoever
    # generates the files; the output must be the same for everyone.
    for text in (reference, example):
        assert str(Path.home()) not in text
    elsewhere = Path("/srv/someone-else")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: elsewhere))
    assert config_docs.render_reference() == reference
    assert config_docs.render_example() == example


def test_download_folder_default_is_described(reference):
    entry = _entry(reference, "delivery.download_dir")
    assert ("**Default:** the `Downloads/MeManga` folder in your home "
            "folder, stored as a full path") in entry


# ─── Release boundary ───────────────────────────────────────────────────

def test_release_is_the_one_the_site_names():
    site = (ROOT / "docs/.vitepress/release.ts").read_text(encoding="utf-8")
    assert f"tag: '{config_docs.RELEASE_TAG}'" in site


def test_only_newer_keys_are_marked(reference):
    badge = f'<Badge type="info" text="Not in {config_docs.RELEASE_TAG}" />'
    for key in _documented():
        marked = badge in _entry(reference, key)
        assert marked == (key not in config_docs.RELEASE_KEYS), key


def _release_has(tag, key):
    result = subprocess.run(
        ["git", "grep", "-q", "-F", f'"{key}"', tag, "--", "memanga"],
        cwd=ROOT, capture_output=True, timeout=60)
    return result.returncode == 0


def test_release_keys_are_the_keys_the_release_reads():
    tag = config_docs.RELEASE_TAG
    if shutil.which("git") is None or subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],
            cwd=ROOT, capture_output=True, timeout=60).returncode != 0:
        pytest.skip(f"the {tag} tag is not in this checkout")
    for key in _documented():
        assert _release_has(tag, key) == (key in config_docs.RELEASE_KEYS), key


# ─── Site and CI ────────────────────────────────────────────────────────

def test_page_shows_the_reference_and_the_example():
    page = (ROOT / "docs/reference/config.md").read_text(encoding="utf-8")
    assert "<!--@include: ./config-keys.md-->" in page
    assert "\n<<< ../../examples/config.example.yaml\n" in page
    # The plain key headings are set in the code font on this page only.
    assert "\npageClass: config-reference\n" in page
    assert ".config-reference .vp-doc h3 {" in page
    site = (ROOT / "docs/.vitepress/config.mts").read_text(encoding="utf-8")
    assert "'reference/config-keys.md'" in site
    assert "link: '/reference/config'" in site


def test_reference_is_checked_in_ci():
    workflow = (ROOT / ".github/workflows/source-docs.yml").read_text(
        encoding="utf-8")
    assert "python -m memanga.config_docs --check" in workflow
