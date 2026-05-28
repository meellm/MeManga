"""Tests for memanga.downloader — chapter checking, file output paths,
sanitization, format conversion, fallback delay logic."""

from __future__ import annotations

import types
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────
# _sanitize_filename — pure function, easy to exercise
# ─────────────────────────────────────────────────────────────────────────


class TestSanitizeFilename:
    def test_strips_path_separators(self):
        from memanga.downloader import _sanitize_filename
        assert "/" not in _sanitize_filename("a/b/c")
        assert "\\" not in _sanitize_filename("a\\b\\c")

    def test_strips_reserved_chars(self):
        from memanga.downloader import _sanitize_filename
        out = _sanitize_filename('a<b>c:d"e|f?g*h')
        for ch in '<>:"|?*':
            assert ch not in out

    def test_preserves_safe_text(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename("Chainsaw Man") == "Chainsaw Man"


class TestFormatChapterNumber:
    def test_integer_passes_through(self):
        from memanga.downloader import _format_chapter_number
        # Plain integers are kept as-is (sorting uses float, not strings).
        assert _format_chapter_number("5") == "5"
        assert _format_chapter_number("10") == "10"

    def test_part_chapters_zero_padded(self):
        from memanga.downloader import _format_chapter_number
        # "2 Part 1" → "2.01" so it sorts between "2" and "2.5".
        assert _format_chapter_number("2 Part 1") == "2.01"
        assert _format_chapter_number("2 Part 2") == "2.02"
        # Lexicographic ordering of part-formatted strings is consistent
        assert _format_chapter_number("2 Part 1") < _format_chapter_number("2 Part 2")

    def test_decimal_chapters_passed_through(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("2.5") == "2.5"


# ─────────────────────────────────────────────────────────────────────────
# check_for_updates — uses mock scraper
# ─────────────────────────────────────────────────────────────────────────


class TestCheckForUpdates:
    def test_returns_chapters_above_last_chapter(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        state.set_last_chapter("Mock", "3")
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new, all_ = check_for_updates(manga, state, return_all=True)
        # Mock returns chapters 1..5, last_chapter=3, so new should be 4 + 5
        nums = [c.number for c in new]
        assert "4" in nums and "5" in nums
        assert "3" not in nums

    def test_returns_all_when_no_last_chapter(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        manga = {"title": "Fresh", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new, all_ = check_for_updates(manga, state, return_all=True)
        assert len(new) >= 5

    def test_from_chapter_override(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        # from_chapter=3 should include chapters 3+
        # Without return_all=True, the function returns just the list.
        new = check_for_updates(manga, state, from_chapter=3)
        assert all(float(c.number) >= 3 for c in new)


# ─────────────────────────────────────────────────────────────────────────
# download_chapter — issue #23: every format under <dir>/<title>/
# ─────────────────────────────────────────────────────────────────────────


class TestDownloadChapterPath:
    """Verify the issue #23 fix — every format ends up in
    <output_dir>/<manga_title>/*."""

    @pytest.fixture
    def fake_state(self):
        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass
        return S()

    @pytest.mark.parametrize("fmt", ["pdf", "epub", "cbz", "zip", "jpg"])
    def test_output_path_is_under_manga_subfolder(self, fmt, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state):
        from memanga.downloader import download_chapter
        out = tmp_path / "downloads"
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="5", title="", url="https://mock.test/c/5",
            source="mock.test", source_url="https://mock.test/c/5",
            is_backup=False,
        )
        path = download_chapter(manga, chapter, out, fmt, fake_state)
        rel = Path(path).relative_to(out)
        assert rel.parts[0] == "Bleach", (
            f"format {fmt!r} produced {rel} — not under Bleach/"
        )


class TestNamingTemplate:
    def test_template_variables_substituted(self, tmp_path,
                                             patch_get_scraper):
        from memanga.downloader import download_chapter

        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass

        manga = {"title": "MyManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )
        path = download_chapter(
            manga, chapter, tmp_path, "pdf", S(),
            naming_template="{title}__ch{chapter}",
        )
        assert "MyManga__ch1" in Path(path).stem


# ─────────────────────────────────────────────────────────────────────────
# get_supported_sources — registry exposed to the GUI
# ─────────────────────────────────────────────────────────────────────────


class TestGetSupportedSources:
    def test_returns_nonempty_list(self):
        from memanga.downloader import get_supported_sources
        srcs = get_supported_sources()
        assert isinstance(srcs, (list, set))
        assert len(list(srcs)) > 0

    def test_contains_known_sources(self):
        from memanga.downloader import get_supported_sources
        srcs = set(get_supported_sources())
        # MangaDex + MangaFire are baseline scrapers in this repo.
        assert "mangadex.org" in srcs
        assert "mangafire.to" in srcs
