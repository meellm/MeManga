"""Tests for memanga.gui.cache.CoverCache — disk + memory LRU."""

from __future__ import annotations

import pytest


@pytest.fixture
def cover_cache(qapp, isolated_home, event_bus):
    # qapp: QPixmap construction aborts without a QGuiApplication, so
    # the cache needs one even though no widget is shown.
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

    def test_loads_valid_image_from_disk(self, cover_cache):
        from PIL import Image
        url = "https://covers.test/good.jpg"
        Image.new("RGB", (200, 300), "white").save(
            cover_cache._disk_path(url), format="PNG")

        pm = cover_cache.get_cover(url, (50, 60))
        assert pm.width() == 50 and pm.height() == 60
        assert pm is not cover_cache.get_placeholder((50, 60))


class TestCorruptDiskCache:
    """Issue #48 — cached bytes that don't decode as an image (e.g. an
    HTML block page saved by an older build) must be dropped and the
    URL refetched, not returned as a permanent placeholder.
    """

    def test_bad_cached_bytes_dropped_and_refetched(self, cover_cache,
                                                    event_bus):
        url = "https://cdn.covers.test/blocked.webp"
        disk_path = cover_cache._disk_path(url)
        disk_path.write_bytes(b"<!DOCTYPE html><html>blocked</html>")

        requested = []
        event_bus.subscribe("cover_fetch_request",
                            lambda d: requested.append(d))

        pm = cover_cache.get_cover(url, (50, 60))

        assert not pm.isNull()        # placeholder while refetching
        assert not disk_path.exists()  # corrupt file dropped
        event_bus.poll()
        assert requested and requested[0]["url"] == url
