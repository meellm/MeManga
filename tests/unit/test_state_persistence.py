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

    def test_older_save_cannot_overwrite_newer_state(self, state, monkeypatch):
        """A delayed old save must not publish after a newer mutation."""
        state.set("publication_order", "old")
        original_replace = __import__("os").replace
        first_replace_ready = threading.Event()
        release_first_replace = threading.Event()
        replace_count = 0
        count_lock = threading.Lock()
        publication_lock_held = []
        thread_errors = []

        def controlled_replace(src, dst):
            nonlocal replace_count
            with count_lock:
                replace_count += 1
                call_number = replace_count

            probe_acquired_lock = []

            def probe_lock():
                acquired = state._lock.acquire(blocking=False)
                probe_acquired_lock.append(acquired)
                if acquired:
                    state._lock.release()

            probe = threading.Thread(target=probe_lock)
            probe.start()
            probe.join(timeout=5)
            assert not probe.is_alive()
            publication_lock_held.append(not probe_acquired_lock[0])

            if call_number == 1:
                first_replace_ready.set()
                assert release_first_replace.wait(timeout=5)
            original_replace(src, dst)

        monkeypatch.setattr("memanga.state.os.replace", controlled_replace)

        def capture_errors(fn, *args):
            try:
                fn(*args)
            except Exception as exc:  # pragma: no cover - failure path
                thread_errors.append(exc)

        old_save = threading.Thread(target=capture_errors, args=(state.save,))
        old_save.start()
        assert first_replace_ready.wait(timeout=5)

        newer_save = threading.Thread(
            target=capture_errors,
            args=(state.set, "publication_order", "new"))
        newer_save.start()

        release_first_replace.set()
        old_save.join(timeout=5)
        newer_save.join(timeout=5)

        assert not old_save.is_alive()
        assert not newer_save.is_alive()
        assert thread_errors == []
        assert publication_lock_held == [True, True]
        assert json.loads(state.state_path.read_text())["publication_order"] == "new"


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

    def test_import_merge_serializes_with_worker_mutation(self, state):
        """Backup merge must not publish an old manga snapshot over workers."""
        state.add_downloaded_chapter("Existing", "1")
        worker_started = threading.Event()
        worker_done = threading.Event()
        worker_errors = []
        worker_threads = []

        class InterleavingImport(dict):
            def items(self):
                def worker():
                    try:
                        worker_started.set()
                        state.add_downloaded_chapter("Existing", "2")
                        worker_done.set()
                    except Exception as exc:  # pragma: no cover - failure path
                        worker_errors.append(exc)

                thread = threading.Thread(target=worker)
                worker_threads.append(thread)
                thread.start()
                assert worker_started.wait(timeout=5)
                time.sleep(0.02)
                assert not worker_done.is_set()
                return super().items()

        imported = InterleavingImport({
            "Existing": {"downloaded": ["imported"]},
            "Missing": {"downloaded": ["9"]},
        })

        state.merge_missing_manga_state(imported)

        for thread in worker_threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        assert worker_errors == []
        assert state.get_downloaded_chapters("Existing") == ["1", "2"]
        assert state.get_downloaded_chapters("Missing") == ["9"]

    def test_cli_import_merge_unions_downloaded_under_lock(self, state):
        state.add_downloaded_chapter("Existing", "1")

        state.merge_missing_manga_state(
            {
                "Existing": {"downloaded": ["2", "10"]},
                "Missing": {"downloaded": ["3"]},
            },
            merge_existing_downloaded=True,
        )

        assert state.get_downloaded_chapters("Existing") == ["1", "2", "10"]
        assert state.get_downloaded_chapters("Missing") == ["3"]

    def test_import_merge_rejects_non_dict_state(self, state):
        with pytest.raises(TypeError):
            state.merge_missing_manga_state([])


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


# ─────────────────────────────────────────────────────────────────────────
# Getter isolation (issue #110) — returned containers are snapshots, so
# GUI code can iterate them while workers mutate the underlying state
# ─────────────────────────────────────────────────────────────────────────


class TestGetterIsolation:
    def test_downloaded_list_is_a_copy(self, state):
        state.add_downloaded_chapter("X", "1")
        state.get_downloaded_chapters("X").append("999")
        assert state.get_downloaded_chapters("X") == ["1"]

    def test_manga_state_is_a_snapshot(self, state):
        state.add_downloaded_chapter("X", "1")
        snap = state.get_manga_state("X")
        snap["downloaded"].append("999")
        snap["last_chapter"] = "999"
        assert state.get_downloaded_chapters("X") == ["1"]
        assert state.get_last_chapter("X") == "1"

    def test_source_health_is_a_copy(self, state):
        state.update_source_health("a.test", True, latency_ms=50)
        state.get_all_source_health()["a.test"]["status"] = "error"
        state.get_source_health("a.test")["status"] = "error"
        assert state.get_source_health("a.test")["status"] == "ok"

    def test_notifications_are_copies(self, state):
        state.add_notification("info", "x")
        state.get_notifications()[0]["read"] = True
        assert state.get_unread_count() == 1

    def test_generic_get_returns_copy(self, state):
        state.set("custom", {"nested": [1]})
        state.get("custom")["nested"].append(2)
        assert state.get("custom") == {"nested": [1]}

    @pytest.mark.parametrize("getter", [
        lambda state: state.get_available_chapters("X"),
        lambda state: state.get_download_history(),
        lambda state: state.get_all_pending_backups("X"),
        lambda state: state.get_failed_chapters("X"),
        lambda state: state.get_source_health("src.test"),
        lambda state: state.get_all_source_health(),
        lambda state: state.get_reading_progress("X"),
        lambda state: state.get_check_history(),
    ])
    def test_nested_getters_return_snapshots(self, state, getter):
        state.set("manga", {"X": {
            "available_chapters": [{"metadata": {"tags": ["original"]}}],
            "pending_backup": {"1": {"metadata": {"tags": ["original"]}}},
            "failed_chapters": {"1": {"failed_pages": [[1]]}},
            "reading_progress": {"metadata": {"tags": ["original"]}},
        }})
        state.set("download_history", [
            {"metadata": {"tags": ["original"]}},
        ])
        state.set("check_history", [
            {"metadata": {"tags": ["original"]}},
        ])
        state.set("source_health", {
            "src.test": {"metadata": {"tags": ["original"]}},
        })

        snapshot = getter(state)
        original = state._snapshot(snapshot)

        def mutate_nested(value):
            if isinstance(value, dict):
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        mutate_nested(child)
                        return
            elif isinstance(value, list):
                if value and isinstance(value[0], (dict, list)):
                    mutate_nested(value[0])
                else:
                    value.append("changed")

        mutate_nested(snapshot)
        assert getter(state) == original

    def test_setter_inputs_are_snapshotted(self, state):
        available = [{"metadata": {"tags": ["original"]}}]
        suspicious = {"chapters": [{"number": "1"}]}
        failed_pages = [[1]]
        custom = {"nested": ["original"]}

        state.set_available_chapters("X", available)
        state.set_suspicious_batch("X", suspicious)
        state.add_failed_chapter("X", "1", "src.test", "boom", failed_pages)
        state.set("custom", custom)

        available[0]["metadata"]["tags"].append("changed")
        suspicious["chapters"][0]["number"] = "999"
        failed_pages[0].append(2)
        custom["nested"].append("changed")

        assert state.get_available_chapters("X") == [
            {"metadata": {"tags": ["original"]}},
        ]
        assert state.get_suspicious_batch("X") == {
            "chapters": [{"number": "1"}],
        }
        assert state.get_failed_chapters("X")["1"]["failed_pages"] == [[1]]
        assert state.get("custom") == {"nested": ["original"]}

    def test_mutator_that_saves_does_not_deadlock(self, state):
        # Immediate-save mutators call save() while holding the state
        # lock — the reentrant lock must let that through.
        state.set_pending_backup("X", "1", "backup.test", "https://b/1")
        state.add_failed_chapter("X", "2", "src.test", "boom")
        state.clear_pending_backup("X", "1")
        assert state.get_pending_backup("X", "1") is None

    def test_rename_manga_moves_state_entry_and_persists(self, state):
        state.add_downloaded_chapter("Old", "1")

        assert state.rename_manga("Old", "New") is True
        assert state.get_manga_state("Old") == {}
        assert state.get_downloaded_chapters("New") == ["1"]
        assert "New" in json.loads(state.state_path.read_text())["manga"]

    def test_rename_manga_returns_false_for_missing_entry(self, state):
        assert state.rename_manga("Missing", "New") is False
        assert state.get_manga_state("New") == {}


# ─────────────────────────────────────────────────────────────────────────
# Stress (issue #110) — GUI-style worker mutations interleaved with the
# main thread's periodic flush + close-time save
# ─────────────────────────────────────────────────────────────────────────


class TestFlushMutationStress:
    N_MANGA = 4
    N_CHAPTERS = 25
    N_SOURCES = 4
    N_NOTIFICATIONS = 80

    def test_no_lost_updates_under_interleaved_flush(self, state):
        """Simulate the GUI: download/check/health workers mutating state
        while the flush timer and close handler serialize it. No chapter,
        read mark, notification, history entry, or health entry may be
        lost, and the file on disk must stay valid JSON."""
        stop = threading.Event()
        errors = []

        def guarded(fn):
            def run(*args):
                try:
                    fn(*args)
                except Exception as e:  # pragma: no cover - failure path
                    errors.append(e)
            return run

        @guarded
        def flusher():
            while True:
                state.flush()
                state.save()
                if stop.is_set():
                    return
                time.sleep(0.001)

        @guarded
        def download_worker(idx):
            title = "Manga %d" % idx
            for n in range(1, self.N_CHAPTERS + 1):
                state.add_downloaded_chapter(title, str(n))
                state.mark_chapter_read(title, str(n))
                state.add_download_history(title, str(n), "cbz", size_mb=1.0)
                state.add_failed_chapter(title, "f%d" % n, "src.test", "boom")

        @guarded
        def check_worker(idx):
            title = "Manga %d" % idx
            for n in range(self.N_CHAPTERS):
                state.set_new_chapters(title, n)
                state.set_available_chapters(
                    title, [dict(number=str(i)) for i in range(n + 1)])
                state.get_manga_state(title)  # GUI refresh-style read
                state.get_stats()

        @guarded
        def health_worker(idx):
            domain = "src%d.test" % idx
            for n in range(self.N_CHAPTERS):
                state.update_source_health(domain, n % 4 != 0,
                                           "timeout", latency_ms=100 + n)
                state.get_all_source_health()

        @guarded
        def notify_worker():
            for n in range(self.N_NOTIFICATIONS):
                state.add_notification("download", "n%d" % n)
                state.get_notifications()

        flush_thread = threading.Thread(target=flusher, daemon=True)
        workers = []
        for i in range(self.N_MANGA):
            workers.append(threading.Thread(target=download_worker, args=(i,)))
            workers.append(threading.Thread(target=check_worker, args=(i,)))
        for i in range(self.N_SOURCES):
            workers.append(threading.Thread(target=health_worker, args=(i,)))
        workers.append(threading.Thread(target=notify_worker))

        flush_thread.start()
        for t in workers:
            t.start()
        for t in workers:
            t.join(timeout=60)
        stop.set()
        flush_thread.join(timeout=60)
        alive = [t for t in workers + [flush_thread] if t.is_alive()]
        assert not alive, "threads deadlocked or still running"
        assert errors == []

        # In-memory: nothing lost.
        expected = [str(n) for n in range(1, self.N_CHAPTERS + 1)]
        for i in range(self.N_MANGA):
            title = "Manga %d" % i
            assert sorted(state.get_downloaded_chapters(title),
                          key=float) == expected
            assert sorted(state.get_read_chapters(title),
                          key=float) == expected
            assert len(state.get_failed_chapters(title)) == self.N_CHAPTERS
            assert len(state.get_available_chapters(title)) == self.N_CHAPTERS
        assert len(state.get_download_history(limit=1000)) == \
            self.N_MANGA * self.N_CHAPTERS
        assert len(state.get_notifications(limit=1000)) == self.N_NOTIFICATIONS
        for i in range(self.N_SOURCES):
            health = state.get_source_health("src%d.test" % i)
            assert health.get("latency_ms") == 100 + self.N_CHAPTERS - 1

        # On disk: valid JSON that round-trips the same data.
        data = json.loads(state.state_path.read_text())
        for i in range(self.N_MANGA):
            assert sorted(data["manga"]["Manga %d" % i]["downloaded"],
                          key=float) == expected
        assert len(data["download_history"]) == self.N_MANGA * self.N_CHAPTERS
        assert len(data["notifications"]) == self.N_NOTIFICATIONS
        assert len(data["source_health"]) == self.N_SOURCES
