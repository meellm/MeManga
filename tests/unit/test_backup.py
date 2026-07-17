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
