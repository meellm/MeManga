"""The data files reference page matches the state and export code
(issue #273).

These tests check what the page says, not the state file itself.
"""

import json
import re
from pathlib import Path

import pytest

from memanga import backup
from memanga.schema import STATE_SCHEMA_VERSION
from memanga.state_stores.activity import ActivityStore
from memanga.state_stores.notifications import NotificationStore

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "reference" / "state.md"

# Top-level keys that State writes only when first needed.
LATER_TOP_LEVEL = {"search_history"}
# Per-series keys that are written outside the import checks.
OTHER_SERIES_FIELDS = {"catalogue_baseline", "suspicious_batch"}


@pytest.fixture(scope="module")
def page():
    return PAGE.read_text(encoding="utf-8")


def _section(page, heading):
    """Text from ``heading`` up to the next heading of the same or a
    higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = page.index(heading + "\n")
    rest = page[start + len(heading):]
    stop = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[:stop.start()] if stop else rest


def _row_fields(text):
    """Field names in the first column of the tables in ``text``."""
    fields = set()
    for line in text.splitlines():
        if line.startswith("| `"):
            first = line.split("|")[1]
            fields.update(re.findall(r"`([a-z_]+)`", first))
    return fields


def _row(text, field):
    for line in text.splitlines():
        if line.startswith(f"| `{field}`"):
            return line
    raise AssertionError(f"no table row for {field}")


def _example(page):
    blocks = re.findall(r"```json\n(.*?)```", _section(page, "## Export and import"),
                        re.DOTALL)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def test_headings_are_plain_text(page):
    # The permalink label of a heading repeats its source text.
    headings = re.findall(r"^#+ .*$", page, re.MULTILINE)
    assert headings
    for heading in headings:
        assert not re.search(r"[`*<>{}\[\]]", heading), heading


def test_top_level_table_lists_every_state_key(page, state):
    documented = _row_fields(_section(page, "### Top level"))
    assert documented == set(state._default_state()) | LATER_TOP_LEVEL


def test_series_tables_list_every_series_field(page):
    documented = _row_fields(_section(page, "### Each series"))
    assert documented == set(backup._STATE_FIELD_CHECKS) | OTHER_SERIES_FIELDS


def test_new_entry_sentence_names_the_fields_of_a_new_entry(page, state):
    with state._lock:
        state._ensure_manga_entry("Example Series")
    entry = state._data["manga"]["Example Series"]
    sentence = re.search(r"A new entry has (.*?); the other fields",
                         _section(page, "### Each series"), re.DOTALL).group(1)
    assert set(re.findall(r"`([a-z_]+)`", sentence)) == set(entry)


@pytest.mark.parametrize("field, limit", [
    ("check_history", ActivityStore.MAX_CHECKS),
    ("download_history", ActivityStore.MAX_DOWNLOADS),
    ("notifications", NotificationStore.MAX_NOTIFICATIONS),
])
def test_history_limits_match_the_stores(page, field, limit):
    row = _row(_section(page, "### Top level"), field)
    assert f"The newest {limit} are kept." in row


def test_error_details_limit_matches_the_store(page):
    row = _row(_section(page, "## Files in the config folder"), "error-details/")
    assert f"newest {NotificationStore.MAX_DETAIL_FILES} of them" in row


def test_version_numbers_match_the_code(page):
    assert f"For `state.json` it is currently `{STATE_SCHEMA_VERSION}`." in page
    assert (f"It is `{backup.EXPORT_VERSION}`"
            in _row(_section(page, "### Export"), "version"))
    assert _example(page)["version"] == backup.EXPORT_VERSION


def test_export_example_passes_the_import_checks(page):
    data = backup.validate_backup(_example(page))
    manga, state = backup.validate_backup_contents(data)
    assert [entry["title"] for entry in manga] == list(state)
    assert backup.merge_backup_state({}, state) == state


def test_merge_table_names_only_checked_fields(page):
    named = _row_fields(_section(page, "### Import and merge"))
    assert named
    assert named <= set(backup._STATE_FIELD_CHECKS)
