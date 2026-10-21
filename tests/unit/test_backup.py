"""Backup schema-version validation (issue #42).

Exports have stamped ``"version": 1`` since the feature shipped, but
the importers never read it — any file with a ``manga`` array was
imported blindly. ``validate_backup`` now gates every import: version 1
passes through, anything missing/malformed/newer is rejected with a
user-facing message, and older versions go through ``_MIGRATIONS``
(empty while EXPORT_VERSION == 1).
"""

from __future__ import annotations

import pytest

from memanga.backup import (
    EXPORT_VERSION,
    BackupVersionError,
    merge_backup_state,
    merge_manga_state,
    validate_backup,
    validate_backup_contents,
    _MIGRATIONS,
)


class TestValidateBackup:
    def test_current_version_passes_through(self):
        data = {"version": 1, "manga": [], "state": {}}
        assert validate_backup(data) is data

    def test_export_version_is_supported(self):
        # Whatever we export must round-trip through our own validator.
        assert validate_backup({"version": EXPORT_VERSION})["version"] == EXPORT_VERSION

    def test_missing_version_rejected(self):
        with pytest.raises(BackupVersionError, match="no version field"):
            validate_backup({"manga": []})

    def test_non_dict_rejected(self):
        for payload in ([], "x", 1, None):
            with pytest.raises(BackupVersionError, match="Not a MeManga backup"):
                validate_backup(payload)

    @pytest.mark.parametrize("bad", ["1", 1.0, True, [1], {}])
    def test_malformed_version_rejected(self, bad):
        with pytest.raises(BackupVersionError, match="Invalid backup version"):
            validate_backup({"version": bad, "manga": []})

    def test_non_dict_state_rejected(self):
        with pytest.raises(BackupVersionError, match="state must be an object"):
            validate_backup({"version": EXPORT_VERSION, "manga": [], "state": []})

    def test_newer_version_rejected_with_update_hint(self):
        with pytest.raises(BackupVersionError, match="newer.*update MeManga"):
            validate_backup({"version": EXPORT_VERSION + 1, "manga": []})

    def test_older_version_without_migration_rejected(self):
        # No version 0 ever existed, so nothing migrates from it.
        with pytest.raises(BackupVersionError, match="not supported"):
            validate_backup({"version": 0, "manga": []})

    def test_migration_chain_runs(self, monkeypatch):
        # Document how a future schema bump is expected to work: register
        # a step per old version and validate_backup walks the chain.
        monkeypatch.setitem(
            _MIGRATIONS, 0, lambda d: {**d, "version": 1, "migrated": True}
        )
        out = validate_backup({"version": 0, "manga": []})
        assert out["migrated"] is True


class TestMergeMangaState:
    def test_partial_chapters_preserve_imported_records_and_local_conflicts(self):
        local = {
            "partial_chapters": {
                "4": {"pages": ["local-1.jpg"], "error": "local"},
            }
        }
        imported = {
            "partial_chapters": {
                "4": {"pages": ["imported-1.jpg"], "error": "imported"},
                "5": {"pages": ["imported-2.jpg"], "error": "backup"},
            }
        }

        merged = merge_manga_state(local, imported)

        assert merged["partial_chapters"]["4"] == local["partial_chapters"]["4"]
        assert merged["partial_chapters"]["5"] == imported["partial_chapters"]["5"]

    def test_preserves_local_and_imported_progress_fields(self):
        local = {
            "downloaded": ["1", "3"],
            "read_chapters": ["1"],
            "external_chapters": ["7"],
            "failed_chapters": {
                "4": {"error": "local", "attempts": 2},
            },
            "available_chapters": [
                {"number": "1", "source": "local", "source_url": "local/1"},
            ],
            "reading_progress": {
                "last_chapter": "3",
                "last_read": "2026-07-17T09:00:00",
            },
            "new_chapters_available": 1,
        }
        imported = {
            "downloaded": ["2", "3"],
            "read_chapters": ["2"],
            "external_chapters": ["8"],
            "failed_chapters": {
                "4": {"error": "imported", "attempts": 1},
                "5": {"error": "backup", "attempts": 1},
            },
            "available_chapters": [
                {"number": "1", "source": "local", "source_url": "local/1"},
                {"number": "2", "source": "backup", "source_url": "backup/2"},
            ],
            "reading_progress": {
                "last_chapter": "5",
                "last_read": "2026-07-17T10:00:00",
            },
            "new_chapters_available": 4,
        }

        merged = merge_manga_state(local, imported)

        assert merged["downloaded"] == ["1", "2", "3"]
        assert merged["read_chapters"] == ["1", "2"]
        assert merged["external_chapters"] == ["7", "8"]
        assert merged["failed_chapters"]["4"]["error"] == "local"
        assert merged["failed_chapters"]["5"]["error"] == "backup"
        assert merged["available_chapters"] == [
            {"number": "1", "source": "local", "source_url": "local/1"},
            {"number": "2", "source": "backup", "source_url": "backup/2"},
        ]
        assert merged["reading_progress"]["last_chapter"] == "5"
        assert merged["new_chapters_available"] == 4

    def test_merge_backup_state_adds_new_titles(self):
        merged = merge_backup_state(
            {"Local": {"downloaded": ["1"]}},
            {
                "Local": {"downloaded": ["2"]},
                "Imported": {"read_chapters": ["9"]},
            },
        )

        assert merged["Local"]["downloaded"] == ["1", "2"]
        assert merged["Imported"]["read_chapters"] == ["9"]

    def test_merge_backup_state_alias_preserves_local_key_casing(self):
        merged = merge_backup_state(
            {
                "Stateful": {
                    "downloaded": ["1"],
                    "failed_chapters": {
                        "4": {"error": "local", "attempts": 2},
                    },
                }
            },
            {
                "stateful": {
                    "downloaded": ["2"],
                    "failed_chapters": {
                        "4": {"error": "imported", "attempts": 1},
                        "5": {"error": "backup", "attempts": 1},
                    },
                }
            },
            title_aliases={"stateful": "Stateful"},
        )

        assert list(merged) == ["Stateful"]
        assert merged["Stateful"]["downloaded"] == ["1", "2"]
        assert merged["Stateful"]["failed_chapters"]["4"]["error"] == "local"
        assert merged["Stateful"]["failed_chapters"]["5"]["error"] == "backup"
        assert "stateful" not in merged

    def test_merge_backup_state_keeps_new_import_casing_without_alias(self):
        merged = merge_backup_state(
            {"Stateful": {"downloaded": ["1"]}},
            {"stateful": {"downloaded": ["2"]}},
        )

        assert merged["Stateful"]["downloaded"] == ["1"]
        assert merged["stateful"]["downloaded"] == ["2"]

    def test_last_chapter_uses_chapter_order_not_string_order(self):
        merged = merge_manga_state(
            {"last_chapter": "9"},
            {"last_chapter": "10"},
        )

        assert merged["last_chapter"] == "10"

    @pytest.mark.parametrize("local, imported", [("1", ".5"), (".5", "1")])
    def test_leading_dot_last_chapter_does_not_roll_back(self, local, imported):
        # Issue #227: ".5" is chapter 0.5, so it never replaces cursor "1".
        merged = merge_manga_state(
            {"last_chapter": local},
            {"last_chapter": imported},
        )

        assert merged["last_chapter"] == "1"

    def test_leading_dot_chapter_merges_in_chapter_order(self):
        merged = merge_manga_state(
            {"downloaded": ["5", "1"]},
            {"downloaded": [".5"]},
        )

        assert merged["downloaded"] == [".5", "1", "5"]

    def test_labelled_last_chapter_uses_its_chapter_number(self):
        # Issue #227: "9 Part 1" is chapter 9, so it does not beat "10".
        merged = merge_manga_state(
            {"last_chapter": "9 Part 1"},
            {"last_chapter": "10"},
        )

        assert merged["last_chapter"] == "10"

    def test_merged_chapters_use_shared_chapter_order(self):
        merged = merge_manga_state(
            {"downloaded": ["10 Part 1", "Extra", "2"]},
            {"downloaded": ["10", "2.5", "Bonus"]},
        )

        assert merged["downloaded"] == [
            "Bonus", "Extra", "2", "2.5", "10", "10 Part 1"]


class TestValidateBackupContents:
    """Issue #354: payload shape is checked before an import writes."""

    def test_valid_payload_returns_manga_and_state(self):
        manga = [{"title": "A", "url": "u"}]
        state = {"A": {"downloaded": ["1"]}}
        assert validate_backup_contents(
            {"version": 1, "manga": manga, "state": state}) == (manga, state)

    @pytest.mark.parametrize("state", [None, "missing"])
    def test_absent_state_is_empty(self, state):
        data = {"version": 1, "manga": []}
        if state != "missing":
            data["state"] = state
        assert validate_backup_contents(data) == ([], {})

    @pytest.mark.parametrize("data, match", [
        ({"version": 1}, "missing 'manga' key"),
        ({"version": 1, "manga": {}}, "manga must be a list"),
        ({"version": 1, "manga": [None]}, "entry 1 must be an object"),
        ({"version": 1, "manga": [{}]}, "entry 1 has no title"),
        ({"version": 1, "manga": [{"title": ""}]}, "entry 1 has no title"),
        ({"version": 1, "manga": [{"title": ["A"]}]}, "entry 1 has no title"),
        ({"version": 1, "manga": [], "state": []}, "state must be an object"),
        ({"version": 1, "manga": [], "state": {"A": "x"}}, "state for 'A'"),
    ])
    def test_malformed_payload_rejected(self, data, match):
        with pytest.raises(BackupVersionError, match=match):
            validate_backup_contents(data)

    @pytest.mark.parametrize("field, value", [
        ("downloaded", 5),
        ("downloaded", "12"),
        ("downloaded", [True]),
        ("read_chapters", [None]),
        ("external_chapters", {}),
        ("available_chapters", [1]),
        ("failed_chapters", []),
        ("pending_backup", "x"),
        ("partial_chapters", 1),
        ("saved_chapter_groups", []),
        ("reading_progress", []),
        ("reader_positions", []),
        ("reader_positions", "1"),
        ("reader_positions", None),
        ("new_chapters_available", "3"),
        ("new_chapters_available", True),
        ("last_chapter", {}),
        ("last_updated", 1),
        ("created", []),
    ])
    def test_malformed_nested_state_field_rejected(self, field, value):
        data = {"version": 1, "manga": [], "state": {"A": {field: value}}}
        with pytest.raises(BackupVersionError, match=f"state for 'A': {field}"):
            validate_backup_contents(data)

    def test_none_and_unknown_state_fields_pass(self):
        entry = {key: None for key in (
            "downloaded", "available_chapters", "failed_chapters",
            "reading_progress", "new_chapters_available", "last_chapter",
            "last_updated", "created")}
        entry["future_field"] = object()
        data = {"version": 1, "manga": [], "state": {"A": entry}}
        assert validate_backup_contents(data)[1] == {"A": entry}

    def test_state_as_written_by_state_passes(self):
        entry = {
            "downloaded": ["1", 2, 2.5], "read_chapters": [],
            "external_chapters": ["3"],
            "available_chapters": [{"number": "1", "url": "u"}],
            "failed_chapters": {"4": {"error": "e", "attempts": 1}},
            "pending_backup": {}, "partial_chapters": {},
            "saved_chapter_groups": {},
            "reading_progress": {"last_chapter": None, "last_read": None},
            "reader_positions": {"2": {"mode": "paged", "page_index": 3,
                                       "updated_at": "2026-01-01T00:00:00"}},
            "new_chapters_available": 0, "last_chapter": "2.5",
            "last_updated": "2026-01-01T00:00:00",
            "created": "2026-01-01T00:00:00",
        }
        data = {"version": 1, "manga": [], "state": {"A": entry}}
        assert validate_backup_contents(data)[1] == {"A": entry}
