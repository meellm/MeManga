"""Tests for memanga.gui.cache.CoverCache — disk + memory LRU."""

from __future__ import annotations

import pytest


@pytest.fixture
def cover_cache(isolated_home, event_bus):
    from memanga.gui.cache import CoverCache
    return CoverCache(isolated_home / ".config" / "memanga", event_bus)


class TestPlaceholder:
    def test_returns_pixmap_for_size(self, cover_cache):
        pm = cover_cache.get_placeholder((170, 230))
        assert not pm.isNull()
        assert pm.width() == 170 and pm.height() == 230

    def test_cached_per_size(self, cover_cache):
        a = cover_cache.get_placeholder((100, 100))
        b = cover_cache.get_placeholder((100, 100))
        assert a is b  # identity — cached


class TestGetCover:
    def test_returns_placeholder_for_none_url(self, cover_cache):
        pm = cover_cache.get_cover(None, (170, 230))
        assert not pm.isNull()

    def test_marks_failed(self, cover_cache):
        cover_cache.mark_failed("https://broken.test/x.jpg")
        assert "https://broken.test/x.jpg" in cover_cache._failed
