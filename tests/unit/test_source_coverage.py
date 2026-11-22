"""`memanga sources` reads parser test and live probe facts from a
packaged, generated module, never from the tests (issue #266)."""

import ast
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from memanga import source_docs
from memanga.scrapers import coverage_data
from memanga.scrapers.catalog import source_catalog, source_coverage

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / source_docs.COVERAGE_MODULE


def test_missing_and_partial_entries():
    tests = {"a.example": {"own": ("search",), "shared": ()},
             "b.example": {"shared": ("pages",)}}
    probes = {"a.example": ("search", "chapters"), "c.example": ()}
    assert source_coverage("a.example", tests, probes) == {
        "parser_tests": {"own": ["search"], "shared": []},
        "live_probe": ["search", "chapters"]}
    assert source_coverage("b.example", tests, probes) == {
        "parser_tests": {"own": [], "shared": ["pages"]},
        "live_probe": None}
    assert source_coverage("c.example", tests, probes) == {
        "parser_tests": {"own": [], "shared": []},
        "live_probe": []}
    assert source_coverage("unknown.example", tests, probes) == {
        "parser_tests": {"own": [], "shared": []},
        "live_probe": None}


def test_packaged_data_matches_the_generator():
    sources = source_catalog()
    tested = source_docs.source_parser_tests(
        sources, source_docs.parser_test_declarations(ROOT))
    probed = source_docs.source_probe_steps(
        sources, source_docs.pipeline_probe_steps(ROOT))
    assert coverage_data.PARSER_TESTS == {
        domain: {"own": mine, "shared": shared}
        for domain, (mine, shared) in tested.items()}
    assert coverage_data.LIVE_PROBE == probed
    assert MODULE.read_text(encoding="utf-8") == \
        source_docs.render_coverage_module(ROOT)


def test_every_entry_is_a_registered_source():
    domains = {source.domain for source in source_catalog()}
    assert set(coverage_data.PARSER_TESTS) <= domains
    assert set(coverage_data.LIVE_PROBE) <= domains


def test_packaged_data_is_plain_literals():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the docstring
        assert isinstance(node, ast.Assign), ast.dump(node)
        ast.literal_eval(node.value)
        names.extend(target.id for target in node.targets)
    assert names == ["PARSER_TESTS", "LIVE_PROBE"]


def test_runtime_modules_do_not_import_the_generator_or_tests():
    for path in (ROOT / "memanga").rglob("*.py"):
        if path.name in ("source_docs.py", "cli_docs.py", "config_docs.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            for name in names:
                assert "source_docs" not in name, path
                assert name.split(".")[0] not in ("tests", "pytest"), path


def test_package_discovery_ships_the_data_module():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    find = config["tool"]["setuptools"]["packages"]["find"]
    package = ".".join(Path(source_docs.COVERAGE_MODULE).parent.parts)
    assert any(fnmatch.fnmatch(package, pattern) for pattern in find["include"])
    assert not any(fnmatch.fnmatch(package, pattern)
                   for pattern in find.get("exclude", []))
    assert (MODULE.parent / "__init__.py").is_file()
    assert MODULE.suffix == ".py"


CHILD = r"""
import json, os, sys
root, config_dir = sys.argv[1], sys.argv[2]
tests_dir = os.path.join(root, "tests") + os.sep
seen = []

def hook(event, args):
    if event in ("open", "os.listdir", "os.scandir") and args:
        target = args[0]
        if isinstance(target, (str, bytes, os.PathLike)):
            if os.path.abspath(os.fsdecode(target)).startswith(tests_dir):
                seen.append(os.fsdecode(target))
    elif event == "import":
        name = args[0]
        if name in ("pytest", "memanga.source_docs") or name.split(".")[0] == "tests":
            seen.append(name)

sys.addaudithook(hook)
sys.argv = ["memanga", "--config-dir", config_dir, "sources", "--json"]
from memanga import cli
code = 0
try:
    cli.main()
except SystemExit as exc:
    code = exc.code or 0
sys.stdout.flush()
if seen:
    sys.stderr.write("used the tests or the generator: %r\n" % sorted(set(seen)))
    os._exit(3)
sys.exit(code)
"""


def test_sources_json_runs_without_the_tests_or_generator(tmp_path):
    env = dict(os.environ)
    env.update(HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "config"),
               XDG_DATA_HOME=str(tmp_path / "data"),
               XDG_CACHE_HOME=str(tmp_path / "cache"),
               PYTHONPATH=os.pathsep.join(
                   [str(ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])))
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(ROOT), str(tmp_path / "cfg")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    rows = {row["domain"]: row for row in json.loads(result.stdout)["sources"]}
    for domain, row in rows.items():
        assert {k: row[k] for k in ("parser_tests", "live_probe")} == \
            source_coverage(domain)
