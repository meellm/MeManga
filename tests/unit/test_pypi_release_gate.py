"""#218: only a canonical stable tag from 0.5.0 on, on main, with its own
sdist and wheel goes to PyPI, and anything unclear fails closed."""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pypi_release_gate.py"
SDIST = "memanga-0.5.0.tar.gz"
WHEEL = "memanga-0.5.0-py3-none-any.whl"


@pytest.fixture(scope="module")
def gate():
    name = "memanga_pypi_release_gate"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _metadata(name="memanga", version="0.5.0", extra=""):
    # The description below the headers is not metadata.
    return (f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{extra}"
            "\nName: not-a-header\nVersion: 9.9.9\n").encode("utf-8")


def _write_sdist(path, top="memanga-0.5.0", metadata=None):
    data = _metadata() if metadata is None else metadata
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(f"{top}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _write_wheel(path, info="memanga-0.5.0.dist-info", metadata=None):
    data = _metadata() if metadata is None else metadata
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{info}/METADATA", data)


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    folder.mkdir()
    _write_sdist(folder / SDIST)
    _write_wheel(folder / WHEEL)
    return folder


@pytest.fixture
def output(tmp_path, monkeypatch):
    path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository with one commit on main and one beside it."""
    folder = tmp_path / "repo"
    folder.mkdir()

    def git(*args):
        result = subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test",
             "-c", "commit.gpgsign=false", *args],
            cwd=folder, check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()

    git("init", "--quiet")
    git("commit", "--quiet", "--allow-empty", "-m", "on main")
    on_main = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", on_main)
    git("commit", "--quiet", "--allow-empty", "-m", "off main")
    off_main = git("rev-parse", "HEAD")
    monkeypatch.chdir(folder)
    return SimpleNamespace(on_main=on_main, off_main=off_main, git=git)


@pytest.mark.parametrize("tag, version", [
    ("v0.5.0", "0.5.0"),
    ("v0.5.1", "0.5.1"),
    ("v0.10.0", "0.10.0"),
    ("v1.0.0", "1.0.0"),
    ("v0.4.4", None),
    ("v0.4.99", None),
    ("v0.0.0", None),
    ("v0.5.0rc1", None),
    ("v0.5.0-rc.1", None),
    ("v0.5.0.post1", None),
    ("v0.5.0+local", None),
    ("v0.5", None),
    ("v0.5.0.1", None),
    ("0.5.0", None),
    ("V0.5.0", None),
    ("v00.5.0", None),
    ("v0.05.0", None),
    ("v0.5.00", None),
    ("v0.5.0\n", None),
    ("v٠.٥.٠", None),
])
def test_only_canonical_stable_tags_from_0_5_0_publish(gate, tag, version):
    assert gate.publishable_version(tag) == version


def test_stable_tag_on_main_with_its_packages_publishes(gate, repo, dist, output):
    assert gate.main(["v0.5.0", repo.on_main, str(dist)]) == 0
    assert output.read_text(encoding="utf-8") == "publish=true\n"


def test_v0_4_4_is_never_published(gate, repo, tmp_path, output):
    # Even from main, and with packages that match the tag.
    folder = tmp_path / "old"
    folder.mkdir()
    old = _metadata(version="0.4.4")
    _write_sdist(folder / "memanga-0.4.4.tar.gz", "memanga-0.4.4", old)
    _write_wheel(folder / "memanga-0.4.4-py3-none-any.whl",
                 "memanga-0.4.4.dist-info", old)
    assert gate.main(["v0.4.4", repo.on_main, str(folder)]) == 0
    assert output.read_text(encoding="utf-8") == "publish=false\n"


def test_prerelease_stays_off_pypi_without_failing_its_release(
        gate, repo, tmp_path, output):
    assert gate.main(["v0.5.0-rc.1", repo.off_main, str(tmp_path / "none")]) == 0
    assert output.read_text(encoding="utf-8") == "publish=false\n"


def test_commit_off_main_fails(gate, repo, dist, output, capsys):
    assert gate.main(["v0.5.0", repo.off_main, str(dist)]) == 1
    assert "is not on main" in capsys.readouterr().err
    assert not output.exists()


def test_unknown_commit_fails(gate, repo, dist, output, capsys):
    assert gate.main(["v0.5.0", "0" * 40, str(dist)]) == 1
    assert "cannot check" in capsys.readouterr().err
    assert not output.exists()


def test_missing_main_ref_fails(gate, repo, dist, output, capsys):
    repo.git("update-ref", "-d", "refs/remotes/origin/main")
    assert gate.main(["v0.5.0", repo.on_main, str(dist)]) == 1
    assert "cannot check" in capsys.readouterr().err
    assert not output.exists()


def test_missing_git_fails(gate, repo, dist, output, monkeypatch, capsys):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(gate.subprocess, "run", no_git)
    assert gate.main(["v0.5.0", repo.on_main, str(dist)]) == 1
    assert "cannot check" in capsys.readouterr().err
    assert not output.exists()


def test_missing_dist_folder_fails(gate, repo, tmp_path, output):
    assert gate.main(["v0.5.0", repo.on_main, str(tmp_path / "none")]) == 1
    assert not output.exists()


def test_missing_github_output_fails(gate, repo, dist, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert gate.main(["v0.5.0", repo.on_main, str(dist)]) == 1


BROKEN = {
    "no sdist": lambda d: (d / SDIST).unlink(),
    "no wheel": lambda d: (d / WHEEL).unlink(),
    "extra file": lambda d: (d / "memanga-0.5.1.tar.gz").write_bytes(b""),
    "corrupt sdist": lambda d: (d / SDIST).write_bytes(b"not a tar"),
    "corrupt wheel": lambda d: (d / WHEEL).write_bytes(b"not a zip"),
    "sdist without metadata": lambda d: _write_sdist(d / SDIST, top="other"),
    "wheel without metadata": lambda d: _write_wheel(d / WHEEL, info="other.dist-info"),
    "sdist of another project": lambda d: _write_sdist(
        d / SDIST, metadata=_metadata(name="other")),
    "wheel of another project": lambda d: _write_wheel(
        d / WHEEL, metadata=_metadata(name="other")),
    "sdist of another version": lambda d: _write_sdist(
        d / SDIST, metadata=_metadata(version="0.4.4")),
    "wheel of another version": lambda d: _write_wheel(
        d / WHEEL, metadata=_metadata(version="0.4.4")),
    "repeated version": lambda d: _write_wheel(
        d / WHEEL, metadata=_metadata(extra="Version: 0.4.4\n")),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_wrong_packages_fail(gate, repo, dist, output, capsys, case):
    BROKEN[case](dist)
    assert gate.main(["v0.5.0", repo.on_main, str(dist)]) == 1
    assert "error:" in capsys.readouterr().err
    assert not output.exists()
