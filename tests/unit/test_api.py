"""The supported Python API, memanga.api (issue #359)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

import memanga.api as api
from memanga.api import Library, LibraryError, Series, Source


def _write_library(root: Path, manga, state=None, **config) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "manga": manga, **config}
    (root / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    if state is not None:
        payload = {"schema_version": 1, "manga": state}
        (root / "state.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def _snapshot(root: Path):
    return {p.name: p.read_bytes() for p in sorted(root.iterdir())}


@pytest.fixture
def library_dir(isolated_home, tmp_path):
    return _write_library(
        tmp_path / "cfg",
        [
            {"title": "Blue Lock", "status": "reading",
             "sources": [{"source": "mangadex", "url": "https://mangadex.org/title/a"},
                         {"url": ""},
                         "https://example.org/blue-lock"],
             "send_to_kindle": True},
            {"title": "Old Entry", "source": "mangakakalot",
             "url": "https://mangakakalot.com/old", "status": "completed",
             "mode": "manual"},
            {"title": "Paused", "status": "on-hold",
             "sources": [{"source": "mangadex", "url": "https://mangadex.org/title/p"}]},
        ],
        state={
            "Blue Lock": {
                "last_chapter": "10",
                "downloaded": ["10", "2", "9.5", "Extra"],
                "failed_chapters": {"12": {"error": "x"}, "11": {"error": "y"}},
            },
        },
        email={"kindle_scope": "selected"},
    )


class TestPublicSurface:
    def test_all_lists_the_supported_names(self):
        assert sorted(api.__all__) == ["Library", "LibraryError", "Series", "Source"]

    def test_results_are_immutable(self, library_dir):
        series = Library(library_dir).series()[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            series.title = "changed"
        assert isinstance(series.sources, tuple)
        assert isinstance(series.downloaded_chapters, tuple)


class TestSeries:
    def test_reads_every_manga_in_library_order(self, library_dir):
        library = Library(library_dir)
        assert [s.title for s in library.series()] == ["Blue Lock", "Old Entry", "Paused"]
        assert [s.position for s in library.series()] == [1, 2, 3]

    def test_fields_of_a_tracked_manga(self, library_dir):
        blue = Library(library_dir).series()[0]
        assert blue == Series(
            position=1,
            title="Blue Lock",
            status="reading",
            mode="auto",
            sources=(Source("mangadex", "https://mangadex.org/title/a"),
                     Source("example.org", "https://example.org/blue-lock")),
            last_chapter="10",
            downloaded_chapters=("Extra", "2", "9.5", "10"),
            failed_chapters=("11", "12"),
            send_to_kindle=True,
        )

    def test_legacy_single_source_and_defaults(self, library_dir):
        old = Library(library_dir).series()[1]
        assert old.sources == (Source("mangakakalot", "https://mangakakalot.com/old"),)
        assert old.mode == "manual"
        assert old.last_chapter is None
        assert old.downloaded_chapters == ()
        assert old.failed_chapters == ()

    def test_kindle_flag_follows_scope_without_own_choice(self, library_dir):
        assert Library(library_dir).series()[2].send_to_kindle is False

    def test_status_filter(self, library_dir):
        library = Library(library_dir)
        assert [s.title for s in library.series(status="completed")] == ["Old Entry"]
        assert [s.title for s in library.series(status=["reading", "on-hold"])] == [
            "Blue Lock", "Paused"]
        assert library.series(status="dropped") == []

    def test_get_matches_the_exact_title(self, library_dir):
        library = Library(library_dir)
        assert library.get("Paused").position == 3
        assert library.get("paused") is None
        assert library.get("Missing") is None

    def test_empty_library(self, isolated_home, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        assert Library(root).series() == []
        assert Library(root).config_dir == root.absolute()


class TestConfigDirSelection:
    def test_argument_accepts_str_and_path(self, library_dir):
        assert Library(str(library_dir)).config_dir == library_dir
        assert Library(library_dir).config_dir == library_dir

    def test_environment_variable_when_no_argument(self, library_dir, monkeypatch):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(library_dir))
        assert Library().config_dir == library_dir
        assert len(Library().series()) == 3

    def test_default_folder(self, isolated_home):
        default = isolated_home / ".config" / "memanga"
        _write_library(default, [{"title": "Home", "url": "https://mangadex.org/title/h"}])
        library = Library()
        assert library.config_dir == default
        assert [s.title for s in library.series()] == ["Home"]

    def test_download_dir(self, library_dir):
        _write_library(library_dir, [], delivery={"download_dir": str(library_dir / "out")})
        assert Library(library_dir).download_dir == library_dir / "out"


class TestReadOnly:
    def test_opening_and_reading_change_no_file(self, library_dir):
        before = _snapshot(library_dir)
        library = Library(library_dir)
        library.series()
        library.reload()
        assert _snapshot(library_dir) == before

    def test_reload_sees_later_changes(self, library_dir):
        library = Library(library_dir)
        _write_library(library_dir, [{"title": "New", "url": "https://mangadex.org/title/n"}])
        assert len(library.series()) == 3
        library.reload()
        assert [s.title for s in library.series()] == ["New"]

    def test_prints_nothing(self, library_dir, capsys):
        Library(library_dir).series()
        assert capsys.readouterr() == ("", "")

    def test_works_while_the_config_dir_is_locked(self, library_dir):
        from memanga.process_lock import ConfigDirLock
        lock = ConfigDirLock(library_dir)
        lock.acquire()
        try:
            assert len(Library(library_dir).series()) == 3
        finally:
            lock.release()


class TestLoadErrors:
    def test_broken_config_raises(self, library_dir):
        (library_dir / "config.yaml").write_text("manga: [unclosed", encoding="utf-8")
        with pytest.raises(LibraryError, match="config.yaml"):
            Library(library_dir)

    def test_damaged_state_raises_and_is_left_alone(self, library_dir):
        (library_dir / "state.json").write_text("{not json", encoding="utf-8")
        before = _snapshot(library_dir)
        with pytest.raises(LibraryError, match="state.json"):
            Library(library_dir)
        assert _snapshot(library_dir) == before

    def test_failed_reload_keeps_previous_data(self, library_dir):
        library = Library(library_dir)
        (library_dir / "config.yaml").write_text("- not a mapping\n", encoding="utf-8")
        with pytest.raises(LibraryError):
            library.reload()
        assert len(library.series()) == 3


class TestRootIsNeverCreatedOrMoved:
    @pytest.fixture
    def native(self, isolated_home, monkeypatch):
        from memanga import config as config_mod
        native = isolated_home / "native" / "memanga"
        monkeypatch.setattr(config_mod, "platform_config_dir",
                            lambda *args, **kwargs: native)
        return native

    def test_legacy_only_library_is_read_in_place(self, isolated_home, native):
        legacy = _write_library(isolated_home / ".config" / "memanga",
                                [{"title": "Old", "url": "https://mangadex.org/title/o"}])
        before = _snapshot(legacy)
        library = Library()
        assert library.config_dir == legacy
        assert [s.title for s in library.series()] == ["Old"]
        library.reload()
        # Not moved, no moved note, no lock file, platform folder not made.
        assert _snapshot(legacy) == before
        assert not native.exists()
        assert not native.parent.exists()

    def test_platform_folder_wins_when_it_has_data(self, isolated_home, native):
        _write_library(isolated_home / ".config" / "memanga", [{"title": "Old"}])
        _write_library(native, [{"title": "New"}])
        assert Library().config_dir == native

    def test_reload_follows_a_later_move(self, isolated_home, native):
        legacy = _write_library(isolated_home / ".config" / "memanga", [{"title": "Old"}])
        library = Library()
        native.parent.mkdir(parents=True)
        legacy.rename(native)
        legacy.mkdir()
        library.reload()
        assert library.config_dir == native
        assert [s.title for s in library.series()] == ["Old"]

    def test_missing_explicit_folder_raises_and_is_not_created(self, isolated_home, tmp_path):
        missing = tmp_path / "missing" / "cfg"
        with pytest.raises(LibraryError, match="does not exist"):
            Library(missing)
        assert not missing.parent.exists()

    def test_missing_default_folder_raises_and_is_not_created(self, native):
        with pytest.raises(LibraryError, match="does not exist"):
            Library()
        assert not native.parent.exists()

    def test_file_instead_of_folder_raises(self, isolated_home, tmp_path):
        path = tmp_path / "not-a-folder"
        path.write_text("", encoding="utf-8")
        with pytest.raises(LibraryError, match="does not exist"):
            Library(path)


BAD_CONFIGS = {
    "manga-not-a-list": ("not a list", {}),
    "entry-not-a-mapping": (["just text"], {}),
    "no-title": ([{"url": "https://mangadex.org/title/a"}], {}),
    "title-not-text": ([{"title": 5}], {}),
    "status-not-text": ([{"title": "A", "status": ["reading"]}], {}),
    "sources-not-a-list": ([{"title": "A", "sources": "https://mangadex.org/title/a"}], {}),
    "source-url-not-text": ([{"title": "A", "sources": [{"url": 5}]}], {}),
    "source-not-url-or-mapping": ([{"title": "A", "sources": [5]}], {}),
    "download-dir-not-text": ([], {"delivery": {"download_dir": 5}}),
}

BAD_STATES = {
    "manga-not-a-mapping": [],
    "entry-not-a-mapping": {"A": []},
    "entry-null": {"A": None},
    "downloaded-null": {"A": {"downloaded": None}},
    "failed-null": {"A": {"failed_chapters": None}},
    "downloaded-not-a-list": {"A": {"downloaded": "10"}},
    "downloaded-not-chapters": {"A": {"downloaded": [["10"]]}},
    "failed-not-a-mapping": {"A": {"failed_chapters": ["10"]}},
    "last-chapter-not-a-chapter": {"A": {"last_chapter": {"n": 1}}},
}


class TestMalformedValues:
    @pytest.mark.parametrize("manga,extra", BAD_CONFIGS.values(), ids=BAD_CONFIGS.keys())
    def test_bad_config_value_raises_library_error(self, isolated_home, tmp_path,
                                                   manga, extra):
        root = _write_library(tmp_path / "cfg", manga, **extra)
        before = _snapshot(root)
        with pytest.raises(LibraryError, match="config.yaml"):
            Library(root)
        assert _snapshot(root) == before

    @pytest.mark.parametrize("state", BAD_STATES.values(), ids=BAD_STATES.keys())
    def test_bad_state_value_raises_library_error(self, isolated_home, tmp_path, state):
        root = _write_library(tmp_path / "cfg", [{"title": "A"}], state=state)
        before = _snapshot(root)
        with pytest.raises(LibraryError, match="state.json"):
            Library(root)
        assert _snapshot(root) == before

    def test_failed_reload_on_bad_value_keeps_previous_data(self, library_dir):
        library = Library(library_dir)
        _write_library(library_dir, [{"title": "A", "sources": "oops"}])
        with pytest.raises(LibraryError):
            library.reload()
        assert len(library.series()) == 3

    def test_numeric_last_chapter_is_text(self, isolated_home, tmp_path):
        root = _write_library(tmp_path / "cfg", [{"title": "A"}],
                              state={"A": {"last_chapter": 7}})
        assert Library(root).get("A").last_chapter == "7"

    def test_failed_reload_on_null_entry_keeps_previous_data(self, library_dir):
        library = Library(library_dir)
        _write_library(library_dir, [{"title": "A"}], state={"A": None})
        with pytest.raises(LibraryError, match="state.json"):
            library.reload()
        assert len(library.series()) == 3

    def test_null_optional_values_read_as_unset(self, isolated_home, tmp_path):
        root = _write_library(
            tmp_path / "cfg",
            [{"title": "A", "status": None, "mode": None, "source": None,
              "url": None, "send_to_kindle": None}],
            state={"A": {"last_chapter": None}},
        )
        series = Library(root).get("A")
        assert (series.status, series.mode, series.sources, series.last_chapter,
                series.send_to_kindle) == ("reading", "auto", (), None, False)
