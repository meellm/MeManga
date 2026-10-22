"""Tests for memanga.config.Config — dotted-key get/set, manga list
mutation, app-password keyring helpers, persistence round-trips."""

from __future__ import annotations

import sys

import pytest


class TestConfigBasics:
    def test_get_returns_default_for_unknown_key(self, config):
        assert config.get("nope.nothing.here", "fallback") == "fallback"

    def test_set_then_get(self, config):
        config.set("delivery.output_format", "epub")
        assert config.get("delivery.output_format") == "epub"

    def test_mangadex_original_is_default_and_choice_persists(self, config):
        assert config.get("mangadex.data_saver") is False
        assert config.get("mangadex.removed_group_ids") == []
        config.set("mangadex.data_saver", True)
        config.set("mangadex.removed_group_ids", ["group-1"])
        config.save()
        config.reload()
        assert config.get("mangadex.data_saver") is True
        assert config.get("mangadex.removed_group_ids") == ["group-1"]

    def test_dotted_key_creates_nested(self, config):
        config.set("a.b.c", 42)
        assert config.get("a.b.c") == 42
        # Top-level nested dicts should also be readable directly.
        a = config.get("a")
        assert a == {"b": {"c": 42}}


class TestConfigLocking:
    """Issue #246: set() and reset() mutate under the same lock as save()."""

    @staticmethod
    def _blocks_until_lock_released(config, action):
        import threading
        config._lock.acquire()
        worker = threading.Thread(target=action, daemon=True)
        try:
            worker.start()
            worker.join(0.3)
            assert worker.is_alive(), "ran without taking the config lock"
        finally:
            config._lock.release()
        worker.join(5)
        assert not worker.is_alive()

    def test_set_waits_for_lock(self, config):
        self._blocks_until_lock_released(
            config, lambda: config.set("gui.sort_by", "status"))
        assert config.get("gui.sort_by") == "status"

    def test_reset_waits_for_lock(self, config):
        config.set("gui.sort_by", "status")
        self._blocks_until_lock_released(config, config.reset)
        assert config.get("gui.sort_by") == "title"
        config.reload()
        assert config.get("gui.sort_by") == "title"


class TestPartialChapterConfig:
    """Partial-chapter tolerance settings (issue #86)."""

    def test_disabled_by_default(self, config):
        assert config.partial_enabled is False
        # Default threshold is exposed as a float for the downloader.
        assert config.partial_threshold == 5.0

    def test_enable_and_set_threshold(self, config):
        config.set("partial_chapters.enabled", True)
        config.set("partial_chapters.threshold_percent", 10)
        assert config.partial_enabled is True
        assert config.partial_threshold == 10.0

    def test_threshold_falls_back_on_garbage(self, config):
        config.set("partial_chapters.threshold_percent", "not-a-number")
        assert config.partial_threshold == 5.0

    def test_threshold_clamps_above_100(self, config):
        config.set("partial_chapters.threshold_percent", 150)
        assert config.partial_threshold == 100.0

    def test_threshold_clamps_below_0(self, config):
        config.set("partial_chapters.threshold_percent", -20)
        assert config.partial_threshold == 0.0


class TestConfigPersistence:
    def test_save_then_reload(self, isolated_home):
        from memanga.config import Config
        c1 = Config()
        c1.set("delivery.naming_template", "{title}-{chapter}")
        c1.save()
        c2 = Config()  # fresh load from disk
        assert c2.get("delivery.naming_template") == "{title}-{chapter}"


class TestMangaList:
    def test_add_manga_via_set(self, config):
        config.set("manga", [{"title": "X", "url": "u"}])
        assert len(config.get("manga", [])) == 1

    def test_update_manga_mutates_and_persists(self, config):
        config.set("manga", [{"title": "X", "url": "u", "status": "reading"}])

        def _mutator(entry):
            entry["status"] = "completed"
            return True

        ok = config.update_manga("X", _mutator)
        assert ok
        assert config.get("manga")[0]["status"] == "completed"

    def test_update_manga_unknown_returns_false(self, config):
        config.set("manga", [])
        assert not config.update_manga("never", lambda e: True)


class TestKeyringHelpers:
    def test_set_then_get_app_password(self, config, monkeypatch):
        # Patch keyring so the test never touches the real OS keychain.
        store = {}
        import keyring
        monkeypatch.setattr(keyring, "set_password",
                            lambda s, u, p: store.__setitem__((s, u), p))
        monkeypatch.setattr(keyring, "get_password",
                            lambda s, u: store.get((s, u)))
        from memanga.config import set_app_password, get_app_password
        set_app_password(config, "secret-pw")
        assert get_app_password(config) == "secret-pw"

    def test_get_app_password_missing_returns_empty(self, config, monkeypatch):
        import keyring
        monkeypatch.setattr(keyring, "get_password", lambda s, u: None)
        from memanga.config import get_app_password
        # Contract: when nothing stored in keyring AND nothing in config,
        # return the empty string (not None — Config never stores None).
        assert get_app_password(config) == ""


class TestAppPasswordStorage:
    """Issue #247: the plaintext fallback is reported, and the password
    can be injected through the environment."""

    @pytest.fixture
    def keyring_store(self, monkeypatch):
        import keyring
        store = {}
        monkeypatch.setattr(keyring, "set_password",
                            lambda s, u, p: store.__setitem__((s, u), p))
        monkeypatch.setattr(keyring, "get_password",
                            lambda s, u: store.get((s, u)))
        return store

    @pytest.fixture
    def broken_keyring(self, monkeypatch):
        import keyring

        def broken(*a):
            raise RuntimeError("no backend")
        monkeypatch.setattr(keyring, "set_password", broken)
        monkeypatch.setattr(keyring, "get_password", broken)

    def test_keyring_store_reported_and_config_cleared(self, config, keyring_store):
        from memanga.config import set_app_password
        config.set("email.app_password", "old-plain")
        assert set_app_password(config, "secret-pw") == "keyring"
        assert config.get("email.app_password") == ""
        assert keyring_store == {("memanga", "app_password"): "secret-pw"}

    def test_keyring_failure_falls_back_to_config(self, config, broken_keyring):
        from memanga.config import get_app_password, set_app_password
        assert set_app_password(config, "secret-pw") == "config"
        config.reload()
        assert config.get("email.app_password") == "secret-pw"
        assert get_app_password(config) == "secret-pw"

    def test_discarding_keyring_counts_as_unavailable(self, config, monkeypatch):
        import keyring
        monkeypatch.setattr(keyring, "set_password", lambda s, u, p: None)
        monkeypatch.setattr(keyring, "get_password", lambda s, u: None)
        from memanga.config import get_app_password, set_app_password
        assert set_app_password(config, "secret-pw") == "config"
        assert get_app_password(config) == "secret-pw"

    def test_plaintext_notice_names_path_not_password(self, config, broken_keyring):
        from memanga.config import plaintext_password_notice, set_app_password
        set_app_password(config, "secret-pw")
        notice = plaintext_password_notice(config)
        assert str(config.config_path) in notice
        assert "MEMANGA_SMTP_PASSWORD_FILE" in notice
        assert "secret-pw" not in notice

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_plaintext_fallback_file_is_private(self, config, broken_keyring):
        import os
        import stat
        from memanga.config import set_app_password
        set_app_password(config, "secret-pw")
        mode = stat.S_IMODE(os.stat(config.config_path).st_mode)
        assert mode & 0o077 == 0

    def test_env_password_wins_and_is_not_stored(self, config, keyring_store,
                                                 monkeypatch):
        from memanga.config import get_app_password
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        config.set("email.app_password", "config-pw")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD", "env-pw")
        assert get_app_password(config) == "env-pw"
        assert config.get("email.app_password") == "config-pw"
        assert keyring_store == {("memanga", "app_password"): "keyring-pw"}
        assert not config.config_path.exists()

    def test_password_file_wins_and_strips_newline(self, config, keyring_store,
                                                   monkeypatch, tmp_path):
        from memanga.config import get_app_password
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        secret = tmp_path / "smtp_password"
        secret.write_bytes(b"file pw with spaces\n")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", str(secret))
        assert get_app_password(config) == "file pw with spaces"

    def test_empty_env_values_count_as_unset(self, config, keyring_store,
                                             monkeypatch):
        from memanga.config import app_password_override, get_app_password
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD", "")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", "")
        assert app_password_override() is None
        assert get_app_password(config) == "keyring-pw"

    @pytest.mark.parametrize("problem", ["both", "missing", "empty", "directory",
                                         "too_large", "not_utf8"])
    def test_unusable_override_fails_safe(self, config, keyring_store, monkeypatch,
                                          tmp_path, caplog, problem):
        from memanga.config import (AppPasswordError, app_password_override,
                                    get_app_password)
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        config.set("email.app_password", "config-pw")
        secret = tmp_path / "smtp_password"
        if problem == "both":
            secret.write_text("file-pw", encoding="utf-8")
            monkeypatch.setenv("MEMANGA_SMTP_PASSWORD", "env-pw")
        elif problem == "empty":
            secret.write_text("\n", encoding="utf-8")
        elif problem == "directory":
            secret.mkdir()
        elif problem == "too_large":
            secret.write_text("x" * 5000, encoding="utf-8")
        elif problem == "not_utf8":
            secret.write_bytes(b"\xff\xfe\xfa")
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE", str(secret))

        with pytest.raises(AppPasswordError) as excinfo:
            app_password_override()
        message = str(excinfo.value)
        assert "file-pw" not in message and "env-pw" not in message
        # Never falls back to a stored password, and never raises.
        with caplog.at_level("WARNING", logger="memanga.config"):
            assert get_app_password(config) == ""
        assert "MEMANGA_SMTP_PASSWORD" in caplog.text
        assert "file-pw" not in caplog.text and "env-pw" not in caplog.text

    @pytest.mark.parametrize("file_name", [
        "smtp\x00password",                      # open() raises ValueError
        "~memanga-no-such-user-247\x00/pw",      # expanduser() raises ValueError
    ])
    def test_nul_in_password_file_path_fails_safe(self, config, keyring_store,
                                                  monkeypatch, caplog, file_name):
        # A NUL must not escape get_app_password, wherever it is caught.
        # The OS environment cannot hold a NUL, so the value is injected
        # through a mapping, and config's os.environ is replaced by a
        # plain dict for this test only.
        from memanga import config as config_mod
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        config.set("email.app_password", "config-pw")
        environ = {"MEMANGA_SMTP_PASSWORD_FILE": file_name}
        with pytest.raises(config_mod.AppPasswordError) as excinfo:
            config_mod.app_password_override(environ)
        message = str(excinfo.value)
        assert "MEMANGA_SMTP_PASSWORD_FILE" in message
        assert "not a valid file path" in message
        monkeypatch.setattr(config_mod.os, "environ",
                            dict(config_mod.os.environ, **environ))
        with caplog.at_level("WARNING", logger="memanga.config"):
            assert config_mod.get_app_password(config) == ""
        for text in (message, caplog.text):
            assert "keyring-pw" not in text and "config-pw" not in text

    def test_unknown_user_in_password_file_path_fails_safe(self, config, keyring_store,
                                                           monkeypatch):
        # Through the real environment: get_app_password never raises.
        from memanga.config import (AppPasswordError, app_password_override,
                                    get_app_password)
        keyring_store[("memanga", "app_password")] = "keyring-pw"
        monkeypatch.setenv("MEMANGA_SMTP_PASSWORD_FILE",
                           "~memanga-no-such-user-247/smtp_password")
        with pytest.raises(AppPasswordError) as excinfo:
            app_password_override()
        assert "MEMANGA_SMTP_PASSWORD_FILE" in str(excinfo.value)
        assert get_app_password(config) == ""

    def test_unresolvable_home_in_password_file_path(self, monkeypatch):
        from memanga import config as config_mod

        def no_home(self):
            raise RuntimeError("Could not determine home directory.")
        monkeypatch.setattr(config_mod.Path, "expanduser", no_home)
        with pytest.raises(config_mod.AppPasswordError) as excinfo:
            config_mod.app_password_override(
                {"MEMANGA_SMTP_PASSWORD_FILE": "~/smtp_password"})
        assert "home folder" in str(excinfo.value)


class TestInvalidConfigFile:
    def _write(self, isolated_home, text):
        path = isolated_home / ".config" / "memanga" / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_strict_by_default(self, isolated_home):
        import yaml
        from memanga.config import Config
        self._write(isolated_home, "manga: [unclosed\n")
        with pytest.raises(yaml.YAMLError):
            Config()

    @pytest.mark.parametrize("text", ["manga: [unclosed\n", "- just\n- a list\n"])
    def test_tolerant_loads_defaults_and_refuses_save(self, isolated_home, text):
        from memanga.config import Config, ConfigError
        path = self._write(isolated_home, text)
        cfg = Config(tolerate_errors=True)
        assert cfg.load_error
        assert cfg.get("manga") == []
        with pytest.raises(ConfigError):
            cfg.save()
        assert path.read_text(encoding="utf-8") == text

    def test_reload_clears_error_once_fixed(self, isolated_home):
        from memanga.config import Config
        path = self._write(isolated_home, "manga: [unclosed\n")
        cfg = Config(tolerate_errors=True)
        path.write_text("manga: []\n", encoding="utf-8")
        cfg.reload()
        assert cfg.load_error is None
        cfg.save()


class TestConfigKeys:
    """Schema behind `config get/set/edit` (issue #353)."""

    @pytest.mark.parametrize("key,text,expected", [
        ("delivery.output_format", "EPUB", "epub"),
        ("delivery.mode", "email", "email"),
        ("delivery.delete_after_send", "yes", True),
        ("gui.auto_check", "off", False),
        ("email.smtp_port", "587", 587),
        ("email.smtp_timeout", "30", 30),
        ("partial_chapters.threshold_percent", "12.5", 12.5),
        ("cron.time", "6:5", "06:05"),
        ("delivery.post_processing.command", "", ""),
        ("email.kindle_email", "me@kindle.com", "me@kindle.com"),
    ])
    def test_parse_accepts(self, key, text, expected):
        from memanga.config import parse_config_value
        value = parse_config_value(key, text)
        assert value == expected
        assert type(value) is type(expected)

    @pytest.mark.parametrize("key,text", [
        ("delivery.output_format", "mobi"),
        ("delivery.delete_after_send", "maybe"),
        ("email.smtp_port", "0"),
        ("email.smtp_port", "70000"),
        ("email.smtp_port", "5.5"),
        ("email.smtp_timeout", "0"),
        ("email.smtp_timeout", "601"),
        ("partial_chapters.threshold_percent", "150"),
        ("partial_chapters.threshold_percent", "nan"),
        ("cron.time", "25:00"),
        ("cron.time", "noon"),
        ("delivery.naming_template", "  "),
        ("gui.auto_check_interval", "5"),
        ("mangadex.removed_group_ids", "x"),
    ])
    def test_parse_rejects(self, key, text):
        from memanga.config import parse_config_value
        with pytest.raises(ValueError):
            parse_config_value(key, text)

    def test_unknown_key(self):
        from memanga.config import UnknownConfigKey, parse_config_value
        with pytest.raises(UnknownConfigKey):
            parse_config_value("manga", "[]")

    def test_defaults_are_valid(self, isolated_home):
        from memanga.config import CONFIG_KEYS, Config, config_value_problem
        cfg = Config()
        for key in CONFIG_KEYS:
            assert config_value_problem(key, cfg.get(key)) is None, key

    @pytest.mark.parametrize("key,value", [
        ("email.smtp_port", "587"),
        ("email.smtp_port", True),
        ("delivery.delete_after_send", "yes"),
        ("delivery.output_format", "mobi"),
        ("cron.time", 450),  # unquoted 7:30 in YAML 1.1
        ("partial_chapters.threshold_percent", 101),
        ("mangadex.removed_group_ids", "abc"),
    ])
    def test_value_problem(self, key, value):
        from memanga.config import config_value_problem
        assert config_value_problem(key, value)

    @pytest.mark.parametrize("data,expected", [
        ({}, []),
        ({"delivery": {"mode": "local"}}, []),
        ({"delivery": {"post_processing": "oops"}},
         ["delivery.post_processing: expected a section"]),
        ({"delivery": None}, ["delivery: expected a section"]),
        ({"email": [], "gui": 3},
         ["email: expected a section", "gui: expected a section"]),
        ({"manga": "not checked here"}, []),
    ])
    def test_section_problems(self, data, expected):
        from memanga.config import config_section_problems
        assert config_section_problems(data) == expected
