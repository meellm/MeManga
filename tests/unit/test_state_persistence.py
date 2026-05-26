"""Persistence + concurrency tests for State and Config.

These exercise behaviors the GUI + CLI both depend on:
  - Atomic save (no torn writes on crash mid-flush)
  - Corruption recovery
  - Concurrent writes don't lose data (thread safety)
  - YAML round-trip preserves nested dicts
  - Migrations from older state schemas (if any)
"""

from __future__ import annotations

import json
import threading
import time
import pytest


# ─────────────────────────────────────────────────────────────────────────
# Atomic save — state.json should never be partially written
# ─────────────────────────────────────────────────────────────────────────


class TestAtomicSave:
    def test_flush_uses_temp_file(self, state, tmp_path, monkeypatch):
        """flush() should write to a .tmp file then rename atomically.
        We patch tempfile.mkstemp to verify the temp-file pattern."""
        import tempfile
        original_mkstemp = tempfile.mkstemp
        calls = []
        def _spy(*a, **k):
            r = original_mkstemp(*a, **k)
            calls.append((a, k))
            return r
        monkeypatch.setattr(tempfile, "mkstemp", _spy)
        state.add_notification("info", "x")
        state.flush()
        assert calls, "flush() must use mkstemp for atomic write"

    def test_save_survives_partial_write(self, state, isolated_home):
        """Even if a previous run died mid-flush leaving a .tmp file
        behind, the next load shouldn't be confused by it."""
        cfg = isolated_home / ".config" / "memanga"
        cfg.mkdir(parents=True, exist_ok=True)
        # Leave a stray tmp file behind
        (cfg / "state.json.tmp").write_text("{partial")
        # Re-instantiate — should not raise
        from memanga.state import State
        s = State(config_dir=cfg)
        assert s.get_notifications() == []


# ─────────────────────────────────────────────────────────────────────────
# Concurrent mutation — multiple workers writing State at once
# ─────────────────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_parallel_add_downloaded(self, state):
        """100 threads each mark 10 chapters — no entries lost."""
        def worker(thread_id):
            for i in range(10):
                state.add_downloaded_chapter("X", f"{thread_id}-{i}")
        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(state.get_downloaded_chapters("X")) == 100

    def test_parallel_notification_add(self, state):
        def worker():
            for _ in range(20):
                state.add_notification("info", "msg")
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        # Capped at 100 — but no exception should have been raised.
        assert len(state.get_notifications()) > 0

    def test_concurrent_flush_safe(self, state):
        def writer():
            for i in range(20):
                state.add_notification("info", f"n{i}")
                state.flush()
        threads = [threading.Thread(target=writer) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        # File should still be valid JSON.
        data = json.loads(state.state_path.read_text())
        assert "notifications" in data


# ─────────────────────────────────────────────────────────────────────────
# Config persistence — YAML round-trip
# ─────────────────────────────────────────────────────────────────────────


class TestConfigPersistence:
    def test_nested_dict_round_trips(self, config, isolated_home):
        config.set("delivery.email.smtp.server", "smtp.gmail.com")
        config.set("delivery.email.smtp.port", 587)
        config.save()

        from memanga.config import Config
        reload = Config()
        assert reload.get("delivery.email.smtp.server") == "smtp.gmail.com"
        assert reload.get("delivery.email.smtp.port") == 587

    def test_manga_list_round_trips(self, config, sample_manga_with_backup):
        config.set("manga", [sample_manga_with_backup])
        config.save()
        from memanga.config import Config
        reload = Config()
        loaded = reload.get("manga")
        assert len(loaded) == 1
        assert loaded[0]["title"] == sample_manga_with_backup["title"]
        # Backup source structure preserved
        assert len(loaded[0]["sources"]) == 2

    def test_unicode_in_manga_title(self, config):
        config.set("manga", [{"title": "恋愛 マニュアル",
                               "source": "mangadex.org",
                               "url": "https://x",
                               "status": "reading"}])
        config.save()
        from memanga.config import Config
        reload = Config()
        assert reload.get("manga")[0]["title"] == "恋愛 マニュアル"


# ─────────────────────────────────────────────────────────────────────────
# Schema evolution — old state files should still load
# ─────────────────────────────────────────────────────────────────────────


class TestSchemaCompat:
    def test_missing_top_level_key_defaulted(self, isolated_home):
        """A state.json that's missing one of the newer top-level keys
        (e.g. `source_health`) shouldn't crash."""
        cfg = isolated_home / ".config" / "memanga"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "state.json").write_text(json.dumps({
            "manga": {}, "last_check": None,
        }))
        from memanga.state import State
        s = State(config_dir=cfg)
        # New methods should still return sensible defaults
        assert s.get_all_source_health() == {} or isinstance(
            s.get_all_source_health(), dict)
        assert s.get_notifications() == []

    def test_manga_state_for_unseen_title_does_not_raise(self, state):
        # Even with zero history, get_manga_state must not raise.
        st = state.get_manga_state("never-touched")
        assert isinstance(st, dict)
