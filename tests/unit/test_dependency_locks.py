"""#315: pyproject.toml is the only dependency declaration. The pinned
installs in requirements/ are generated from it by
scripts/lock_dependencies.py, and a lock left behind after a change to
pyproject.toml is caught here and by `lock_dependencies.py --check`."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "lock_dependencies.py"
TARGETS = ("cli", "gui", "dev", "build")
# The platforms and Python versions the locks must agree on: the Docker
# image (Linux 3.12), the release legs (3.12) and the source docs check
# (Linux 3.10).
ENVIRONMENTS = [
    {"sys_platform": plat, "platform_system": system, "os_name": os_name,
     "python_version": version, "python_full_version": f"{version}.0",
     "implementation_name": "cpython", "platform_python_implementation": "CPython",
     "extra": ""}
    for plat, system, os_name in (("linux", "Linux", "posix"),
                                  ("win32", "Windows", "nt"),
                                  ("darwin", "Darwin", "posix"))
    for version in ("3.10", "3.12")
]


def _load_script():
    name = "memanga_lock_dependencies"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def locks():
    return _load_script()


@pytest.fixture(scope="module")
def project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _rows(name):
    """(requirement, hashes) for every pinned row of requirements/<name>.txt."""
    rows = []
    for line in (ROOT / "requirements" / f"{name}.txt").read_text(
            encoding="utf-8").splitlines():
        stripped = line.strip().rstrip("\\").strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] != " ":
            rows.append((Requirement(stripped), []))
        elif stripped.startswith("--hash=sha256:"):
            rows[-1][1].append(stripped)
    return rows


def _pin(req):
    (spec,) = req.specifier
    assert spec.operator == "==", str(req)
    return spec.version


# ─── The locks in the repository ────────────────────────────────────────

def test_locks_match_pyproject(locks):
    assert locks.check() == []
    assert locks.main(["--check", "--offline"]) == 0


def test_no_hand_maintained_dependency_lists():
    assert sorted(p.name for p in ROOT.glob("requirements*.txt")) == []
    assert not (ROOT / "tests" / "requirements-test.txt").exists()
    assert sorted(p.name for p in (ROOT / "requirements").iterdir()) == sorted(
        f"{name}.txt" for name in TARGETS)


@pytest.mark.parametrize("target", TARGETS)
def test_lock_pins_every_requirement_of_its_target(locks, project, target):
    rows = _rows(target)
    assert rows
    by_name = {}
    for req, hashes in rows:
        assert hashes, f"{req.name} has no hash in {target}.txt"
        by_name.setdefault(canonicalize_name(req.name), []).append(_pin(req))
    for line in locks.target_requirements(project, locks.TARGETS[target]):
        req = Requirement(line)
        if req.marker is not None and not any(
                req.marker.evaluate(env) for env in ENVIRONMENTS):
            continue
        name = canonicalize_name(req.name)
        assert name in by_name, f"{req.name} is not pinned in {target}.txt"
        for version in by_name[name]:
            assert req.specifier.contains(version, prereleases=True), (
                f"{target}.txt pins {req.name}=={version}, pyproject.toml "
                f"needs {req.specifier}")


def test_locks_never_pin_the_project_itself(project):
    own = canonicalize_name(project["name"])
    for target in TARGETS:
        assert own not in {canonicalize_name(r.name) for r, _ in _rows(target)}


@pytest.mark.parametrize("env", ENVIRONMENTS,
                         ids=lambda e: f"{e['sys_platform']}-{e['python_version']}")
def test_shared_packages_have_one_version_across_locks(env):
    # The Docker image, the source setup, the tests and the builds use
    # the same version of every package they share.
    seen = {}
    for target in TARGETS:
        for req, _ in _rows(target):
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            name = canonicalize_name(req.name)
            version = _pin(req)
            first = seen.setdefault(name, (target, version))
            assert first[1] == version, (
                f"{name}: {first[0]}.txt pins {first[1]}, {target}.txt {version}")


def test_lock_python_floor_is_requires_python(locks, project):
    assert project["requires-python"] == ">=3.10"
    assert locks.python_floor(project) == "3.10"


def test_lock_policy_times_are_utc(locks):
    policy = locks.load_policy(ROOT / "pyproject.toml")
    assert policy["resolve-at"]
    assert locks.policy_problems(policy) == []


def test_every_package_with_its_own_time_is_locked(locks):
    # A leftover entry would hide that nothing uses it any more.
    locked = {canonicalize_name(r.name) for target in TARGETS for r, _ in _rows(target)}
    later = locks.load_policy(ROOT / "pyproject.toml")["resolve-package-at"]
    assert {canonicalize_name(name) for name in later} <= locked


# ─── Consumers ──────────────────────────────────────────────────────────

def _workflow_runs(name):
    data = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(
        encoding="utf-8"))
    return [step.get("run", "") for job in data["jobs"].values()
            for step in job["steps"]]


def test_release_workflow_installs_the_build_lock():
    runs = "\n".join(_workflow_runs("release.yml"))
    assert "pip install -r requirements/build.txt" in runs
    assert "pip install pyinstaller" not in runs


def test_builds_install_the_build_lock():
    for script in ("build.py", "build_app.py"):
        text = (ROOT / script).read_text(encoding="utf-8")
        assert '"requirements/build.txt"' in text, script
        assert '"pyinstaller' not in text, script


def test_source_docs_check_installs_the_cli_lock():
    assert "python -m pip install -r requirements/cli.txt" in _workflow_runs(
        "source-docs.yml")


def test_lock_check_runs_in_ci_with_the_pinned_uv(locks):
    runs = _workflow_runs("dependency-locks.yml")
    install = f'python -m pip install "uv=={locks.UV_VERSION}"'
    assert install in runs
    # The full check, which generates the locks again, not --offline.
    assert runs.index(install) < runs.index("python scripts/lock_dependencies.py --check")


# ─── The check itself ───────────────────────────────────────────────────

PYPROJECT = """\
[project]
name = "Demo_App"
requires-python = ">=3.10"
dependencies = ["alpha>=1", "beta>=1"]

[project.optional-dependencies]
gui = ["gamma>=1"]
dev = ["demo-app[gui]", "delta>=1"]
build = ["demo-app[gui]", "epsilon>=1; sys_platform == 'win32'"]

[tool.lock-dependencies]
resolve-at = "2026-02-01T00:00:00Z"
"""
# The rows the stand-in uv below prints for every target of PYPROJECT.
BODY = "alpha==1.0 \\\n    --hash=sha256:aa\n"


def _write(root, locks, text=PYPROJECT):
    (root / "pyproject.toml").write_text(text, encoding="utf-8")
    project = locks.load_project(root / "pyproject.toml")
    policy = locks.load_policy(root / "pyproject.toml")
    (root / "requirements").mkdir(exist_ok=True)
    for name, extras in locks.TARGETS.items():
        (root / "requirements" / f"{name}.txt").write_text(
            locks.lock_text(name, BODY, locks.input_digest(project, extras, policy)),
            encoding="utf-8")


def test_self_references_expand_to_the_extras(locks):
    project = tomllib.loads(PYPROJECT)["project"]
    assert locks.target_requirements(project, ("dev",)) == [
        "alpha>=1", "beta>=1", "delta>=1", "gamma>=1"]
    assert locks.target_requirements(project, ()) == ["alpha>=1", "beta>=1"]


def test_check_passes_for_current_locks(tmp_path, locks):
    _write(tmp_path, locks)
    assert locks.check(tmp_path) == []


def test_check_ignores_order_whitespace_and_comments(tmp_path, locks):
    _write(tmp_path, locks)
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT.replace('["alpha>=1", "beta>=1"]',
                          '[\n    # comment\n    "beta >= 1",\n    "alpha>=1",\n]'),
        encoding="utf-8")
    assert locks.check(tmp_path) == []


def test_changing_an_extra_makes_only_its_locks_stale(tmp_path, locks):
    _write(tmp_path, locks)
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT.replace('"gamma>=1"', '"gamma>=2"'), encoding="utf-8")
    assert locks.check(tmp_path) == [
        "requirements/gui.txt is out of date with pyproject.toml",
        "requirements/dev.txt is out of date with pyproject.toml",
        "requirements/build.txt is out of date with pyproject.toml",
    ]


@pytest.mark.parametrize("old, new", [
    ('"alpha>=1"', '"alpha>=2"'),
    ('"beta>=1"]', '"beta>=1", "zeta"]'),
    ('">=3.10"', '">=3.11"'),
    ('"2026-02-01T00:00:00Z"', '"2026-03-01T00:00:00Z"'),
    ('resolve-at = "2026-02-01T00:00:00Z"\n',
     'resolve-at = "2026-02-01T00:00:00Z"\n'
     '[tool.lock-dependencies.resolve-package-at]\nalpha = "2026-04-01T00:00:00Z"\n'),
], ids=["floor", "new-dependency", "python", "resolve-at", "package-time"])
def test_changing_a_dependency_python_or_policy_makes_every_lock_stale(
        tmp_path, locks, old, new):
    _write(tmp_path, locks)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT.replace(old, new),
                                             encoding="utf-8")
    assert len(locks.check(tmp_path)) == len(TARGETS)


def test_check_reports_missing_unmarked_and_stray_files(tmp_path, locks):
    _write(tmp_path, locks)
    (tmp_path / "requirements" / "cli.txt").unlink()
    (tmp_path / "requirements" / "dev.txt").write_text("alpha==1.0\n", encoding="utf-8")
    (tmp_path / "requirements" / "docker.txt").write_text("alpha==1.0\n", encoding="utf-8")
    assert locks.check(tmp_path) == [
        "requirements/cli.txt is missing",
        "requirements/dev.txt is out of date with pyproject.toml",
        "requirements/docker.txt is not a generated lock",
    ]


@pytest.mark.parametrize("when", ["2026-02-01", "2026-02-01T00:00:00+00:00",
                                  "yesterday Z", 20260201])
def test_policy_times_must_be_utc(locks, when):
    problems = locks.policy_problems({"resolve-at": "2026-02-01T00:00:00Z",
                                      "resolve-package-at": {"alpha": when}})
    assert len(problems) == 1 and "resolve-package-at.alpha" in problems[0]


def test_check_mode_exits_1_and_names_the_fix(tmp_path, locks, monkeypatch, capsys):
    _write(tmp_path, locks)
    (tmp_path / "requirements" / "gui.txt").unlink()
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    assert locks.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "requirements/gui.txt is missing" in err
    assert "python scripts/lock_dependencies.py" in err


def test_lock_header_names_the_file_the_command_and_the_digest(locks):
    text = locks.lock_text("cli", "alpha==1.0 \\\n    --hash=sha256:00\n", "abc")
    lines = text.splitlines()
    assert lines[0].startswith("# requirements/cli.txt: ")
    assert f"#    {locks.COMMAND}" in lines
    assert locks.recorded_digest(text) == "abc"
    assert all(line.startswith("#") for line in lines[:-2])
    assert lines[-2:] == ["alpha==1.0 \\", "    --hash=sha256:00"]


@pytest.mark.parametrize("target", TARGETS)
def test_real_locks_carry_only_the_project_header(locks, target):
    # The comment lines before the first row are exactly this project's
    # header; the resolver's own header is left out.
    text = (ROOT / "requirements" / f"{target}.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    first_row = next(i for i, line in enumerate(lines) if not line.startswith("#"))
    expected = locks.lock_text(target, "", locks.recorded_digest(text)).splitlines()
    assert lines[:first_row] == expected


def test_generate_without_uv_explains_how_to_get_it(locks, monkeypatch, capsys):
    monkeypatch.setattr(locks, "_uv", lambda: None)
    assert locks.main([]) == 1
    assert f'pip install "uv=={locks.UV_VERSION}"' in capsys.readouterr().err


def test_generate_takes_no_uv_arguments(locks):
    # Versions move only through [tool.lock-dependencies].
    with pytest.raises(SystemExit):
        locks.main(["--upgrade-package", "urllib3"])


# ─── Generating and the full check, with a stand-in resolver ────────────

# A small resolver standing in for uv. It reads the package index next to
# it, honours --exclude-newer (no cutoff without it), --exclude-newer-package
# and constraint files the way uv does, logs its arguments, and prints the
# lock.
FAKE_UV = """\
import json, pathlib, sys
args = sys.argv[1:]
here = pathlib.Path(__file__).parent
if args == ['--version']:
    print('uv ' + (here / 'version').read_text())
    sys.exit(0)
with (here / 'calls').open('a') as log:
    log.write(json.dumps(args) + '\\n')
if (here / 'fail').exists() or '--output-file' in args:
    sys.exit(1)
def values(flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]
cutoff = (values('--exclude-newer') or ['9999'])[0]
per_package = dict(v.split('=', 1) for v in values('--exclude-newer-package'))
pinned = {}
for path in values('--constraint') + values('-c'):
    for line in pathlib.Path(path).read_text().splitlines():
        if '==' in line:
            name, version = line.split('==')
            pinned[name.strip()] = version.split()[0]
out = [] if '--no-header' in args else ['# fake header']
for name, releases in sorted(json.loads((here / 'index.json').read_text()).items()):
    limit = per_package.get(name, cutoff)
    fits = [r for r in releases if r['uploaded'] <= limit
            and pinned.get(name, r['version']) == r['version']]
    newest = max(fits, key=lambda r: r['uploaded'])
    out += [name + '==' + newest['version'] + ' \\\\',
            '    --hash=sha256:' + newest['sha256']]
print('\\n'.join(out))
"""
# alpha 1.1 fits alpha>=1, but came out after PYPROJECT's resolve-at.
INDEX = {"alpha": [
    {"version": "1.0", "uploaded": "2026-01-01T00:00:00Z", "sha256": "aa"},
    {"version": "1.1", "uploaded": "2026-03-01T00:00:00Z", "sha256": "bb"},
]}


@pytest.fixture
def fake_uv(tmp_path, locks, monkeypatch):
    home = tmp_path / "uv"
    home.mkdir()
    (home / "uv.py").write_text(FAKE_UV, encoding="utf-8")
    (home / "index.json").write_text(json.dumps(INDEX), encoding="utf-8")
    (home / "version").write_text(f"{locks.UV_VERSION} (test)", encoding="utf-8")
    monkeypatch.setattr(locks, "_uv", lambda: [sys.executable, str(home / "uv.py")])
    return home


def _files(root):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (root / "requirements").iterdir()}


def _calls(home):
    return [json.loads(line) for line in
            (home / "calls").read_text(encoding="utf-8").splitlines()]


def test_full_check_passes_and_writes_nothing(tmp_path, locks, fake_uv):
    _write(tmp_path, locks)
    before = _files(tmp_path)
    assert locks.check_generated(tmp_path, locks._uv()) == []
    assert _files(tmp_path) == before


def test_full_check_resolves_from_pyproject_alone(tmp_path, locks, fake_uv):
    _write(tmp_path, locks)
    locks.check_generated(tmp_path, locks._uv())
    calls = _calls(fake_uv)
    assert len(calls) == len(TARGETS)
    for args in calls:
        # Nothing from the files under check reaches the resolver.
        assert not {"--constraint", "-c", "--output-file", "-o"} & set(args)
        assert not [a for a in args if "requirements" in a]
        assert args[args.index("--exclude-newer") + 1] == "2026-02-01T00:00:00Z"
        assert "--no-config" in args
        # The resolver's own header stays out of the locks.
        assert "--no-header" in args


def test_full_check_catches_a_fitting_repin_with_valid_hashes(tmp_path, locks, fake_uv):
    """The edit a resolver held to the committed pins would reproduce:
    alpha moved to 1.1, which fits alpha>=1, with 1.1's own hash."""
    _write(tmp_path, locks)
    path = tmp_path / "requirements" / "gui.txt"
    path.write_text(path.read_text(encoding="utf-8")
                    .replace("alpha==1.0", "alpha==1.1").replace("sha256:aa", "sha256:bb"),
                    encoding="utf-8")
    edited_row = "alpha==1.1 \\\n    --hash=sha256:bb\n"
    assert edited_row in path.read_text(encoding="utf-8")
    # A check that holds the resolver to the committed pins (no cutoff,
    # the pins as constraints) gets exactly the edited row back, so it
    # would pass the edit.
    pins = tmp_path / "pins.txt"
    pins.write_text("alpha==1.1\n", encoding="utf-8")
    constrained = subprocess.run([*locks._uv(), "--constraint", str(pins)],
                                 capture_output=True, text=True, check=True).stdout
    assert edited_row in constrained
    # Resolving from pyproject.toml's policy alone gives alpha 1.0 instead.
    independent = subprocess.run([*locks._uv(), "--exclude-newer", "2026-02-01T00:00:00Z"],
                                 capture_output=True, text=True, check=True).stdout
    assert "alpha==1.0 \\\n    --hash=sha256:aa\n" in independent
    assert "alpha==1.1" not in independent
    # The digest is current, so only the full check sees it.
    assert locks.check(tmp_path) == []
    assert locks.check_generated(tmp_path, locks._uv()) == [
        "requirements/gui.txt differs from what pyproject.toml generates"]


@pytest.mark.parametrize("edit", [
    lambda t: t.replace("alpha==1.0 \\\n    --hash=sha256:aa\n", ""),
    lambda t: t.replace("sha256:aa", "sha256:cc"),
    lambda t: t.replace(" \\\n    --hash=sha256:aa", ""),
    lambda t: t.replace("alpha==1.0", "alpha==1.0 ; sys_platform == 'linux'"),
    lambda t: t + "beta==2.0 \\\n    --hash=sha256:dd\n",
    lambda t: t + "    # via someone\n",
], ids=["row-removed", "hash-changed", "hash-removed", "marker-added", "row-added",
        "comment-added"])
def test_full_check_catches_other_hand_edits(tmp_path, locks, fake_uv, edit):
    _write(tmp_path, locks)
    path = tmp_path / "requirements" / "dev.txt"
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    before = _files(tmp_path)
    assert locks.check(tmp_path) == []
    assert locks.check_generated(tmp_path, locks._uv()) == [
        "requirements/dev.txt differs from what pyproject.toml generates"]
    assert _files(tmp_path) == before


def test_full_check_reports_a_failed_generation(tmp_path, locks, fake_uv):
    _write(tmp_path, locks)
    (fake_uv / "fail").touch()
    before = _files(tmp_path)
    problems = locks.check_generated(tmp_path, locks._uv())
    assert problems[0] == "requirements/cli.txt could not be generated"
    assert len(problems) == len(TARGETS)
    assert _files(tmp_path) == before


def test_moving_a_package_time_updates_it(tmp_path, locks, fake_uv, monkeypatch):
    # The update route: move the time in pyproject.toml, regenerate, and
    # both checks pass with the newer release.
    _write(tmp_path, locks)
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT + '\n[tool.lock-dependencies.resolve-package-at]\n'
                    'alpha = "2026-04-01T00:00:00Z"\n', encoding="utf-8")
    assert len(locks.check(tmp_path)) == len(TARGETS)
    assert locks.main([]) == 0
    text = (tmp_path / "requirements" / "cli.txt").read_text(encoding="utf-8")
    assert "alpha==1.1 \\\n    --hash=sha256:bb" in text
    assert "--exclude-newer-package" in _calls(fake_uv)[-1]
    assert "alpha=2026-04-01T00:00:00Z" in _calls(fake_uv)[-1]
    assert locks.main(["--check"]) == 0


def test_check_mode_runs_the_full_check(tmp_path, locks, fake_uv, monkeypatch, capsys):
    _write(tmp_path, locks)
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    assert locks.main(["--check"]) == 0
    path = tmp_path / "requirements" / "build.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("alpha==1.0", "alpha==1.1")
                    .replace("sha256:aa", "sha256:bb"), encoding="utf-8")
    assert locks.main(["--check"]) == 1
    assert "requirements/build.txt differs" in capsys.readouterr().err


def test_check_mode_needs_the_pinned_uv(tmp_path, locks, fake_uv, monkeypatch, capsys):
    _write(tmp_path, locks)
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    (fake_uv / "version").write_text("0.0.1", encoding="utf-8")
    assert locks.main(["--check"]) == 1
    assert f"needs uv {locks.UV_VERSION}" in capsys.readouterr().err
    # Generating needs it as well; --offline needs no uv.
    assert locks.main([]) == 1
    assert locks.main(["--check", "--offline"]) == 0
    monkeypatch.setattr(locks, "_uv", lambda: None)
    assert locks.main(["--check"]) == 1
    assert "uv was not found" in capsys.readouterr().err
