"""Tests for memanga.config.Config — dotted-key get/set, manga list
mutation, app-password keyring helpers, persistence round-trips."""

from __future__ import annotations

import pytest


class TestConfigBasics:
    def test_get_returns_default_for_unknown_key(self, config):
        assert config.get("nope.nothing.here", "fallback") == "fallback"

    def test_set_then_get(self, config):
        config.set("delivery.output_format", "epub")
        assert config.get("delivery.output_format") == "epub"

    def test_dotted_key_creates_nested(self, config):
        config.set("a.b.c", 42)
        assert config.get("a.b.c") == 42
        # Top-level nested dicts should also be readable directly.
        a = config.get("a")
        assert a == {"b": {"c": 42}}


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
