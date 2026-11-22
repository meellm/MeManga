"""Schema versions and migrations for config.yaml and state.json (#409).

Pins that files written before versioning load unchanged and are stamped
on their next save (the previous file becomes the .bak copy), that a
file from a newer MeManga is refused and never overwritten, and how a
future layout change is expected to register its migration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from memanga.schema import SCHEMA_VERSION_KEY, SchemaVersionError, migrate

SAMPLES = Path(__file__).parent / "fixtures" / "schema"


@pytest.fixture
def cfg_dir(isolated_home):
    d = isolated_home / ".config" / "memanga"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestMigrate:
    def test_missing_version_is_zero_and_migrates(self):
        seen = []
        steps = {0: lambda d: (seen.append(dict(d)), d)[1]}
        out = migrate({"k": 1}, 1, steps, "test")
        assert out == {"k": 1, SCHEMA_VERSION_KEY: 1}
        assert seen == [{"k": 1}]

    def test_current_version_passes_through(self):
        data = {SCHEMA_VERSION_KEY: 2, "k": 1}
        assert migrate(data, 2, {}, "test") == {SCHEMA_VERSION_KEY: 2, "k": 1}

    def test_chain_runs_each_step_in_order(self):
        steps = {
            0: lambda d: {**d, "order": d.get("order", []) + [0]},
            1: lambda d: {**d, "order": d["order"] + [1]},
            2: lambda d: {**d, "order": d["order"] + [2]},
        }
        out = migrate({SCHEMA_VERSION_KEY: 1, "order": []}, 3, steps, "test")
        assert out == {SCHEMA_VERSION_KEY: 3, "order": [1, 2]}

    def test_newer_version_rejected_with_update_hint(self):
        with pytest.raises(SchemaVersionError, match="newer.*update MeManga"):
            migrate({SCHEMA_VERSION_KEY: 3}, 2, {}, "test")

    @pytest.mark.parametrize("bad", ["1", 1.0, True, None, -1, [1]])
    def test_malformed_version_rejected(self, bad):
        with pytest.raises(SchemaVersionError, match="invalid test schema"):
            migrate({SCHEMA_VERSION_KEY: bad}, 1, {0: lambda d: d}, "test")

    def test_missing_step_rejected(self):
        with pytest.raises(SchemaVersionError, match="version 1 is not supported"):
            migrate({SCHEMA_VERSION_KEY: 1}, 2, {0: lambda d: d}, "test")


class TestConfigSchema:
    def _write_sample(self, cfg_dir):
        path = cfg_dir / "config.yaml"
        path.write_bytes((SAMPLES / "config-v0.yaml").read_bytes())
        return path

    def test_fresh_config_is_saved_with_current_version(self, cfg_dir):
        from memanga.config import CONFIG_SCHEMA_VERSION, Config
        Config(cfg_dir).save()
        data = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
        assert data[SCHEMA_VERSION_KEY] == CONFIG_SCHEMA_VERSION == 1

    def test_unversioned_sample_loads_unchanged(self, cfg_dir):
        from memanga.config import Config
        path = self._write_sample(cfg_dir)
        original = path.read_bytes()
        config = Config(cfg_dir)
        assert config.get(SCHEMA_VERSION_KEY) == 1
        assert config.delivery_mode == "email"
        assert config.output_format == "epub"
        assert config.get("delivery.download_dir") == "/data/manga"
        assert config.get("cron.time") == "07:30"
        assert config.get("gui.sort_by") == "last_updated"
        assert config.get("gui.auto_check") is False
        assert [m["title"] for m in config.get("manga")] == [
            "One Piece", "Solo Leveling"]
        assert config.get("manga")[1]["sources"][1]["url"].startswith(
            "https://mangadex.org/")
        # Sections added after the sample was written get their defaults.
        assert config.get("reader.remove_after_read") is False
        assert config.partial_threshold == 5.0
        assert config.get("gui.auto_check_interval") == 3600
        # Loading alone never rewrites the file.
        assert path.read_bytes() == original

    def test_unversioned_sample_stamped_on_save_with_backup(self, cfg_dir):
        from memanga.config import Config
        path = self._write_sample(cfg_dir)
        original = path.read_bytes()
        Config(cfg_dir).save()
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert saved[SCHEMA_VERSION_KEY] == 1
        assert saved["delivery"]["output_format"] == "epub"
        assert (cfg_dir / "config.yaml.bak").read_bytes() == original
        again = Config(cfg_dir)
        assert again.get(SCHEMA_VERSION_KEY) == 1
        assert [m["title"] for m in again.get("manga")] == [
            "One Piece", "Solo Leveling"]

    def test_newer_config_refused_and_kept(self, cfg_dir):
        from memanga.config import Config, ConfigError
        path = cfg_dir / "config.yaml"
        path.write_text("schema_version: 99\nmanga: []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="newer.*update MeManga"):
            Config(cfg_dir)
        config = Config(cfg_dir, tolerate_errors=True)
        assert "schema version 99 is newer" in config.load_error
        with pytest.raises(ConfigError, match="Refusing to overwrite"):
            config.save()
        assert path.read_text(encoding="utf-8") == "schema_version: 99\nmanga: []\n"
        assert not (cfg_dir / "config.yaml.bak").exists()

    def test_invalid_version_refused(self, cfg_dir):
        from memanga.config import Config
        (cfg_dir / "config.yaml").write_text(
            "schema_version: one\nmanga: []\n", encoding="utf-8")
        config = Config(cfg_dir, tolerate_errors=True)
        assert "invalid config schema version: 'one'" in config.load_error

    def test_future_migration_runs_before_defaults_merge(
            self, cfg_dir, monkeypatch):
        # How a layout change is expected to work: bump the version and
        # register a step from the previous one.
        from memanga import config as config_mod

        def rename_section(data):
            data["delivery"] = data.pop("output", {})
            return data
        monkeypatch.setattr(config_mod, "CONFIG_SCHEMA_VERSION", 2)
        monkeypatch.setitem(config_mod._CONFIG_MIGRATIONS, 1, rename_section)
        (cfg_dir / "config.yaml").write_text(
            "schema_version: 1\noutput:\n  output_format: cbz\n",
            encoding="utf-8")
        config = config_mod.Config(cfg_dir)
        assert config.get(SCHEMA_VERSION_KEY) == 2
        assert config.output_format == "cbz"
        assert config.get("delivery.mode") == "local"
        assert config.get("output") is None


class TestStateSchema:
    def _write_sample(self, cfg_dir, name="state.json"):
        path = cfg_dir / name
        path.write_bytes((SAMPLES / "state-v0.json").read_bytes())
        return path

    def test_fresh_state_is_saved_with_current_version(self, cfg_dir):
        from memanga.state import STATE_SCHEMA_VERSION, State
        State(config_dir=cfg_dir).save()
        data = json.loads((cfg_dir / "state.json").read_text(encoding="utf-8"))
        assert data[SCHEMA_VERSION_KEY] == STATE_SCHEMA_VERSION == 1

    def test_clear_all_keeps_version(self, cfg_dir):
        from memanga.state import State
        self._write_sample(cfg_dir)
        s = State(config_dir=cfg_dir)
        s.clear_all()
        data = json.loads((cfg_dir / "state.json").read_text(encoding="utf-8"))
        assert data[SCHEMA_VERSION_KEY] == 1
        assert data["manga"] == {}

    def test_unversioned_sample_loads_unchanged(self, cfg_dir):
        from memanga.state import State
        path = self._write_sample(cfg_dir)
        original = path.read_bytes()
        s = State(config_dir=cfg_dir)
        assert s.load_error is None
        assert s.get(SCHEMA_VERSION_KEY) == 1
        assert s.library.get_downloaded("One Piece") == ["1130", "1131", "1132"]
        assert s.library.get_last_chapter("One Piece") == "1132"
        assert s.reading.get_read("One Piece") == ["1130", "1131"]
        assert s.reading.get_progress("One Piece")["last_chapter"] == "1131"
        assert s.get("last_check") == "2026-05-27T12:00:00"
        assert path.read_bytes() == original

    def test_unversioned_sample_stamped_on_save_with_backup(self, cfg_dir):
        from memanga.state import State
        path = self._write_sample(cfg_dir)
        original = path.read_bytes()
        State(config_dir=cfg_dir).save()
        saved = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads(original)
        expected[SCHEMA_VERSION_KEY] = 1
        assert saved == expected
        assert (cfg_dir / "state.json.bak").read_bytes() == original

    def test_read_only_load_never_writes(self, cfg_dir):
        from memanga.state import State
        path = self._write_sample(cfg_dir)
        original = path.read_bytes()
        s = State(config_dir=cfg_dir, recover=False)
        s.flush()
        assert s.get(SCHEMA_VERSION_KEY) == 1
        assert path.read_bytes() == original
        assert not (cfg_dir / "state.json.bak").exists()

    @pytest.mark.parametrize("recover", [True, False])
    def test_newer_state_refused_and_kept(self, cfg_dir, recover):
        from memanga.state import State, StateError
        path = cfg_dir / "state.json"
        newer = json.dumps({SCHEMA_VERSION_KEY: 99, "manga": {"X": {}}})
        path.write_text(newer, encoding="utf-8")
        s = State(config_dir=cfg_dir, recover=recover)
        assert "state schema version 99 is newer" in s.load_error
        assert "update MeManga" in s.load_error
        assert s.get("manga") == {}
        with pytest.raises(StateError, match="Refusing to overwrite"):
            s.save()
        assert path.read_text(encoding="utf-8") == newer
        assert not (cfg_dir / "state.json.bak").exists()
        assert not list(cfg_dir.glob("state.json.corrupt-*"))

    def test_invalid_version_refused(self, cfg_dir):
        from memanga.state import State
        (cfg_dir / "state.json").write_text(
            json.dumps({SCHEMA_VERSION_KEY: "1", "manga": {}}), encoding="utf-8")
        s = State(config_dir=cfg_dir)
        assert "invalid state schema version: '1'" in s.load_error

    def test_restored_backup_written_back_as_it_was(self, cfg_dir):
        """Issue #243 restore copies the backup back unchanged; the
        upgrade is only in memory until the next save."""
        from memanga.state import State
        backup = self._write_sample(cfg_dir, "state.json.bak")
        (cfg_dir / "state.json").write_text("{truncated", encoding="utf-8")
        s = State(config_dir=cfg_dir)
        assert "Restored the previous copy" in s.recovery_notice
        assert s.get(SCHEMA_VERSION_KEY) == 1
        assert s.library.get_downloaded("One Piece") == ["1130", "1131", "1132"]
        assert json.loads((cfg_dir / "state.json").read_text(encoding="utf-8")) \
            == json.loads(backup.read_text(encoding="utf-8"))

    def test_future_migration_runs_on_load(self, cfg_dir, monkeypatch):
        from memanga import state as state_mod

        def move_history(data):
            data["check_history"] = data.pop("checks", [])
            return data
        monkeypatch.setattr(state_mod, "STATE_SCHEMA_VERSION", 2)
        monkeypatch.setitem(state_mod._STATE_MIGRATIONS, 1, move_history)
        (cfg_dir / "state.json").write_text(json.dumps({
            SCHEMA_VERSION_KEY: 1, "manga": {},
            "checks": [{"timestamp": "t", "new_chapters": 1, "downloaded": 0}],
        }), encoding="utf-8")
        s = state_mod.State(config_dir=cfg_dir)
        assert s.get(SCHEMA_VERSION_KEY) == 2
        assert s.get("check_history")[0]["new_chapters"] == 1
        assert s.get("checks") is None
