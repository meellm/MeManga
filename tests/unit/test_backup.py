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
