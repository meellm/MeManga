"""Settings → Advanced → Cover Cache (issue #404): the size limit is
shown, saved, applied to the running cache and reset, and the size label
and Clear cache follow."""

from __future__ import annotations

import os
import time

import pytest

MB = 1024 * 1024


@pytest.fixture
def page(app_window, monkeypatch):
    from memanga.gui.pages import settings as settings_mod
    monkeypatch.setattr(settings_mod, "Toast", lambda *a, **k: None)
    return app_window._pages["settings"]


def _put(cache, name, size, age):
    """A cached cover file of ``size`` bytes last used ``age`` seconds ago."""
    path = cache._disk_path(f"https://covers.test/{name}.jpg")
    path.write_bytes(b"x" * size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_limit_is_shown_saved_and_applied(app_window, page):
    from memanga.config import Config
    cache = app_window.cover_cache
    assert page._cache_limit.value() == 200
    assert page._cache_limit.accessibleName() == "Cover cache size limit"
    old = _put(cache, "old", 8 * MB, age=300)
    new = _put(cache, "new", 8 * MB, age=100)

    page._cache_limit.setValue(10)
    page._save()

    assert app_window.config.get("gui.cover_cache_max_mb") == 10
    assert Config(app_window.config.config_dir).get(
        "gui.cover_cache_max_mb") == 10
    # Applied to the running cache at once: trimmed, oldest first.
    assert cache.disk_limit_bytes == 10 * MB
    assert not old.exists() and new.exists()
    assert page._cache_size_label.text() == "8.0 MB of 10 MB used"
    assert page._clear_cache_btn.text() == "Clear 8 MB"


def test_reset_restores_the_limit_and_clear_empties_the_cache(
        app_window, page, monkeypatch):
    import memanga.gui.components.dialogs as dialogs_mod
    cache = app_window.cover_cache
    app_window.config.set("gui.cover_cache_max_mb", 50)
    cache.set_disk_limit_mb(50)
    page._load_config_into_widgets()
    assert page._cache_limit.value() == 50

    page._reset_to_defaults()

    assert app_window.config.get("gui.cover_cache_max_mb") == 200
    assert page._cache_limit.value() == 200
    assert cache.disk_limit_bytes == 200 * MB

    # Clear cache, with its confirmation answered "yes".
    cover = _put(cache, "cover", 2 * MB, age=10)
    page._refresh_cache_size()
    assert page._cache_size_label.text() == "2.0 MB of 200 MB used"
    monkeypatch.setattr(
        dialogs_mod, "ConfirmDialog",
        lambda parent, title="", message="", on_confirm=None, **k: on_confirm())
    page._clear_cache()
    assert not cover.exists()
    assert page._cache_size_label.text() == "Cache is empty"
    assert page._clear_cache_btn.text() == "Clear cache"
