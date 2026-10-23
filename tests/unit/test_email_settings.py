"""Tests for memanga.email_settings: Kindle delivery settings read from
config in one place (issue #296)."""

from __future__ import annotations

import dataclasses

import pytest

from memanga import config as config_mod
from memanga.email_settings import (DEFAULT_SMTP_PORT, DEFAULT_SMTP_SERVER,
                                    EmailSettings, kindle_delivery_settings,
                                    manga_sends_to_kindle)


@pytest.fixture
def no_keyring(monkeypatch):
    """The password comes from the environment or config, never the OS
    keychain of the machine running the tests."""
    import keyring
    monkeypatch.setattr(keyring, "get_password", lambda service, user: None)


def _email_on(config):
    config.set("delivery.mode", "email")
    config.set("email.kindle_email", "reader@kindle.example.invalid")
    config.set("email.sender_email", "sender@example.invalid")


class TestFromConfig:
    def test_defaults_of_a_new_config(self, config, no_keyring):
        settings = EmailSettings.from_config(config)

        assert settings == EmailSettings(
            kindle_email="", sender_email="",
            smtp_server="smtp.gmail.com", smtp_port=587,
            smtp_timeout=60, max_email_mb=25, app_password="")

    def test_defaults_when_keys_are_missing(self, config, no_keyring):
        # A hand-edited config without the SMTP keys keeps the usual ones.
        config.set("email", {"kindle_email": "reader@kindle.example.invalid"})

        settings = EmailSettings.from_config(config)

        assert settings.smtp_server == DEFAULT_SMTP_SERVER == "smtp.gmail.com"
        assert settings.smtp_port == DEFAULT_SMTP_PORT == 587
        assert settings.smtp_timeout is None  # the emailer default applies
        assert settings.max_email_mb is None
        assert settings.sender_email == ""

    def test_reads_the_smtp_settings(self, config, no_keyring):
        _email_on(config)
        config.set("email.smtp_server", "smtp.example.invalid")
        config.set("email.smtp_port", 2525)
        config.set("email.smtp_timeout", 9)
        config.set("email.max_email_mb", 20)
        config.set("email.app_password", "config-pw")

        settings = EmailSettings.from_config(config)

        assert settings == EmailSettings(
            kindle_email="reader@kindle.example.invalid",
            sender_email="sender@example.invalid",
            smtp_server="smtp.example.invalid", smtp_port=2525,
            smtp_timeout=9, max_email_mb=20, app_password="config-pw")

    def test_values_are_kept_as_configured(self, config, no_keyring):
        # The emailer validates when sending, so a bad port fails that
        # chapter's delivery instead of building the settings.
        config.set("email.smtp_port", "not-a-port")
        assert EmailSettings.from_config(config).smtp_port == "not-a-port"

    def test_missing_password_is_empty(self, config, no_keyring):
        _email_on(config)
        assert EmailSettings.from_config(config).app_password == ""

    def test_environment_password_wins(self, config, no_keyring, monkeypatch):
        # Issue #247: the injected password is the one delivery uses.
        config.set("email.app_password", "config-pw")
        monkeypatch.setenv(config_mod.SMTP_PASSWORD_ENV, "env-pw")
        assert EmailSettings.from_config(config).app_password == "env-pw"

    def test_unusable_override_is_not_replaced(self, config, no_keyring,
                                               monkeypatch, tmp_path):
        # A broken override must fail delivery, not fall back to the
        # stored password.
        config.set("email.app_password", "config-pw")
        monkeypatch.setenv(config_mod.SMTP_PASSWORD_FILE_ENV,
                           str(tmp_path / "missing"))
        assert EmailSettings.from_config(config).app_password == ""

    def test_password_lookup_can_be_left_to_the_caller(self, config,
                                                       monkeypatch):
        looked_up = []
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: looked_up.append(cfg) or "pw")

        settings = EmailSettings.from_config(config, resolve_password=False)

        assert settings.app_password is None
        assert looked_up == []


class TestEmailSettings:
    def test_password_is_not_in_the_repr(self):
        settings = EmailSettings(kindle_email="reader@kindle.example.invalid",
                                 app_password="hunter2-secret")
        assert "hunter2-secret" not in repr(settings)
        assert "reader@kindle.example.invalid" in repr(settings)

    def test_is_immutable(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            EmailSettings().smtp_port = 25

    def test_fields_are_keyword_only(self):
        with pytest.raises(TypeError):
            EmailSettings("reader@kindle.example.invalid")


class TestKindleDeliverySettings:
    def test_local_delivery_has_none(self, config, no_keyring):
        config.set("email.kindle_email", "reader@kindle.example.invalid")
        assert config.delivery_mode == "local"
        assert kindle_delivery_settings(config) is None

    def test_email_mode_without_kindle_address_has_none(self, config,
                                                        no_keyring):
        config.set("delivery.mode", "email")
        assert kindle_delivery_settings(config) is None

    def test_disabled_delivery_never_looks_up_the_password(self, config,
                                                           monkeypatch):
        looked_up = []
        monkeypatch.setattr("memanga.email_settings.get_app_password",
                            lambda cfg: looked_up.append(cfg) or "pw")
        assert kindle_delivery_settings(config) is None
        assert looked_up == []

    def test_email_delivery_has_the_settings(self, config, no_keyring):
        _email_on(config)
        config.set("email.app_password", "config-pw")

        settings = kindle_delivery_settings(config)

        assert settings == EmailSettings.from_config(config)
        assert settings.app_password == "config-pw"

    @pytest.mark.parametrize("manga, expected", [
        ({"title": "Old entry"}, True),  # no send_to_kindle: it takes part
        ({"title": "On", "send_to_kindle": True}, True),
        ({"title": "Off", "send_to_kindle": False}, False),
    ])
    def test_manga_choice_is_respected(self, config, no_keyring, manga,
                                       expected):
        # Issue #341: a manga's own Kindle setting wins over global email.
        _email_on(config)
        assert manga_sends_to_kindle(manga) is expected
        assert (kindle_delivery_settings(config, manga) is not None) is expected

    def test_pipeline_reexports_the_manga_check(self):
        from memanga import chapter_pipeline
        assert chapter_pipeline.manga_sends_to_kindle is manga_sends_to_kindle
