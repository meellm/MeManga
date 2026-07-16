"""Exhaustive tests for memanga.state.State.

State is the JSON-backed bag of everything-the-GUI-needs-to-remember.
We test every public method here, including edge cases (missing manga,
malformed numbers, idempotency, persistence round-trips).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Construction + persistence
# ─────────────────────────────────────────────────────────────────────────


class TestStateLifecycle:
    def test_creates_config_dir_if_missing(self, isolated_home):
        from memanga.state import State
        d = isolated_home / "fresh-test"
        assert not d.exists()
        s = State(config_dir=d)
        assert d.exists()
        assert s.state_path.parent == d

    def test_starts_with_default_structure(self, state):
        # Default state has all the expected top-level keys.
        for key in ("manga", "notifications", "check_history",
                    "download_history", "source_health"):
            assert key in state._data, f"missing default key: {key}"

    def test_flush_writes_json(self, state):
        state.add_notification("info", "hello")
        state.flush()
        assert state.state_path.exists()
        data = json.loads(state.state_path.read_text())
        assert any(n["message"] == "hello" for n in data["notifications"])

    def test_corrupted_state_file_falls_back_to_defaults(self, isolated_home):
        from memanga.state import State
        d = isolated_home / ".config" / "memanga"
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text("{this is not json")
        # Should not raise — falls back to defaults.
        s = State(config_dir=d)
        assert s.get_notifications() == []

    def test_get_set_arbitrary_key(self, state):
        state.set("custom_key", {"a": 1})
        assert state.get("custom_key") == {"a": 1}

    def test_dirty_flag_set_on_mutation(self, state):
        # Pristine state should not be dirty.
        state._dirty = False
        state.add_notification("info", "x")
        assert state._dirty is True


# ─────────────────────────────────────────────────────────────────────────
# Chapter tracking — downloaded / last / external / read (issue #18)
# ─────────────────────────────────────────────────────────────────────────


class TestChapterTracking:
    def test_add_downloaded_chapter_is_idempotent(self, state):
        state.add_downloaded_chapter("X", "5")
        state.add_downloaded_chapter("X", "5")
        assert state.get_downloaded_chapters("X") == ["5"]

    def test_is_chapter_downloaded(self, state):
        state.add_downloaded_chapter("X", "1")
        assert state.is_chapter_downloaded("X", "1")
        assert not state.is_chapter_downloaded("X", "2")
        assert not state.is_chapter_downloaded("Y", "1")

    def test_set_last_chapter(self, state):
        state.set_last_chapter("X", "10")
        assert state.get_last_chapter("X") == "10"

    def test_set_last_chapter_none_clears(self, state):
        state.set_last_chapter("X", "10")
        state.set_last_chapter("X", None)
        assert state.get_last_chapter("X") is None

    def test_get_last_chapter_unknown_manga(self, state):
        assert state.get_last_chapter("never-added") is None

    def test_get_manga_state_unknown_returns_empty(self, state):
        # Should not raise — returns an empty-ish dict.
        st = state.get_manga_state("never-added")
        assert isinstance(st, dict)


class TestExternalChapters:
    def test_mark_and_check_external(self, state):
        state.mark_external_chapter("X", "3")
        assert state.is_external_chapter("X", "3")
        assert not state.is_external_chapter("X", "4")

    def test_external_chapters_list(self, state):
        state.mark_external_chapter("X", "1")
        state.mark_external_chapter("X", "2")
        ext = state.get_external_chapters("X")
        assert "1" in ext and "2" in ext

    def test_available_chapters_set_and_get(self, state):
        chapters = [{"number": "1", "title": "first"},
                    {"number": "2", "title": "second"}]
        state.set_available_chapters("X", chapters)
        assert state.get_available_chapters("X") == chapters


class TestReadChapters:
    """Issue #18 — per-chapter read tracking."""

    def test_mark_chapter_read_is_idempotent(self, state):
        state.mark_chapter_read("X", "5")
        state.mark_chapter_read("X", "5")
        assert state.get_read_chapters("X") == ["5"]
        assert state.get_read_count("X") == 1

    def test_unmark_chapter_read(self, state):
        state.mark_chapter_read("X", "5")
        state.unmark_chapter_read("X", "5")
        assert state.get_read_chapters("X") == []

    def test_unmark_unknown_is_noop(self, state):
        state.unmark_chapter_read("never", "1")  # must not raise

    def test_is_chapter_read(self, state):
        state.mark_chapter_read("X", "1")
        assert state.is_chapter_read("X", "1")
        assert not state.is_chapter_read("X", "2")

    def test_blank_chapter_id_ignored(self, state):
        state.mark_chapter_read("X", "")
        state.mark_chapter_read("X", None)  # type: ignore
        assert state.get_read_chapters("X") == []


# ─────────────────────────────────────────────────────────────────────────
# Reading progress
# ─────────────────────────────────────────────────────────────────────────


class TestReadingProgress:
    def test_set_reading_progress_writes_chapter_and_timestamp(self, state):
        state.set_reading_progress("X", "7")
        rp = state.get_reading_progress("X")
        assert rp["last_chapter"] == "7"
        assert rp["last_read"]  # ISO timestamp string

    def test_get_continue_reading_picks_most_recent(self, state):
        state.set_reading_progress("Old", "1")
        # Ensure two distinct ISO timestamps.
        import time; time.sleep(0.01)
        state.set_reading_progress("New", "5")
        cr = state.get_continue_reading()
        assert cr["title"] == "New"

    def test_get_continue_reading_none_when_empty(self, state):
        assert state.get_continue_reading() is None


class TestReaderPosition:
    """Issue #106 — per-chapter in-reader resume position."""

    def test_set_and_get_paged_position(self, state):
        state.set_reader_position("X", "7", mode="paged", page_index=12)
        pos = state.get_reader_position("X", "7")
        assert pos["mode"] == "paged"
        assert pos["page_index"] == 12
        assert "scroll_ratio" not in pos
        assert pos["updated_at"]  # ISO timestamp string

    def test_set_and_get_scroll_position(self, state):
        state.set_reader_position("X", "7", mode="webtoon", scroll_ratio=0.42)
        pos = state.get_reader_position("X", "7")
        assert pos["mode"] == "webtoon"
        assert pos["scroll_ratio"] == pytest.approx(0.42)
        assert "page_index" not in pos

    def test_positions_are_per_chapter(self, state):
        state.set_reader_position("X", "1", mode="paged", page_index=3)
        state.set_reader_position("X", "2", mode="paged", page_index=9)
        assert state.get_reader_position("X", "1")["page_index"] == 3
        assert state.get_reader_position("X", "2")["page_index"] == 9

    def test_set_overwrites_previous(self, state):
        state.set_reader_position("X", "1", mode="paged", page_index=3)
        state.set_reader_position("X", "1", mode="webtoon", scroll_ratio=0.5)
        pos = state.get_reader_position("X", "1")
        assert pos["mode"] == "webtoon"
        assert "page_index" not in pos

    def test_page_index_clamped_nonnegative(self, state):
        state.set_reader_position("X", "1", mode="paged", page_index=-5)
        assert state.get_reader_position("X", "1")["page_index"] == 0

    def test_scroll_ratio_clamped_to_unit_range(self, state):
        state.set_reader_position("X", "1", mode="webtoon", scroll_ratio=1.7)
        assert state.get_reader_position("X", "1")["scroll_ratio"] == 1.0
        state.set_reader_position("X", "2", mode="webtoon", scroll_ratio=-0.3)
        assert state.get_reader_position("X", "2")["scroll_ratio"] == 0.0

    def test_chapter_keys_are_stringified(self, state):
        state.set_reader_position("X", 7, mode="paged", page_index=1)
        assert state.get_reader_position("X", "7")["page_index"] == 1

    def test_get_unknown_manga_or_chapter_returns_none(self, state):
        assert state.get_reader_position("never-added", "1") is None
        state.set_reader_position("X", "1", mode="paged", page_index=0)
        assert state.get_reader_position("X", "99") is None

    def test_clear_reader_position(self, state):
        state.set_reader_position("X", "1", mode="paged", page_index=4)
        state.clear_reader_position("X", "1")
        assert state.get_reader_position("X", "1") is None

    def test_clear_unknown_is_noop(self, state):
        state.clear_reader_position("never-added", "1")  # must not raise
        state.set_reader_position("X", "1", mode="paged", page_index=0)
        state.clear_reader_position("X", "99")  # must not raise

    def test_blank_chapter_id_ignored(self, state):
        state.set_reader_position("X", "", mode="paged", page_index=1)
        state.set_reader_position("X", None, mode="paged", page_index=1)
        assert state.get_manga_state("X").get("reader_positions", {}) == {}

    def test_old_state_file_without_reader_positions(self, state):
        # Entry created before the feature existed lacks the key entirely.
        state._ensure_manga_entry("Legacy")
        state._data["manga"]["Legacy"].pop("reader_positions", None)
        assert state.get_reader_position("Legacy", "1") is None
        state.clear_reader_position("Legacy", "1")  # must not raise
        state.set_reader_position("Legacy", "1", mode="paged", page_index=2)
        assert state.get_reader_position("Legacy", "1")["page_index"] == 2


# ─────────────────────────────────────────────────────────────────────────
# Notifications + filter API (issue #18)
# ─────────────────────────────────────────────────────────────────────────


class TestNotifications:
    def test_add_then_get(self, state):
        state.add_notification("info", "hello")
        n = state.get_notifications()
        assert len(n) == 1
        assert n[0]["message"] == "hello"
        assert n[0]["type"] == "info"

    def test_unread_count(self, state):
        state.add_notification("info", "a")
        state.add_notification("info", "b")
        assert state.get_unread_count() == 2
        state.mark_notifications_read()
        assert state.get_unread_count() == 0

    def test_clear_notifications(self, state):
        state.add_notification("info", "a")
        state.clear_notifications()
        assert state.get_notifications() == []

    def test_filter_by_category(self, state):
        state.add_notification("check", "new chapters")
        state.add_notification("download", "downloaded x")
        state.add_notification("error", "oops")
        assert all(n["type"] == "check"
                   for n in state.filter_notifications("new"))
        assert all(n["type"] == "download"
                   for n in state.filter_notifications("downloads"))
        assert all(n["type"] == "error"
                   for n in state.filter_notifications("system"))
        assert len(state.filter_notifications("all")) == 3

    def test_notification_capped_at_100(self, state):
        for i in range(150):
            state.add_notification("info", f"n{i}")
        assert len(state._data["notifications"]) <= 100


# ─────────────────────────────────────────────────────────────────────────
# Search history (issue #16 dependency)
# ─────────────────────────────────────────────────────────────────────────


class TestSearchHistory:
    def test_recent_queries_lifo(self, state):
        state.add_search_query("first")
        state.add_search_query("second")
        recents = state.get_recent_searches()
        assert recents[0] == "second"

    def test_dedupe_case_insensitive(self, state):
        state.add_search_query("Naruto")
        state.add_search_query("naruto")
        assert len(state.get_recent_searches()) == 1

    def test_capped_at_limit(self, state):
        for i in range(20):
            state.add_search_query(f"q{i}")
        assert len(state.get_recent_searches(limit=8)) <= 8

    def test_blank_query_ignored(self, state):
        state.add_search_query("")
        state.add_search_query("   ")
        assert state.get_recent_searches() == []

    def test_clear_search_history(self, state):
        state.add_search_query("x")
        state.clear_search_history()
        assert state.get_recent_searches() == []


# ─────────────────────────────────────────────────────────────────────────
# Source health
# ─────────────────────────────────────────────────────────────────────────


class TestSourceHealth:
    def test_success_updates_status_ok(self, state):
        state.update_source_health("mangadex.org", True, latency_ms=120)
        h = state.get_source_health("mangadex.org")
        assert h["status"] == "ok"
        assert h["latency_ms"] == 120

    def test_moderate_latency_stays_ok(self, state):
        # Sub-threshold responses are normal network variance, not a
        # problem — they must not be flagged. Regression test for the
        # old 500 ms threshold that painted healthy sources "warning".
        for latency in (589, 635, 711, state.SLOW_LATENCY_MS):
            state.update_source_health("ok.test", True, latency_ms=latency)
            assert state.get_source_health("ok.test")["status"] == "ok"

    def test_slow_latency_flagged_warning(self, state):
        state.update_source_health(
            "slow.test", True, latency_ms=state.SLOW_LATENCY_MS + 1,
        )
        assert state.get_source_health("slow.test")["status"] == "warning"

    def test_repeated_failures_escalate_to_error(self, state):
        for _ in range(4):
            state.update_source_health("dead.test", False, "timeout")
        assert state.get_source_health("dead.test")["status"] == "error"

    def test_get_all_source_health_returns_dict(self, state):
        state.update_source_health("a.test", True, latency_ms=50)
        state.update_source_health("b.test", True, latency_ms=80)
        all_h = state.get_all_source_health()
        assert "a.test" in all_h and "b.test" in all_h


# ─────────────────────────────────────────────────────────────────────────
# Reset / wipe behaviors
# ─────────────────────────────────────────────────────────────────────────


class TestResetManga:
    def test_reset_with_zero_clears_all(self, state):
        state.add_downloaded_chapter("X", "1")
        state.add_downloaded_chapter("X", "2")
        state.set_last_chapter("X", "2")
        state.reset_manga_progress("X", from_chapter=0)
        assert state.get_downloaded_chapters("X") == []
        assert state.get_last_chapter("X") is None

    def test_reset_with_threshold_keeps_lower_chapters(self, state):
        for c in ["1", "2", "3", "4", "5"]:
            state.add_downloaded_chapter("X", c)
        state.reset_manga_progress("X", from_chapter=3)
        kept = state.get_downloaded_chapters("X")
        # Only chapters strictly < 3 survive
        assert "1" in kept and "2" in kept
        assert "3" not in kept and "4" not in kept and "5" not in kept

    def test_remove_manga(self, state):
        state.add_downloaded_chapter("X", "1")
        assert state.remove_manga("X") is True
        assert state.get_downloaded_chapters("X") == []
        assert state.remove_manga("never") is False

    def test_clear_all_resets_everything(self, state):
        state.add_notification("info", "x")
        state.add_search_query("q")
        state.clear_all()
        assert state.get_notifications() == []
        assert state.get_recent_searches() == []


# ─────────────────────────────────────────────────────────────────────────
# Download history
# ─────────────────────────────────────────────────────────────────────────


class TestDownloadHistory:
    def test_add_and_retrieve(self, state):
        state.add_download_history("X", "1", "pdf", "/tmp/x.pdf", 12.5)
        hist = state.get_download_history()
        assert hist[0]["title"] == "X"
        assert hist[0]["size_mb"] == 12.5

    def test_capped_at_200(self, state):
        for i in range(220):
            state.add_download_history("X", str(i), "pdf", "", 0.1)
        assert len(state._data["download_history"]) <= 200


# ─────────────────────────────────────────────────────────────────────────
# Stats helpers used by Library + Downloads
# ─────────────────────────────────────────────────────────────────────────


class TestStats:
    def test_get_stats_shape(self, state):
        s = state.get_stats()
        assert "total_manga" in s and "total_chapters" in s

    def test_update_last_check_round_trips(self, state):
        state.update_last_check(new_chapters=3)
        assert state.get("last_check") is not None
