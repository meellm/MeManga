"""Static checks for the routine CI, the dependency audit, the scraper
health run and how the release workflow depends on them (#255, #317,
#285, #385)."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(data):
    # YAML 1.1 reads the bare key `on` as True.
    return data.get("on", data.get(True))


def _runs(job):
    return [step.get("run", "") for step in job.get("steps", [])]


def _pytest_runs(job):
    return [line for run in _runs(job) for line in run.splitlines()
            if "-m pytest" in line]


@pytest.fixture(scope="module")
def ci():
    return _load("ci.yml")


@pytest.fixture(scope="module")
def release():
    return _load("release.yml")


@pytest.fixture(scope="module")
def audit():
    return _load("dependency-audit.yml")


# ─── Routine CI ─────────────────────────────────────────────────────────

def test_ci_runs_on_main_and_for_the_release(ci):
    on = _triggers(ci)
    assert on["push"]["branches"] == ["main"]
    assert on["pull_request"]["branches"] == ["main"]
    assert "workflow_call" in on
    assert ci["permissions"] == {"contents": "read"}
    # Whole suite on every docs change too: tests read README.md and
    # CHANGELOG.md, so no path filter.
    assert "paths" not in on["push"] and "paths" not in on["pull_request"]


def test_ci_cancels_only_superseded_pull_request_runs(ci):
    assert ci["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}")


def test_ci_steps_fail_on_the_first_failed_command(ci):
    assert ci["defaults"]["run"]["shell"] == "bash"


def test_every_ci_job_has_a_timeout(ci):
    for name, job in ci["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int), name


def _shards(ci):
    """shard -> (selected paths, --ignore paths) of its pytest run."""
    shards = {}
    for cell in ci["jobs"]["tests"]["strategy"]["matrix"]["include"]:
        args = shlex.split(cell["paths"])
        ignored = [a.split("=", 1)[1] for a in args if a.startswith("--ignore=")]
        selected = [a for a in args if not a.startswith("-")]
        shards[cell["shard"]] = (selected, ignored)
    return shards


def _under(path, roots):
    return any(path == root or path.startswith(root + "/") for root in roots)


def test_every_test_file_runs_in_exactly_one_linux_shard(ci):
    # The full suite runs once, split by path: a new test file or folder
    # must land in a shard, and no file may run twice.
    shards = _shards(ci)
    files = sorted(p.relative_to(ROOT).as_posix()
                   for p in (ROOT / "tests").rglob("test_*.py"))
    assert files
    for path in files:
        owners = [name for name, (selected, ignored) in shards.items()
                  if _under(path, selected) and not _under(path, ignored)]
        assert len(owners) == 1, (path, owners)


def test_setup_heavy_shards_hand_out_single_tests(ci):
    # The GUI and integration tests build the main window per test; with
    # one file per worker the largest file alone sets the shard's time.
    for cell in ci["jobs"]["tests"]["strategy"]["matrix"]["include"]:
        selected, _ = _shards(ci)[cell["shard"]]
        if any(_under(p, ["tests/unit/gui", "tests/integration"]) for p in selected):
            assert cell["dist"] == "worksteal", cell["shard"]
    (line,) = _pytest_runs(ci["jobs"]["tests"])
    assert "--dist ${{ matrix.dist }} ${{ matrix.paths }}" in line


def test_linux_shards_run_the_release_python(ci):
    job = ci["jobs"]["tests"]
    assert job["runs-on"] == "ubuntu-latest"
    (setup,) = [s for s in job["steps"]
                if str(s.get("uses", "")).startswith("actions/setup-python@")]
    assert setup["with"]["python-version"] == "3.12"


def test_ci_keeps_the_default_marker_selection(ci):
    # The live/health probes stay out of routine CI.
    for name, job in ci["jobs"].items():
        for line in _pytest_runs(job):
            assert " -m " not in line.replace("-m pytest", ""), (name, line)
            assert "-n auto" in line, (name, line)


def test_core_tests_cover_the_supported_python_range(ci):
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python = ">=(\d+\.\d+)"', pyproject).group(1)
    newest = max(re.findall(r'Python :: (3\.\d+)"', pyproject),
                 key=lambda v: int(v.split(".")[1]))
    cells = ci["jobs"]["compat"]["strategy"]["matrix"]["include"]
    linux = {c["python"] for c in cells if c["os"] == "ubuntu-latest"}
    assert {floor, newest} <= linux
    assert {"os": "windows-latest", "python": "3.12"} in cells


def test_macos_core_tests_skip_pull_requests(ci):
    job = ci["jobs"]["compat-macos"]
    assert job["runs-on"] == "macos-latest"
    assert job["if"] == "github.event_name != 'pull_request'"
    assert _pytest_runs(job) == _pytest_runs(ci["jobs"]["compat"])


def test_test_jobs_install_the_hashed_dev_lock(ci):
    for name in ("tests", "compat", "compat-macos"):
        runs = "\n".join(_runs(ci["jobs"][name]))
        assert "python -m pip install --require-hashes -r requirements/dev.txt" in runs
        assert "python -m pip install --no-deps -e ." in runs


def test_lint_installs_ruff_from_its_hashed_wheel(ci):
    (run,) = [r for r in _runs(ci["jobs"]["lint"]) if "ruff" in r]
    assert re.search(r'"ruff==[\d.]+ --hash=sha256:[0-9a-f]{64}"', run)
    assert "--require-hashes --only-binary :all:" in run
    assert "ruff check" in run


def test_package_job_builds_checks_and_starts_the_wheel(ci):
    runs = "\n".join(_runs(ci["jobs"]["package"]))
    for command in ('"build==', "pyproject-build --outdir dist .",
                    "dist/memanga-*.tar.gz", "dist/memanga-*-py3-none-any.whl",
                    "twine check --strict dist/*",
                    "--require-hashes -r requirements/cli.txt",
                    "--no-deps dist/memanga-*-py3-none-any.whl", "-m pip check",
                    'bin/memanga" --help'):
        assert command in runs, command


def _python_modules(run):
    return re.findall(r"\bpython3?(?:\s+-[A-Za-z]+)*\s+-m\s+([\w.]+)", run)


def test_python_m_finds_the_intended_module_in_every_workflow():
    # From the checkout, `python -m NAME` runs a repository-root NAME.py
    # before an installed package: `python -m build` ran the desktop dev
    # build (build.py) instead of the sdist/wheel builder.
    shadowing = {p.stem for p in ROOT.glob("*.py")}
    assert "build" in shadowing
    checked = 0
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        data = _load(workflow.name)
        for name, job in data["jobs"].items():
            for run in _runs(job):
                for module in _python_modules(run):
                    checked += 1
                    assert module.split(".")[0] not in shadowing, (
                        workflow.name, name, module)
    assert checked


def test_python_module_pattern_reads_flags():
    assert _python_modules("python -m build") == ["build"]
    assert _python_modules('python3 -I -m pip install x') == ["pip"]
    assert _python_modules('"$env_python" -m pip check') == []
    assert _python_modules("pyproject-build --outdir dist .") == []


# ─── Release gating ─────────────────────────────────────────────────────

def test_release_publishes_only_after_tests_and_audit(release):
    jobs = release["jobs"]
    assert jobs["tests"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["audit"]["uses"] == "./.github/workflows/dependency-audit.yml"
    assert set(jobs["release"]["needs"]) == {"build", "tests", "audit"}
    # The builds still start right away, in parallel with the tests.
    assert jobs["build"]["needs"] == "locks"


def test_changelog_section_is_checked_before_anything_else_runs(release):
    # A tag without release notes fails in seconds, before the tests, the
    # audit and the release builds spend their minutes.
    jobs = release["jobs"]
    notes = jobs["notes"]
    assert "needs" not in notes
    assert notes["permissions"] == {"contents": "read"}
    (run,) = [r for r in _runs(notes) if r]
    assert run.strip() == (
        'python3 scripts/release_notes.py "${{ github.ref_name }}" > /dev/null')
    for name in ("tests", "audit", "locks"):
        assert jobs[name]["needs"] == "notes", name
    # Every other job waits for it, directly or through another job.
    def waits(name, seen=()):
        needs = jobs[name].get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        return "notes" in needs or any(waits(n, seen + (name,)) for n in needs
                                       if n not in seen)
    for name in jobs:
        if name != "notes":
            assert waits(name), name


def test_only_the_release_job_can_write(release):
    assert release["permissions"] == {"contents": "read"}
    for name, job in release["jobs"].items():
        permissions = job.get("permissions", {})
        if name == "release":
            assert permissions == {"contents": "write"}
        else:
            assert "write" not in permissions.values(), name


def test_release_body_is_the_changelog_section(release):
    steps = release["jobs"]["release"]["steps"]
    (notes,) = [i for i, s in enumerate(steps)
                if "scripts/release_notes.py" in s.get("run", "")]
    (publish,) = [i for i, s in enumerate(steps)
                  if str(s.get("uses", "")).startswith("softprops/action-gh-release@")]
    assert notes < publish
    run = steps[notes]["run"]
    assert '"${{ github.ref_name }}"' in run
    assert '--output "$RUNNER_TEMP/release-notes.md"' in run
    with_ = steps[publish]["with"]
    assert with_["body_path"] == "${{ runner.temp }}/release-notes.md"
    assert with_["generate_release_notes"] is True
    assert str(steps[0].get("uses", "")).startswith("actions/checkout@")


# ─── Dependency audit ───────────────────────────────────────────────────

def test_audit_scans_every_lock(audit):
    (run,) = [r for r in _runs(audit["jobs"]["osv-scanner"]) if "scan source" in r]
    scanned = set(re.findall(r"--lockfile=requirements\.txt:(requirements/\S+)", run))
    locks = {f"requirements/{p.name}" for p in (ROOT / "requirements").glob("*.txt")}
    assert locks and scanned == locks
    assert "--config=.github/osv-scanner.toml" in run
    assert (ROOT / ".github" / "osv-scanner.toml").is_file()


def test_audit_scanner_is_checksum_pinned(audit):
    (run,) = [r for r in _runs(audit["jobs"]["osv-scanner"]) if "curl" in r]
    assert re.search(r"/releases/download/v[\d.]+/osv-scanner_linux_amd64", run)
    assert re.search(r'echo "[0-9a-f]{64}  \$RUNNER_TEMP/osv-scanner" \| '
                     r"sha256sum --check --strict", run)


def test_audit_runs_on_dependency_changes_weekly_and_for_releases(audit):
    on = _triggers(audit)
    for event in ("push", "pull_request"):
        assert "requirements/**" in on[event]["paths"]
        assert "pyproject.toml" in on[event]["paths"]
    assert on["schedule"]
    assert "workflow_call" in on
    assert audit["permissions"] == {"contents": "read"}


def test_dependabot_updates_the_workflow_actions():
    data = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(
        encoding="utf-8"))
    ecosystems = {u["package-ecosystem"] for u in data["updates"]}
    # The Python locks are generated by scripts/lock_dependencies.py.
    assert ecosystems == {"github-actions"}


# ─── Scraper health ─────────────────────────────────────────────────────

def test_scraper_health_runs_the_live_probes_on_a_schedule_only():
    data = _load("scraper-health.yml")
    on = _triggers(data)
    assert set(on) == {"schedule", "workflow_dispatch"}
    job = data["jobs"]["live"]
    (line,) = _pytest_runs(job)
    assert "-m live tests/scrapers/live/" in line
    assert "--health-report=health.json" in line
    (upload,) = [s for s in job["steps"]
                 if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "health.json"
