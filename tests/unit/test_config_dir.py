"""Platform config folder and the one-time move of ~/.config/memanga
(issue #249)."""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

import pytest

from memanga import config as config_mod
from memanga.config import MOVED_NOTE, platform_config_dir
from memanga.process_lock import ConfigDirLock, _held, _key


class TestPlatformConfigDir:
    def test_linux_uses_xdg_config_home(self, tmp_path):
        xdg = tmp_path / "xdg"
        got = platform_config_dir("linux", {"XDG_CONFIG_HOME": str(xdg)},
                                  tmp_path / "home")
        assert got == xdg / "memanga"

    @pytest.mark.parametrize("environ", [{}, {"XDG_CONFIG_HOME": ""},
                                         {"XDG_CONFIG_HOME": "relative/cfg"}])
    def test_linux_falls_back_to_dot_config(self, tmp_path, environ):
        home = tmp_path / "home"
        assert platform_config_dir("linux", environ, home) == home / ".config" / "memanga"

    def test_other_unix_follows_xdg(self, tmp_path):
        xdg = tmp_path / "xdg"
        got = platform_config_dir("freebsd14", {"XDG_CONFIG_HOME": str(xdg)},
                                  tmp_path / "home")
        assert got == xdg / "memanga"

    def test_macos_uses_application_support(self, tmp_path):
        home = tmp_path / "home"
        got = platform_config_dir("darwin", {"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
                                  home)
        assert got == home / "Library" / "Application Support" / "memanga"

    def test_windows_uses_appdata(self, tmp_path):
        appdata = tmp_path / "Roaming"
        got = platform_config_dir("win32", {"APPDATA": str(appdata)},
                                  tmp_path / "home")
        assert got == appdata / "memanga"

    def test_windows_without_appdata(self, tmp_path):
        home = tmp_path / "home"
        got = platform_config_dir("win32", {}, home)
        assert got == home / "AppData" / "Roaming" / "memanga"


@pytest.fixture
def dirs(isolated_home, monkeypatch):
    """A legacy ~/.config/memanga and a separate platform folder."""
    legacy = isolated_home / ".config" / "memanga"
    native = isolated_home / "platform" / "memanga"
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    return legacy, native


def _unlocked(*directories) -> bool:
    """No lock of this process is left on ``directories``."""
    return not any(_key(d) in _held for d in directories)


def _seed(directory: Path, title="Blue Lock"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.yaml").write_text(
        f"manga:\n- title: {title}\n  url: https://example.org/{title}\n",
        encoding="utf-8")
    (directory / "state.json").write_text("{}", encoding="utf-8")
    (directory / "covers").mkdir()
    (directory / "covers" / "a.jpg").write_bytes(b"jpg")


class TestSelectedConfigDir:
    def test_flag_wins_over_env(self, dirs, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "env"))
        assert config_mod.selected_config_dir(str(tmp_path / "flag")) == tmp_path / "flag"

    def test_env_wins_over_default(self, dirs, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "env"))
        assert config_mod.selected_config_dir() == tmp_path / "env"

    def test_explicit_is_expanded_and_absolute(self, dirs, monkeypatch, isolated_home):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", "~/cfg")
        assert config_mod.explicit_config_dir() == isolated_home / "cfg"
        monkeypatch.delenv("MEMANGA_CONFIG_DIR")
        assert config_mod.explicit_config_dir() is None

    def test_default_when_nothing_explicit(self, dirs):
        legacy, native = dirs
        assert config_mod.selected_config_dir() == native

    def test_explicit_never_moves_legacy(self, dirs, monkeypatch, tmp_path):
        legacy, native = dirs
        _seed(legacy)
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "env"))
        assert config_mod.selected_config_dir() == tmp_path / "env"
        assert config_mod.selected_config_dir(str(tmp_path / "flag")) == tmp_path / "flag"
        assert (legacy / "config.yaml").exists()
        assert not native.exists()


class TestDefaultConfigDir:
    def test_same_folder_on_linux_needs_no_move(self, isolated_home, monkeypatch):
        legacy = isolated_home / ".config" / "memanga"
        _seed(legacy)
        monkeypatch.setattr(config_mod, "platform_config_dir", lambda: legacy)
        assert config_mod.default_config_dir() == legacy
        assert not (legacy / MOVED_NOTE).exists()

    def test_fresh_install_uses_platform_folder(self, dirs):
        legacy, native = dirs
        assert config_mod.default_config_dir() == native
        assert not native.exists()
        assert not (legacy / MOVED_NOTE).exists()

    def test_legacy_data_is_moved(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        before = (legacy / "config.yaml").read_text(encoding="utf-8")

        assert config_mod.default_config_dir() == native

        assert (native / "config.yaml").read_text(encoding="utf-8") == before
        assert (native / "state.json").exists()
        assert (native / "covers" / "a.jpg").read_bytes() == b"jpg"
        # Only the note is left, so old cron lines can still cd/log here.
        assert sorted(p.name for p in legacy.iterdir()) == [MOVED_NOTE]
        assert str(native) in (legacy / MOVED_NOTE).read_text(encoding="utf-8")
        # The migration lock is released.
        assert _unlocked(legacy, native)

    def test_move_happens_once(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        assert config_mod.default_config_dir() == native
        note = (legacy / MOVED_NOTE).read_text(encoding="utf-8")
        assert config_mod.default_config_dir() == native
        assert (legacy / MOVED_NOTE).read_text(encoding="utf-8") == note

    def test_empty_platform_folder_is_replaced(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        native.mkdir(parents=True)
        assert config_mod.default_config_dir() == native
        assert (native / "config.yaml").exists()

    def test_platform_data_wins_and_legacy_is_left_alone(self, dirs):
        legacy, native = dirs
        _seed(legacy, "Old")
        _seed(native, "New")
        assert config_mod.default_config_dir() == native
        assert "Old" in (legacy / "config.yaml").read_text(encoding="utf-8")
        assert not (legacy / MOVED_NOTE).exists()

    def test_non_empty_platform_folder_keeps_legacy(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        native.mkdir(parents=True)
        (native / "notes.txt").write_text("mine", encoding="utf-8")
        assert config_mod.default_config_dir() == legacy
        assert (legacy / "config.yaml").exists()
        assert sorted(p.name for p in native.iterdir()) == ["notes.txt"]

    @pytest.mark.parametrize("path", ["{legacy}/downloads",
                                      "~/.config/memanga/downloads"])
    def test_path_inside_legacy_keeps_legacy(self, dirs, path):
        legacy, native = dirs
        _seed(legacy)
        path = path.format(legacy=legacy.as_posix())
        with open(legacy / "config.yaml", "a", encoding="utf-8") as f:
            f.write(f"delivery:\n  download_dir: {path}\n")
        assert config_mod.default_config_dir() == legacy
        assert not native.exists()

    def test_windows_path_in_state_keeps_legacy(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        (legacy / "state.json").write_text(
            json.dumps({"x": "C:\\Users\\me\\.config\\memanga\\downloads"}),
            encoding="utf-8")
        assert config_mod.default_config_dir() == legacy

    def test_locked_legacy_is_not_moved(self, dirs, lock_holder):
        legacy, native = dirs
        _seed(legacy)
        lock_holder.hold(legacy)
        assert config_mod.default_config_dir() == legacy
        assert (legacy / "config.yaml").exists()
        assert not native.exists()

    def test_legacy_held_by_this_process_is_not_moved(self, dirs):
        legacy, native = dirs
        _seed(legacy)
        with ConfigDirLock(legacy):
            assert config_mod.default_config_dir() == legacy
        assert not native.exists()

    def test_failed_rename_keeps_legacy(self, dirs, monkeypatch):
        legacy, native = dirs
        _seed(legacy)

        def cross_device(src, dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(config_mod.os, "rename", cross_device)
        assert config_mod.default_config_dir() == legacy
        assert (legacy / "config.yaml").exists()
        assert not (legacy / MOVED_NOTE).exists()
        assert _unlocked(legacy, native)

    def test_config_and_state_follow_the_move(self, dirs):
        from memanga.config import Config
        from memanga.state import State
        legacy, native = dirs
        _seed(legacy)
        config = Config()
        state = State()
        assert config.config_dir == state.config_dir == native
        assert config.get("manga")[0]["title"] == "Blue Lock"


def _status_paths(monkeypatch, capsys, *argv):
    from memanga import cli
    monkeypatch.setattr(sys, "argv", ["memanga", *argv, "status", "--json"])
    capsys.readouterr()
    cli.main()
    return json.loads(capsys.readouterr().out)["paths"]


class TestCliConfigDir:
    def test_default_moves_legacy_and_keeps_library(self, dirs, monkeypatch,
                                                     capsys):
        from memanga import cli
        legacy, native = dirs
        _seed(legacy)
        paths = _status_paths(monkeypatch, capsys)
        assert paths["config_dir"] == str(native)
        assert paths["state"] == str(native / "state.json")
        assert cli.config.config_dir == cli.state.config_dir == native
        assert [m["title"] for m in cli.config.get("manga")] == ["Blue Lock"]

    def test_flag_never_moves_legacy(self, dirs, monkeypatch, capsys, tmp_path):
        legacy, native = dirs
        _seed(legacy)
        root = tmp_path / "portable"
        paths = _status_paths(monkeypatch, capsys, "--config-dir", str(root))
        assert paths["config_dir"] == str(root)
        assert (legacy / "config.yaml").exists()
        assert not native.exists()

    def test_env_var_never_moves_legacy(self, dirs, monkeypatch, capsys,
                                        tmp_path):
        legacy, native = dirs
        _seed(legacy)
        root = tmp_path / "from-env"
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
        paths = _status_paths(monkeypatch, capsys)
        assert paths["config_dir"] == str(root)
        assert (legacy / "config.yaml").exists()
        assert not native.exists()

    @staticmethod
    def _gui_kwargs(monkeypatch, *argv):
        import types
        from memanga import cli
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
        monkeypatch.setattr(sys, "argv", ["memanga", *argv, "--gui"])
        seen = []
        monkeypatch.setitem(sys.modules, "memanga.gui", types.SimpleNamespace(
            launch_gui=lambda **kwargs: seen.append(kwargs)))
        cli.main()
        return seen[0]

    def test_gui_flag_hands_platform_folder_to_gui(self, dirs, monkeypatch):
        legacy, native = dirs
        _seed(legacy)
        got = self._gui_kwargs(monkeypatch)
        assert got["config"].config_dir == native
        assert got["state"].config_dir == native
        assert got["explicit_config_dir"] is None

    def test_gui_with_flag_never_moves_legacy(self, dirs, monkeypatch, tmp_path):
        legacy, native = dirs
        _seed(legacy)
        root = tmp_path / "portable"
        got = self._gui_kwargs(monkeypatch, "--config-dir", str(root))
        assert got["config"].config_dir == got["state"].config_dir == root
        assert (legacy / "config.yaml").exists()
        assert not native.exists()

    def test_gui_with_env_never_moves_legacy(self, dirs, monkeypatch, tmp_path):
        legacy, native = dirs
        _seed(legacy)
        root = tmp_path / "from-env"
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
        got = self._gui_kwargs(monkeypatch)
        assert got["config"].config_dir == got["state"].config_dir == root
        assert (legacy / "config.yaml").exists()
        assert not native.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_symlinked_legacy_to_platform_folder_is_not_moved(isolated_home,
                                                          monkeypatch):
    native = isolated_home / "platform" / "memanga"
    _seed(native)
    legacy = isolated_home / ".config" / "memanga"
    legacy.rmdir()
    legacy.symlink_to(native, target_is_directory=True)
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    assert config_mod.default_config_dir() == native
    assert legacy.is_symlink()


class TestMoveRaceWithCommand:
    """Issue #249: process B picks the legacy folder while process A holds
    its migration lock; A renames it before B takes the operation lock.
    B must never load or save in the recreated, orphaned legacy folder."""

    @staticmethod
    def _stale_selection(monkeypatch, legacy, native, after_move=None):
        """First default_config_dir() call in the CLI returns legacy and
        then lets "process A" finish its move, as in the race.
        ``after_move`` runs right after the rename."""
        from memanga import cli
        real = config_mod.default_config_dir
        calls = []

        def selected_then_moved():
            calls.append(1)
            if len(calls) == 1:
                # The mover creates the parent first (migrate_legacy_config_dir).
                native.parent.mkdir(parents=True, exist_ok=True)
                os.rename(legacy, native)
                legacy.mkdir()
                (legacy / MOVED_NOTE).write_text("moved", encoding="utf-8")
                if after_move is not None:
                    after_move()
                return legacy
            return real()

        monkeypatch.setattr(cli, "default_config_dir", selected_then_moved)
        return calls

    @staticmethod
    def _run(monkeypatch, *argv) -> int:
        from memanga import cli
        monkeypatch.setattr(sys, "argv", ["memanga", *argv])
        try:
            cli.main()
        except SystemExit as e:
            return e.code or 0
        return 0

    def test_mutating_command_saves_in_platform_folder(self, dirs, monkeypatch):
        from memanga import cli
        legacy, native = dirs
        _seed(legacy)
        calls = self._stale_selection(monkeypatch, legacy, native)

        assert self._run(monkeypatch, "config", "set",
                         "delivery.output_format", "epub") == 0

        assert len(calls) == 2
        assert cli.config.config_dir == cli.state.config_dir == native
        assert "epub" in (native / "config.yaml").read_text(encoding="utf-8")
        assert "Blue Lock" in (native / "config.yaml").read_text(encoding="utf-8")
        assert not (legacy / "config.yaml").exists()
        assert not (legacy / "state.json").exists()
        assert _unlocked(legacy, native)

    def test_read_only_command_reads_platform_folder(self, dirs, monkeypatch,
                                                      capsys):
        legacy, native = dirs
        _seed(legacy)
        self._stale_selection(monkeypatch, legacy, native)
        paths = _status_paths(monkeypatch, capsys)
        assert paths["config_dir"] == str(native)
        assert not (legacy / "config.yaml").exists()

    def test_busy_platform_folder_exits_without_writing(self, dirs, monkeypatch,
                                                        lock_holder, capsys):
        """Process A still holds the moved lock: B exits 1 and changes
        nothing anywhere."""
        legacy, native = dirs
        _seed(legacy)
        before = (legacy / "config.yaml").read_text(encoding="utf-8")
        self._stale_selection(monkeypatch, legacy, native,
                              after_move=lambda: lock_holder.hold(native))

        assert self._run(monkeypatch, "config", "set",
                         "delivery.output_format", "epub") == 1
        assert "is using" in capsys.readouterr().err
        assert (native / "config.yaml").read_text(encoding="utf-8") == before
        assert not (legacy / "config.yaml").exists()

    def test_explicit_legacy_path_is_kept(self, dirs, monkeypatch, capsys):
        """--config-dir naming the old folder is a choice, not a stale
        default: it is used even though the platform folder has data."""
        legacy, native = dirs
        _seed(native)
        paths = _status_paths(monkeypatch, capsys, "--config-dir", str(legacy))
        assert paths["config_dir"] == str(legacy)
        assert self._run(monkeypatch, "--config-dir", str(legacy), "config",
                         "set", "delivery.output_format", "cbz") == 0
        assert "cbz" in (legacy / "config.yaml").read_text(encoding="utf-8")
        assert "cbz" not in (native / "config.yaml").read_text(encoding="utf-8")
