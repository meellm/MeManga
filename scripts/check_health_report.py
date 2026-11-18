#!/usr/bin/env python3
"""Tell failing sources from a broken scraper health run.

  python scripts/check_health_report.py health.json <pytest exit code>

The scraper health workflow runs the live probes, then this. A source
that is down, blocks the runner or changed its pages fails its probe,
and pytest exits 1; health.json holds a DEAD, HTTP_ERROR or STALE row
for it. That is what the run is for, so it is listed, not fatal.

It exits 1, failing the run, when the probes did not run or report:
pytest exited with anything but 0 or 1 (interrupted, collection or
internal error, usage error, no tests), health.json is missing,
unreadable or holds no rows, or pytest counted a different number of
failed tests than the report has failing sources, which means some
test failed for another reason than its source.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The statuses of a source whose probe fails (tests/scrapers/live/_helpers.py).
FAILING = ("DEAD", "HTTP_ERROR", "STALE")


def problems(report: object, exit_code: int) -> list[str]:
    """Why the run is broken; empty when only sources failed."""
    if exit_code not in (0, 1):
        return [f"pytest exited {exit_code}: the probes did not complete"]
    if not isinstance(report, dict):
        return ["the health report is not a JSON object"]
    results = report.get("results")
    counts = report.get("pytest")
    summary = report.get("summary")
    if not isinstance(results, list) or not isinstance(counts, dict) \
            or not isinstance(summary, dict):
        return ["the health report has no results, pytest counts or summary"]
    if not results:
        return ["the health report has no results: no probe recorded one"]
    out = []
    if summary.get("total") != len(results):
        out.append(f"the summary counts {summary.get('total')} results, "
                   f"the report has {len(results)}")
    if counts.get("exitstatus") != exit_code:
        out.append(f"pytest exited {exit_code}, the report says "
                   f"{counts.get('exitstatus')}")
    failing = sum(1 for r in results if r.get("status") in FAILING)
    if counts.get("failed") != failing:
        out.append(f"pytest counted {counts.get('failed')} failed tests, the "
                   f"report has {failing} failing sources: a test failed for "
                   "another reason than its source")
    return out


def failing_sources(report: dict) -> list[str]:
    return sorted(f"{r.get('domain')}: {r.get('status')}"
                  + (f" at {r['stage']}" if r.get("stage") else "")
                  for r in report["results"] if r.get("status") in FAILING)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or not argv[1].lstrip("-").isdigit():
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
    lines = [f"{len(report['results'])} probe results, "
             f"{len(failed)} failing sources (details in health.json)"]
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
