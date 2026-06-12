"""Tests for suspicious chapter-batch detection (issue #35).

Covers:
  - evaluate_chapter_batch heuristics, including the real MangaFire
    incident (manga tracked at ~52.3 suddenly "gaining" 64 chapters up
    to 148, then 154/156)
  - history estimation helpers (typical batch size, days since update)
  - the check_for_updates guard: blocking, backup verification,
    force_suspicious, from_chapter bypass, stale-record clearing
  - State suspicious_batch persistence
  - CLI: --force-suspicious flag and warning output
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import pytest

from memanga.suspicion import (
    SUSPICION_THRESHOLD,
    evaluate_chapter_batch,
    estimate_typical_batch_size,
    get_days_since_last_update,
)


# The bogus chapter list MangaFire exposed on 2026-05-10:
# 53, 55-93, 103-104, 124-141, 143-144, 147-148 (64 chapters).
MANGAFIRE_BOGUS_BATCH = (
    [53.0]
    + [float(n) for n in range(55, 94)]
    + [103.0, 104.0]
    + [float(n) for n in range(124, 142)]
    + [143.0, 144.0, 147.0, 148.0]
)


# -------------------------------------------------------------------------
# evaluate_chapter_batch: pure heuristics
# -------------------------------------------------------------------------


class TestEvaluateChapterBatch:
    def test_mangafire_incident_is_flagged(self):
        result = evaluate_chapter_batch(MANGAFIRE_BOGUS_BATCH, 52.3)
        assert result.suspicious
        assert result.score >= SUSPICION_THRESHOLD
        assert result.reasons

    def test_followup_huge_jump_is_flagged(self):
        # Second event from the issue: only chapters 154 and 156 appear,
        # but the manga is tracked at 52.3, so the jump alone is enough.
        result = evaluate_chapter_batch([154.0, 156.0], 52.3)
        assert result.suspicious

    def test_normal_weekly_update_passes(self):
        result = evaluate_chapter_batch([53.0], 52.3)
        assert not result.suspicious
        assert result.score == 0

    def test_decimal_split_chapters_pass(self):
        # 52 -> 52.1 / 52.2 / 52.5 is a known decimal/split pattern.
        result = evaluate_chapter_batch([52.1, 52.2, 52.5], 52.0)
        assert not result.suspicious

    def test_batch_release_matching_history_passes(self):
        # A series that normally drops 4 chapters at once.
        result = evaluate_chapter_batch(
            [101.0, 102.0, 103.0, 104.0], 100.0, typical_batch_size=4.0
        )
        assert not result.suspicious

    def test_no_baseline_never_flags(self):
        # Fresh manga: the whole catalogue is "new", which is normal.
        result = evaluate_chapter_batch([float(n) for n in range(1, 201)], 0.0)
        assert not result.suspicious

    def test_empty_batch_never_flags(self):
        assert not evaluate_chapter_batch([], 52.3).suspicious

    def test_dormant_series_catchup_passes(self):
        # 8 chapters after 60 idle days is a plausible catch-up.
        result = evaluate_chapter_batch(
            [float(n) for n in range(11, 19)], 10.0,
            days_since_last_update=60.0,
        )
        assert not result.suspicious

    def test_large_contiguous_dump_on_active_series_is_flagged(self):
        # 30 chapters overnight on a series tracked at 10 is not normal.
        result = evaluate_chapter_batch(
            [float(n) for n in range(11, 41)], 10.0,
            days_since_last_update=1.0,
        )
        assert result.suspicious


# -------------------------------------------------------------------------
# History estimation helpers
# -------------------------------------------------------------------------


class _HistoryStub:
    """Minimal state stand-in exposing only download_history."""

    def __init__(self, history):
        self._history = history

    def get(self, key, default=None):
        if key == "download_history":
            return self._history
        return default


class TestEstimateTypicalBatchSize:
    def test_median_of_grouped_batches(self):
        base = datetime(2026, 5, 1, 8, 0)
        history = []
        # Three weekly batches of sizes 1, 3, 1 -> median 1.
        for week, size in enumerate((1, 3, 1)):
            for i in range(size):
                history.append({
                    "title": "X",
                    "chapter": str(week * 10 + i),
                    "timestamp": (base + timedelta(days=7 * week, minutes=i)).isoformat(),
                })
        assert estimate_typical_batch_size(_HistoryStub(history), "X") == 1.0

    def test_other_titles_ignored(self):
        history = [{
            "title": "Other",
            "chapter": "1",
            "timestamp": datetime.now().isoformat(),
        }]
        assert estimate_typical_batch_size(_HistoryStub(history), "X") is None

    def test_no_history_returns_none(self):
        assert estimate_typical_batch_size(_HistoryStub([]), "X") is None

    def test_state_without_get_is_tolerated(self):
        class NoGet:
            pass
        assert estimate_typical_batch_size(NoGet(), "X") is None


class TestDaysSinceLastUpdate:
    def test_reads_last_updated_from_state(self, state):
        state.set_last_chapter("X", "5")
        days = get_days_since_last_update(state, "X")
        assert days is not None
        assert days < 0.1

    def test_unknown_manga_returns_none(self, state):
        assert get_days_since_last_update(state, "Nope") is None


# -------------------------------------------------------------------------
# check_for_updates guard integration
# -------------------------------------------------------------------------


def _scraper_returning(numbers):
    from memanga.scrapers.base import Chapter

    class _Scraper:
        def get_chapters(self, url):
            return [Chapter(f"{n:g}", "", f"u/{n:g}") for n in numbers]

    return _Scraper()


def _patch_scrapers(monkeypatch, by_domain):
    import memanga.downloader as dl
    monkeypatch.setattr(dl, "get_scraper", lambda d: by_domain[d])


SINGLE_SOURCE_MANGA = {
    "title": "Tomodachi",
    "source": "primary.test",
    "url": "https://primary.test/m",
}

MULTI_SOURCE_MANGA = {
    "title": "Tomodachi",
    "fallback_delay_days": 2,
    "sources": [
        {"source": "primary.test", "url": "https://primary.test/m"},
        {"source": "backup.test", "url": "https://backup.test/m"},
    ],
}


class TestCheckForUpdatesGuard:
    def test_suspicious_batch_blocked_without_backup(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        new = check_for_updates(SINGLE_SOURCE_MANGA, state)

        assert new == []
        record = state.get_suspicious_batch("Tomodachi")
        assert record is not None
        assert record["count"] == len(MANGAFIRE_BOGUS_BATCH)
        assert record["backup_status"] == "no backup source available to verify"
        # Nothing was committed as downloaded.
        assert state.get_downloaded_chapters("Tomodachi") == []
        # A warning notification was logged for the GUI.
        notifs = state.get_notifications()
        assert any(n["type"] == "warn" and "Tomodachi" in n["message"] for n in notifs)

    def test_backup_confirming_batch_allows_it(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        chapters = [52.3] + MANGAFIRE_BOGUS_BATCH
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning(chapters),
            "backup.test": _scraper_returning(chapters),
        })

        new = check_for_updates(MULTI_SOURCE_MANGA, state)

        assert len(new) == len(MANGAFIRE_BOGUS_BATCH)
        assert state.get_suspicious_batch("Tomodachi") is None

    def test_backup_disagreeing_blocks_batch(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
            # Backup agrees the series is only around chapter 52.x.
            "backup.test": _scraper_returning([51.0, 52.0, 52.3]),
        })

        new = check_for_updates(MULTI_SOURCE_MANGA, state)

        assert new == []
        record = state.get_suspicious_batch("Tomodachi")
        assert record is not None
        assert "backup confirmed only 0" in record["backup_status"]

    def test_force_suspicious_accepts_batch(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        # First run blocks and records the batch.
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        assert state.get_suspicious_batch("Tomodachi") is not None

        # Forced run accepts it and clears the record.
        new = check_for_updates(SINGLE_SOURCE_MANGA, state, force_suspicious=True)
        assert len(new) == len(MANGAFIRE_BOGUS_BATCH)
        assert state.get_suspicious_batch("Tomodachi") is None

    def test_from_chapter_bypasses_guard(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        # Explicit bulk re-download is a deliberate user action.
        new = check_for_updates(SINGLE_SOURCE_MANGA, state, from_chapter=0)
        assert len(new) == len(MANGAFIRE_BOGUS_BATCH) + 1

    def test_record_cleared_when_source_recovers(self, state, monkeypatch):
        from memanga.downloader import check_for_updates
        import memanga.downloader as dl

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        assert state.get_suspicious_batch("Tomodachi") is not None

        # Source fixes its list: only the genuine next chapter remains.
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3, 53.0]),
        })
        new = check_for_updates(SINGLE_SOURCE_MANGA, state)
        assert [c.number for c in new] == ["53"]
        assert state.get_suspicious_batch("Tomodachi") is None

    def test_normal_update_unaffected(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.0, 52.3, 53.0, 54.0]),
        })

        new = check_for_updates(SINGLE_SOURCE_MANGA, state)
        assert [c.number for c in new] == ["53", "54"]
        assert state.get_suspicious_batch("Tomodachi") is None


# -------------------------------------------------------------------------
# State persistence of the suspicious record
# -------------------------------------------------------------------------


class TestStateSuspiciousBatch:
    def test_roundtrip_and_clear(self, state):
        info = {"count": 64, "reasons": ["jump"], "backup_status": "none"}
        state.set_suspicious_batch("X", info)
        assert state.get_suspicious_batch("X") == info

        state.clear_suspicious_batch("X")
        assert state.get_suspicious_batch("X") is None

    def test_clear_unknown_manga_is_noop(self, state):
        state.clear_suspicious_batch("Never Seen")  # must not raise

    def test_persists_across_reload(self, state, isolated_home):
        from memanga.state import State
        state.set_suspicious_batch("X", {"count": 2})
        reloaded = State(config_dir=isolated_home / ".config" / "memanga")
        assert reloaded.get_suspicious_batch("X") == {"count": 2}


# -------------------------------------------------------------------------
# CLI: --force-suspicious flag and warning output
# -------------------------------------------------------------------------


class TestCliForceSuspicious:
    @pytest.fixture
    def cli(self, isolated_home, monkeypatch):
        """memanga.cli with its module-level config/state rebound to the
        isolated home (they are built at import time)."""
        from memanga import cli as cli_mod
        from memanga.config import Config
        from memanga.state import State
        monkeypatch.setattr(cli_mod, "config", Config())
        monkeypatch.setattr(
            cli_mod, "state",
            State(config_dir=isolated_home / ".config" / "memanga"),
        )
        return cli_mod

    @staticmethod
    def _check_args(**overrides):
        defaults = dict(
            title=None, auto=True, yes=False, quiet=True,
            from_chapter=None, all=False, safe=False, dry_run=True,
            format=None, retries=3, force_suspicious=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_check_help_mentions_flag(self, cli, capsys, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["memanga", "check", "--help"])
        with pytest.raises(SystemExit):
            cli.main()
        assert "--force-suspicious" in capsys.readouterr().out

    def test_flag_is_passed_to_check_for_updates(self, cli, monkeypatch):
        cli.config.set("manga", [dict(SINGLE_SOURCE_MANGA)])

        seen = {}

        def _fake_check(manga, state, from_chapter=None, force_suspicious=False):
            seen["force_suspicious"] = force_suspicious
            return []

        monkeypatch.setattr(cli, "check_for_updates", _fake_check)
        cli.cmd_check(self._check_args(force_suspicious=True))
        assert seen["force_suspicious"] is True

    def test_warning_printed_when_batch_withheld(self, cli, monkeypatch, capsys):
        cli.config.set("manga", [dict(SINGLE_SOURCE_MANGA)])
        cli.state.set_suspicious_batch("Tomodachi", {
            "count": 64, "highest": 148.0, "last_chapter": 52.3,
            "reasons": ["chapter number jumped from 52.3 to 148"],
            "backup_status": "no backup source available to verify",
        })

        monkeypatch.setattr(
            cli, "check_for_updates",
            lambda manga, state, from_chapter=None, force_suspicious=False: [],
        )
        cli.cmd_check(self._check_args())

        out = capsys.readouterr().out
        assert "Suspicious chapter batch detected" in out
        assert "--force-suspicious" in out
        assert "Skipped auto-delivery" in out
