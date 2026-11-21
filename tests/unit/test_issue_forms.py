"""#279: the GitHub issue forms and the template chooser: the rules of
GitHub's form schema that an edit can break, and the fields triage needs."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

TEMPLATES = Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE"
LABELS = {"bug_report": "bug", "feature_request": "enhancement",
          "scraper_broken": "scraper"}
# What a report of something broken cannot be triaged without.
REPORT_FIELDS = {"actual", "expected", "action", "version", "os", "install",
                 "logs"}
INPUT_TYPES = {"input", "textarea", "dropdown", "checkboxes"}


def _load(name):
    return yaml.safe_load((TEMPLATES / f"{name}.yml").read_text(encoding="utf-8"))


def _fields(form):
    return [e for e in form["body"] if e["type"] != "markdown"]


def _required(form):
    return {e["id"] for e in _fields(form)
            if e.get("validations", {}).get("required")}


def test_each_template_is_a_form_with_no_markdown_twin():
    # A leftover .md would show the same report twice in the chooser.
    assert sorted(p.name for p in TEMPLATES.iterdir()) == sorted(
        ["config.yml", *(f"{name}.yml" for name in LABELS)])


@pytest.mark.parametrize("name,label", LABELS.items())
def test_form_follows_the_schema(name, label):
    form = _load(name)
    assert len(form["name"]) > 3 and form["description"]
    assert form["labels"] == [label]
    assert "assignees" not in form

    fields = _fields(form)
    assert fields
    ids = [e["id"] for e in fields]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids)
    titles = [e["attributes"]["label"] for e in fields]
    assert len(titles) == len(set(titles))
    for element in fields:
        assert element["type"] in INPUT_TYPES
        if element["type"] == "dropdown":
            options = element["attributes"]["options"]
            assert options and len(options) == len(set(options))
    for element in form["body"]:
        if element["type"] == "markdown":
            assert "validations" not in element and "id" not in element


def test_form_names_are_unique():
    assert len({_load(name)["name"] for name in LABELS}) == len(LABELS)


@pytest.mark.parametrize("name", ["bug_report", "scraper_broken"])
def test_problem_reports_require_what_triage_needs(name):
    form = _load(name)
    assert REPORT_FIELDS <= _required(form)
    # Required, but someone without a log can say so.
    (logs,) = [e for e in _fields(form) if e["id"] == "logs"]
    assert "`none`" in logs["attributes"]["description"]


def test_scraper_report_never_requires_running_a_probe():
    form = _load("scraper_broken")
    assert {"source", "page", "problem"} <= _required(form)
    assert "probe" not in _required(form)


def test_feature_request_asks_for_no_environment():
    assert _required(_load("feature_request")) == {"problem", "solution"}
    ids = {e["id"] for e in _fields(_load("feature_request"))}
    assert not ids & {"version", "os", "install", "logs"}


def test_chooser_keeps_blank_issues_and_routes_support_and_security():
    config = _load("config")
    assert config["blank_issues_enabled"] is True
    links = config["contact_links"]
    assert all(link["name"] and link["about"]
               and link["url"].startswith("https://") for link in links)
    urls = {link["url"] for link in links}
    assert "https://github.com/meellm/MeManga/discussions" in urls
    assert "https://github.com/meellm/MeManga/security/policy" in urls
