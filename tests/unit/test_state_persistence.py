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
            if str(dst) != str(state.state_path):
                # Backup rotation (issue #243) is not a publication.
                return original_replace(src, dst)
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

        monkeypatch.setattr("memanga.persist.os.replace", controlled_replace)

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


# ─────────────────────────────────────────────────────────────────────────
# Issue #243 — a damaged state.json is kept, never replaced by defaults
# ─────────────────────────────────────────────────────────────────────────


class TestCorruptStateRecovery:
    @pytest.fixture
    def cfg_dir(self, isolated_home):
        d = isolated_home / ".config" / "memanga"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _preserved(cfg_dir):
        return sorted(cfg_dir.glob("state.json.corrupt-*"))

    @pytest.mark.parametrize("content", [
        "{this is not json", '{"manga": {"A": {"downloaded": ["1"', "",
        "[]", "null", b"\xff\xfe\x00bad".decode("latin-1"),
    ])
    def test_damaged_file_is_preserved_and_later_save_keeps_it(
            self, cfg_dir, content):
        from memanga.state import State
        (cfg_dir / "state.json").write_text(content, encoding="latin-1")
        original = (cfg_dir / "state.json").read_bytes()

        s = State(config_dir=cfg_dir)
        preserved = self._preserved(cfg_dir)
        assert preserved == [s.preserved_path]
        assert preserved[0].read_bytes() == original
        assert s.load_error is None
        assert "No usable backup" in s.recovery_notice
        assert str(s.preserved_path) in s.recovery_notice
        assert s.get_notifications() == []

        s.add_notification("info", "after recovery")
        s.save()
        assert preserved[0].read_bytes() == original
        assert json.loads((cfg_dir / "state.json").read_text())["notifications"]

    def test_valid_backup_is_restored_and_written_back(self, cfg_dir):
        from memanga.state import State
        good = {"manga": {"Berserk": {"downloaded": ["1", "2"]}},
                "notifications": []}
        (cfg_dir / "state.json.bak").write_text(json.dumps(good))
        (cfg_dir / "state.json").write_text("{truncated")

        s = State(config_dir=cfg_dir)
        assert s.get_downloaded_chapters("Berserk") == ["1", "2"]
        assert "Restored the previous copy" in s.recovery_notice
        assert json.loads((cfg_dir / "state.json").read_text()) == good
        assert self._preserved(cfg_dir)[0].read_text() == "{truncated"
        # Restoring does not rotate the damaged file into the backup.
        assert json.loads((cfg_dir / "state.json.bak").read_text()) == good
        # The next start loads the restored file without any notice.
        again = State(config_dir=cfg_dir)
        assert again.recovery_notice is None
        assert again.get_downloaded_chapters("Berserk") == ["1", "2"]

    @pytest.mark.parametrize("backup", [None, '{"manga": {}}'])
    def test_without_recovery_damaged_file_is_left_alone(self, cfg_dir, backup):
        """Issue #244: an unlocked reader never preserves, removes or
        restores; it refuses and leaves every file as it was."""
        from memanga.state import State, StateError
        (cfg_dir / "state.json").write_text("{truncated")
        if backup is not None:
            (cfg_dir / "state.json.bak").write_text(backup)
        before = sorted((p.name, p.read_bytes()) for p in cfg_dir.iterdir())

        s = State(config_dir=cfg_dir, recover=False)
        assert s.needs_recovery
        assert "nothing was changed" in s.load_error
        assert s.recovery_notice is None and s.preserved_path is None
        with pytest.raises(StateError):
            s.save()
        assert sorted((p.name, p.read_bytes()) for p in cfg_dir.iterdir()) == before

    def test_without_recovery_healthy_file_loads(self, cfg_dir):
        from memanga.state import State
        good = {"manga": {"Berserk": {"downloaded": ["1"]}}}
        (cfg_dir / "state.json").write_text(json.dumps(good))
        s = State(config_dir=cfg_dir, recover=False)
        assert not s.needs_recovery and s.load_error is None
        assert s.get_downloaded_chapters("Berserk") == ["1"]

    def test_invalid_backup_falls_back_to_defaults(self, cfg_dir):
        from memanga.state import State
        (cfg_dir / "state.json.bak").write_text("[1, 2]")
        (cfg_dir / "state.json").write_text("{bad")
        s = State(config_dir=cfg_dir)
        assert "No usable backup" in s.recovery_notice
        assert s.get("manga") == {}
        assert (cfg_dir / "state.json.bak").read_text() == "[1, 2]"

    def test_missing_file_starts_fresh_without_restoring_backup(self, cfg_dir):
        """Deleting state.json on purpose must still give a fresh start."""
        from memanga.state import State
        (cfg_dir / "state.json.bak").write_text(json.dumps(
            {"manga": {"Old": {"downloaded": ["9"]}}}))
        s = State(config_dir=cfg_dir)
        assert s.recovery_notice is None and s.load_error is None
        assert s.get("manga") == {}

    def _fail_state_replace(self, monkeypatch, cfg_dir):
        import os
        original_replace = self._real_replace = os.replace

        def replace(src, dst):
            if str(dst) == str(cfg_dir / "state.json"):
                raise OSError("No space left on device")
            return original_replace(src, dst)
        monkeypatch.setattr("memanga.persist.os.replace", replace)

    def test_failed_restore_write_back_blocks_and_keeps_backup(
            self, cfg_dir, monkeypatch):
        from memanga.state import State, StateError
        good = json.dumps({"manga": {"Berserk": {"downloaded": ["1"]}}})
        (cfg_dir / "state.json.bak").write_text(good)
        (cfg_dir / "state.json").write_text("{truncated")
        self._fail_state_replace(monkeypatch, cfg_dir)

        s = State(config_dir=cfg_dir)
        assert "could not be written back" in s.load_error
        assert "left as it is" in s.load_error
        assert s.recovery_notice is None
        # The damaged file never left its place, so the next start retries.
        assert (cfg_dir / "state.json").read_text() == "{truncated"
        assert [p.read_text() for p in self._preserved(cfg_dir)] == ["{truncated"]
        assert (cfg_dir / "state.json.bak").read_text() == good
        with pytest.raises(StateError):
            s.save()
        assert (cfg_dir / "state.json.bak").read_text() == good
        assert [p for p in cfg_dir.iterdir() if p.suffix == ".tmp"] == []

        # A second failing start reuses the identical preserved copy.
        retry = State(config_dir=cfg_dir)
        assert "could not be written back" in retry.load_error
        assert retry.preserved_path == s.preserved_path
        assert [p.read_text() for p in self._preserved(cfg_dir)] == ["{truncated"]

        monkeypatch.setattr("memanga.persist.os.replace", self._real_replace)
        again = State(config_dir=cfg_dir)
        assert again.load_error is None
        assert again.get_downloaded_chapters("Berserk") == ["1"]
        assert json.loads((cfg_dir / "state.json").read_text()) == json.loads(good)
        assert len(self._preserved(cfg_dir)) == 1

    def test_failed_recovery_never_becomes_a_fresh_start(
            self, cfg_dir, monkeypatch):
        """Across restarts: a start whose restore write fails, then one
        whose copy aside also fails, both refuse instead of loading empty
        state, and keep the damaged file and the backup. The first start
        that can write recovers the backup."""
        from memanga import state as state_mod
        good = json.dumps({"manga": {"Berserk": {"downloaded": ["1"]}}})
        (cfg_dir / "state.json.bak").write_text(good)
        (cfg_dir / "state.json").write_text("{truncated")
        self._fail_state_replace(monkeypatch, cfg_dir)

        first = state_mod.State(config_dir=cfg_dir)
        assert "could not be written back" in first.load_error

        def deny(path):
            raise OSError("No space left on device")
        monkeypatch.setattr(state_mod, "preserve_corrupt", deny)
        second = state_mod.State(config_dir=cfg_dir)
        assert "could not be copied for recovery" in second.load_error
        with pytest.raises(state_mod.StateError):
            second.save()

        assert (cfg_dir / "state.json").read_text() == "{truncated"
        assert (cfg_dir / "state.json.bak").read_text() == good
        assert [p.read_text() for p in self._preserved(cfg_dir)] == ["{truncated"]

        from memanga.persist import preserve_corrupt
        monkeypatch.setattr(state_mod, "preserve_corrupt", preserve_corrupt)
        monkeypatch.setattr("memanga.persist.os.replace", self._real_replace)
        third = state_mod.State(config_dir=cfg_dir)
        assert third.load_error is None
        assert "Restored the previous copy" in third.recovery_notice
        assert third.get_downloaded_chapters("Berserk") == ["1"]
        assert json.loads((cfg_dir / "state.json").read_text()) == json.loads(good)
        assert (cfg_dir / "state.json.bak").read_text() == good
        assert len(self._preserved(cfg_dir)) == 1

    def test_uncopyable_damaged_file_blocks_saves(self, cfg_dir, monkeypatch):
        from memanga import state as state_mod
        (cfg_dir / "state.json").write_text("{bad")

        def deny(path):
            raise PermissionError("denied")
        monkeypatch.setattr(state_mod, "preserve_corrupt", deny)

        s = state_mod.State(config_dir=cfg_dir)
        assert "could not be copied for recovery" in s.load_error
        s.add_notification("info", "x")  # only marks state dirty
        with pytest.raises(state_mod.StateError):
            s.save()
        assert (cfg_dir / "state.json").read_text() == "{bad"
        assert not (cfg_dir / "state.json.bak").exists()

    def test_unreadable_backup_refuses_instead_of_starting_empty(self, cfg_dir):
        from memanga.state import State, StateError
        (cfg_dir / "state.json").write_text("{bad")
        # A directory in the backup's place: it exists but open() fails
        # with an OSError, like a permission or I/O error would.
        (cfg_dir / "state.json.bak").mkdir()
        s = State(config_dir=cfg_dir)
        assert "could not be read" in s.load_error
        assert s.recovery_notice is None
        # The damaged primary stays (and is copied); nothing is replaced.
        assert (cfg_dir / "state.json").read_text() == "{bad"
        assert [p.read_text() for p in self._preserved(cfg_dir)] == ["{bad"]
        assert (cfg_dir / "state.json.bak").is_dir()
        with pytest.raises(StateError):
            s.save()
        assert (cfg_dir / "state.json").read_text() == "{bad"

    def test_unreadable_file_is_left_in_place(self, cfg_dir):
        from memanga.state import State, StateError
        # A directory in its place makes open() fail with an OSError.
        (cfg_dir / "state.json").mkdir()
        s = State(config_dir=cfg_dir)
        assert s.load_error and "cannot read" in s.load_error
        assert s.recovery_notice is None
        assert self._preserved(cfg_dir) == []
        with pytest.raises(StateError):
            s.save()
        assert (cfg_dir / "state.json").is_dir()


class TestSaveBackup:
    def test_first_save_has_no_backup(self, state):
        state.set("k", 1)
        assert not state.backup_path.exists()

    def test_save_keeps_one_previous_generation(self, state):
        state.set("k", 1)
        state.set("k", 2)
        assert json.loads(state.backup_path.read_text())["k"] == 1
        state.set("k", 3)
        assert json.loads(state.backup_path.read_text())["k"] == 2
        assert json.loads(state.state_path.read_text())["k"] == 3
        names = sorted(p.name for p in state.config_dir.iterdir()
                       if p.name.startswith("state.json"))
        assert names == ["state.json", "state.json.bak"]

    def test_copy_fallback_without_hard_links(self, state, monkeypatch):
        def no_link(*a, **k):
            raise OSError("hard links not supported")
        monkeypatch.setattr("memanga.persist.os.link", no_link)
        state.set("k", 1)
        state.set("k", 2)
        assert json.loads(state.backup_path.read_text())["k"] == 1

    def test_copy_fallback_is_fsynced_before_publication(
            self, state, monkeypatch):
        import os
        import stat as stat_mod
        real_fsync = os.fsync
        synced = []

        def spy(fd):
            if stat_mod.S_ISREG(os.fstat(fd).st_mode):
                synced.append(fd)
            return real_fsync(fd)
        state.set("k", 1)
        monkeypatch.setattr("memanga.persist.os.fsync", spy)
        state.set("k", 2)
        with_links = len(synced)

        def no_link(*a, **k):
            raise OSError("hard links not supported")
        monkeypatch.setattr("memanga.persist.os.link", no_link)
        synced.clear()
        state.set("k", 3)
        # The primary's temp file plus the backup copy.
        assert len(synced) == with_links + 1
        assert self._k(state.backup_path) == 2

    @pytest.mark.skipif(__import__("os").name == "nt",
                        reason="POSIX permission bits")
    def test_config_backup_copy_keeps_private_mode(self, config, monkeypatch):
        import os
        import stat as stat_mod

        def no_link(*a, **k):
            raise OSError("hard links not supported")
        monkeypatch.setattr("memanga.persist.os.link", no_link)
        config.save()
        # A mode mkstemp never produces, so a copy that only gets its bits
        # afterwards (or keeps the umask's) cannot pass by accident.
        os.chmod(config.config_path, 0o640)
        real_open = os.open
        created = []

        def spy_open(path, flags, mode=0o777, *a, **k):
            if flags & os.O_CREAT and str(path).startswith(
                    str(config.config_dir / "config.yaml.bak")):
                created.append(mode)
            return real_open(path, flags, mode, *a, **k)
        monkeypatch.setattr("memanga.persist.os.open", spy_open)
        config.set("delivery.mode", "email")
        config.save()
        backup = config.config_dir / "config.yaml.bak"
        # Created with the source's bits from the start, not after writing.
        assert created == [0o640]
        assert stat_mod.S_IMODE(backup.stat().st_mode) == 0o640

    def test_interrupted_backup_swap_still_syncs_the_folder(
            self, state, monkeypatch):
        import os
        state.set("k", 1)
        state.set("k", 2)
        real_replace = os.replace
        synced = []

        def replace(src, dst):
            if str(dst) == str(state.backup_path):
                raise KeyboardInterrupt
            return real_replace(src, dst)
        monkeypatch.setattr("memanga.persist.os.replace", replace)
        monkeypatch.setattr("memanga.persist._fsync_dir", synced.append)
        with pytest.raises(KeyboardInterrupt):
            state.set("k", 3)
        assert synced == [state.config_dir]
        assert self._k(state.state_path) == 3
        assert self._k(state.backup_path) == 1
        assert self._tmp_files(state) == []

    def test_directory_fsync_failure_does_not_fail_save(
            self, state, monkeypatch):
        import os
        import stat as stat_mod
        real_fsync = os.fsync
        dir_syncs = []

        def fsync(fd):
            if stat_mod.S_ISDIR(os.fstat(fd).st_mode):
                dir_syncs.append(fd)
                raise OSError("fsync not supported on this directory")
            return real_fsync(fd)
        monkeypatch.setattr("memanga.persist.os.fsync", fsync)
        state.set("k", 1)
        assert self._k(state.state_path) == 1
        if os.name != "nt":
            assert dir_syncs  # attempted where the platform allows it

    @staticmethod
    def _k(path):
        return json.loads(path.read_text())["k"]

    @staticmethod
    def _tmp_files(state):
        return [p.name for p in state.config_dir.iterdir() if p.suffix == ".tmp"]

    def test_backup_preparation_failure_fails_save_and_keeps_old_backup(
            self, state, monkeypatch):
        import errno
        from memanga.persist import SaveError
        state.set("k", 1)
        state.set("k", 2)

        def fail(*a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")
        monkeypatch.setattr("memanga.persist.os.link", fail)
        monkeypatch.setattr("memanga.persist._copy_durable", fail)
        with pytest.raises(SaveError) as exc:
            state.set("k", 3)
        # Still an OSError for existing handlers, with the cause kept.
        assert isinstance(exc.value, OSError)
        assert exc.value.errno == errno.ENOSPC
        assert exc.value.path == state.state_path
        assert str(exc.value) == (
            f"could not save {state.state_path}: No space left on device")
        assert self._k(state.state_path) == 2
        assert self._k(state.backup_path) == 1
        assert self._tmp_files(state) == []

    def test_partial_backup_copy_is_removed(self, state, monkeypatch):
        state.set("k", 1)
        state.set("k", 2)

        def no_link(*a, **k):
            raise OSError("hard links not supported")

        def torn_copy(src, dst):
            dst.write(b"{torn")
            raise OSError("disk full")
        monkeypatch.setattr("memanga.persist.os.link", no_link)
        monkeypatch.setattr("memanga.persist.shutil.copyfileobj", torn_copy)
        with pytest.raises(OSError):
            state.set("k", 3)
        assert self._k(state.state_path) == 2
        assert self._k(state.backup_path) == 1
        assert self._tmp_files(state) == []

    def test_failed_write_leaves_file_and_backup(self, state, monkeypatch):
        state.set("k", 1)
        state.set("k", 2)

        def fail_replace(src, dst):
            raise OSError("disk full")
        monkeypatch.setattr("memanga.persist.os.replace", fail_replace)
        with pytest.raises(OSError):
            state.set("k", 3)
        assert self._k(state.state_path) == 2
        assert self._k(state.backup_path) == 1
        assert self._tmp_files(state) == []

    def test_failed_backup_swap_after_save_keeps_old_backup(
            self, state, monkeypatch):
        state.set("k", 1)
        state.set("k", 2)
        original_replace = __import__("os").replace

        def replace(src, dst):
            if str(dst) == str(state.backup_path):
                raise OSError("I/O error")
            return original_replace(src, dst)
        monkeypatch.setattr("memanga.persist.os.replace", replace)
        state.set("k", 3)
        assert self._k(state.state_path) == 3
        assert self._k(state.backup_path) == 1
        assert self._tmp_files(state) == []

    def test_config_save_keeps_backup(self, config):
        config.set("delivery.mode", "local")
        config.save()
        first = config.config_path.read_text(encoding="utf-8")
        config.set("delivery.mode", "email")
        config.save()
        backup = config.config_dir / "config.yaml.bak"
        assert backup.read_text(encoding="utf-8") == first
        assert "email" in config.config_path.read_text(encoding="utf-8")


class TestPreserveCorrupt:
    @staticmethod
    def _copies(directory):
        return sorted(directory.glob("state.json.corrupt-*"))

    def test_symlink_to_primary_is_not_taken_as_the_copy(self, isolated_home):
        """A ``state.json.corrupt-*`` symlink pointing at state.json hashes
        identical; reusing it and then removing state.json (no backup)
        would leave only a dangling link."""
        import os
        from memanga.state import State
        cfg = isolated_home / ".config" / "memanga"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "state.json").write_text("{bad")
        link = cfg / "state.json.corrupt-20260101T000000"
        try:
            os.symlink(cfg / "state.json", link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available")

        s = State(config_dir=cfg)
        assert s.preserved_path != link
        assert not s.preserved_path.is_symlink()
        assert s.preserved_path.read_text() == "{bad"
        assert not (cfg / "state.json").exists()  # removed: no backup

    def test_hard_link_to_primary_is_not_taken_as_the_copy(self, tmp_path):
        import os
        from memanga.persist import preserve_corrupt
        target = tmp_path / "state.json"
        target.write_text("{bad")
        alias = tmp_path / "state.json.corrupt-20260101T000000"
        try:
            os.link(target, alias)
        except OSError:
            pytest.skip("hard links not available")
        copy = preserve_corrupt(target)
        assert copy != alias
        assert os.stat(copy).st_ino != os.stat(target).st_ino
        assert copy.read_text() == "{bad"

    def test_copy_still_being_written_is_never_reused(
            self, isolated_home, monkeypatch):
        """Process A has written every byte of its copy but fails before
        it is durable (fsync/mode, e.g. ENOSPC) and removes it. Process B
        starts in between, finds no usable backup and removes state.json
        once it has a copy, so that copy must be B's own: reusing A's
        would leave nothing after A cleans up."""
        import os
        import shutil
        from memanga.state import State
        cfg = isolated_home / ".config" / "memanga"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "state.json").write_text("{damaged bytes")
        real_copy = shutil.copyfileobj
        states = {}

        def copy_then_fail(src, dst, *a, **k):
            real_copy(src, dst, *a, **k)
            if "b" in states:  # B's own copy: no interference
                return
            states["b"] = None
            # A's copy is complete in size and bytes; B starts now.
            assert self._copies(cfg) == []  # A's copy is not visible
            states["b"] = State(config_dir=cfg)
            raise OSError(28, "No space left on device")
        monkeypatch.setattr("memanga.persist.shutil.copyfileobj", copy_then_fail)

        a = State(config_dir=cfg)
        b = states["b"]
        assert "could not be copied for recovery" in a.load_error
        assert b.load_error is None and b.recovery_notice
        assert self._copies(cfg) == [b.preserved_path]
        assert b.preserved_path.read_text() == "{damaged bytes"
        if os.name != "nt":  # Windows cannot remove a file A still has open
            assert not (cfg / "state.json").exists()
        assert [p.name for p in cfg.iterdir() if p.suffix == ".tmp"] == []

    @pytest.mark.parametrize("hard_links", [True, False])
    def test_copy_is_published_only_when_complete(
            self, tmp_path, monkeypatch, hard_links):
        import os
        from memanga.persist import preserve_corrupt
        target = tmp_path / "state.json"
        target.write_text("{bad")
        real_link, real_rename = os.link, os.rename
        seen = []

        def publish_check(src, dst):
            # Before publication the copy holds every byte, under a name
            # the reuse scan does not look at.
            seen.append((open(src).read(), str(dst)))
            assert self._copies(tmp_path) == []

        def link(src, dst, *a, **k):
            if not hard_links:
                raise PermissionError("hard links not supported")
            publish_check(src, dst)
            return real_link(src, dst, *a, **k)

        def rename(src, dst, *a, **k):
            publish_check(src, dst)
            return real_rename(src, dst, *a, **k)
        monkeypatch.setattr("memanga.persist.os.link", link)
        monkeypatch.setattr("memanga.persist.os.rename", rename)
        try:
            copy = preserve_corrupt(target)
        except OSError:
            if hard_links:
                pytest.skip("hard links not available")
            raise
        assert seen == [("{bad", str(copy))]
        assert copy.read_text() == "{bad"
        assert target.read_text() == "{bad"
        assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []

    def test_publication_never_replaces_an_existing_name(
            self, tmp_path, monkeypatch):
        """If the chosen name is somehow taken, publishing fails and the
        existing file is left alone (link: EEXIST; fallback: checked)."""
        from memanga import persist
        target = tmp_path / "state.json"
        target.write_text("{bad")
        import types
        monkeypatch.setattr(persist.secrets, "token_hex", lambda n: "fixed")
        monkeypatch.setattr(persist, "datetime", types.SimpleNamespace(
            now=lambda: types.SimpleNamespace(strftime=lambda f: "20260101T000000")))
        for hard_links in (True, False):
            taken = tmp_path / "state.json.corrupt-20260101T000000-fixed"
            taken.write_text("someone else's copy")
            if not hard_links:
                def no_link(*a, **k):
                    raise PermissionError("hard links not supported")
                monkeypatch.setattr("memanga.persist.os.link", no_link)
            monkeypatch.setattr(persist, "_identical_copy", lambda p: None)
            with pytest.raises(FileExistsError):
                persist.preserve_corrupt(target)
            assert taken.read_text() == "someone else's copy"
            assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
            taken.unlink()

    def test_never_replaces_an_earlier_preserved_copy(self, tmp_path):
        from memanga.persist import preserve_corrupt
        target = tmp_path / "state.json"
        target.write_text("first")
        p1 = preserve_corrupt(target)
        target.write_text("second")
        p2 = preserve_corrupt(target)
        assert p1 != p2
        assert p1.read_text() == "first"
        assert p2.read_text() == "second"
        # The original stays in place for the caller to replace.
        assert target.read_text() == "second"

    def test_identical_bytes_reuse_the_existing_copy(self, tmp_path):
        from memanga.persist import preserve_corrupt
        target = tmp_path / "state.json"
        target.write_text("{same")
        p1 = preserve_corrupt(target)
        p2 = preserve_corrupt(target)
        assert p1 == p2
        assert sorted(tmp_path.glob("state.json.corrupt-*")) == [p1]
        # Same size, different bytes: a new copy, the old one untouched.
        target.write_text("{diff")
        p3 = preserve_corrupt(target)
        assert p3 != p1
        assert p1.read_text() == "{same" and p3.read_text() == "{diff"

    def test_failed_copy_leaves_no_partial_file(self, tmp_path, monkeypatch):
        from memanga.persist import preserve_corrupt
        target = tmp_path / "state.json"
        target.write_text("{bad")

        def fail(src, dst):
            dst.write(b"{b")
            raise OSError("No space left on device")
        monkeypatch.setattr("memanga.persist.shutil.copyfileobj", fail)
        with pytest.raises(OSError):
            preserve_corrupt(target)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
        assert target.read_text() == "{bad"
