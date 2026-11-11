"""Tests for memanga.downloader — chapter checking, file output paths,
sanitization, format conversion, fallback delay logic."""

from __future__ import annotations

import types
import sys
import time
import shutil
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

    def test_dot_components_fall_back(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename(".") == "untitled"
        assert _sanitize_filename("..") == "untitled"
        # "../" loses its slash and would otherwise collapse to ".."
        assert _sanitize_filename("../") == "untitled"

    def test_empty_and_whitespace_fall_back(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename("") == "untitled"
        assert _sanitize_filename("   ") == "untitled"

    def test_all_invalid_chars_fall_back(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename('<>:"/\\|?*') == "untitled"

    def test_truncation_never_leaves_trailing_dot_or_space(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename("a" * 99 + " b") == "a" * 99
        assert _sanitize_filename("a" * 99 + ".b") == "a" * 99
        assert _sanitize_filename("Vol. 2.") == "Vol. 2"

    def test_strips_control_characters(self):
        # Issue #246: control characters are invalid in Windows names.
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename("A\x00B\nC\tD\x7fE\x85F") == "ABCDEF"
        assert _sanitize_filename("\x01\x02") == "untitled"

    @pytest.mark.parametrize("name, expected", [
        ("CON", "CON_"),
        ("nul", "nul_"),
        ("Aux", "Aux_"),
        ("prn.v2", "prn_.v2"),
        ("COM1", "COM1_"),
        ("lpt9.cbz", "lpt9_.cbz"),
        ("COM¹", "COM¹_"),
        ("CON .x", "CON_.x"),
        ("CON.", "CON_"),
    ])
    def test_windows_device_names_get_suffix(self, name, expected):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename(name) == expected

    @pytest.mark.parametrize("name", [
        "Console", "COM10", "CONTACT", "Nul - Chapter 0001.000", "A CON",
    ])
    def test_names_merely_containing_device_names_unchanged(self, name):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename(name) == name

    def test_device_name_suffix_keeps_length_limit(self):
        from memanga.downloader import _sanitize_filename
        out = _sanitize_filename("CON." + "a" * 200)
        assert out.startswith("CON_.")
        assert len(out) <= 100


class TestDownloadFolderKey:
    """Issue #246: titles that would share one download folder."""

    @pytest.mark.parametrize("a, b", [
        ("A:B", "AB"),
        ("Bleach", "BLEACH"),
        ("Café", "Café"),  # composed vs decomposed accent
        ("Title.", "Title"),
    ])
    def test_colliding_titles_share_key(self, a, b):
        from memanga.downloader import _download_folder_key
        assert _download_folder_key(a) == _download_folder_key(b)

    def test_distinct_titles_differ(self):
        from memanga.downloader import _download_folder_key
        assert _download_folder_key("Bleach") != _download_folder_key("Naruto")


# Chapter labels in order. A name must sort after every name in an earlier
# group and before every name in a later group. Labels inside one group
# have the same chapter number (to three decimal places), so their order
# among themselves is not part of the naming contract.
_CHAPTER_GROUPS = [
    ["1"],
    ["2", "2.0", "2.00", "02", "2.0001"],
    ["2.001"], ["2.01"], ["2.05"], ["2.1", "2.10"], ["2.5", "2.50"],
    ["3"], ["10"], ["999"], ["1000"],
]
# Parts sort after their chapter's numeric names and before the next
# chapter; whether they come before or after its decimals is not specified.
_PART_LABELS = ["2 Part 1", "2 Part 2", "2 Part 10", "2 part 2", "02 Part 2"]
_PART_PAIRS = [("2 Part 1", "2 Part 2"), ("2 Part 2", "2 Part 10")]
_ALL_LABELS = [label for group in _CHAPTER_GROUPS for label in group] \
    + _PART_LABELS
# Text that may follow {chapter}: extensions, a folder name's end, and
# custom-template continuations.
_CONTINUATIONS = [".pdf", ".epub", ".cbz", ".zip", "", " - X", "-X", "_X"]


def _alnum_collation_key(name):
    """Model of locale collation that skips punctuation and case at the
    first level (glibc en_* locales do this)."""
    return [c for c in name.casefold() if c.isalnum()]


def _assert_chapter_order(names, key):
    """``names`` maps chapter label -> complete file name."""
    position = {name: i
                for i, name in enumerate(sorted(names.values(), key=key))}
    group_of = {label: g for g, group in enumerate(_CHAPTER_GROUPS)
                for label in group}
    for a in group_of:
        for b in group_of:
            if group_of[a] < group_of[b]:
                assert position[names[a]] < position[names[b]], (
                    names[a], names[b])
    for part in _PART_LABELS:
        for label in _CHAPTER_GROUPS[1]:
            assert position[names[label]] < position[names[part]], (
                names[label], names[part])
        assert position[names[part]] < position[names["3"]], names[part]
    for a, b in _PART_PAIRS:
        assert position[names[a]] < position[names[b]], (names[a], names[b])


def _names(continuation):
    from memanga.downloader import _format_chapter_number
    return {label: f"X - Chapter {_format_chapter_number(label)}{continuation}"
            for label in _ALL_LABELS}


class TestFormatChapterNumber:
    def test_numeric_labels_get_fixed_width_key(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("2") == "0002.000"
        assert _format_chapter_number("10") == "0010.000"
        assert _format_chapter_number("2.5") == "0002.500"
        assert _format_chapter_number("2.001") == "0002.001"
        assert _format_chapter_number("2.01") == "0002.010"
        assert _format_chapter_number("12.125") == "0012.125"

    def test_long_numbers_are_kept_whole(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("1100") == "1100.000"
        assert _format_chapter_number("12345") == "12345.000"

    def test_labels_the_key_does_not_spell_keep_their_text(self):
        # Issue #241: "2" and "2.00" used to share one file name, so the
        # second download overwrote the first.
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("2.0") == "0002.000 (2.0)"
        assert _format_chapter_number("2.00") == "0002.000 (2.00)"
        assert _format_chapter_number("02") == "0002.000 (02)"
        assert _format_chapter_number("2.50") == "0002.500 (2.50)"
        assert _format_chapter_number("2.0001") == "0002.000 (2.0001)"

    def test_part_chapters_stay_readable(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("2 Part 1") == "0002_Part 01"
        assert _format_chapter_number("2 Part 10") == "0002_Part 10"
        assert _format_chapter_number("2 Part 3 (End)") == \
            "0002_Part 03 (End)"
        assert _format_chapter_number("2 part 10") == \
            "0002_Part 10 (2 part 10)"
        assert _format_chapter_number("2Part3") == "0002_Part 03 (2Part3)"

    def test_distinct_labels_never_share_a_name(self):
        from memanga.downloader import _format_chapter_number
        labels = _ALL_LABELS + ["2 Part 01", "2Part2", "Extra", "Chapter 3",
                                " 2", "2 "]
        assert len({_format_chapter_number(n) for n in labels}) == len(labels)

    def test_very_long_digit_strings_are_handled_as_text(self):
        from memanga.downloader import _format_chapter_number
        label = "1" * 5000
        assert _format_chapter_number(label) == label + ".000"

    @pytest.mark.parametrize("continuation", _CONTINUATIONS)
    def test_full_names_sort_in_chapter_order_by_bytes(self, continuation):
        # Issue #241: complete names, extension included, sort in chapter
        # order by plain string (code point) comparison.
        _assert_chapter_order(_names(continuation), None)

    @pytest.mark.parametrize("continuation", _CONTINUATIONS)
    def test_full_names_sort_when_punctuation_is_ignored(self, continuation):
        # Locale collation may compare only letters and digits first, so
        # "Chapter 2.cbz" compares as "chapter2cbz" and would lose to
        # "chapter25cbz". Deterministic model, no installed locale needed.
        _assert_chapter_order(_names(continuation), _alnum_collation_key)

    @pytest.mark.parametrize("name", ["en_GB.UTF-8", "en_US.UTF-8",
                                      "de_DE.UTF-8", "C.UTF-8"])
    @pytest.mark.parametrize("continuation", [".cbz", ".pdf", ".zip", ""])
    def test_full_names_sort_under_installed_locale(self, name, continuation):
        # Test-only: the application itself never changes the locale.
        if sys.platform == "darwin" and not name.startswith("C."):
            # macOS (like other BSDs) collates its UTF-8 language locales
            # with a plain ASCII table rather than language rules, so
            # strxfrm says nothing about what this test checks there
            # (https://bugs.python.org/issue23195).
            pytest.skip(f"{name} collation on macOS is an ASCII table")
        import locale
        saved = locale.setlocale(locale.LC_COLLATE)
        try:
            try:
                locale.setlocale(locale.LC_COLLATE, name)
            except locale.Error:
                pytest.skip(f"locale {name} is not installed")
            _assert_chapter_order(_names(continuation), locale.strxfrm)
        finally:
            locale.setlocale(locale.LC_COLLATE, saved)

    def test_special_labels_are_unchanged(self):
        from memanga.downloader import _format_chapter_number
        for label in ("Extra", "Oneshot", "Chapter 3", "2a", "1-2", "",
                      " 2", "2 "):
            assert _format_chapter_number(label) == label


# 98 ASCII characters; with the default template the full name is longer
# than the 100-character name limit.
_LONG_TITLE = ("Long Title " * 9).strip()


class TestChapterBaseName:
    def test_short_names_are_unchanged(self):
        from memanga.downloader import _sanitize_filename
        from memanga.downloader.naming import _chapter_base_name
        for template in ("{title} - Chapter {chapter}",
                         "{title}__ch{chapter}", "{chapter} [{source}]"):
            full = (template.replace("{title}", "My: Manga")
                    .replace("{chapter}", "0002.000 (2.0)")
                    .replace("{source}", "mock.test"))
            assert _chapter_base_name(template, "My: Manga", "0002.000 (2.0)",
                                      "mock.test") == _sanitize_filename(full)

    @pytest.mark.parametrize("length", [66, 80, 81, 84, 88, 90, 98, 150])
    def test_long_title_keeps_chapter_text_whole(self, length):
        # Issue #241: cutting the end of the whole name dropped the
        # " (2.00)" source label, so "2" and "2.00" got the same file.
        from memanga.downloader import _format_chapter_number
        from memanga.downloader.naming import _chapter_base_name
        title = ("Long Title " * 20)[:length]
        labels = ["2", "2.0", "2.00", "02", "2.5", "3", "2 Part 2",
                  "2 part 2"]
        names = {}
        for label in labels:
            chapter = _format_chapter_number(label)
            name = _chapter_base_name("{title} - Chapter {chapter}", title,
                                      chapter)
            assert len(name) <= 100
            assert name.endswith(f" - Chapter {chapter}"), name
            names[label] = name
        assert len(set(names.values())) == len(labels)
        # Every chapter keeps the same shortened title prefix.
        prefixes = {n[:n.index(" - Chapter ")] for n in names.values()}
        assert len(prefixes) == 1

    def test_invalid_title_characters_do_not_count(self):
        from memanga.downloader.naming import _chapter_base_name
        title = "?" * 50 + "a" * 60
        assert _chapter_base_name("{title} - Chapter {chapter}", title,
                                  "0002.000 (2.0)") == \
            "a" * 60 + " - Chapter 0002.000 (2.0)"

    def test_long_chapter_text_is_kept_whole(self):
        from memanga.downloader.naming import _chapter_base_name
        chapter = "0002_Part 01 A Very Long Part Subtitle Here"
        name = _chapter_base_name("{title} - Chapter {chapter}", _LONG_TITLE,
                                  chapter)
        assert len(name) <= 100
        assert name.endswith(f" - Chapter {chapter}")

    def test_without_title_too_long_name_is_cut_at_end(self):
        from memanga.downloader import _sanitize_filename
        from memanga.downloader.naming import _chapter_base_name
        source = "s" * 120
        assert _chapter_base_name("{source} {chapter}", "T", "0002.000",
                                  source) == \
            _sanitize_filename(f"{source} 0002.000")


class TestChapterFilenameLabels:
    def test_current_form_first_then_legacy_forms(self):
        from memanga.downloader.naming import _chapter_filename_labels
        assert _chapter_filename_labels("2") == ["0002.000", "2", "2.0"]
        assert _chapter_filename_labels("2 Part 1") == [
            "0002_Part 01", "2.01", "2 Part 1", "2 Part 1.0"]
        assert _chapter_filename_labels("2.5") == [
            "0002.500", "2.5", "2.5.0"]
        assert _chapter_filename_labels("2.0") == [
            "0002.000 (2.0)", "2.0", "2.0.0"]

    def test_special_label_is_not_duplicated(self):
        from memanga.downloader.naming import _chapter_filename_labels
        assert _chapter_filename_labels("Extra") == ["Extra", "Extra.0"]


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

    @staticmethod
    def _set_mock_chapters(scraper, numbers):
        from memanga.scrapers.base import Chapter
        scraper._chapters = [
            Chapter(number=n, url=f"https://mock.test/c/{i}")
            for i, n in enumerate(numbers)
        ]

    @pytest.mark.parametrize("label, catalogue, expected", [
        ("10 Part 1", ["9", "10", "10 Part 1", "11", "12"], ["11", "12"]),
        ("Chapter 5", ["4", "5", "Chapter 5", "6", "7"], ["6", "7"]),
    ])
    def test_labelled_last_chapter_uses_embedded_number(
            self, state, patch_get_scraper, label, catalogue, expected):
        # Issue #228: a labelled last chapter used to raise ValueError.
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper, catalogue)
        state.add_downloaded_chapter("Mock", label)
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state)
        assert [c.number for c in new] == expected

    def test_non_numeric_last_chapter_falls_back_to_zero(
            self, state, patch_get_scraper):
        # Issue #228: "Extra" has no number, so it is treated like an empty
        # last chapter; downloaded chapters are still skipped.
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper, ["1", "2", "Extra", "3"])
        state.add_downloaded_chapter("Mock", "1")
        state.add_downloaded_chapter("Mock", "Extra")
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state)
        assert [c.number for c in new] == ["2", "3"]

    @pytest.mark.parametrize("stored, expected", [
        ("4.999", ["5", "6"]),
        ("-0.001", ["0", "1", "2", "3", "4", "5", "6"]),
    ])
    def test_numeric_last_chapter_keeps_float_parsing(
            self, state, patch_get_scraper, stored, expected):
        # Values written by "download from chapter X" keep their exact
        # value, including the sign of the chapter-0 reset.
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper, [str(i) for i in range(7)])
        state.set_last_chapter("Mock", stored)
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state)
        assert [c.number for c in new] == expected

    @pytest.mark.parametrize("label, expected_backlog", [
        ("5", [str(i) for i in range(6, 11)]),
        ("Extra", [str(i) for i in range(1, 11)]),
    ])
    def test_last_chapter_label_cannot_bypass_suspicion_guard(
            self, state, patch_get_scraper, label, expected_backlog):
        # Issue #228: a digit-free label parses to 0.0 but must still score
        # a beyond-baseline batch exactly like a numeric last chapter.
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper,
                                [str(i) for i in range(1, 61)])
        state.add_downloaded_chapter("Mock", label)
        state.set_catalogue_baseline("Mock", 10.0)
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state)
        assert [c.number for c in new] == expected_backlog
        record = state.get_suspicious_batch("Mock")
        assert record is not None
        assert record["chapters"] == [str(i) for i in range(11, 61)]
        assert record["last_chapter"] == 10.0
        assert state.get_catalogue_baseline("Mock") == 10.0

    def test_empty_last_chapter_with_baseline_is_not_scored(
            self, state, patch_get_scraper):
        # A truly empty last chapter (fresh or "download all" reset) keeps
        # returning the whole catalogue unscored.
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper,
                                [str(i) for i in range(1, 61)])
        state.set_catalogue_baseline("Mock", 10.0)
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state)
        assert len(new) == 60
        assert state.get_suspicious_batch("Mock") is None
        assert state.get_catalogue_baseline("Mock") == 60.0

    def test_from_chapter_still_bypasses_guard_with_label(
            self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        self._set_mock_chapters(patch_get_scraper,
                                [str(i) for i in range(1, 61)])
        state.add_downloaded_chapter("Mock", "Extra")
        state.set_catalogue_baseline("Mock", 10.0)
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new = check_for_updates(manga, state, from_chapter=1)
        assert len(new) == 60
        assert state.get_suspicious_batch("Mock") is None


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

    def test_invalid_title_uses_safe_folder(self, tmp_path,
                                            patch_get_scraper, fake_state):
        """Invalid stored titles should use a safe manga folder."""
        from memanga.downloader import download_chapter
        out = tmp_path / "downloads"
        manga = {"title": "../", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )
        path = download_chapter(manga, chapter, out, "cbz", fake_state)
        rel = Path(path).resolve().relative_to(out.resolve())
        assert rel.parts[0] == "untitled"


class TestDownloadChapterCancel:
    def test_cancel_waits_for_started_page_workers(self, tmp_path,
                                                   patch_get_scraper):
        """Issue #246: page workers already running when the user cancels
        finish before the temp directory is removed, so none writes into
        a deleted (or re-created) folder."""
        import threading
        from PIL import Image
        from memanga.downloader import download_chapter

        scraper = patch_get_scraper
        scraper._page_count = 4
        gate = threading.Event()
        cancel = threading.Event()
        lock = threading.Lock()
        started, finished, written = [], [], []

        def download_image(url, path):
            with lock:
                started.append(url)
            if not url.endswith("/0.jpg"):
                gate.wait(5)
            Image.new("RGB", (20, 30), "white").save(path)
            with lock:
                finished.append(url)
                written.append(Path(path))
            return True

        def on_progress(done, total):
            cancel.set()
            threading.Timer(0.3, gate.set).start()

        scraper.download_image = download_image
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )
        try:
            with pytest.raises(InterruptedError):
                download_chapter(manga, chapter, tmp_path / "out", "cbz",
                                 None, progress_callback=on_progress,
                                 cancel_event=cancel, max_retries=0)
            with lock:
                assert sorted(finished) == sorted(started)
            # Every page was written before the temp folder was removed,
            # and the folder was not re-created by a late worker.
            assert written
            assert not any(p.parent.exists() for p in written)
        finally:
            gate.set()


class TestDownloadChapterMetadata:
    def test_epub_uses_manga_author_and_language(self, tmp_path,
                                                 patch_get_scraper):
        # Issue #246: EPUB metadata comes from the manga entry.
        import zipfile
        import xml.etree.ElementTree as ET
        from memanga.downloader import download_chapter
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test", "author": "Tite Kubo",
                 "language": "ja"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )
        path = download_chapter(manga, chapter, tmp_path, "epub", None)
        with zipfile.ZipFile(path) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
        dc = "{http://purl.org/dc/elements/1.1/}"
        meta = opf.find("{http://www.idpf.org/2007/opf}metadata")
        assert meta.find(f"{dc}creator").text == "Tite Kubo"
        assert meta.find(f"{dc}language").text == "ja"

    @staticmethod
    def _chapter():
        return types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )

    def test_epub_language_undetermined_when_unknown(self, tmp_path,
                                                     patch_get_scraper):
        import zipfile
        import xml.etree.ElementTree as ET
        from memanga.downloader import download_chapter
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test"}
        path = download_chapter(manga, self._chapter(), tmp_path, "epub", None)
        with zipfile.ZipFile(path) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
        dc = "{http://purl.org/dc/elements/1.1/}"
        meta = opf.find("{http://www.idpf.org/2007/opf}metadata")
        assert meta.find(f"{dc}language").text == "und"

    @pytest.mark.parametrize("direction, manga_flag", [
        ("rtl", "YesAndRightToLeft"), (None, None),
    ])
    def test_cbz_uses_source_language_and_direction(
            self, tmp_path, patch_get_scraper, direction, manga_flag):
        # The chapter's source declares what it knows about its titles.
        import zipfile
        import xml.etree.ElementTree as ET
        from memanga.downloader import download_chapter
        patch_get_scraper.content_language = "es"
        patch_get_scraper.reading_direction = direction
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test"}
        path = download_chapter(manga, self._chapter(), tmp_path, "cbz", None)
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("ComicInfo.xml"))
        fields = {child.tag: child.text for child in root}
        assert fields["LanguageISO"] == "es"
        assert fields.get("Manga") == manga_flag


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
        assert Path(path).name == "MyManga__ch0001.000.pdf"

    @staticmethod
    def _chapter(number):
        return types.SimpleNamespace(
            number=number, title="", url=f"https://mock.test/c/{number}",
            source="mock.test", source_url=f"https://mock.test/c/{number}",
            is_backup=False,
        )

    @pytest.fixture
    def state(self):
        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass
        return S()

    def test_default_names_sort_in_chapter_order(self, tmp_path,
                                                 patch_get_scraper, state):
        # Issue #241: complete default-template file names, extension
        # included, sort in chapter order in the real output directory.
        from memanga.downloader import download_chapter
        manga = {"title": "MyManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        numbers = ["2", "2 Part 2", "2 Part 10", "2.001", "2.5", "3", "10"]
        paths = [Path(download_chapter(manga, self._chapter(n), tmp_path,
                                       "cbz", state))
                 for n in numbers]
        names = dict(zip(numbers, (p.name for p in paths)))
        assert names == {
            "2": "MyManga - Chapter 0002.000.cbz",
            "2 Part 2": "MyManga - Chapter 0002_Part 02.cbz",
            "2 Part 10": "MyManga - Chapter 0002_Part 10.cbz",
            "2.001": "MyManga - Chapter 0002.001.cbz",
            "2.5": "MyManga - Chapter 0002.500.cbz",
            "3": "MyManga - Chapter 0003.000.cbz",
            "10": "MyManga - Chapter 0010.000.cbz",
        }
        listing = [p.name for p in paths[0].parent.iterdir()]
        assert sorted(listing) == sorted(names.values())
        for key in (None, _alnum_collation_key):
            order = sorted(listing, key=key)
            # Chapter 2 first, then its decimals in value order; its parts
            # after its numeric names (in part order); then 3 and 10.
            assert order[0] == names["2"]
            assert order.index(names["2.001"]) < order.index(names["2.5"])
            assert set(order[1:5]) == {names["2.001"], names["2.5"],
                                       names["2 Part 2"], names["2 Part 10"]}
            assert (order.index(names["2 Part 2"])
                    < order.index(names["2 Part 10"]))
            assert order[5:] == [names["3"], names["10"]]

    @pytest.mark.parametrize("output_format", ["cbz", "pdf", "epub", "zip"])
    def test_long_title_paths_stay_distinct(self, tmp_path,
                                            patch_get_scraper, state,
                                            output_format):
        # Issue #241: with a long title the 100-character cap used to cut
        # the source label, so "2" and "2.0" wrote to one path.
        from memanga.downloader import _format_chapter_number, download_chapter
        manga = {"title": _LONG_TITLE, "url": "https://mock.test/m",
                 "source": "mock.test"}
        labels = ["2", "2.0", "2.00", "2.5", "3", "10", "2 Part 2",
                  "2 Part 10"]
        paths = {n: Path(download_chapter(manga, self._chapter(n), tmp_path,
                                          output_format, state))
                 for n in labels}
        assert len(set(paths.values())) == len(labels)
        folder = paths["2"].parent
        assert all(p.parent == folder for p in paths.values())
        assert sorted(p.name for p in folder.iterdir()) == \
            sorted(p.name for p in paths.values())
        for label, path in paths.items():
            assert len(path.stem) <= 100
            assert path.stem.endswith(
                f" - Chapter {_format_chapter_number(label)}"), path.name
        for key in (None, _alnum_collation_key):
            order = sorted((p.name for p in paths.values()), key=key)
            rank = {name: i for i, name in enumerate(order)}
            same_number = {paths[n].name for n in ("2", "2.0", "2.00")}
            assert set(order[:3]) == same_number
            assert max(rank[n] for n in same_number) < rank[paths["2.5"].name]
            assert rank[paths["2 Part 2"].name] < rank[paths["2 Part 10"].name]
            assert order[-2:] == [paths["3"].name, paths["10"].name]

    @pytest.mark.parametrize("output_format", ["cbz", "pdf"])
    def test_distinct_labels_never_overwrite(self, tmp_path,
                                             patch_get_scraper, state,
                                             output_format):
        # Issue #241: "2" and "2.00" (and other labels with the same
        # number) used to map to one path, and the writers replace it.
        from memanga.downloader import download_chapter
        manga = {"title": "MyManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        labels = ["2", "2.0", "2.00", "02", "2.001", "2.01", "2.05", "2.5",
                  "2.50", "3", "10", "2 Part 2", "2 Part 10", "2 part 2"]
        paths = [Path(download_chapter(manga, self._chapter(n), tmp_path,
                                       output_format, state))
                 for n in labels]
        assert len(set(paths)) == len(labels)
        assert all(p.parent == paths[0].parent for p in paths)
        listing = sorted(p.name for p in paths[0].parent.iterdir())
        assert listing == sorted(p.name for p in paths)
        assert "MyManga - Chapter 0002.000 (2.00).%s" % output_format \
            in listing

    def test_image_folder_name_is_padded(self, tmp_path, patch_get_scraper,
                                         state):
        from memanga.downloader import download_chapter
        manga = {"title": "MyManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        path = download_chapter(manga, self._chapter("7"), tmp_path, "jpg",
                                state)
        assert Path(path).name == "Chapter 0007.000"
        assert Path(path).is_dir()


# ─────────────────────────────────────────────────────────────────────────
# download_chapter — issue #89: optional post-processing hook
# ─────────────────────────────────────────────────────────────────────────


class TestPostProcessing:
    """Verify the configurable post-download command hook."""

    @pytest.fixture
    def fake_state(self):
        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass
        return S()

    def _manga_and_chapter(self):
        manga = {"title": "PPManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="3", title="", url="https://mock.test/c/3",
            source="mock.test", source_url="https://mock.test/c/3",
            is_backup=False,
        )
        return manga, chapter

    def test_disabled_by_default_does_not_run(self, tmp_path,
                                              patch_get_scraper, fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "ran.txt"
        pp = {"enabled": False, "command": f'touch "{marker}"',
              "fail_on_error": False}
        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)
        assert not marker.exists()

    def test_none_config_is_noop(self, tmp_path, patch_get_scraper, fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        # Simply must not raise when no config is passed.
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=None)
        assert path is not None

    def test_successful_command_runs(self, tmp_path, patch_get_scraper,
                                     fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "ran.txt"
        pp = {
            "enabled": True,
            "command": (
                f'"{sys.executable}" -c '
                f'"from pathlib import Path; Path({str(marker)!r}).touch()"'
            ),
            "fail_on_error": True,
        }
        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)
        assert marker.exists()

    def test_placeholders_and_env_vars(self, tmp_path, patch_get_scraper,
                                       fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        out_marker = tmp_path / "placeholders.txt"
        env_marker = tmp_path / "env.txt"
        script = tmp_path / "record_post_processing.py"
        script.write_text(
            "import os, sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text('|'.join(sys.argv[3:]))\n"
            "Path(sys.argv[2]).write_text('|'.join([\n"
            "    os.environ['MEMANGA_MANGA_TITLE'],\n"
            "    os.environ['MEMANGA_CHAPTER'],\n"
            "    os.environ['MEMANGA_OUTPUT_FORMAT'],\n"
            "    os.environ['MEMANGA_IS_DIR'],\n"
            "]))\n"
            "assert Path(os.environ['MEMANGA_OUTPUT_PATH']).exists()\n"
        )
        command = (
            f'"{sys.executable}" "{script}" "{out_marker}" "{env_marker}" '
            "{title} {chapter} {source} {format} {is_dir}"
        )
        pp = {"enabled": True, "command": command, "fail_on_error": True}
        download_chapter(manga, chapter, tmp_path, "cbz", fake_state,
                         post_processing=pp)
        assert out_marker.read_text().strip() == "PPManga|3|mock.test|cbz|0"
        assert env_marker.read_text().strip() == "PPManga|3|cbz|0"

    def test_image_folder_output_is_dir_flag(self, tmp_path, patch_get_scraper,
                                             fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "isdir.txt"
        script = tmp_path / "check_dir.py"
        script.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['MEMANGA_OUTPUT_PATH']).is_dir() or exit(1)\n"
            f"Path({str(marker)!r}).write_text(os.environ['MEMANGA_IS_DIR'])\n"
        )
        # For an image folder, is_dir should be "1" and the path a directory.
        command = f'"{sys.executable}" "{script}"'
        pp = {"enabled": True, "command": command, "fail_on_error": True}
        path = download_chapter(manga, chapter, tmp_path, "jpg", fake_state,
                                post_processing=pp)
        assert Path(path).is_dir()
        assert marker.read_text().strip() == "1"

    def test_fail_on_error_false_only_warns(self, tmp_path, patch_get_scraper,
                                            fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
            "fail_on_error": False,
        }
        # Should NOT raise — download stays successful.
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=pp)
        assert path is not None and Path(path).exists()

    def test_fail_on_error_true_raises(self, tmp_path, patch_get_scraper,
                                       fake_state):
        from memanga.downloader import download_chapter, DownloaderError
        manga, chapter = self._manga_and_chapter()
        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" -c "import sys; sys.exit(3)"',
            "fail_on_error": True,
        }
        with pytest.raises(DownloaderError):
            download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                             post_processing=pp)

    def test_empty_command_is_noop(self, tmp_path, patch_get_scraper,
                                   fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        pp = {"enabled": True, "command": "   ", "fail_on_error": True}
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=pp)
        assert path is not None

    def test_placeholder_values_are_not_shell_evaluated(self, tmp_path,
                                                        patch_get_scraper,
                                                        fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "placeholder.txt"
        injected = tmp_path / "injected.txt"
        manga["title"] = f"PPManga; touch {injected}"
        script = tmp_path / "write_arg.py"
        script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(sys.argv[2])\n"
        )

        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" "{script}" "{marker}" {{title}}',
            "fail_on_error": True,
        }

        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp, naming_template="{chapter}")

        assert marker.read_text() == manga["title"]
        assert not injected.exists()

    def test_placeholder_values_are_not_reexpanded(self, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "placeholder.txt"
        script = tmp_path / "write_arg.py"
        script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(sys.argv[2])\n"
        )
        manga["title"] = "Title {source}"

        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" "{script}" "{marker}" {{title}}',
            "fail_on_error": True,
        }

        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)

        assert marker.read_text() == "Title {source}"

    def test_timeout_stops_explicit_shell_children(self, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state,
                                                   monkeypatch):
        sh = shutil.which("sh")
        if not sh:
            pytest.skip("requires POSIX sh")

        import memanga.downloader as dl
        from memanga.downloader import download_chapter, DownloaderError

        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "late.txt"
        monkeypatch.setattr(dl.post_processing, "POST_PROCESSING_TIMEOUT", 1)

        pp = {
            "enabled": True,
            "command": f'"{sh}" -c "sleep 3; touch {marker}"',
            "fail_on_error": True,
        }

        with pytest.raises(DownloaderError, match="timed out"):
            download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                             post_processing=pp)

        time.sleep(3.5)
        assert not marker.exists()


class TestPostProcessingCommandSplit:
    def test_windows_paths_keep_backslashes(self, monkeypatch):
        import memanga.downloader as dl

        monkeypatch.setattr(dl.post_processing.os, "name", "nt")

        assert dl._split_post_processing_command(
            r'python C:\Tools\after_download.py {output_path}'
        ) == ["python", r"C:\Tools\after_download.py", "{output_path}"]
        assert dl._split_post_processing_command(
            r'"C:\Program Files\Tool\hook.exe" "{output_path}"'
        ) == [r"C:\Program Files\Tool\hook.exe", "{output_path}"]
        assert dl._split_post_processing_command(
            r'python --input="C:\Program Files\x" --out="{output_path}"'
        ) == ["python", r"--input=C:\Program Files\x", "--out={output_path}"]


class TestPostProcessingDrainAfterTimeout:
    """The timeout cleanup must stay bounded even if draining keeps blocking."""

    class _FakeStream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _WedgedProcess:
        """A process whose pipes never reach EOF, mimicking a stuck grandchild."""

        def __init__(self):
            import subprocess as sp
            self._sp = sp
            self.communicate_calls = 0
            self.kill_calls = 0
            self.stdout = TestPostProcessingDrainAfterTimeout._FakeStream()
            self.stderr = TestPostProcessingDrainAfterTimeout._FakeStream()

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            raise self._sp.TimeoutExpired(cmd="hook", timeout=timeout)

        def kill(self):
            self.kill_calls += 1

    def test_gives_up_and_closes_pipes_instead_of_hanging(self):
        import memanga.downloader as dl

        proc = self._WedgedProcess()
        stdout, stderr = dl._drain_after_timeout(proc, drain_timeout=0)

        assert (stdout, stderr) == (None, None)
        assert proc.kill_calls == 1
        assert proc.communicate_calls == 2
        assert proc.stdout.closed and proc.stderr.closed

    def test_returns_output_when_drain_succeeds(self):
        import memanga.downloader as dl

        class _CleanProcess:
            def communicate(self, timeout=None):
                return "out", "err"

            def kill(self):  # pragma: no cover - should not be called
                raise AssertionError("kill should not run on a clean drain")

        stdout, stderr = dl._drain_after_timeout(_CleanProcess(), drain_timeout=5)
        assert (stdout, stderr) == ("out", "err")


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
