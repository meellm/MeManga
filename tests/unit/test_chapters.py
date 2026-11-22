"""The shared chapter model (issue #227): one set of rules for reading a
number, an order and a display value out of chapter identifiers."""

from __future__ import annotations

import subprocess
import sys

import pytest

from memanga.chapters import (Chapter, ChapterWithSource, chapter_number,
                              chapter_order_key, chapter_sort_key,
                              chapter_value, format_chapter_value)

# label, chapter_value, chapter_sort_key
LABELS = [
    ("5", 5.0, 5.0),
    ("12.5", 12.5, 12.5),
    (".5", 0.5, 0.5),
    ("10.", 10.0, 10.0),
    (" 7 ", 7.0, 7.0),
    ("-1", -1.0, -1.0),
    ("+2", 2.0, 2.0),
    ("Chapter 10", 10.0, 10.0),
    ("10 Part 1", 10.0, 10.0),
    ("3.5 Part 2", 3.5, 3.5),
    ("Vol 2 - 10", 2.0, 2.0),
    # Not decimal chapter numbers: read by the embedded-number rule, and
    # never a non-finite sort key.
    ("1e2", 1.0, 1.0),
    ("nan", None, 0.0),
    ("inf", None, 0.0),
    ("Extra", None, 0.0),
    ("", None, 0.0),
    (None, None, 0.0),
    (7, 7.0, 7.0),
    (2.5, 2.5, 2.5),
    (float("nan"), None, 0.0),
    (float("inf"), None, 0.0),
]


class TestChapterValues:
    @pytest.mark.parametrize("label,value,sort_key", LABELS)
    def test_value_and_sort_key(self, label, value, sort_key):
        assert chapter_value(label) == value
        assert chapter_sort_key(label) == sort_key

    @pytest.mark.parametrize("label,value,_", LABELS)
    def test_chapter_numeric_uses_the_same_rules(self, label, value, _):
        expected = value if value is not None else 0.0
        assert Chapter(number=label).numeric == expected

    def test_chapter_number_reads_the_embedded_number(self):
        assert chapter_number("Chapter 12.5 (Part 2)") == 12.5
        assert chapter_number("Extra") is None

    def test_chapters_sort_by_numeric_value(self):
        chapters = [Chapter(number=n) for n in ("10 Part 1", "2", "Chapter 3", "1.5")]
        assert [c.number for c in sorted(chapters)] == [
            "1.5", "2", "Chapter 3", "10 Part 1"]


class TestChapterOrder:
    LABELS = ["11", "10 Part 1", "2", "Extra", "2.5", "10", "Chapter 3",
              "Bonus", ".5", "-1", "1"]
    EXPECTED = ["-1", "Bonus", "Extra", ".5", "1", "2", "2.5", "Chapter 3",
                "10", "10 Part 1", "11"]

    def test_labelled_decimal_part_and_non_numeric(self):
        assert sorted(self.LABELS, key=chapter_order_key) == self.EXPECTED

    def test_order_does_not_depend_on_input_order(self):
        assert sorted(reversed(self.LABELS), key=chapter_order_key) == self.EXPECTED

    def test_leading_dot_decimal_sorts_by_its_value(self):
        # ".5" is chapter 0.5, before chapter 1, never next to chapter 5.
        assert sorted(["5", "1", ".5"], key=chapter_order_key) == [".5", "1", "5"]
        assert chapter_sort_key(".5") == Chapter(number=".5").numeric == 0.5

    def test_non_numeric_ties_ignore_case(self):
        assert sorted(["Extra", "bonus"], key=chapter_order_key) == ["bonus", "Extra"]

    def test_backup_merge_matches_stored_state_order(self, state):
        # No two labels share a number, so both orders are fully determined.
        from memanga.backup import merge_manga_state
        labels = ["11", "Extra", "2.5", "10 Part 1", ".5", "-1", "2"]
        for label in labels:
            state.add_downloaded_chapter("X", label)
        merged = merge_manga_state({"downloaded": labels}, {})
        assert merged["downloaded"] == state.get_downloaded_chapters("X")


class TestFormatChapterValue:
    @pytest.mark.parametrize("value,expected", [
        (47.0, "47"), (12.5, "12.5"), (0.0, "0"), (3, "3"),
    ])
    def test_whole_numbers_drop_the_decimal(self, value, expected):
        assert format_chapter_value(value) == expected


class TestChapterWithSource:
    def test_keeps_chapter_fields_and_source(self):
        base = Chapter(number="10 Part 1", title="T", url="u", date="d")
        base.group_ids = ["g"]
        ch = ChapterWithSource(base, "mangadex.org", "https://m/x", is_backup=True)
        assert (ch.number, ch.title, ch.url, ch.date) == ("10 Part 1", "T", "u", "d")
        assert (ch.source, ch.source_url, ch.is_backup) == (
            "mangadex.org", "https://m/x", True)
        assert ch.group_ids == ["g"]
        assert ch.group_names == []
        assert ch.numeric == 10.0
        assert isinstance(ch, Chapter)


class TestCompatibleImports:
    def test_old_import_paths_resolve_to_the_model(self):
        import memanga.chapters as chapters
        import memanga.downloader as dl
        import memanga.state as state
        from memanga.downloader import sources
        from memanga.scrapers import base

        assert base.Chapter is chapters.Chapter
        assert dl.ChapterWithSource is chapters.ChapterWithSource
        assert sources.ChapterWithSource is chapters.ChapterWithSource
        assert state._chapter_number is chapters.chapter_number
        assert state._chapter_sort_key is chapters.chapter_sort_key
        assert state._CHAPTER_NUMBER_RE is chapters.CHAPTER_NUMBER_RE

    def test_model_import_stays_light(self):
        code = (
            "import sys, memanga.chapters; "
            "heavy = ('memanga.scrapers', 'memanga.downloader', 'memanga.state'); "
            "sys.exit(1 if any(m == h or m.startswith(h + '.') "
            "for m in sys.modules for h in heavy) else 0)"
        )
        assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class TestSharedRulesInCallers:
    def test_cached_catalogue_counts_labelled_chapters(self):
        from memanga.downloader.updates import _max_cached_chapter
        cached = [{"number": "12 Part 1"}, {"number": "Extra"},
                  {"number": "3"}, {"number": None}, "junk"]
        assert _max_cached_chapter(cached) == 12.0
