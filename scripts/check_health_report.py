#!/usr/bin/env python3
"""Tell failing sources from a broken scraper health run.

  python scripts/check_health_report.py health.json <pytest exit code>

The scraper health workflow runs the live probes, then this. A source
that is down, blocks the runner or changed its pages fails its probe,
and pytest exits 1: the probe records one DEAD, HTTP_ERROR or STALE row
in health.json, then fails in its call phase. That is what the run is
for, so it is listed, not fatal.

It exits 1, failing the run, when the probes did not run or report:
pytest exited with anything but 0 or 1 (interrupted, collection or
internal error, usage error, no tests); health.json is missing,
unreadable, malformed, holds no rows or disagrees with itself or with
pytest; not every collected test ran; or a test failed other than by
its source failing (a fixture or teardown error, a crash before or
after its row, a failing row whose test passed).
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

# The row statuses (tests/scrapers/live/_helpers.py), and the summary
# key that counts each.
STATUSES = {"OK": "ok", "DEAD": "dead", "PROTECTED": "protected",
            "HTTP_ERROR": "http_error", "STALE": "stale", "SKIP": "skip"}
# The statuses of a source whose probe fails.
FAILING = ("DEAD", "HTTP_ERROR", "STALE")
PHASES = ("setup", "call", "teardown")


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _name(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _shape(report) -> list[str]:
    """What is missing or of the wrong type; empty when well formed."""
    if not isinstance(report, dict):
        return ["the health report is not a JSON object"]
    summary, counts, results = (report.get(k) for k in ("summary", "pytest", "results"))
    if not (isinstance(summary, dict) and isinstance(counts, dict)
            and isinstance(results, list)):
        return ["the health report has no summary, pytest counts or results"]
    out = [f"summary.{key} is not a count"
           for key in ("total", *STATUSES.values()) if not _count(summary.get(key))]
    out += [f"pytest.{key} is not a count"
            for key in ("exitstatus", "collected", "ran", "failed")
            if not _count(counts.get(key))]
    failures = counts.get("failures")
    if not isinstance(failures, list) or not all(
            isinstance(f, dict) and _name(f.get("test")) and f.get("when") in PHASES
            for f in failures):
        out.append("pytest.failures is not a list of failed test phases")
    for i, row in enumerate(results):
        if not isinstance(row, dict):
            out.append(f"result {i} is not an object")
        elif not (_name(row.get("domain")) and _name(row.get("test"))):
            out.append(f"result {i} names no domain or test")
        elif row.get("status") not in STATUSES:
            out.append(f"result {i} ({row['domain']}) has an unknown status "
                       f"{row.get('status')!r}")
    return out


def problems(report: object, exit_code: int) -> list[str]:
    """Why the run is broken; empty when only sources failed."""
    if exit_code not in (0, 1):
        return [f"pytest exited {exit_code}: the probes did not complete"]
    out = _shape(report)
    if out:
        return out
    summary, counts, results = report["summary"], report["pytest"], report["results"]
    if not results:
        return ["the health report has no results: no probe recorded one"]

    statuses = Counter(row["status"] for row in results)
    if summary["total"] != len(results):
        out.append(f"the summary counts {summary['total']} results, "
                   f"the report has {len(results)}")
    for status, key in STATUSES.items():
        if summary[key] != statuses[status]:
            out.append(f"the summary counts {summary[key]} {status}, "
                       f"the report has {statuses[status]}")
    if counts["exitstatus"] != exit_code:
        out.append(f"pytest exited {exit_code}, the report says {counts['exitstatus']}")
    if counts["collected"] == 0 or counts["ran"] != counts["collected"]:
        out.append(f"pytest collected {counts['collected']} tests and ran "
                   f"{counts['ran']}")

    failures = counts["failures"]
    if counts["failed"] != len(failures):
        out.append(f"pytest counted {counts['failed']} failures, the report "
                   f"lists {len(failures)}")
    if (exit_code == 1) != bool(failures):
        out.append(f"pytest exited {exit_code} with {len(failures)} failures")
    for failure in failures:
        if failure["when"] != "call":
            out.append(f"{failure['test']} failed in {failure['when']}")

    # One row per probe; tests that probe nothing (the summary) record none.
    rows = Counter(row["test"] for row in results)
    out += [f"{test} recorded {n} results" for test, n in rows.items() if n > 1]
    if len(rows) > counts["ran"]:
        out.append(f"{len(rows)} tests recorded results, pytest ran {counts['ran']}")
    failed = {f["test"] for f in failures if f["when"] == "call"}
    failing = {row["test"] for row in results if row["status"] in FAILING}
    out += [f"{test} failed without recording a source failure"
            for test in sorted(failed - failing)]
    out += [f"{test} recorded a source failure but did not fail"
            for test in sorted(failing - failed)]
    return out


def failing_sources(report: dict) -> list[str]:
    return sorted(f"{r['domain']}: {r['status']}"
                  + (f" at {r['stage']}" if r.get("stage") else "")
                  for r in report["results"] if r["status"] in FAILING)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or not argv[1].isdigit():
        print("usage: check_health_report.py <health.json> <pytest exit code>",
              file=sys.stderr)
        return 2
    path, exit_code = Path(argv[0]), int(argv[1])
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        found = [f"cannot read the health report {path}: {e}"]
        if exit_code not in (0, 1):
            found += problems(None, exit_code)
    else:
        found = problems(report, exit_code)
    if found:
        for problem in found:
            print(f"::error::{problem}")
        return 1

    failed = failing_sources(report)
    lines = [f"{len(report['results'])} probe results from "
             f"{report['pytest']['ran']} tests, {len(failed)} failing sources "
             "(details in health.json)"]
    lines += [f"- {source}" for source in failed]
    print("\n".join(lines))
    if failed:
        print(f"::warning::{len(failed)} sources failed their probes; "
              "see the run summary and health.json")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Scraper health\n\n" + "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
