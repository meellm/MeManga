"""Static checks for the routine CI, the dependency audit, the scraper
health run, the documentation site and how the release workflow depends
on them (#255, #317, #285, #385, #423)."""
from __future__ import annotations

import hashlib
import json
import os
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
    # The minor version of the floor: setup-python's "3.11" is its newest
    # patch release.
    floor = re.search(r'requires-python = ">=(\d+\.\d+)(?:\.\d+)?"', pyproject).group(1)
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


def test_package_mirror_stall_fails_fast(ci):
    # A stalled Ubuntu mirror held a test shard in apt-get until the job
    # timeout; every apt step now has its own short timeout and retries.
    steps = [s for job in ci["jobs"].values() for s in job.get("steps", [])
             if "apt-get" in s.get("run", "")]
    assert steps
    for step in steps:
        assert step["timeout-minutes"] <= 10, step["name"]
        assert "Acquire::http::Timeout=" in step["run"], step["name"]
        for line in step["run"].splitlines():
            if "apt-get" in line:
                assert "$apt_options" in line, line


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
    assert set(jobs["release"]["needs"]) == {"build", "tests", "audit", "pypi-check"}
    # The builds still start right away, in parallel with the tests.
    assert set(jobs["build"]["needs"]) == {"locks", "recovery-proof"}


def test_changelog_section_is_checked_before_anything_else_runs(release):
    # A tag without release notes fails in seconds, before the tests, the
    # audit and the release builds spend their minutes.
    jobs = release["jobs"]
    notes = jobs["notes"]
    assert "needs" not in notes
    assert notes["permissions"] == {"contents": "read"}
    changelog, announcement = [r.strip() for r in _runs(notes) if r]
    assert changelog == (
        'python3 scripts/release_notes.py "$RELEASE_TAG" > /dev/null')
    assert announcement == (
        "grep -q '[^[:space:]]' "
        '".github/release-announcements/${RELEASE_TAG}.md"')
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
        elif name == "publish-pypi":
            # Its PyPI identity, and no access to the repository.
            assert permissions == {"id-token": "write"}
        else:
            assert "write" not in permissions.values(), name


def test_release_body_is_the_tag_announcement(release):
    steps = release["jobs"]["release"]["steps"]
    assert not [s for s in steps if "scripts/release_notes.py" in s.get("run", "")]
    (publish,) = [s for s in steps
                  if str(s.get("uses", "")).startswith("softprops/action-gh-release@")]
    with_ = publish["with"]
    assert with_["tag_name"] == "${{ env.RELEASE_TAG }}"
    assert "target_commitish" not in with_
    assert with_["body_path"] == (
        ".github/release-announcements/${{ env.RELEASE_TAG }}.md")
    assert with_["generate_release_notes"] is False
    assert str(steps[0].get("uses", "")).startswith("actions/checkout@")


# ─── PyPI publishing ────────────────────────────────────────────────────

def _steps_using(job, action):
    return [s for s in job["steps"]
            if str(s.get("uses", "")).startswith(f"{action}@")]


def test_only_the_release_keeps_the_checked_packages(ci, release):
    # #218: PyPI gets the files the package job checked, not a second build.
    upload_dist = _triggers(ci)["workflow_call"]["inputs"]["upload_dist"]
    assert upload_dist["type"] == "boolean" and upload_dist["default"] is False
    assert release["jobs"]["tests"]["with"] == {"upload_dist": True}
    steps = ci["jobs"]["package"]["steps"]
    (upload,) = _steps_using(ci["jobs"]["package"], "actions/upload-artifact")
    assert steps[-1] is upload
    assert upload["if"] == "inputs.upload_dist"
    assert upload["with"]["name"] == "python-dist"
    assert upload["with"]["path"] == "dist/"
    assert upload["with"]["if-no-files-found"] == "error"
    # Failed jobs can be run again for 30 days.
    assert upload["with"]["retention-days"] >= 30


def test_pypi_gate_reads_the_packages_before_the_github_release(release):
    job = release["jobs"]["pypi-check"]
    assert set(job["needs"]) == {"tests", "recovery-proof"}
    assert job["permissions"] == {"contents": "read"}
    assert job["outputs"] == {"publish": "${{ steps.gate.outputs.publish }}"}
    (checkout,) = _steps_using(job, "actions/checkout")
    assert checkout["with"]["fetch-depth"] == 0
    (download,) = _steps_using(job, "actions/download-artifact")
    assert download["with"] == {"name": "python-dist", "path": "dist"}
    (check,) = [s for s in job["steps"] if s.get("id") == "gate"]
    assert check["run"].strip() == (
        'python3 scripts/pypi_release_gate.py "$RELEASE_TAG" "$RELEASE_SHA" dist')
    assert "pypi-check" in release["jobs"]["release"]["needs"]


def test_pypi_upload_follows_the_github_release(release):
    job = release["jobs"]["publish-pypi"]
    assert set(job["needs"]) == {"release", "pypi-check"}
    assert job["if"] == (
        "${{ !cancelled() && needs.release.result == 'success' "
        "&& needs.pypi-check.outputs.publish == 'true' }}")
    assert job["environment"]["name"] == "pypi"
    # Two pinned actions, no repository code.
    download, publish = job["steps"]
    assert download["with"] == {"name": "python-dist", "path": "dist"}
    assert re.fullmatch(r"actions/download-artifact@[0-9a-f]{40}", download["uses"])
    assert re.fullmatch(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", publish["uses"])
    # Trusted publishing with its default attestations.
    assert "with" not in publish


# ─── One-shot v0.5.0 recovery ───────────────────────────────────────────

RECOVERY_SHA = "969798f361ea18fb0c63b8bedde10479477de593"


def test_manual_release_run_can_only_recover_v0_5_0(release):
    # No inputs: a manual run cannot name another version or commit.
    triggers = _triggers(release)
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["workflow_dispatch"] is None
    manual = "${{ github.event_name == 'workflow_dispatch' && "
    assert release["env"] == {
        "RELEASE_TAG": manual + "'v0.5.0' || github.ref_name }}",
        "RELEASE_SHA": manual + f"'{RECOVERY_SHA}' || github.sha }}}}",
        "RECOVERY_SOURCE": manual + f"'{RECOVERY_SHA}' || '' }}}}",
    }
    # Every source checkout: the tag's commit by hand, the default on a push.
    for name in ("notes", "locks", "build", "pypi-check", "release"):
        (checkout,) = _steps_using(release["jobs"][name], "actions/checkout")
        assert checkout["with"]["ref"] == "${{ env.RECOVERY_SOURCE }}", name


def test_recovery_proof_runs_no_repository_code(release):
    job = release["jobs"]["recovery-proof"]
    assert job["needs"] == "notes"
    assert job["if"] == "github.event_name == 'workflow_dispatch'"
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert not _steps_using(job, "actions/checkout")
    proof = job["steps"][0]["run"]
    for required in ('expect "workflow ref" "$GITHUB_REF" "refs/heads/main"',
                     "$TAG_OBJECT", "$CI_RUN", "$SOURCE_RUN", "$PACKAGE_DIGEST",
                     '"$release_status" 404', '"$pypi_status" 404'):
        assert required in proof, required
    (download,) = _steps_using(job, "actions/download-artifact")
    assert re.fullmatch(r"actions/download-artifact@[0-9a-f]{40}", download["uses"])
    assert download["with"]["name"] == "python-dist"
    assert download["with"]["run-id"] == "${{ env.SOURCE_RUN }}"
    assert "digest-mismatch" not in download["with"]
    (upload,) = _steps_using(job, "actions/upload-artifact")
    assert upload["with"]["name"] == "python-dist"
    assert upload["with"]["if-no-files-found"] == "error"


def test_recovery_skips_only_the_checks_it_reuses(release):
    jobs = release["jobs"]
    for name in ("tests", "audit"):
        assert jobs[name]["if"] == "github.event_name == 'push'", name
    for name in ("notes", "locks"):
        assert "if" not in jobs[name], name
    for needed in ("locks", "recovery-proof"):
        assert f"needs.{needed}.result == 'success'" in jobs["build"]["if"]
    assert "needs.recovery-proof.result == 'success'" in jobs["pypi-check"]["if"]
    # A tag push still needs everything it needed before.
    assert ("github.event_name == 'push' && needs.tests.result == 'success'"
            in jobs["pypi-check"]["if"])
    for needed in ("build", "pypi-check", "tests", "audit"):
        assert f"needs.{needed}.result == 'success'" in jobs["release"]["if"]


def test_recovery_replaces_only_the_release_spec(release):
    # The tag stays as it is: one build file, at an exact blob, comes from
    # the workflow's commit. Remove this with the one-shot recovery.
    steps = release["jobs"]["build"]["steps"]
    assert str(steps[0]["uses"]).startswith("actions/checkout@")
    step = steps[1]
    assert step["if"] == "github.event_name == 'workflow_dispatch'"
    assert step["shell"] == "bash"
    spec = (ROOT / "packaging" / "memanga-release.spec").read_bytes()
    assert step["env"] == {
        "TAG_SPEC_BLOB": "06a7ca436acc5af675d34c1f1ca0686a09f12d31",
        "FIXED_SPEC_BLOB": hashlib.sha1(b"blob %d\0" % len(spec) + spec).hexdigest(),
    }
    lines = step["run"].splitlines()
    assert lines[0] == "spec=packaging/memanga-release.spec"
    for guard in ('test "$(git rev-parse HEAD)" = "$RELEASE_SHA"',
                  'test -z "$(git status --porcelain)"',
                  'test "$(git rev-parse "HEAD:$spec")" = "$TAG_SPEC_BLOB"',
                  'test "$(git rev-parse "FETCH_HEAD:$spec")" = "$FIXED_SPEC_BLOB"',
                  'test "$(git hash-object --no-filters -- "$spec")" = "$FIXED_SPEC_BLOB"',
                  'test "$(git status --porcelain)" = " M $spec"'):
        assert guard in lines, guard
    assert lines.index('git show "FETCH_HEAD:$spec" > "$spec"') < lines.index(
        'test "$(git status --porcelain)" = " M $spec"')
    (build,) = [s for s in steps if s.get("name") == "Build release executable"]
    assert build["env"]["MEMANGA_RECIPE_COMMIT"] == (
        "${{ github.event_name == 'workflow_dispatch' && github.sha || '' }}")
    names = [s.get("name") for s in steps]
    note = names.index("Confirm the notices name the recovery recipe")
    assert note == names.index("Check third-party notices") + 1
    assert steps[note]["if"] == "github.event_name == 'workflow_dispatch'"
    assert steps[note]["shell"] == "bash"
    assert steps[note]["run"].strip() == (
        'grep -Fq "$GITHUB_SHA" release/THIRD_PARTY_NOTICES.txt')


def test_only_the_release_publisher_and_pages_deploy_request_an_identity():
    # PyPI trusts publish-pypi within release.yml; the Pages deployment
    # needs its own identity.
    allowed = {("release.yml", "publish-pypi"), ("docs.yml", "deploy")}
    found = set()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        data = _load(workflow.name)
        assert "id-token" not in (data.get("permissions") or {}), workflow.name
        for name, job in data["jobs"].items():
            permissions = job.get("permissions") or {}
            if "id-token" in permissions:
                assert permissions["id-token"] == "write", (workflow.name, name)
                found.add((workflow.name, name))
    assert found == allowed


def test_github_release_assets_leave_out_the_python_packages(release):
    (download,) = _steps_using(release["jobs"]["release"], "actions/download-artifact")
    assert download["with"]["pattern"] == "MeManga-*"
    for cell in release["jobs"]["build"]["strategy"]["matrix"]["include"]:
        assert cell["asset_name"].startswith("MeManga-"), cell["asset_name"]


# ─── Dependency audit ───────────────────────────────────────────────────

def test_audit_scans_every_lock(audit):
    (run,) = [r for r in _runs(audit["jobs"]["osv-scanner"]) if "scan source" in r]
    scanned = set(re.findall(r"--lockfile=requirements\.txt:(requirements/\S+)", run))
    locks = {f"requirements/{p.name}" for p in (ROOT / "requirements").glob("*.txt")}
    assert locks and scanned == locks
    assert "--lockfile=package-lock.json:docs/package-lock.json" in run
    assert (ROOT / "docs" / "package-lock.json").is_file()
    assert "--config=.github/osv-scanner.toml" in run
    assert (ROOT / ".github" / "osv-scanner.toml").is_file()


def test_docs_lock_keeps_the_patched_build_tools():
    # VitePress 1.6.4 asks for Vite 5, which has no patched release, so
    # docs/package.json overrides its Vite. A regenerated lock must not
    # fall back to the vulnerable versions.
    packages = json.loads((ROOT / "docs" / "package-lock.json").read_text(
        encoding="utf-8"))["packages"]
    for name, floor in (("vite", (6, 4, 4)), ("esbuild", (0, 25, 0))):
        found = [entry["version"] for path, entry in packages.items()
                 if path.endswith(f"node_modules/{name}")]
        assert found, name
        for version in found:
            assert tuple(map(int, version.split("-")[0].split("."))) >= floor, (
                name, version)


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
        assert "docs/package.json" in on[event]["paths"]
        assert "docs/package-lock.json" in on[event]["paths"]
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


def test_scraper_health_runs_without_qt():
    # pytest-qt imports Qt in every pytest run it loads in, and Qt needs
    # system libraries (libEGL first); the probes use no Qt, so the
    # health run does not load the plugin nor install those libraries.
    job = _load("scraper-health.yml")["jobs"]["live"]
    (line,) = _pytest_runs(job)
    assert "-p no:pytest-qt" in line
    assert not [r for r in _runs(job) if "apt-get" in r]


def test_scraper_health_runs_where_the_pinned_playwright_installs():
    # Playwright 1.60 cannot install its browsers on Ubuntu 26.04, which
    # ubuntu-latest became; the job stays on the newest image it supports.
    job = _load("scraper-health.yml")["jobs"]["live"]
    assert job["runs-on"] == "ubuntu-24.04"
    lock = (ROOT / "requirements" / "dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^playwright==1\.60\.", lock, re.M), (
        "Playwright moved: check its supported Ubuntu releases and runs-on")


def test_scraper_health_fails_only_on_a_broken_run():
    # Failing sources are reported; the run fails when the browsers do not
    # start, the probes do not run, or health.json does not account for
    # every failed test (scripts/check_health_report.py).
    job = _load("scraper-health.yml")["jobs"]["live"]
    steps = job["steps"]
    names = [s.get("name") for s in steps]
    assert all("continue-on-error" not in s for s in steps)
    assert all("|| true" not in r for r in _runs(job))
    browsers, probes, check = (names.index(n) for n in (
        "Check that the browsers start", "Run live probes",
        "Check the health report"))
    assert browsers < probes < check
    assert steps[browsers]["run"] == (
        "memanga doctor --check browsers --launch-browsers")
    assert "if" not in steps[browsers]
    run = steps[probes]["run"].splitlines()
    assert run[0] == "set +e" and "-m pytest" in run[1]
    assert run[2] == 'echo "exit-code=$?" >> "$GITHUB_OUTPUT"'
    assert steps[check]["run"] == (
        "python scripts/check_health_report.py health.json "
        '"${{ steps.%s.outputs.exit-code }}"' % steps[probes]["id"])
    assert "if" not in steps[check]


def test_branch_checks_can_run_by_hand():
    # The read-only checks run on a branch without a pull request.
    for name in ("ci.yml", "dependency-audit.yml", "dependency-locks.yml",
                 "source-docs.yml", "scraper-health.yml"):
        assert "workflow_dispatch" in _triggers(_load(name)), name


# ─── Documentation site ─────────────────────────────────────────────────

# `<<< path` and `<!--@include: path-->` put another file into a page.
_EMBED = re.compile(r"^<<<\s+(\S+)|<!--\s*@include:\s*(\S+?)\s*-->", re.M)


def _site_pages():
    docs = ROOT / "docs"
    for folder, subfolders, files in os.walk(docs):
        # Installed packages and build output are not site pages.
        subfolders[:] = [d for d in subfolders
                         if d not in {"node_modules", "dist", "cache"}]
        for name in files:
            if name.endswith(".md"):
                yield Path(folder) / name


def _files_shown_from_outside_docs():
    shown = set()
    for page in _site_pages():
        for match in _EMBED.finditer(page.read_text(encoding="utf-8")):
            # Drop a line range or region: file{1-3}, file#region.
            target = re.split(r"[{#]", match[1] or match[2])[0]
            if target.startswith("@/"):
                path = ROOT / "docs" / target[2:]
            else:
                path = page.parent / target
            relative = path.resolve().relative_to(ROOT).as_posix()
            if not relative.startswith("docs/"):
                shown.add(relative)
    return shown


def test_docs_site_is_rebuilt_when_a_file_it_shows_changes():
    # A page can show a file from outside docs/. Without that file in the
    # path filter, a change to it would leave the old copy on the site.
    paths = _triggers(_load("docs.yml"))["push"]["paths"]
    shown = _files_shown_from_outside_docs()
    assert {"compose.yaml", "compose.dev.yaml"} <= shown
    assert "docs/**" in paths
    for relative in sorted(shown):
        assert (ROOT / relative).is_file(), relative
        assert relative in paths, relative
