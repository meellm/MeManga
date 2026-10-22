"""Tests for the focused state stores behind State (issue #225).

The stores split State's rules by domain but share one state.json, one
lock and one dirty flag. These tests pin:
  - the compatibility wrappers: every flat State method still exists,
    keeps its signature and forwards every argument to its store;
  - the shared backend: stores see the same data, lock and save path;
  - schema compatibility: existing state files load and save unchanged,
    and store writes produce the same keys as before;
  - common CLI and GUI state flows through the store APIs, persisted and
    read back through the old flat methods.
"""

from __future__ import annotations

import inspect
import json
from contextlib import contextmanager

import pytest


# Flat State method -> (store attribute, store method).
WRAPPERS = {
    # state.library
    "merge_missing_manga_state": ("library", "merge_missing"),
    "get_manga_state": ("library", "get_entry"),
    "get_last_chapter": ("library", "get_last_chapter"),
    "set_last_chapter": ("library", "set_last_chapter"),
    "get_downloaded_chapters": ("library", "get_downloaded"),
    "add_downloaded_chapter": ("library", "add_downloaded"),
    "is_chapter_downloaded": ("library", "is_downloaded"),
    "remove_downloaded_chapter": ("library", "remove_downloaded"),
    "set_chapter_groups": ("library", "set_chapter_groups"),
    "get_chapter_groups": ("library", "get_chapter_groups"),
    "mark_external_chapter": ("library", "mark_external"),
    "get_external_chapters": ("library", "get_external"),
    "is_external_chapter": ("library", "is_external"),
    "reset_manga_progress": ("library", "reset_progress"),
    "rename_manga": ("library", "rename"),
    "remove_manga": ("library", "remove"),
    # state.backups
    "get_pending_backup": ("backups", "get_pending"),
    "set_pending_backup": ("backups", "set_pending"),
    "clear_pending_backup": ("backups", "clear_pending"),
    "clear_all_pending_backups": ("backups", "clear_all_pending"),
    "get_all_pending_backups": ("backups", "get_all_pending"),
    "set_suspicious_batch": ("backups", "set_suspicious_batch"),
    "get_suspicious_batch": ("backups", "get_suspicious_batch"),
    "clear_suspicious_batch": ("backups", "clear_suspicious_batch"),
    # state.failures
    "add_failed_chapter": ("failures", "add_failed"),
    "get_failed_chapters": ("failures", "get_failed"),
    "get_all_failed_chapters": ("failures", "get_all_failed"),
    "clear_failed_chapter": ("failures", "clear_failed"),
    "add_partial_chapter": ("failures", "add_partial"),
    "get_partial_chapters": ("failures", "get_partials"),
    "get_partial_chapter": ("failures", "get_partial"),
    "get_all_partial_chapters": ("failures", "get_all_partials"),
    "clear_partial_chapter": ("failures", "clear_partial"),
    # state.activity
    "update_last_check": ("activity", "record_check"),
    "get_check_history": ("activity", "get_check_history"),
    "get_stats": ("activity", "get_stats"),
    "add_download_history": ("activity", "add_download"),
    "get_download_history": ("activity", "get_download_history"),
    # state.reading
    "set_reading_progress": ("reading", "set_progress"),
    "get_reading_progress": ("reading", "get_progress"),
    "get_continue_reading": ("reading", "get_continue_reading"),
    "set_reader_position": ("reading", "set_position"),
    "get_reader_position": ("reading", "get_position"),
    "clear_reader_position": ("reading", "clear_position"),
    "mark_chapter_read": ("reading", "mark_read"),
    "unmark_chapter_read": ("reading", "unmark_read"),
    "is_chapter_read": ("reading", "is_read"),
    "get_read_chapters": ("reading", "get_read"),
    "get_read_count": ("reading", "get_read_count"),
    # state.catalogue
    "set_new_chapters": ("catalogue", "set_new_count"),
    "get_new_chapters": ("catalogue", "get_new_count"),
    "clear_new_chapters": ("catalogue", "clear_new_count"),
    "decrement_new_chapters": ("catalogue", "decrement_new_count"),
    "set_available_chapters": ("catalogue", "set_available"),
    "get_available_chapters": ("catalogue", "get_available"),
    "get_available_chapter_count": ("catalogue", "get_available_count"),
    "get_catalogue_baseline": ("catalogue", "get_baseline"),
    "set_catalogue_baseline": ("catalogue", "set_baseline"),
    # state.notifications
    "add_notification": ("notifications", "add"),
    "get_notifications": ("notifications", "get_recent"),
    "get_unread_count": ("notifications", "get_unread_count"),
    "mark_notifications_read": ("notifications", "mark_all_read"),
    "clear_notifications": ("notifications", "clear"),
    "filter_notifications": ("notifications", "filter"),
    # state.searches
    "add_search_query": ("searches", "add"),
    "get_recent_searches": ("searches", "get_recent"),
    "clear_search_history": ("searches", "clear"),
    # state.source_health
    "update_source_health": ("source_health", "update"),
    "get_source_health": ("source_health", "get"),
    "get_all_source_health": ("source_health", "get_all"),
}

# Public State methods that belong to the persistence layer itself.
CORE_METHODS = {"get", "set", "save", "flush", "clear_all"}

STORE_ATTRS = ("library", "catalogue", "backups", "failures", "reading",
               "notifications", "searches", "activity", "source_health")


def _store_class(attr):
    from memanga import state_stores
    return {
        "library": state_stores.LibraryStore,
        "catalogue": state_stores.CatalogueStore,
        "backups": state_stores.BackupStore,
        "failures": state_stores.FailureStore,
        "reading": state_stores.ReadingStore,
        "notifications": state_stores.NotificationStore,
        "searches": state_stores.SearchHistoryStore,
        "activity": state_stores.ActivityStore,
        "source_health": state_stores.SourceHealthStore,
    }[attr]


def _params(func):
    """Parameters of a method without ``self``, comparable across classes."""
    return [
        (p.name, p.kind, p.default)
        for p in inspect.signature(func).parameters.values()
        if p.name != "self"
    ]


# ─────────────────────────────────────────────────────────────────────────
# Compatibility surface
# ─────────────────────────────────────────────────────────────────────────


class TestCompatibilityWrappers:
    def test_public_surface_is_unchanged(self):
        # Every public method is either the persistence layer or a mapped
        # wrapper, so no flat call used by the CLI/GUI went missing.
        from memanga.state import State
        public = {
            name for name, member in inspect.getmembers(State, inspect.isfunction)
            if not name.startswith("_")
        }
        assert public == CORE_METHODS | set(WRAPPERS)

    def test_legacy_imports_still_work(self):
        from memanga.state import State, StateError, _chapter_number, _chapter_sort_key
        from memanga.state_stores import SourceHealthStore

        assert issubclass(StateError, Exception)
        assert _chapter_number("Chapter 12.5") == 12.5
        assert _chapter_sort_key("extra") == 0.0
        assert State.SLOW_LATENCY_MS == SourceHealthStore.SLOW_LATENCY_MS == 2500

    @pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
    def test_wrapper_signature_matches_store(self, wrapper):
        from memanga.state import State
        attr, method = WRAPPERS[wrapper]
        store_method = getattr(_store_class(attr), method)
        assert _params(getattr(State, wrapper)) == _params(store_method)

    @pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
    def test_wrapper_forwards_every_argument(self, state, monkeypatch, wrapper):
        attr, method = WRAPPERS[wrapper]
        store_cls = _store_class(attr)
        signature = inspect.signature(getattr(store_cls, method))
        calls = []
        result = object()

        def spy(self, *args, **kwargs):
            calls.append((self, signature.bind(self, *args, **kwargs).arguments))
            return result

        monkeypatch.setattr(store_cls, method, spy)

        # A distinct sentinel per parameter, passed the way a caller may.
        sent = {}
        args, kwargs = [], {}
        for param in list(signature.parameters.values())[1:]:
            value = sent[param.name] = object()
            if param.kind is inspect.Parameter.KEYWORD_ONLY:
                kwargs[param.name] = value
            else:
                args.append(value)

        returned = getattr(state, wrapper)(*args, **kwargs)

        assert len(calls) == 1
        store, arguments = calls[0]
        assert store is getattr(state, attr)
        arguments.pop("self")
        assert arguments == sent
        if signature.return_annotation in ("None", None):
            assert returned is None
        else:
            assert returned is result


# ─────────────────────────────────────────────────────────────────────────
# One file, one lock, one dirty flag
# ─────────────────────────────────────────────────────────────────────────


class TestSharedBackend:
    def test_every_store_is_backed_by_the_state(self, state):
        for attr in STORE_ATTRS:
            assert getattr(state, attr)._backend is state

    def test_store_and_wrapper_see_the_same_data(self, state):
        state.library.add_downloaded("X", "1")
        state.add_downloaded_chapter("X", "2")
        assert state.get_downloaded_chapters("X") == ["1", "2"]
        assert state.library.get_downloaded("X") == ["1", "2"]

    def test_stores_follow_clear_all(self, state):
        # clear_all() rebinds _data; stores must not hold the old dict.
        state.reading.mark_read("X", "1")
        state.clear_all()
        assert state.reading.get_read("X") == []
        state.reading.mark_read("Y", "2")
        assert state._data["manga"]["Y"]["read_chapters"] == ["2"]

    def test_store_mutators_take_the_instance_lock(self, state):
        entries = []
        original_locked = state._locked

        @contextmanager
        def recording_locked():
            entries.append(True)
            with original_locked() as data:
                yield data

        state._locked = recording_locked

        state.reading.set_position("X", "1", mode="paged", page_index=2)
        state.catalogue.set_baseline("X", 3)
        state.notifications.add("info", "x")
        state.source_health.update("a.test", True)

        assert len(entries) == 4

    def test_store_mutators_mark_the_shared_dirty_flag(self, state):
        state.flush()
        assert state._dirty is False
        state.searches.add("berserk")
        assert state._dirty is True
        state.flush()
        assert state._dirty is False
        assert json.loads(state.state_path.read_text())["search_history"] == ["berserk"]

    def test_immediate_saves_go_through_state_save(self, state, monkeypatch):
        from memanga.state import State
        saves = []
        original_save = State.save

        def counting_save(self):
            saves.append(self)
            original_save(self)

        monkeypatch.setattr(State, "save", counting_save)

        state.failures.add_failed("X", "1", "src", "boom")
        state.backups.set_pending("X", "2", "backup", "https://b.test/2")
        state.activity.record_check(new_chapters=1)

        assert saves == [state, state, state]


# ─────────────────────────────────────────────────────────────────────────
# Schema compatibility
# ─────────────────────────────────────────────────────────────────────────


LEGACY_STATE = {
    "manga": {
        "Legacy Title": {
            "downloaded": ["1", "2", "3"],
            "last_chapter": "3",
            "last_updated": "2026-05-27T12:00:00",
            "created": "2026-01-01T00:00:00",
            "reading_progress": {"last_chapter": "2", "last_read": "2026-05-27T12:05:00"},
            "new_chapters_available": 2,
            "available_chapters": [
                {"number": "4", "title": "", "source": "src.test",
                 "source_url": "https://src.test/4", "is_backup": False},
            ],
            "external_chapters": ["0.5"],
            "partial_chapters": {
                "3": {"accepted_at": "2026-05-27T12:00:00", "source": "src.test",
                      "failed_pages": [4], "total_pages": 20, "path": "c3.pdf",
                      "from_backup": False},
            },
            "failed_chapters": {
                "5": {"failed_at": "2026-05-27T12:00:00", "source": "src.test",
                      "error": "timeout", "failed_pages": [], "attempts": 2},
            },
            "pending_backup": {
                "6": {"first_seen": "2026-05-27T12:00:00",
                      "backup_source": "backup.test",
                      "backup_url": "https://backup.test/6"},
            },
            "suspicious_batch": {"chapters": [{"number": "90"}], "score": 3},
            "reader_positions": {
                "2": {"mode": "paged", "updated_at": "2026-05-27T12:05:00",
                      "page_index": 7},
            },
            "read_chapters": ["1", "2"],
            "saved_chapter_groups": {
                "1": {"source": "src.test", "group_ids": ["g1"],
                      "group_names": ["Group"]},
            },
            "catalogue_baseline": 4.0,
        },
    },
    "last_check": "2026-05-27T12:00:00",
    "check_history": [
        {"timestamp": "2026-05-27T12:00:00", "new_chapters": 2, "downloaded": 1},
    ],
    "notifications": [
        {"type": "check", "message": "Found 2 new chapter(s)",
         "timestamp": "2026-05-27T12:00:00", "read": False},
    ],
    "download_history": [
        {"title": "Legacy Title", "chapter": "3", "format": "pdf",
         "path": "c3.pdf", "size_mb": 4.2, "kindle_sent": False,
         "timestamp": "2026-05-27T12:01:30"},
    ],
    "source_health": {
        "src.test": {"status": "ok", "last_success": "2026-05-27T12:00:00",
                     "latency_ms": 220, "error_count": 0},
    },
    "search_history": ["legacy"],
    "custom_key": {"kept": True},
}


@pytest.fixture
def legacy_state(isolated_home):
    from memanga.state import State
    cfg = isolated_home / ".config" / "memanga"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "state.json").write_text(json.dumps(LEGACY_STATE))
    return State(config_dir=cfg)


class TestSchemaCompatibility:
    def test_default_top_level_keys_unchanged(self, state):
        assert set(state._data) == {
            "schema_version", "manga", "last_check", "check_history",
            "notifications", "download_history", "source_health",
        }

    def test_new_manga_entry_keys_unchanged(self, state):
        state.library.add_downloaded("X", "1")
        assert set(state._data["manga"]["X"]) == {
            "downloaded", "last_chapter", "last_updated", "created",
            "reading_progress", "new_chapters_available",
            "available_chapters", "external_chapters", "partial_chapters",
        }

    def test_existing_file_round_trips_unchanged(self, legacy_state):
        # Only the schema version (issue #409) is added on save.
        legacy_state.save()
        assert json.loads(legacy_state.state_path.read_text()) == {
            **LEGACY_STATE, "schema_version": 1}

    def test_stores_read_existing_file(self, legacy_state):
        s, title = legacy_state, "Legacy Title"
        assert s.library.get_downloaded(title) == ["1", "2", "3"]
        assert s.library.get_external(title) == ["0.5"]
        assert s.library.get_chapter_groups(title, "1")["group_names"] == ["Group"]
        assert s.catalogue.get_available_count(title) == 1
        assert s.catalogue.get_baseline(title) == 4.0
        assert s.catalogue.get_new_count(title) == 2
        assert s.failures.get_failed(title)["5"]["attempts"] == 2
        assert s.failures.get_partial(title, "3")["total_pages"] == 20
        assert s.backups.get_pending(title, "6")["backup_source"] == "backup.test"
        assert s.backups.get_suspicious_batch(title)["score"] == 3
        assert s.reading.get_position(title, "2")["page_index"] == 7
        assert s.reading.get_read_count(title) == 2
        assert s.reading.get_continue_reading()["title"] == title
        assert s.notifications.get_unread_count() == 1
        assert s.searches.get_recent() == ["legacy"]
        assert s.activity.get_stats() == {
            "total_manga": 1, "total_chapters": 3,
            "last_check": "2026-05-27T12:00:00", "checks_logged": 1,
        }
        assert s.source_health.get("src.test")["latency_ms"] == 220
        assert s.get("custom_key") == {"kept": True}

    def test_store_writes_keep_serialized_keys(self, state):
        t = "X"
        state.failures.add_failed(t, "1", "src", "boom", failed_pages=[2])
        state.failures.add_partial(t, "2", "src", [3], 10, "c2.pdf", True)
        state.backups.set_pending(t, "3", "backup", "https://b.test/3")
        state.backups.set_suspicious_batch(t, {"chapters": ["9"]})
        state.library.set_chapter_groups(t, "1", "src", ["g"], ["G"])
        state.library.mark_external(t, "0")
        state.reading.set_progress(t, "1")
        state.reading.set_position(t, "1", mode="scroll", scroll_ratio=0.5)
        state.reading.mark_read(t, "1")
        state.catalogue.set_available(t, [{"number": "4"}])
        state.catalogue.set_new_count(t, 1)
        state.catalogue.set_baseline(t, 4)
        state.notifications.add("check", "found")
        state.searches.add("query")
        state.activity.add_download(t, "1", "pdf", source="src")
        state.activity.record_check(new_chapters=1, downloaded=1)
        state.source_health.update("src.test", False, "down", latency_ms=10)
        state.flush()

        data = json.loads(state.state_path.read_text())
        entry = data["manga"][t]
        assert set(entry["failed_chapters"]["1"]) == {
            "failed_at", "source", "error", "failed_pages", "attempts"}
        assert set(entry["partial_chapters"]["2"]) == {
            "accepted_at", "source", "failed_pages", "total_pages", "path",
            "from_backup"}
        assert set(entry["pending_backup"]["3"]) == {
            "first_seen", "backup_source", "backup_url"}
        assert entry["suspicious_batch"] == {"chapters": ["9"]}
        assert entry["saved_chapter_groups"]["1"] == {
            "source": "src", "group_ids": ["g"], "group_names": ["G"]}
        assert entry["external_chapters"] == ["0"]
        assert set(entry["reading_progress"]) == {"last_chapter", "last_read"}
        assert set(entry["reader_positions"]["1"]) == {
            "mode", "updated_at", "scroll_ratio"}
        assert entry["read_chapters"] == ["1"]
        assert entry["available_chapters"] == [{"number": "4"}]
        assert entry["new_chapters_available"] == 1
        assert entry["catalogue_baseline"] == 4.0
        assert set(data["notifications"][0]) == {"type", "message", "timestamp", "read"}
        assert data["search_history"] == ["query"]
        assert set(data["download_history"][0]) == {
            "title", "chapter", "format", "path", "size_mb", "kindle_sent",
            "source", "from_backup", "partial", "deleted_after_send",
            "timestamp"}
        assert set(data["check_history"][0]) == {"timestamp", "new_chapters", "downloaded"}
        assert set(data["source_health"]["src.test"]) == {
            "error_count", "last_error", "last_error_msg", "status", "latency_ms"}
        assert data["last_check"] == data["check_history"][0]["timestamp"]

    def test_notification_details_are_optional_and_redacted(self, state):
        # Issue #342: the full error behind a short message, never a secret.
        state.notifications.add("error", "Check failed: X - short…",
                                details="boom password=hunter22 at end")
        state.notifications.add("error", "plain")
        state.notifications.add("error", "blank", details="")
        s = _reload(state)
        blank, plain, detailed = s.get_notifications()
        assert detailed["details"] == "boom password=*** at end"
        assert "details" not in plain
        assert "details" not in blank

    def test_long_details_kept_whole_in_a_private_side_file(self, state):
        # Issue #342: the actionable tail after the inline preview is not
        # lost; state.json keeps only the preview and a file name.
        import os
        from memanga.output import DETAIL_MAX_CHARS
        error = "x" * (DETAIL_MAX_CHARS + 500) + " token=abc123 CAUSE: refused"
        state.notifications.add("error", "Failed: T - x…", details=error)
        state.flush()

        note = json.loads(state.state_path.read_text())["notifications"][0]
        assert len(note["details"]) == DETAIL_MAX_CHARS
        assert note["details_chars"] > DETAIL_MAX_CHARS
        assert "/" not in note["details_file"] and "\\" not in note["details_file"]

        text, complete = state.notifications.full_details(note)
        assert complete
        assert text.endswith("token=*** CAUSE: refused")
        assert "abc123" not in text
        path = state.config_dir / "error-details" / note["details_file"]
        if os.name == "posix":
            assert path.stat().st_mode & 0o077 == 0

    def test_runaway_details_are_bounded_and_flagged(self, state, monkeypatch):
        from memanga.state_stores import NotificationStore
        monkeypatch.setattr(NotificationStore, "FULL_DETAILS_MAX_CHARS", 6000)
        state.notifications.add("error", "m", details="y" * 9000)
        note = state.get_notifications()[0]
        text, complete = state.notifications.full_details(note)
        assert len(text) == 6000
        assert not complete

    def test_missing_or_foreign_side_file_falls_back_to_preview(self, state):
        from memanga.output import DETAIL_MAX_CHARS
        state.notifications.add("error", "m", details="z" * (DETAIL_MAX_CHARS + 1))
        note = state.get_notifications()[0]
        (state.config_dir / "error-details" / note["details_file"]).unlink()
        text, complete = state.notifications.full_details(note)
        assert text == note["details"] and not complete

        outside = state.config_dir / "secret.txt"
        outside.write_text("not for the dialog", encoding="utf-8")
        forged = dict(note, details_file="../secret.txt")
        text, complete = state.notifications.full_details(forged)
        assert text == note["details"] and not complete

    def test_side_files_go_with_their_notifications(self, state, monkeypatch):
        from memanga.output import DETAIL_MAX_CHARS
        from memanga.state_stores import NotificationStore
        folder = state.config_dir / "error-details"
        monkeypatch.setattr(NotificationStore, "MAX_NOTIFICATIONS", 2)
        long = "w" * (DETAIL_MAX_CHARS + 1)
        state.notifications.add("error", "a", details=long)
        state.notifications.add("error", "b", details=long)
        assert len(list(folder.glob("*.txt"))) == 2
        state.notifications.add("error", "c", details="short")
        # "a" dropped off the capped log, and its file with it.
        assert len(list(folder.glob("*.txt"))) == 1
        state.notifications.clear()
        assert list(folder.glob("*.txt")) == []

    def test_only_newest_long_errors_keep_a_side_file(self, state,
                                                      monkeypatch):
        # Bounded disk use: older long errors keep their preview and are
        # then reported as partial, never as complete.
        from memanga.output import DETAIL_MAX_CHARS
        from memanga.state_stores import NotificationStore
        monkeypatch.setattr(NotificationStore, "MAX_DETAIL_FILES", 1)
        folder = state.config_dir / "error-details"
        long = "v" * (DETAIL_MAX_CHARS + 10)
        state.notifications.add("error", "old", details=long + " OLD")
        state.notifications.add("error", "new", details=long + " NEW")

        assert len(list(folder.glob("*.txt"))) == 1
        new, old = state.get_notifications()
        assert "details_file" not in old
        text, complete = state.notifications.full_details(old)
        assert not complete and text == old["details"]
        text, complete = state.notifications.full_details(new)
        assert complete and text.endswith(" NEW")

    def test_concurrent_add_cannot_lose_a_new_side_file(self, state,
                                                        monkeypatch):
        # A cap-drop prune from another thread must not delete the side
        # file of an entry still being added (issue #342 review).
        import threading
        from memanga.output import DETAIL_MAX_CHARS
        from memanga.state_stores import NotificationStore
        from memanga.state_stores import notifications as notif_mod
        monkeypatch.setattr(NotificationStore, "MAX_NOTIFICATIONS", 2)
        long = "u" * (DETAIL_MAX_CHARS + 10)
        state.notifications.add("error", "oldest", details=long)
        state.notifications.add("error", "short", details="x")

        writing, release = threading.Event(), threading.Event()
        real_write = notif_mod.atomic_write_text

        def slow_write(path, text, *a, **k):
            real_write(path, text, *a, **k)
            writing.set()
            release.wait(5)
        monkeypatch.setattr(notif_mod, "atomic_write_text", slow_write)

        adder = threading.Thread(target=state.notifications.add,
                                 args=("error", "A", long + " A-TAIL"))
        adder.start()
        assert writing.wait(5)
        other = threading.Thread(target=state.notifications.add,
                                 args=("error", "B", "short"))
        other.start()
        other.join(0.3)  # blocked on the state lock while A writes
        release.set()
        adder.join(5)
        other.join(5)
        assert not adder.is_alive() and not other.is_alive()

        a = next(n for n in state.get_notifications() if n["message"] == "A")
        text, complete = state.notifications.full_details(a)
        assert complete and text.endswith(" A-TAIL")

    def test_source_health_keeps_the_whole_redacted_error(self, state):
        error = ("HTTPSConnectionPool(host='127.0.0.1', port=9): Max retries "
                 "exceeded with url: /x?token=abc123 (Caused by "
                 "NewConnectionError('Connection refused'))")
        state.source_health.update("src.test", False, error)
        msg = state.source_health.get("src.test")["last_error_msg"]
        assert msg.endswith("Connection refused'))")
        assert "abc123" not in msg

    def test_caps_unchanged(self, state):
        from memanga.state_stores import ActivityStore, NotificationStore
        assert NotificationStore.MAX_NOTIFICATIONS == 100
        assert ActivityStore.MAX_CHECKS == 50
        assert ActivityStore.MAX_DOWNLOADS == 200
        for i in range(55):
            state.activity.record_check(new_chapters=i)
        assert len(state._data["check_history"]) == 50
        assert state.get_check_history(limit=1)[0]["new_chapters"] == 54


# ─────────────────────────────────────────────────────────────────────────
# Common flows through the stores, read back after a restart
# ─────────────────────────────────────────────────────────────────────────


def _reload(state):
    from memanga.state import State
    state.flush()
    return State(config_dir=state.config_dir)


class TestCliFlow:
    def test_check_download_failure_retry_cycle(self, state):
        t = "Series"
        # A check sees a chapter only on the backup source and a new one
        # on the primary; the primary download fails once.
        state.backups.set_pending(t, "11", "backup.test", "https://b.test/11")
        state.catalogue.set_available(t, [{"number": "10"}, {"number": "11"}])
        state.catalogue.set_new_count(t, 2)
        state.failures.add_failed(t, "10", "src.test", "HTTP 500", failed_pages=[1])
        state.source_health.update("src.test", False, "HTTP 500")
        state.activity.record_check(new_chapters=2, downloaded=0)

        # The retry succeeds; chapter 11 arrives partially from the backup.
        state.library.add_downloaded(t, "10")
        state.failures.clear_failed(t, "10")
        state.activity.add_download(t, "10", "pdf", "c10.pdf", 3.456,
                                    source="src.test")
        state.library.add_downloaded(t, "11")
        state.failures.add_partial(t, "11", "backup.test", [5], 20, "c11.pdf", True)
        state.backups.clear_pending(t, "11")
        state.activity.add_download(t, "11", "pdf", "c11.pdf", 1, source="backup.test",
                                    from_backup=True, partial=True)
        state.catalogue.clear_new_count(t)
        state.source_health.update("src.test", True, latency_ms=300)

        s = _reload(state)
        assert s.get_downloaded_chapters(t) == ["10", "11"]
        assert s.get_last_chapter(t) == "11"
        assert s.get_failed_chapters(t) == {}
        assert s.get_all_failed_chapters() == {}
        assert list(s.get_all_partial_chapters()) == [t]
        assert s.get_partial_chapter(t, "11")["from_backup"] is True
        assert s.get_all_pending_backups(t) == {}
        assert s.get_new_chapters(t) == 0
        history = s.get_download_history()
        assert [h["chapter"] for h in history] == ["11", "10"]
        assert history[1]["size_mb"] == 3.46
        assert history[0]["partial"] is True
        assert s.get_source_health("src.test")["status"] == "ok"
        assert s.get_source_health("src.test")["error_count"] == 0
        assert s.get_stats()["total_chapters"] == 2
        assert s.get_check_history()[0]["new_chapters"] == 2

    def test_undelivered_record_cycle(self, state):
        # Issue #360: a chapter saved but not sent to Kindle stays on
        # record, counts its attempts and is cleared once sent.
        t = "Series"
        state.library.add_downloaded(t, "4")
        state.failures.add_undelivered(t, "4", "c4.pdf", "SMTP down")
        state.failures.add_undelivered(t, "4", "c4.pdf", "x" * 400)
        state.failures.add_undelivered(t, "5", "c5.pdf", "auth failed")

        s = _reload(state)
        record = s.failures.get_undelivered(t)["4"]
        assert (record["path"], record["attempts"]) == ("c4.pdf", 2)
        # UTC with an offset and a fixed fraction, so backups order it.
        from datetime import datetime, timezone
        failed_at = datetime.fromisoformat(record["failed_at"])
        assert failed_at.tzinfo is not None
        assert failed_at.utcoffset() == timezone.utc.utcoffset(None)
        assert len(record["failed_at"]) == len("2026-10-22T08:00:00.000000+00:00")
        assert record["error"] == "x" * 300
        assert sorted(s.failures.get_all_undelivered()[t]) == ["4", "5"]
        # Download records are a separate list.
        assert s.get_all_failed_chapters() == {}

        s.failures.clear_undelivered(t, "4")
        s.failures.clear_undelivered(t, "5")
        s.failures.clear_undelivered(t, "missing")
        s = _reload(s)
        assert s.failures.get_undelivered(t) == {}
        assert s.failures.get_all_undelivered() == {}
        assert s.get_downloaded_chapters(t) == ["4"]
        # The resolutions persist (backup merges rely on them); clearing
        # a chapter with no record leaves none.
        resolved = s.get_manga_state(t)["resolved_deliveries"]
        assert sorted(resolved) == ["4", "5"]
        assert resolved["4"]["reason"] == "cleared"
        assert resolved["4"]["resolved_at"].endswith("+00:00")

        # A new failure supersedes the resolution.
        s.failures.add_undelivered(t, "4", "c4.pdf", "SMTP down")
        assert "4" not in s.get_manga_state(t)["resolved_deliveries"]

    def test_undelivered_split_progress(self, state):
        # Issue #364: the parts the mail server accepted are kept until a
        # later failure reports new progress or the chapter is sent.
        t = "Series"
        parts = {"total": 3, "accepted": [1]}
        state.failures.add_undelivered(t, "4", "c4.pdf", "part 2 failed",
                                       parts=parts)
        parts["accepted"].append(2)  # the caller's dict is not stored
        state.failures.add_undelivered(t, "4", "c4.pdf", "auth failed")

        s = _reload(state)
        record = s.failures.get_undelivered(t)["4"]
        assert (record["parts"], record["attempts"]) == (
            {"total": 3, "accepted": [1]}, 2)

        s.failures.add_undelivered(t, "4", "c4.pdf", "part 3 failed",
                                   parts={"total": 3, "accepted": [1, 2]})
        assert s.failures.get_undelivered(t)["4"]["parts"]["accepted"] == [1, 2]
        # A record without split progress has no ``parts`` key.
        s.failures.add_undelivered(t, "5", "c5.pdf", "SMTP down")
        assert "parts" not in s.failures.get_undelivered(t)["5"]

        s.failures.clear_undelivered(t, "4", reason="sent")
        s.failures.add_undelivered(t, "4", "c4.pdf", "SMTP down")
        assert "parts" not in s.failures.get_undelivered(t)["4"]

    def test_reset_and_rename(self, state):
        state.library.add_downloaded("Old", "1")
        state.library.add_downloaded("Old", "2")
        state.library.reset_progress("Old", from_chapter=2)
        assert state.library.rename("Old", "New") is True
        s = _reload(state)
        assert s.get_manga_state("Old") == {}
        assert s.get_downloaded_chapters("New") == ["1"]
        assert s.get_last_chapter("New") is None

    def test_mark_download_sent_updates_only_the_unsent_entry(self, state):
        # Issue #338: a later successful send updates the chapter's own
        # history entry; other entries keep what they said.
        a = state.activity
        a.add_download("T", "1", "pdf", "old.pdf", 1, True)
        a.add_download("T", "1", "pdf", "c1.pdf", 1)
        a.add_download("T", "2", "pdf", "c2.pdf", 1)
        a.add_download("U", "1", "pdf", "u1.pdf", 1)

        assert a.mark_download_sent("T", "1", "other.pdf") is False
        assert a.mark_download_sent("T", "1", "c1.pdf",
                                    deleted_after_send=True) is True
        assert a.mark_download_sent("T", "1", "c1.pdf") is False

        s = _reload(state)
        status = {h["path"]: (h["kindle_sent"], h["deleted_after_send"])
                  for h in s.get_download_history()}
        assert status == {"old.pdf": (True, False), "c1.pdf": (True, True),
                          "c2.pdf": (False, False), "u1.pdf": (False, False)}

    def test_mark_download_sent_keeps_old_entries_compatible(self, state):
        # An entry logged before #338 has no deleted_after_send key.
        state.activity.add_download("T", "1", "pdf", "c1.pdf", 1)
        with state._locked() as data:
            data["download_history"][0].pop("deleted_after_send")

        assert state.activity.mark_download_sent("T", "1") is True
        entry = _reload(state).get_download_history()[0]
        assert (entry["kindle_sent"], entry["deleted_after_send"]) == (True, False)


class TestGuiFlow:
    def test_reader_detail_and_library_badges(self, state):
        t = "Series"
        state.catalogue.set_available(t, [{"number": str(n)} for n in range(1, 6)])
        state.catalogue.set_new_count(t, 3)
        state.catalogue.decrement_new_count(t)
        state.library.add_downloaded(t, "1")
        state.library.mark_external(t, "0")

        state.reading.set_progress(t, "1")
        state.reading.mark_read(t, "1")
        state.reading.mark_read(t, "2")
        state.reading.unmark_read(t, "2")
        state.reading.set_position(t, "1", mode="paged", page_index=-4)
        state.reading.set_position(t, "3", mode="scroll", scroll_ratio=2.0)
        state.reading.clear_position(t, "3")

        s = _reload(state)
        assert s.get_available_chapter_count(t) == 5
        assert s.get_new_chapters(t) == 2
        assert s.is_external_chapter(t, "0") is True
        assert s.is_chapter_read(t, "1") is True
        assert s.is_chapter_read(t, "2") is False
        assert s.get_read_count(t) == 1
        assert s.get_reader_position(t, "1")["page_index"] == 0
        assert s.get_reader_position(t, "3") is None
        assert s.get_continue_reading()["last_chapter"] == "1"

    def test_notification_chips_and_recent_searches(self, state):
        state.notifications.add("check", "new")
        state.notifications.add("download", "saved")
        state.notifications.add("error", "failed")
        state.searches.add("One Piece")
        state.searches.add("berserk")
        state.searches.add("one piece")

        s = _reload(state)
        assert s.get_unread_count() == 3
        assert [n["message"] for n in s.filter_notifications("downloads")] == ["saved"]
        assert [n["message"] for n in s.filter_notifications("system")] == ["failed"]
        assert [n["message"] for n in s.get_notifications()] == ["failed", "saved", "new"]
        assert s.get_recent_searches() == ["one piece", "berserk"]

        s.notifications.mark_all_read()
        assert s.get_unread_count() == 0
        s.notifications.clear()
        s.searches.clear()
        s = _reload(s)
        assert s.get_notifications() == []
        assert s.get_recent_searches() == []
