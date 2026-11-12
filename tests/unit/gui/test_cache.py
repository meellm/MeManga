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


class TestPlaceholderIdentity:
    def test_placeholder_is_recognised(self, cover_cache):
        assert cover_cache.is_placeholder(cover_cache.get_placeholder((40, 60)))
        assert cover_cache.is_placeholder(cover_cache.get_cover(None, (40, 60)))

    def test_real_cover_is_not_a_placeholder(self, cover_cache):
        from PIL import Image
        url = "https://covers.test/real.jpg"
        Image.new("RGB", (200, 300), "red").save(
            cover_cache._disk_path(url), format="PNG")
        assert not cover_cache.is_placeholder(cover_cache.get_cover(url, (40, 60)))

    def test_placeholder_follows_the_theme(self, cover_cache, qapp, theme):
        dark = cover_cache.get_placeholder((40, 60))
        theme.set_theme("light", qapp)
        light = cover_cache.get_placeholder((40, 60))
        assert dark is not light
        assert (dark.toImage().pixelColor(0, 0).name()
                != light.toImage().pixelColor(0, 0).name())
        # Both are still known as placeholders.
        assert cover_cache.is_placeholder(dark)
        assert cover_cache.is_placeholder(light)


class TestMemoryBudget:
    def test_memory_is_bounded_by_bytes(self, cover_cache, monkeypatch):
        from PIL import Image
        import memanga.gui.cache as cache_mod
        # Room for two 100x100 pixmaps (40 000 bytes each), not three.
        monkeypatch.setattr(cache_mod, "_MEMORY_BUDGET_BYTES", 100_000)
        monkeypatch.setattr(cache_mod, "_pixel_ratio", lambda: 1.0)
        urls = [f"https://covers.test/{i}.jpg" for i in range(3)]
        for url in urls:
            Image.new("RGB", (100, 100), "white").save(
                cover_cache._disk_path(url), format="PNG")
            cover_cache.get_cover(url, (100, 100))
        assert len(cover_cache._memory) == 2
        assert cover_cache._memory_bytes == 80_000
        # The oldest went first.
        assert cover_cache._cache_key(urls[0], (100, 100)) not in cover_cache._memory

    def test_pixmap_carries_the_pixel_ratio(self, cover_cache, monkeypatch):
        from PIL import Image
        import memanga.gui.cache as cache_mod
        monkeypatch.setattr(cache_mod, "_pixel_ratio", lambda: 2.0)
        url = "https://covers.test/dense.jpg"
        Image.new("RGB", (400, 600), "white").save(
            cover_cache._disk_path(url), format="PNG")
        pm = cover_cache.get_cover(url, (50, 60))
        # Twice the pixels, the same size in layouts.
        assert (pm.width(), pm.height()) == (100, 120)
        assert pm.devicePixelRatio() == 2.0


class TestDiskLimit:
    """Issue #404: the cover folder has a size limit; the covers used
    longest ago go first."""

    MB = 1024 * 1024

    @staticmethod
    def _put(cache, name, size, age):
        """A cached file of ``size`` bytes last used ``age`` seconds ago."""
        import os
        import time
        url = f"https://covers.test/{name}.jpg"
        path = cache._disk_path(url)
        path.write_bytes(b"x" * size)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return url, path

    def test_limit_values(self):
        from memanga.gui.cache import (DEFAULT_DISK_LIMIT_MB, MAX_DISK_LIMIT_MB,
                                       MIN_DISK_LIMIT_MB, disk_limit_mb)
        assert disk_limit_mb(None) == DEFAULT_DISK_LIMIT_MB
        assert disk_limit_mb("500") == DEFAULT_DISK_LIMIT_MB
        assert disk_limit_mb(True) == DEFAULT_DISK_LIMIT_MB
        assert disk_limit_mb(1) == MIN_DISK_LIMIT_MB
        assert disk_limit_mb(10 ** 9) == MAX_DISK_LIMIT_MB
        assert disk_limit_mb(300) == 300

    def test_config_default_matches_the_cache(self, config):
        from memanga.config import CONFIG_KEYS
        from memanga.gui.cache import (DEFAULT_DISK_LIMIT_MB, MAX_DISK_LIMIT_MB,
                                       MIN_DISK_LIMIT_MB)
        assert config.get("gui.cover_cache_max_mb") == DEFAULT_DISK_LIMIT_MB
        spec = CONFIG_KEYS["gui.cover_cache_max_mb"]
        assert (spec["min"], spec["max"]) == (MIN_DISK_LIMIT_MB, MAX_DISK_LIMIT_MB)

    def test_least_recently_used_removed_past_the_limit(self, cover_cache):
        cover_cache._max_disk_bytes = 10 * self.MB
        _, oldest = self._put(cover_cache, "oldest", 4 * self.MB, age=300)
        _, middle = self._put(cover_cache, "middle", 4 * self.MB, age=200)
        _, newest = self._put(cover_cache, "newest", 4 * self.MB, age=100)

        removed = cover_cache._trim_disk()

        assert removed == 1
        assert not oldest.exists()
        assert middle.exists() and newest.exists()
        assert cover_cache.disk_usage() <= 10 * self.MB

    def test_under_the_limit_nothing_is_removed(self, cover_cache):
        cover_cache._max_disk_bytes = 10 * self.MB
        _, a = self._put(cover_cache, "a", 2 * self.MB, age=300)
        _, b = self._put(cover_cache, "b", 2 * self.MB, age=100)
        assert cover_cache._trim_disk() == 0
        assert a.exists() and b.exists()

    def test_save_trims_but_keeps_the_cover_just_saved(self, cover_cache,
                                                       event_bus):
        cover_cache._max_disk_bytes = 10 * self.MB
        _, old = self._put(cover_cache, "old", 8 * self.MB, age=300)
        url = "https://covers.test/fresh.jpg"

        cover_cache.save_to_disk(url, b"y" * (6 * self.MB))

        assert cover_cache._disk_path(url).exists()
        assert not old.exists()
        loaded = []
        event_bus.subscribe("cover_loaded", loaded.append)
        event_bus.poll()
        assert loaded == [{"url": url}]

    def test_using_a_cover_protects_it(self, cover_cache):
        from PIL import Image
        cover_cache._max_disk_bytes = 10 * self.MB
        # The oldest file is a real image that gets shown again.
        used_url, used = self._put(cover_cache, "used", 1, age=300)
        Image.new("RGB", (20, 30), "white").save(used, format="PNG")
        import os
        import time
        stamp = time.time() - 300
        os.utime(used, (stamp, stamp))
        _, idle = self._put(cover_cache, "idle", 6 * self.MB, age=200)
        _, recent = self._put(cover_cache, "recent", 6 * self.MB, age=100)

        cover_cache.get_cover(used_url, (20, 30))  # renews its time
        cover_cache._trim_disk()

        assert used.exists()
        assert not idle.exists()
        assert recent.exists()

    def test_lowering_the_limit_trims_at_once(self, cover_cache):
        _, a = self._put(cover_cache, "a", 8 * self.MB, age=300)
        _, b = self._put(cover_cache, "b", 8 * self.MB, age=100)
        cover_cache.set_disk_limit_mb(10)
        assert not a.exists() and b.exists()
        assert cover_cache.disk_limit_bytes == 10 * self.MB

    def test_clear_removes_files_and_memory(self, cover_cache):
        from PIL import Image
        url = "https://covers.test/shown.jpg"
        Image.new("RGB", (20, 30), "white").save(
            cover_cache._disk_path(url), format="PNG")
        cover_cache.get_cover(url, (20, 30))
        self._put(cover_cache, "other", 10, age=10)
        cover_cache.mark_failed("https://covers.test/broken.jpg")

        assert cover_cache.clear() == 2
        assert cover_cache.disk_usage() == 0
        assert not cover_cache._memory and cover_cache._memory_bytes == 0
        assert not cover_cache._failed


class TestDiskAccounting:
    """The running total that spares a folder listing on every save must
    not hide what is really in the folder."""

    MB = 1024 * 1024
    _put = staticmethod(TestDiskLimit._put)

    def test_limit_change_measures_the_folder_again(self, cover_cache):
        # The total was taken while the folder was empty (Settings does
        # this when it shows the cache size); the files arrived without
        # passing through the cache object.
        assert cover_cache.disk_usage() == 0
        _, old = self._put(cover_cache, "old", 8 * self.MB, age=300)
        _, new = self._put(cover_cache, "new", 8 * self.MB, age=100)

        cover_cache.set_disk_limit_mb(10)

        assert not old.exists() and new.exists()
        assert cover_cache._disk_bytes == 8 * self.MB

    def test_running_total_triggers_the_trim_on_save(self, cover_cache):
        import os
        import time
        cover_cache._max_disk_bytes = 10 * self.MB
        assert cover_cache.disk_usage() == 0  # total known from here on
        paths = []
        for i, name in enumerate(("a", "b", "c")):
            url = f"https://covers.test/{name}.jpg"
            cover_cache.save_to_disk(url, b"z" * (4 * self.MB))
            path = cover_cache._disk_path(url)
            if name != "c":
                stamp = time.time() - (300 - 100 * i)
                os.utime(path, (stamp, stamp))
            paths.append(path)
            if name == "b":
                # Two covers, 8 MB: under the limit, counted, kept.
                assert cover_cache._disk_bytes == 8 * self.MB
                assert all(p.exists() for p in paths)

        a, b, c = paths
        assert not a.exists()          # the one used longest ago
        assert b.exists() and c.exists()
        assert cover_cache._disk_bytes == 8 * self.MB

    def test_saving_over_a_cover_counts_the_difference(self, cover_cache):
        url = "https://covers.test/same.jpg"
        assert cover_cache.disk_usage() == 0
        cover_cache.save_to_disk(url, b"z" * 3000)
        cover_cache.save_to_disk(url, b"z" * 1000)
        assert cover_cache._disk_bytes == 1000 == cover_cache.disk_usage()

    def test_oldest_go_first_until_back_under(self, cover_cache):
        cover_cache._max_disk_bytes = 10 * self.MB
        files = [self._put(cover_cache, f"n{i}", 3 * self.MB, age=500 - 100 * i)[1]
                 for i in range(5)]  # n0 oldest ... n4 newest, 15 MB

        assert cover_cache._trim_disk() == 2

        assert [f.exists() for f in files] == [False, False, True, True, True]
