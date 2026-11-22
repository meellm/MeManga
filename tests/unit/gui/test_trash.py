"""Moving files to the system trash (issue #393)."""

import sys
from pathlib import Path

import pytest

from memanga.gui import trash


def test_move_returns_where_the_file_went(fake_trash, tmp_path):
    chapter = tmp_path / "Chapter 1.cbz"
    chapter.write_bytes(b"pages")
    location = trash.move_to_trash(chapter)
    assert not chapter.exists()
    assert Path(location) == fake_trash / "Chapter 1.cbz"
    assert Path(location).read_bytes() == b"pages"


def test_move_takes_a_folder(fake_trash, tmp_path):
    folder = tmp_path / "Chapter 2"
    folder.mkdir()
    (folder / "001.jpg").write_bytes(b"img")
    trash.move_to_trash(folder)
    assert not folder.exists()
    assert (fake_trash / "Chapter 2" / "001.jpg").read_bytes() == b"img"


def _qfile(result, calls=None):
    """A QFile stand-in whose moveToTrash() gives *result* (or raises it)
    and leaves the file where it is."""
    class _QFile:
        def __init__(self, path):
            self._path = path

        def fileName(self):
            return self._path

        def moveToTrash(self):
            if calls is not None:
                calls.append(self._path)
            if isinstance(result, Exception):
                raise result
            return result
    return _QFile


def test_unavailable_trash_keeps_the_file(monkeypatch, tmp_path):
    chapter = tmp_path / "Chapter 1.cbz"
    chapter.write_bytes(b"pages")
    monkeypatch.setattr(trash, "QFile", _qfile(False))
    with pytest.raises(OSError):
        trash.move_to_trash(chapter)
    assert chapter.read_bytes() == b"pages"


@pytest.mark.parametrize("error", [TypeError("bad binding"),
                                   RuntimeError("qt failure")])
def test_binding_error_keeps_the_file(monkeypatch, tmp_path, error):
    # Anything the Qt call raises reaches the caller as OSError, the one
    # error the reader handles by keeping the chapter.
    chapter = tmp_path / "Chapter 1.cbz"
    chapter.write_bytes(b"pages")
    monkeypatch.setattr(trash, "QFile", _qfile(error))
    with pytest.raises(OSError):
        trash.move_to_trash(chapter)
    assert chapter.read_bytes() == b"pages"


def test_non_bool_result_is_not_success(monkeypatch, tmp_path):
    chapter = tmp_path / "Chapter 1.cbz"
    chapter.write_bytes(b"pages")
    monkeypatch.setattr(trash, "QFile", _qfile((True, "")))
    with pytest.raises(OSError):
        trash.move_to_trash(chapter)


def test_missing_file_is_an_error(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(trash, "QFile", _qfile(True, calls))
    with pytest.raises(FileNotFoundError):
        trash.move_to_trash(tmp_path / "gone.cbz")
    assert calls == []


def test_unreported_location_is_empty(monkeypatch, tmp_path):
    # Success that leaves fileName() unchanged means the platform didn't
    # say where the file went.
    chapter = tmp_path / "Chapter 1.cbz"
    chapter.write_bytes(b"pages")
    monkeypatch.setattr(trash, "QFile", _qfile(True))
    assert trash.move_to_trash(chapter) == ""


def test_real_qfile_member_returns_a_bool(tmp_path):
    # The API move_to_trash relies on; a missing path moves nothing.
    from PySide6.QtCore import QFile
    missing = tmp_path / "missing.cbz"
    assert QFile(str(missing)).moveToTrash() is False


def test_trash_name_matches_the_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert trash.trash_name() == "Recycle Bin"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert trash.trash_name() == "Trash"
    monkeypatch.setattr(sys, "platform", "linux")
    assert trash.trash_name() == "Trash"


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="only the freedesktop.org trash can be isolated")
def test_real_trash_follows_the_freedesktop_spec(monkeypatch, tmp_path):
    # The home trash lives under XDG_DATA_HOME, pinned inside tmp_path so
    # the developer's own Trash is never touched.
    data_home = tmp_path / "data"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    data_home.mkdir()
    chapter = tmp_path / "chapter-1.cbz"
    chapter.write_bytes(b"pages")

    location = Path(trash.move_to_trash(chapter))

    assert not chapter.exists()
    assert location.parent == data_home / "Trash" / "files"
    assert location.read_bytes() == b"pages"
    info = data_home / "Trash" / "info" / f"{location.name}.trashinfo"
    assert f"Path={chapter}" in info.read_text()
