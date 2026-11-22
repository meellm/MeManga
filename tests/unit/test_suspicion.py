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
    monkeypatch.setattr(dl.updates, "get_scraper", lambda d: by_domain[d])


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
# #351: check_for_updates(dry_run=True) previews without writing state
# -------------------------------------------------------------------------


def _state_snapshot(state):
    """Everything State would persist, as a comparable copy."""
    import copy
    return copy.deepcopy(state._data)


def _numbers(chapters):
    return [c.number for c in chapters]


class TestCheckForUpdatesDryRun:
    def test_new_suspicious_batch_is_reported_not_recorded(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        state.set_catalogue_baseline("Tomodachi", 52.3)
        state.save()
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        before = _state_snapshot(state)
        on_disk = state.state_path.read_bytes()

        report = {}
        new = check_for_updates(SINGLE_SOURCE_MANGA, state, dry_run=True, report=report)

        assert new == []
        assert report["withheld"]["count"] == len(MANGAFIRE_BOGUS_BATCH)
        assert report["forced"] == 0
        assert _state_snapshot(state) == before
        assert state.state_path.read_bytes() == on_disk
        assert state.get_suspicious_batch("Tomodachi") is None
        assert state.get_notifications() == []

    def test_forced_preview_keeps_batch_held(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        state.set_catalogue_baseline("Tomodachi", 52.3)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        # A real check holds the batch.
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        record = state.get_suspicious_batch("Tomodachi")
        assert record is not None
        before = _state_snapshot(state)

        report = {}
        new = check_for_updates(
            SINGLE_SOURCE_MANGA, state, force_suspicious=True,
            dry_run=True, report=report,
        )

        # The preview shows what accepting would fetch...
        assert len(new) == len(MANGAFIRE_BOGUS_BATCH)
        assert report["forced"] == len(MANGAFIRE_BOGUS_BATCH)
        assert report["withheld"] is None
        # ...but accepts nothing.
        assert _state_snapshot(state) == before
        assert state.get_catalogue_baseline("Tomodachi") == pytest.approx(52.3)
        # The next unforced real check still withholds the batch.
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        assert state.get_suspicious_batch("Tomodachi") is not None

    @pytest.mark.parametrize("from_chapter", [0, 1])
    def test_backfill_preview_does_not_advance_baseline(self, state, monkeypatch,
                                                        from_chapter):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        state.set_catalogue_baseline("Tomodachi", 52.3)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        before = _state_snapshot(state)

        new = check_for_updates(
            SINGLE_SOURCE_MANGA, state, from_chapter=from_chapter, dry_run=True,
        )

        assert len(new) == len(MANGAFIRE_BOGUS_BATCH) + 1
        assert _state_snapshot(state) == before
        assert state.get_catalogue_baseline("Tomodachi") == pytest.approx(52.3)
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []

    def test_real_backfill_still_advances_baseline(self, state, monkeypatch):
        """Characterizes the non-preview path the dry run must not take."""
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        state.set_catalogue_baseline("Tomodachi", 52.3)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        check_for_updates(SINGLE_SOURCE_MANGA, state, from_chapter=0)
        assert state.get_catalogue_baseline("Tomodachi") == pytest.approx(148.0)

    def test_stale_record_is_not_cleared_or_reported(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        assert check_for_updates(SINGLE_SOURCE_MANGA, state) == []
        # The source fixes its list.
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3, 53.0]),
        })

        report = {}
        new = check_for_updates(SINGLE_SOURCE_MANGA, state, dry_run=True, report=report)

        assert _numbers(new) == ["53"]
        assert report["withheld"] is None
        # Only a real check clears the record.
        assert state.get_suspicious_batch("Tomodachi") is not None

    def test_backup_first_seen_does_not_start_clock(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "10")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning(range(1, 11)),
            "backup.test": _scraper_returning(range(1, 12)),
        })

        assert check_for_updates(MULTI_SOURCE_MANGA, state, dry_run=True) == []
        assert state.get_pending_backup("Tomodachi", "11") is None

        # The first real check starts the clock at its own time.
        assert check_for_updates(MULTI_SOURCE_MANGA, state) == []
        pending = state.get_pending_backup("Tomodachi", "11")
        assert pending is not None
        assert datetime.fromisoformat(pending["first_seen"]) > datetime.now() - timedelta(minutes=1)

    def test_due_backup_is_previewed_and_kept_pending(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "10")
        state.set_pending_backup("Tomodachi", "11", "backup.test", "u/11")
        state._data["manga"]["Tomodachi"]["pending_backup"]["11"]["first_seen"] = (
            datetime.now() - timedelta(days=5)
        ).isoformat()
        state.save()
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning(range(1, 11)),
            "backup.test": _scraper_returning(range(1, 12)),
        })
        before = _state_snapshot(state)

        preview = check_for_updates(MULTI_SOURCE_MANGA, state, dry_run=True)
        real = check_for_updates(MULTI_SOURCE_MANGA, state)

        assert _numbers(preview) == _numbers(real) == ["11"]
        assert preview[0].is_backup
        assert before["manga"]["Tomodachi"]["pending_backup"] == \
            state._data["manga"]["Tomodachi"]["pending_backup"]

    def test_primary_catch_up_does_not_clear_pending(self, state, monkeypatch):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "10")
        state.set_pending_backup("Tomodachi", "11", "backup.test", "u/11")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning(range(1, 12)),
            "backup.test": _scraper_returning(range(1, 12)),
        })

        new = check_for_updates(MULTI_SOURCE_MANGA, state, dry_run=True)
        assert _numbers(new) == ["11"]
        assert state.get_pending_backup("Tomodachi", "11") is not None

        check_for_updates(MULTI_SOURCE_MANGA, state)
        assert state.get_pending_backup("Tomodachi", "11") is None

    @pytest.mark.parametrize("primary,backup,kwargs", [
        ([52.0, 52.3, 53.0, 54.0], None, {}),
        ([52.3] + MANGAFIRE_BOGUS_BATCH, None, {}),
        ([52.3] + MANGAFIRE_BOGUS_BATCH, None, {"force_suspicious": True}),
        ([52.3] + MANGAFIRE_BOGUS_BATCH, None, {"from_chapter": 100}),
        ([52.3] + MANGAFIRE_BOGUS_BATCH, [52.3] + MANGAFIRE_BOGUS_BATCH, {}),
        ([52.3] + MANGAFIRE_BOGUS_BATCH, [51.0, 52.3], {}),
    ])
    def test_preview_selects_what_a_real_check_would(self, state, monkeypatch,
                                                     primary, backup, kwargs):
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        state.set_catalogue_baseline("Tomodachi", 52.3)
        scrapers = {"primary.test": _scraper_returning(primary)}
        manga = SINGLE_SOURCE_MANGA
        if backup is not None:
            scrapers["backup.test"] = _scraper_returning(backup)
            manga = MULTI_SOURCE_MANGA
        _patch_scrapers(monkeypatch, scrapers)

        preview = check_for_updates(manga, state, dry_run=True, **kwargs)
        real = check_for_updates(manga, state, **kwargs)
        assert _numbers(preview) == _numbers(real)


# -------------------------------------------------------------------------
# #102: existing catalogue backlog must not read as a suspicious jump
# -------------------------------------------------------------------------


# Blue Lock scenario: a large existing catalogue with only chapter 1 grabbed.
BLUE_LOCK_MANGA = {
    "title": "Blue Lock",
    "mode": "manual",
    "source": "primary.test",
    "url": "https://primary.test/m",
}


def _cache_catalogue(state, title, numbers):
    """Mimic the GUI persisting the primary chapter list after a check."""
    state.set_available_chapters(title, [
        {"number": f"{n:g}", "title": "", "source": "primary.test",
         "source_url": "https://primary.test/m", "is_backup": False,
         "url": f"u/{n:g}"}
        for n in numbers
    ])


class TestManualBacklogNotSuspicious:
    def test_first_manual_check_bootstraps_catalogue_baseline(self, state, monkeypatch):
        # Exact #102 shape: no cached catalogue yet, only chapter 1 is
        # downloaded, and the source reports a large existing catalogue.
        # Manual mode should snapshot that catalogue instead of treating the
        # old backlog as an auto-delivery anomaly.
        from memanga.downloader import check_for_updates

        state.add_downloaded_chapter("Blue Lock", "1")
        assert state.get_available_chapters("Blue Lock") == []
        assert state.get_catalogue_baseline("Blue Lock") is None
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([float(n) for n in range(1, 354)]),
        })

        new = check_for_updates(BLUE_LOCK_MANGA, state)

        assert [c.number for c in new] == [str(n) for n in range(2, 354)]
        assert state.get_suspicious_batch("Blue Lock") is None
        assert state.get_catalogue_baseline("Blue Lock") == 353.0
        assert not any(n["type"] == "warn" for n in state.get_notifications())

    def test_undownloaded_backlog_is_not_flagged(self, state, monkeypatch):
        # Manual manga: chapter 1 downloaded out of an existing 1..344
        # catalogue that has since grown to 353. The backlog must stay
        # visible/downloadable without a suspicious record (#102).
        from memanga.downloader import check_for_updates

        state.add_downloaded_chapter("Blue Lock", "1")
        state.set_catalogue_baseline("Blue Lock", 344.0)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([float(n) for n in range(1, 354)]),
        })

        new = check_for_updates(BLUE_LOCK_MANGA, state)

        # The whole undownloaded backlog (2..353) is offered, none withheld.
        assert [c.number for c in new] == [str(n) for n in range(2, 354)]
        assert state.get_suspicious_batch("Blue Lock") is None
        assert not any(n["type"] == "warn" for n in state.get_notifications())

    def test_baseline_bootstrapped_from_cached_catalogue(self, state, monkeypatch):
        # No explicit baseline yet (pre-existing manga), but the GUI has
        # cached the catalogue up to 344 from an earlier check. That cache
        # bootstraps the baseline so the backlog isn't flagged.
        from memanga.downloader import check_for_updates

        state.add_downloaded_chapter("Blue Lock", "1")
        _cache_catalogue(state, "Blue Lock", range(1, 345))
        assert state.get_catalogue_baseline("Blue Lock") is None
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([float(n) for n in range(1, 354)]),
        })

        new = check_for_updates(BLUE_LOCK_MANGA, state)

        assert state.get_suspicious_batch("Blue Lock") is None
        assert [c.number for c in new] == [str(n) for n in range(2, 354)]
        # The baseline is now persisted at the current catalogue high.
        assert state.get_catalogue_baseline("Blue Lock") == 353.0

    def test_growth_beyond_baseline_is_still_scored(self, state, monkeypatch):
        # A genuine bogus jump beyond the known catalogue is still caught,
        # even when an old backlog sits below the baseline.
        from memanga.downloader import check_for_updates

        state.add_downloaded_chapter("Blue Lock", "1")
        state.set_catalogue_baseline("Blue Lock", 344.0)
        # Source suddenly re-numbers far past the catalogue high.
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning(
                [float(n) for n in range(1, 345)] + [900.0, 950.0, 999.0]
            ),
        })

        new = check_for_updates(BLUE_LOCK_MANGA, state)

        record = state.get_suspicious_batch("Blue Lock")
        assert record is not None
        # Only the newly-appeared chapters beyond 344 are held back; the
        # existing backlog (2..344) is still offered.
        assert record["chapters"] == ["900", "950", "999"]
        assert [c.number for c in new] == [str(n) for n in range(2, 345)]
        # Baseline stays at the trusted 344 — not advanced past the jump.
        assert state.get_catalogue_baseline("Blue Lock") == 344.0

    def test_baseline_advances_on_normal_growth(self, state, monkeypatch):
        # A first check with no download baseline snapshots the catalogue;
        # later growth is measured from that snapshot.
        from memanga.downloader import check_for_updates

        # Fresh manual manga, nothing downloaded yet: guard doesn't run but
        # the catalogue is snapshotted as trusted.
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([float(n) for n in range(1, 345)]),
        })
        check_for_updates(BLUE_LOCK_MANGA, state)
        assert state.get_catalogue_baseline("Blue Lock") == 344.0

        # Now one chapter is downloaded and the source grows modestly.
        state.add_downloaded_chapter("Blue Lock", "1")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([float(n) for n in range(1, 354)]),
        })
        check_for_updates(BLUE_LOCK_MANGA, state)
        assert state.get_suspicious_batch("Blue Lock") is None
        assert state.get_catalogue_baseline("Blue Lock") == 353.0

    def test_mangafire_jump_still_flagged_with_cached_catalogue(self, state, monkeypatch):
        # #35 must be preserved: a manga tracked at 52.3 whose cached
        # catalogue is also ~52 still flags the bogus jump to 148.
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _cache_catalogue(state, "Tomodachi", [50, 51, 52, 52.3])
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        new = check_for_updates(SINGLE_SOURCE_MANGA, state)

        assert new == []
        assert state.get_suspicious_batch("Tomodachi") is not None

    def test_withheld_batch_not_trusted_from_gui_cache_on_next_check(self, state, monkeypatch):
        # GUI checks cache `all_chapters`, including chapters that were
        # withheld as suspicious. That cache must not become a trusted
        # catalogue baseline while the suspicious record is active.
        from memanga.downloader import check_for_updates

        state.set_last_chapter("Tomodachi", "52.3")
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        first_new, first_all = check_for_updates(SINGLE_SOURCE_MANGA, state, return_all=True)
        assert first_new == []
        first_record = state.get_suspicious_batch("Tomodachi")
        assert first_record is not None

        state.set_available_chapters("Tomodachi", [
            {"number": c.number, "title": c.title, "source": c.source,
             "source_url": c.source_url, "is_backup": c.is_backup, "url": c.url}
            for c in first_all
        ])

        second_new, _ = check_for_updates(SINGLE_SOURCE_MANGA, state, return_all=True)

        assert second_new == []
        second_record = state.get_suspicious_batch("Tomodachi")
        assert second_record is not None
        assert second_record["chapters"] == first_record["chapters"]


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
        """memanga.cli bound to a context in the isolated home, as main()
        would after parsing `--config-dir`. monkeypatch restores the
        module globals afterwards."""
        from memanga import cli as cli_mod
        for name in ("_context", "config", "state"):
            monkeypatch.setattr(cli_mod, name, getattr(cli_mod, name))
        cli_mod.use_context(
            cli_mod.build_context(isolated_home / ".config" / "memanga")
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

        def _fake_check(manga, state, from_chapter=None, force_suspicious=False,
                        **kwargs):
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
        cli.cmd_check(self._check_args(dry_run=False))

        # Withheld delivery is a warning, so it goes to stderr (#239).
        err = capsys.readouterr().err
        assert "Suspicious chapter batch detected" in err
        assert "--force-suspicious" in err
        assert "Skipped auto-delivery" in err

    # #351: previews run the real check_for_updates, so these exercise the
    # state it would otherwise write.

    @pytest.fixture
    def downloads(self, cli, monkeypatch, tmp_path):
        got = []

        def _download(manga, ch, *a, **k):
            got.append(ch.number)
            path = tmp_path / f"{ch.number}.pdf"
            path.write_bytes(b"pdf")
            return path

        monkeypatch.setattr(cli, "download_chapter", _download)
        monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: None)
        return got

    @staticmethod
    def _held_batch(cli, monkeypatch):
        """Track Tomodachi at 52.3; a real check holds the bogus batch."""
        cli.config.set("manga", [dict(SINGLE_SOURCE_MANGA)])
        cli.state.set_last_chapter("Tomodachi", "52.3")
        cli.state.set_catalogue_baseline("Tomodachi", 52.3)
        cli.state.save()
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })
        assert cli.cmd_check(TestCliForceSuspicious._check_args(dry_run=False)) is None
        assert cli.state.get_suspicious_batch("Tomodachi") is not None

    @pytest.mark.parametrize("preview", [
        dict(force_suspicious=True),
        dict(all=True),
        dict(from_chapter=1.0),
        dict(force_suspicious=True, all=True),
    ])
    def test_preview_never_accepts_held_batch(self, cli, monkeypatch, capsys,
                                              downloads, preview):
        import copy
        self._held_batch(cli, monkeypatch)
        before = copy.deepcopy(cli.state._data)
        on_disk = cli.state.state_path.read_bytes()
        capsys.readouterr()

        assert cli.cmd_check(self._check_args(dry_run=True, **preview)) is None
        out = capsys.readouterr().out
        assert "[DRY RUN] Chapter 148" in out
        assert downloads == []
        assert cli.state._data == before
        assert cli.state.state_path.read_bytes() == on_disk

        # The next scheduled run still withholds the batch.
        assert cli.cmd_check(self._check_args(dry_run=False)) is None
        assert downloads == []
        err = capsys.readouterr().err
        assert "Suspicious chapter batch detected" in err
        assert cli.state.get_catalogue_baseline("Tomodachi") == pytest.approx(52.3)

    def test_forced_preview_does_not_claim_batch_is_withheld(
            self, cli, monkeypatch, capsys, downloads):
        self._held_batch(cli, monkeypatch)
        capsys.readouterr()

        cli.cmd_check(self._check_args(dry_run=True, force_suspicious=True))
        err = " ".join(capsys.readouterr().err.split())
        assert "Suspicious chapter batch detected" not in err
        assert "--force-suspicious: includes 64 chapter(s)" in err

    def test_preview_reports_batch_it_would_withhold(self, cli, monkeypatch,
                                                     capsys, downloads):
        cli.config.set("manga", [dict(SINGLE_SOURCE_MANGA)])
        cli.state.set_last_chapter("Tomodachi", "52.3")
        cli.state.set_catalogue_baseline("Tomodachi", 52.3)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        # Withheld-only outcome is a warning, not a failure: exit 0.
        assert cli.cmd_check(self._check_args(dry_run=True)) is None
        err = " ".join(capsys.readouterr().err.split())
        assert "Suspicious chapter batch detected: 64 chapter(s)" in err
        assert "A download run would skip these chapters" in err
        assert "--download --force-suspicious" in err
        assert cli.state.get_suspicious_batch("Tomodachi") is None
        assert cli.state.get_notifications() == []

    def test_preview_ignores_stale_record(self, cli, monkeypatch, capsys,
                                          downloads):
        self._held_batch(cli, monkeypatch)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.3, 53.0]),
        })
        capsys.readouterr()

        cli.cmd_check(self._check_args(dry_run=True))
        captured = capsys.readouterr()
        assert "[DRY RUN] Chapter 53" in captured.out
        assert "Suspicious chapter batch" not in captured.err

    def test_withheld_batch_exits_0_with_download(self, cli, monkeypatch,
                                                  capsys, downloads):
        cli.config.set("manga", [dict(SINGLE_SOURCE_MANGA)])
        cli.state.set_last_chapter("Tomodachi", "52.3")
        cli.state.set_catalogue_baseline("Tomodachi", 52.3)
        _patch_scrapers(monkeypatch, {
            "primary.test": _scraper_returning([52.0, 52.3] + MANGAFIRE_BOGUS_BATCH),
        })

        assert cli.cmd_check(self._check_args(dry_run=False)) is None
        assert downloads == []
        assert "Skipped auto-delivery" in capsys.readouterr().err

    def test_forced_download_accepts_batch(self, cli, monkeypatch, downloads):
        self._held_batch(cli, monkeypatch)
        assert cli.cmd_check(
            self._check_args(dry_run=False, force_suspicious=True)) is None
        assert len(downloads) == len(MANGAFIRE_BOGUS_BATCH)
        assert cli.state.get_suspicious_batch("Tomodachi") is None
        assert cli.state.get_catalogue_baseline("Tomodachi") == pytest.approx(148.0)
