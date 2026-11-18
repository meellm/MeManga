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
SUMMARY_TEST = "tests/scrapers/live/test_live_parsing.py::test_zzz_health_summary_report"


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


def _test(i):
    return f"tests/scrapers/live/test_live_reachability.py::test_probe[site{i}.test]"


def _report(check, statuses, extra_failures=(), exitstatus=None):
    """A report as the probes write it: one row per probe test, a failed
    call phase for each failing source, plus the summary test."""
    results = [{"domain": f"site{i}.test", "status": s,
                "stage": "" if s == "OK" else "reachability",
                "detail": "", "elapsed_ms": 0.0, "extra": {}, "test": _test(i)}
               for i, s in enumerate(statuses)]
    failures = [{"test": r["test"], "when": "call"}
                for r in results if r["status"] in check.FAILING]
    failures += list(extra_failures)
    summary = {"total": len(results)}
    for status, key in check.STATUSES.items():
        summary[key] = statuses.count(status)
    ran = len(results) + 1
    return {"summary": summary, "failures_by_stage": {},
            "pytest": {"exitstatus": (1 if failures else 0) if exitstatus is None
                       else exitstatus,
                       "collected": ran, "ran": ran, "failed": len(failures),
                       "failures": failures},
            "results": results}


def test_statuses_are_the_probe_statuses(check):
    helpers = _load("memanga_live_helpers", LIVE / "_helpers.py")
    statuses = {v for k, v in vars(helpers).items() if k.startswith("STATUS_")}
    assert set(check.STATUSES) == statuses
    not_failing = {helpers.STATUS_OK, helpers.STATUS_SKIP, helpers.STATUS_PROTECTED}
    assert set(check.FAILING) == statuses - not_failing


def test_failing_sources_are_not_a_broken_run(check):
    report = _report(check, ["OK", "DEAD", "HTTP_ERROR", "STALE", "PROTECTED"])
    assert check.problems(report, 1) == []
    assert check.problems(_report(check, ["OK", "PROTECTED", "SKIP"]), 0) == []


@pytest.mark.parametrize("code", [2, 3, 4, 5])
def test_pytest_errors_fail_the_run(check, code):
    # Interrupted / collection errors, internal error, usage error, no tests.
    report = _report(check, ["OK"], exitstatus=code)
    assert "did not complete" in check.problems(report, code)[0]


def _broken(check, report, code, fragment):
    found = check.problems(report, code)
    assert any(fragment in p for p in found), found


def test_a_test_failing_without_its_source_row_fails_the_run(check):
    # A crash before the row was recorded.
    report = _report(check, ["OK"], [{"test": _test(7), "when": "call"}])
    _broken(check, report, 1, "failed without recording a source failure")


@pytest.mark.parametrize("when", ["setup", "teardown"])
def test_a_fixture_error_fails_the_run_even_when_counts_match(check, when):
    # The failing source's row and call failure are there; a fixture of
    # another test broke. Counting failures alone would not tell.
    report = _report(check, ["DEAD", "OK"], [{"test": _test(1), "when": when}])
    _broken(check, report, 1, f"failed in {when}")
    # The same error right after the failing source's own row.
    report = _report(check, ["DEAD"], [{"test": _test(0), "when": when}])
    _broken(check, report, 1, f"failed in {when}")


def test_a_failing_row_whose_test_passed_fails_the_run(check):
    report = _report(check, ["STALE"])
    report["pytest"].update(failures=[], failed=0, exitstatus=0)
    _broken(check, report, 0, "recorded a source failure but did not fail")


def test_one_test_records_one_row(check):
    report = _report(check, ["OK", "OK"])
    report["results"][1]["test"] = report["results"][0]["test"]
    _broken(check, report, 0, "recorded 2 results")


@pytest.mark.parametrize("change, fragment", [
    (lambda r: r["results"][0].update(status="invented"), "unknown status"),
    (lambda r: r["results"][0].pop("domain"), "names no domain"),
    (lambda r: r["results"][0].update(domain=" "), "names no domain"),
    (lambda r: r["results"][0].pop("test"), "names no domain or test"),
    (lambda r: r["results"].append("row"), "is not an object"),
    (lambda r: r["pytest"].pop("collected"), "pytest.collected"),
    (lambda r: r["pytest"].update(ran="3"), "pytest.ran"),
    (lambda r: r["pytest"].update(failed=True), "pytest.failed"),
    (lambda r: r["pytest"].update(failures=[{"test": "x", "when": "later"}]),
     "pytest.failures"),
    (lambda r: r["summary"].pop("stale"), "summary.stale"),
], ids=["status", "no-domain", "blank-domain", "no-test", "row-type",
        "collected", "ran-type", "failed-bool", "phase", "summary-key"])
def test_a_malformed_report_fails_the_run(check, change, fragment):
    report = _report(check, ["OK", "DEAD"])
    change(report)
    _broken(check, report, 1, fragment)


@pytest.mark.parametrize("report", [[], {}, None])
def test_a_report_that_is_not_one_fails_the_run(check, report):
    assert check.problems(report, 0)


def test_an_empty_report_fails_the_run(check):
    report = _report(check, [])
    _broken(check, report, 0, "no results")


@pytest.mark.parametrize("change, code, fragment", [
    (lambda r: r["summary"].update(total=3), 0, "counts 3 results"),
    (lambda r: r["summary"].update(ok=0, dead=1), 0, "counts 0 OK"),
    (lambda r: r["pytest"].update(exitstatus=1), 0, "the report says 1"),
    (lambda r: r["pytest"].update(ran=1), 0, "collected 3 tests and ran 1"),
    (lambda r: r["pytest"].update(collected=0, ran=0), 0, "collected 0"),
    (lambda r: r["pytest"].update(failed=1), 0, "counted 1 failures"),
    (lambda r: r["pytest"].update(exitstatus=1), 1, "exited 1 with 0 failures"),
], ids=["total", "per-status", "exitstatus", "not-all-ran", "none-collected",
        "failed-count", "exit-without-failures"])
def test_report_must_agree_with_itself_and_pytest(check, change, code, fragment):
    report = _report(check, ["OK", "OK"])
    change(report)
    _broken(check, report, code, fragment)


def test_main_lists_failing_sources_and_passes(check, tmp_path, monkeypatch, capsys):
    path = tmp_path / "health.json"
    path.write_text(json.dumps(_report(check, ["OK", "STALE"])), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert check.main([str(path), "1"]) == 0
    out = capsys.readouterr().out
    assert "site1.test: STALE at reachability" in out
    assert "::warning::1 sources failed" in out
    assert "site1.test: STALE" in summary.read_text(encoding="utf-8")


def test_main_reports_every_problem_as_an_error(check, tmp_path, capsys):
    path = tmp_path / "health.json"
    report = _report(check, ["OK"])
    report["results"][0]["status"] = "invented"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert check.main([str(path), "0"]) == 1
    assert "::error::result 0 (site0.test) has an unknown status" in (
        capsys.readouterr().out)


@pytest.mark.parametrize("args", [["missing.json", "0"], ["missing.json", "3"]])
def test_main_fails_without_a_report(check, tmp_path, monkeypatch, capsys, args):
    monkeypatch.chdir(tmp_path)
    assert check.main(args) == 1
    assert "::error::cannot read the health report" in capsys.readouterr().out


@pytest.mark.parametrize("code", ["", "-1", "one"])
def test_main_rejects_a_missing_exit_code(check, code):
    assert check.main(["health.json", code]) == 2


# ─── The report the live probes' conftest writes ────────────────────────

def _run(live, tmp_path, probes, phases=(), exitstatus=1):
    """Feed the conftest what pytest would: each probe records its row in
    its call phase, then every phase is reported; finish the session."""
    from _helpers import HealthResult
    path = tmp_path / "health.json"
    for store in (live._RESULTS, live._RESULT_TESTS, live._FAILURES):
        store.clear()
    live._TESTS.clear()
    try:
        for test, row, outcome in probes:
            if row is not None:
                live._record(test, HealthResult(*row))
            for when in ("setup", "call", "teardown"):
                failed = (when == "call" and outcome == "failed") or (
                    (test, when) in phases)
                live.pytest_runtest_logreport(SimpleNamespace(
                    nodeid=test, when=when, failed=failed,
                    outcome="failed" if failed else "passed"))
        session = SimpleNamespace(
            config=SimpleNamespace(getoption=lambda name: str(path)),
            testscollected=len(probes), testsfailed=len(live._FAILURES))
        live.pytest_sessionfinish(session, exitstatus)
    finally:
        for store in (live._RESULTS, live._RESULT_TESTS, live._FAILURES):
            store.clear()
        live._TESTS.clear()
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_report_names_each_row_test_and_failed_phase(check, live, tmp_path):
    report = _run(live, tmp_path, [
        (_test(0), ("a.test", "OK"), "passed"),
        (_test(1), ("b.test", "DEAD", "reachability", "timed out"), "failed"),
        (SUMMARY_TEST, None, "passed"),
    ])
    assert report["pytest"] == {
        "exitstatus": 1, "collected": 3, "ran": 3, "failed": 1,
        "failures": [{"test": _test(1), "when": "call"}]}
    assert [r["test"] for r in report["results"]] == [_test(0), _test(1)]
    assert report["summary"]["dead"] == 1
    assert check.problems(report, 1) == []


def test_live_report_shows_a_teardown_error_after_a_source_row(check, live, tmp_path):
    report = _run(live, tmp_path, [
        (_test(0), ("a.test", "STALE", "search"), "failed"),
        (SUMMARY_TEST, None, "passed"),
    ], phases={(_test(0), "teardown")})
    assert report["pytest"]["failures"] == [
        {"test": _test(0), "when": "call"}, {"test": _test(0), "when": "teardown"}]
    assert any("failed in teardown" in p for p in check.problems(report, 1))


def test_live_report_is_written_without_results(check, live, tmp_path):
    report = _run(live, tmp_path, [(_test(0), None, "failed")])
    assert report["results"] == []
    assert report["pytest"]["failed"] == 1
    assert check.problems(report, 1)


# ─── Which scraper errors count as a failing source ─────────────────────

def _wrapped(outer, cause):
    try:
        raise outer from cause
    except type(outer) as e:
        return e


def _while_handling(outer, context):
    """`outer` raised inside `except` of `context`, without `from`: the
    implicit context, as requests raises its errors over urllib3's."""
    try:
        try:
            raise context
        except type(context):
            raise outer
    except type(outer) as e:
        return e


def _expected_errors():
    """name -> (error, the status its source row gets)."""
    import socket

    import requests
    import urllib3
    from cloudscraper.exceptions import CloudflareChallengeError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    from memanga.scrapers.mangafire import MangaFireError
    from memanga.scrapers.mangapark import MangaParkSourceError
    from memanga.scrapers.playwright_base import BrowserTimeoutError
    from memanga.scrapers.weebcentral import (WeebCentralChallengeError,
                                              WeebCentralError)
    dead, http, stale = "STATUS_DEAD", "STATUS_HTTP_ERROR", "STATUS_STALE"
    pool = urllib3.HTTPConnectionPool("site.test")
    return {
        # What the probes have seen from real sources.
        "mangafire": (MangaFireError("MangaFire returned HTTP 403"), stale),
        "weebcentral": (WeebCentralChallengeError("page list failed"), stale),
        "page-wait": (PlaywrightTimeoutError("Page.wait_for_selector: Timeout"), stale),
        "budget": (BrowserTimeoutError("too little time left"), stale),
        "not-json": (json.JSONDecodeError("Expecting value", "<html>", 0), stale),
        "redirects": (requests.exceptions.TooManyRedirects("too many"), stale),
        "cloudflare": (CloudflareChallengeError("challenge"), stale),
        "mangapark-http": (MangaParkSourceError("HTTP 503 for https://mangapark1.com/x"), stale),
        "mangapark-no-response": (MangaParkSourceError("No response for https://mangapark1.com/x"), stale),
        "mangapark-challenge": (MangaParkSourceError(
            "Cloudflare challenge not cleared for https://mangapark1.com/x"), stale),
        "wrapped-timeout": (_wrapped(WeebCentralError("search failed"),
                                     PlaywrightTimeoutError("Timeout 20000ms")), stale),
        # Network and HTTP failures, as requests raises them (over
        # urllib3's error, implicitly) and as a wrapper naming the
        # network error it came from would.
        "dns": (socket.gaierror(-2, "Name or service not known"), dead),
        "refused": (_while_handling(
            requests.exceptions.ConnectionError("Max retries exceeded"),
            urllib3.exceptions.NewConnectionError(pool, "refused")), dead),
        "read-timeout": (_while_handling(
            requests.exceptions.ReadTimeout("Read timed out"),
            urllib3.exceptions.ReadTimeoutError(pool, "/", "Read timed out")), dead),
        "http-403": (requests.exceptions.HTTPError("403 Client Error"), http),
        "from-dns": (_wrapped(requests.exceptions.ConnectionError("lookup failed"),
                              socket.gaierror(-2, "Name or service not known")), dead),
        "from-reset": (_wrapped(requests.exceptions.ConnectionError("reset"),
                                ConnectionResetError(104, "reset by peer")), dead),
        "from-urllib3": (_wrapped(requests.exceptions.ConnectionError("pool"),
                                  urllib3.exceptions.ProtocolError("aborted")), dead),
        # Only an explicit cause is followed; requests' implicit context
        # (here even a bug's) is not.
        "context-not-followed": (_while_handling(
            requests.exceptions.ConnectionError("reset"), TypeError("bad")), dead),
    }


def _unexpected_errors():
    from playwright.sync_api import Error as PlaywrightError
    from playwright._impl._errors import TargetClosedError

    import socket

    import requests

    from memanga.first_run import BrowserSetupError
    from memanga.scrapers.weebcentral import WeebCentralError
    return {
        "type-error": TypeError("unsupported operand"),
        "attribute-error": AttributeError("'NoneType' object has no attribute 'text'"),
        "runtime-error": RuntimeError("Playwright not available"),
        "mangapark-no-chromium": RuntimeError(
            "MangaPark needs a Chromium-based browser (its Cloudflare check "
            "blocks Firefox)."),
        "value-error": ValueError("too many values to unpack"),
        "browser-closed": TargetClosedError(),
        "browser-error": PlaywrightError("Browser.new_context: crashed"),
        "browser-setup": BrowserSetupError("A browser MeManga needs is not installed"),
        "wrapped-crash": _wrapped(WeebCentralError("search failed"), TargetClosedError()),
        "wrapped-bug": _wrapped(WeebCentralError("search failed"), TypeError("bad")),
        # A network or HTTP error explicitly raised from a bug or a crash
        # is no more a source failure than a scraper error is.
        "connection-from-bug": _wrapped(
            requests.exceptions.ConnectionError("failed"), TypeError("bad")),
        "timeout-from-crash": _wrapped(
            requests.exceptions.Timeout("timed out"), TargetClosedError()),
        "http-from-bug": _wrapped(
            requests.exceptions.HTTPError("500"), AttributeError("no .status")),
        "dns-from-bug": _wrapped(
            socket.gaierror(-2, "unknown"), ValueError("bad host")),
        "deep-bug": _wrapped(
            WeebCentralError("search failed"),
            _wrapped(requests.exceptions.ConnectionError("failed"), TypeError("bad"))),
    }


@pytest.fixture(scope="module")
def helpers():
    return _load("memanga_live_helpers", LIVE / "_helpers.py")


class _Scraper:
    def __init__(self, error):
        self.error = error

    def search(self, query):
        raise self.error


@pytest.mark.parametrize("name", sorted(_expected_errors()))
def test_a_source_error_is_a_failing_source(helpers, name):
    error, status = _expected_errors()[name]
    pipe = helpers.ScraperPipeline(_Scraper(error), "site.test")
    with pytest.raises(helpers.StageFailure) as caught:
        pipe.search("one piece")
    assert caught.value.failed.status == getattr(helpers, status)
    assert caught.value.failed.stage == helpers.STAGE_SEARCH


@pytest.mark.parametrize("name", sorted(_unexpected_errors()))
def test_any_other_error_escapes_the_probe(helpers, name):
    # Not a source row: the test fails without one, which
    # check_health_report.py rejects as a broken run (below).
    error = _unexpected_errors()[name]
    pipe = helpers.ScraperPipeline(_Scraper(error), "site.test")
    with pytest.raises(type(error)) as caught:
        pipe.search("one piece")
    assert caught.value is error
    assert pipe.stages == []


def test_an_escaped_error_fails_the_run(check, live, tmp_path):
    # The probe that raised records no row and fails in its call phase.
    report = _run(live, tmp_path, [
        (_test(0), ("a.test", "STALE", "search"), "failed"),
        (_test(1), None, "failed"),
        (SUMMARY_TEST, None, "passed"),
    ])
    assert any(f"{_test(1)} failed without recording a source failure" in p
               for p in check.problems(report, 1))
    # Without it, the same run is only a failing source.
    report = _run(live, tmp_path, [
        (_test(0), ("a.test", "STALE", "search"), "failed"),
        (SUMMARY_TEST, None, "passed"),
    ])
    assert check.problems(report, 1) == []


# ─── A MangaPark source failing after search, end to end ────────────────

MANGAPARK = ROOT / "tests" / "scrapers" / "fixtures" / "mangapark"


def _mangapark(monkeypatch, routes):
    """The real MangaPark scraper fetching through its own
    _fetch_in_thread, on fake Chromium pages (tests/scrapers/test_mangapark.py)."""
    from memanga.scrapers.mangapark import MangaParkScraper
    fakes = _load("memanga_mangapark_fakes", ROOT / "tests" / "scrapers" / "test_mangapark.py")
    scraper = MangaParkScraper()
    found = {"/filter": fakes.FakeResponse(
        200, (MANGAPARK / "search.html").read_text(encoding="utf-8"))}
    found.update({part: fakes.FakeResponse(*answer) if answer else None
                  for part, answer in routes.items()})
    fakes.fake_browser(monkeypatch, scraper, found)
    return scraper


def _walk(helpers, scraper):
    pipe = helpers.ScraperPipeline(scraper, "mangapark1.com")
    results = pipe.search("one piece")
    chapters = pipe.chapters(results[0].url)
    pipe.pages(chapters[0])


@pytest.mark.parametrize("routes, stage, detail", [
    # The chapter list loads; the reader page answers 503.
    ({"/get-chapter-list": (200, (MANGAPARK / "chapter_list.json").read_text(
        encoding="utf-8")), "/read/": (503,)},
     "pages", "HTTP 503 for https://mangapark1.com/read/one-piece/"),
    # The chapter-list endpoint fails, and so does the manga page it
    # falls back to.
    ({"/get-chapter-list": (503,), "/manga/": None},
     "chapters", "No response for https://mangapark1.com/manga/one-piece"),
], ids=["pages", "chapters"])
def test_a_later_mangapark_source_failure_is_a_failing_source(
        check, live, helpers, tmp_path, monkeypatch, routes, stage, detail):
    scraper = _mangapark(monkeypatch, routes)
    with pytest.raises(helpers.StageFailure) as caught:
        _walk(helpers, scraper)
    failed = caught.value.failed
    assert (failed.stage, failed.status) == (stage, helpers.STATUS_STALE)
    assert detail in failed.detail
    assert [s.status for s in caught.value.stages[:-1]] == [helpers.STATUS_OK] * (
        len(caught.value.stages) - 1)
    # The probe records that row, then fails: the run passes with it
    # listed as a failing source.
    report = _run(live, tmp_path, [
        (_test(0), ("mangapark1.com", failed.status, failed.stage, failed.detail),
         "failed"),
        (SUMMARY_TEST, None, "passed"),
    ])
    assert check.problems(report, 1) == []
    assert check.failing_sources(report) == [f"mangapark1.com: STALE at {stage}"]


def test_a_mangapark_runner_failure_still_fails_the_run(
        check, live, helpers, tmp_path, monkeypatch):
    # Search and chapters load; then the runner has no Chromium for the
    # reader page: a plain RuntimeError, not the source. (MangaPark's
    # search swallows its own fetch errors, so the failure comes later.)
    scraper = _mangapark(monkeypatch, {
        "/get-chapter-list": (200, (MANGAPARK / "chapter_list.json").read_text(
            encoding="utf-8"))})
    fetch = scraper._get_html

    def no_browser_for_pages(url):
        if "/read/" in url:
            raise RuntimeError("MangaPark needs a Chromium-based browser")
        return fetch(url)
    monkeypatch.setattr(scraper, "_get_html", no_browser_for_pages)
    with pytest.raises(RuntimeError, match="Chromium-based browser") as caught:
        _walk(helpers, scraper)
    assert type(caught.value) is RuntimeError
    report = _run(live, tmp_path, [
        (_test(0), None, "failed"),
        (SUMMARY_TEST, None, "passed"),
    ])
    assert any("failed without recording a source failure" in p
               for p in check.problems(report, 1))
