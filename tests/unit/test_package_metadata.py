"""#215: package metadata follows the current packaging standards and the
version is set once, as `memanga.__version__`, which pyproject.toml reads
at build time."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

import memanga

tomllib = pytest.importorskip("tomllib")

ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/meellm/MeManga"


@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _notices():
    """Import packaging/third_party_notices.py by path under the name
    test_third_party_notices uses. The module must be in sys.modules while
    it runs: its @dataclass looks the module up there."""
    name = "memanga_third_party_notices"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "packaging" / "third_party_notices.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_version_is_read_from_the_package(pyproject):
    project = pyproject["project"]
    assert "version" not in project
    assert project["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "memanga.__version__"}


def test_package_version_is_a_plain_pep440_literal():
    # setuptools reads a literal assignment without importing the package.
    init = (ROOT / "memanga" / "__init__.py").read_text(encoding="utf-8")
    assert re.findall(r'^__version__\s*=\s*"([^"]+)"$', init, re.M) == [
        memanga.__version__]
    assert str(Version(memanga.__version__)) == memanga.__version__


def test_release_tag_check_uses_the_package_version():
    notices = _notices()
    assert notices._project_version(ROOT) == memanga.__version__
    assert notices.release_tag_problems(f"v{memanga.__version__}", ROOT) == []


def test_build_backend_supports_spdx_license_metadata(pyproject):
    system = pyproject["build-system"]
    assert system["build-backend"] == "setuptools.build_meta"
    (setuptools,) = [Requirement(r) for r in system["requires"]
                     if Requirement(r).name == "setuptools"]
    # PEP 639 `license` strings and `license-files` need setuptools >= 77.
    assert not setuptools.specifier.contains("76.9")
    assert setuptools.specifier.contains("77.0")


def test_license_is_an_spdx_expression_with_its_file(pyproject):
    project = pyproject["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    # A license classifier next to a license expression is rejected by PEP 639.
    assert not [c for c in project["classifiers"] if c.startswith("License ::")]


def test_authors_have_names_and_no_email(pyproject):
    authors = pyproject["project"]["authors"]
    assert authors and all(a.get("name") for a in authors)
    assert not [a for a in authors if "email" in a]


def test_keywords_are_unique(pyproject):
    keywords = pyproject["project"]["keywords"]
    assert "manga" in keywords
    assert len(keywords) == len(set(keywords))


def test_python_classifiers_match_requires_python(pyproject):
    project = pyproject["project"]
    supported = SpecifierSet(project["requires-python"])
    versions = [c.rsplit(" :: ", 1)[1] for c in project["classifiers"]
                if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)]
    assert versions
    assert all(supported.contains(f"{v}.0") for v in versions)
    # The lowest listed version is the requires-python floor.
    floor = min(Version(v) for v in versions)
    assert not supported.contains(f"{floor.major}.{floor.minor - 1}.0")
    assert "Programming Language :: Python :: 3 :: Only" in project["classifiers"]


def test_classifiers_are_unique(pyproject):
    classifiers = pyproject["project"]["classifiers"]
    assert len(classifiers) == len(set(classifiers))


def test_project_urls_point_at_the_repository(pyproject):
    urls = pyproject["project"]["urls"]
    for label in ("Homepage", "Documentation", "Repository", "Issues", "Changelog"):
        assert urls[label].startswith(REPO_URL)
    assert urls["Issues"] == f"{REPO_URL}/issues"
    # Linked files exist on the default branch.
    for label in ("Documentation", "Changelog"):
        path = urls[label].removeprefix(f"{REPO_URL}/blob/main/")
        assert (ROOT / path).is_file(), label


def test_docker_image_installs_the_package_unmodified():
    # #314: no installed file is deleted afterwards, the whole package is
    # in the build context, and pip check proves the pinned layer
    # satisfies pyproject.toml despite --no-deps.
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    flat = " ".join(text.replace("\\\n", " ").split())
    assert "rm -f /usr/local/bin" not in text
    assert "pip install --no-deps . && python -m pip check" in flat
    ignored = {line.strip().rstrip("/") for line in
               (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    assert not ignored & {"memanga", "memanga/gui"}


def test_docker_package_install_has_the_license_files(pyproject):
    # The image runs `pip install --no-deps .` on what it copied into the
    # working directory; license-files must be there by then.
    lines = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    install = next(i for i, line in enumerate(lines)
                   if "pip install --no-deps ." in line)
    copied = set()
    for line in lines[:install]:
        parts = line.split()
        if parts[:1] == ["COPY"] and parts[-1] == "./":
            copied.update(parts[1:-1])
    ignored = {line.strip() for line in
               (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    for name in pyproject["project"]["license-files"]:
        assert name in copied, name
        assert name not in ignored, name


def test_docker_image_runs_memanga_under_an_init():
    # #333: as PID 1, memanga never reaped the browser processes left
    # behind when a Playwright driver or browser exited early. tini is PID
    # 1 however the container is started; -s keeps it reaping when an
    # outer init (docker run --init) is PID 1 instead. No -g: signals go
    # to memanga only, whose own handlers stop the browsers.
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    flat = " ".join(text.replace("\\\n", " ").split())
    assert "apt-get install -y --no-install-recommends tini" in flat
    directives = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=1)
        if parts and parts[0] in ("ENTRYPOINT", "CMD"):
            directives[parts[0]] = json.loads(parts[1])
    assert directives["ENTRYPOINT"] == ["/usr/bin/tini", "-s", "--", "memanga"]
    assert directives["CMD"] == ["--help"]
