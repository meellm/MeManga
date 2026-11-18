"""The scraper health run fails on a broken run, not on failing sources:
scripts/check_health_report.py and the report the live probes write."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_health_report.py"
LIVE = ROOT / "tests" / "scrapers" / "live"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check():
    return _load("memanga_check_health_report", SCRIPT)


@pytest.fixture(scope="module")
def live():
    """The live probes' conftest, which writes health.json."""
    return _load("memanga_live_conftest", LIVE / "conftest.py")


def _report(statuses, failed, exitstatus=None):
    results = [{"domain": f"site{i}.test", "status": s,
                "stage": "" if s == "OK" else "reachability",
                "detail": "", "elapsed_ms": 0.0, "extra": {}}
               for i, s in enumerate(statuses)]
    if exitstatus is None:
        exitstatus = 1 if failed else 0
    return {"summary": {"total": len(results)}, "failures_by_stage": {},
            "pytest": {"exitstatus": exitstatus, "collected": len(results),
                       "failed": failed},
            "results": results}


def test_failing_statuses_are_the_probe_failures(check):
    helpers = _load("memanga_live_helpers", LIVE / "_helpers.py")
    not_failing = {helpers.STATUS_OK, helpers.STATUS_SKIP, helpers.STATUS_PROTECTED}
    statuses = {v for k, v in vars(helpers).items() if k.startswith("STATUS_")}
    assert set(check.FAILING) == statuses - not_failing


def test_failing_sources_are_not_a_broken_run(check):
    report = _report(["OK", "DEAD", "HTTP_ERROR", "STALE", "PROTECTED"], failed=3)
    assert check.problems(report, 1) == []
    assert check.problems(_report(["OK", "PROTECTED"], failed=0), 0) == []


@pytest.mark.parametrize("code", [2, 3, 4, 5])
def test_pytest_errors_fail_the_run(check, code):
    # Interrupted / collection errors, internal error, usage error, no tests.
    report = _report(["OK"], failed=0, exitstatus=code)
    assert "did not complete" in check.problems(report, code)[0]


def test_a_test_failing_without_a_source_row_fails_the_run(check):
    # A fixture error or a crash before the row was recorded.
    found = check.problems(_report(["OK", "DEAD"], failed=2), 1)
    assert any("another reason than its source" in p for p in found)
    # A failing source row while pytest reports no failure.
    assert check.problems(_report(["DEAD"], failed=0, exitstatus=0), 0)


@pytest.mark.parametrize("report", [
    [],
    {},
    {"summary": {"total": 0}, "pytest": {"exitstatus": 0, "failed": 0},
     "results": []},
])
def test_an_empty_or_malformed_report_fails_the_run(check, report):
    assert check.problems(report, 0)


def test_report_must_agree_with_pytest(check):
    report = _report(["OK"], failed=0)
    report["summary"]["total"] = 2
    assert check.problems(report, 0)
    assert check.problems(_report(["OK"], failed=0, exitstatus=1), 0)


def test_main_lists_failing_sources_and_passes(check, tmp_path, monkeypatch, capsys):
    path = tmp_path / "health.json"
    path.write_text(json.dumps(_report(["OK", "STALE"], failed=1)), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert check.main([str(path), "1"]) == 0
    out = capsys.readouterr().out
    assert "site1.test: STALE at reachability" in out
    assert "::warning::1 sources failed" in out
    assert "site1.test: STALE" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("args", [["missing.json", "0"], ["missing.json", "3"]])
def test_main_fails_without_a_report(check, tmp_path, monkeypatch, capsys, args):
    monkeypatch.chdir(tmp_path)
    assert check.main(args) == 1
    assert "::error::cannot read the health report" in capsys.readouterr().out


def test_main_rejects_a_missing_exit_code(check):
    assert check.main(["health.json", ""]) == 2


def _finish(live, tmp_path, rows, failed, exitstatus):
    path = tmp_path / "health.json"
    session = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: str(path)),
        testscollected=len(rows) + 1, testsfailed=failed)
    live._RESULTS[:] = rows
    try:
        live.pytest_sessionfinish(session, exitstatus)
    finally:
        live._RESULTS.clear()
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_report_carries_what_pytest_counted(check, live, tmp_path):
    from _helpers import HealthResult
    rows = [HealthResult("a.test", "OK"),
            HealthResult("b.test", "DEAD", "reachability", "timed out")]
    report = _finish(live, tmp_path, rows, failed=1, exitstatus=1)
    assert report["pytest"] == {"exitstatus": 1, "collected": 3, "failed": 1}
    assert report["summary"]["dead"] == 1
    assert check.problems(report, 1) == []


def test_live_report_is_written_without_results(check, live, tmp_path):
    report = _finish(live, tmp_path, [], failed=2, exitstatus=1)
    assert report["results"] == []
    assert report["pytest"]["failed"] == 2
    assert check.problems(report, 1)
