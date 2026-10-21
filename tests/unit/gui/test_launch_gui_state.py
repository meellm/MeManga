"""launch_gui() with a broken config or a damaged state file (issue #243).

Qt entry points are replaced with fakes so the test never opens a window
or enters the event loop. The fakes forward every other class attribute to
the real Qt class: pytest-qt calls QApplication.instance() around every
test, and runs while these patches are in place.
"""

from __future__ import annotations

import types

import pytest


@pytest.fixture
def cfg_dir(isolated_home):
    d = isolated_home / ".config" / "memanga"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _forwarding(real):
    """Metaclass that sends unknown class attributes to ``real``."""
    class Forward(type):
        def __getattr__(cls, name):
            return getattr(real, name)
    return Forward


@pytest.fixture
def fake_qt(qapp, monkeypatch):
    import PySide6.QtCore
    import PySide6.QtWidgets
    import memanga.gui as gui
    import memanga.gui.app as app_mod

    calls = {"critical": [], "warning": [], "windows": [], "explicit": []}
    real_app = PySide6.QtWidgets.QApplication

    class FakeApplication(metaclass=_forwarding(real_app)):
        # launch_gui() builds its own QApplication; the session already
        # has one (``qapp``), so the constructor must not create another.
        def __init__(self, argv):
            pass

        def setStyle(self, style):
            pass

        def setWindowIcon(self, icon):
            pass

        def exec(self):
            return 0

    class FakeMessageBox(metaclass=_forwarding(PySide6.QtWidgets.QMessageBox)):
        @staticmethod
        def critical(parent, title, text):
            calls["critical"].append(text)

        @staticmethod
        def warning(parent, title, text):
            calls["warning"].append(text)

    class FakeTimer(metaclass=_forwarding(PySide6.QtCore.QTimer)):
        @staticmethod
        def singleShot(msec, fn):
            fn()

    class FakeWindow:
        def __init__(self, config=None, app_state=None,
                     explicit_config_dir=None):
            calls["windows"].append((config, app_state))
            calls["explicit"].append(explicit_config_dir)

        def show(self):
            pass

    monkeypatch.setattr(PySide6.QtWidgets, "QApplication", FakeApplication)
    monkeypatch.setattr(PySide6.QtWidgets, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(PySide6.QtCore, "QTimer", FakeTimer)
    monkeypatch.setattr(app_mod, "MeMangaApp", FakeWindow)
    monkeypatch.setattr(gui, "_set_windows_app_user_model_id", lambda: None)
    monkeypatch.setattr(gui, "_ensure_browsers", lambda: None)
    monkeypatch.setattr(gui, "_load_app_icon", lambda: None)
    monkeypatch.setattr("memanga.gui.theme.apply", lambda qapp: None)
    return calls


def _launch():
    from memanga.gui import launch_gui
    with pytest.raises(SystemExit) as exc:
        launch_gui()
    return exc.value.code


def test_broken_config_shows_error_instead_of_crashing(cfg_dir, fake_qt):
    (cfg_dir / "config.yaml").write_text("manga: [unclosed\n", encoding="utf-8")
    assert _launch() == 1
    assert "config file" in fake_qt["critical"][0]
    assert fake_qt["windows"] == []
    assert (cfg_dir / "config.yaml").read_text(encoding="utf-8") == "manga: [unclosed\n"


def test_unloadable_state_shows_error_and_keeps_file(cfg_dir, fake_qt):
    (cfg_dir / "state.json").mkdir()
    assert _launch() == 1
    assert "state file" in fake_qt["critical"][0]
    assert fake_qt["windows"] == []
    assert (cfg_dir / "state.json").is_dir()


def test_damaged_state_warns_once_window_is_shown(cfg_dir, fake_qt):
    (cfg_dir / "state.json").write_text("{bad", encoding="utf-8")
    assert _launch() == 0
    assert fake_qt["critical"] == []
    assert len(fake_qt["warning"]) == 1
    assert "kept as" in fake_qt["warning"][0]
    config, state = fake_qt["windows"][0]
    assert state.recovery_notice == fake_qt["warning"][0]


def test_healthy_files_show_no_dialog(cfg_dir, fake_qt):
    assert _launch() == 0
    assert fake_qt["critical"] == [] and fake_qt["warning"] == []
    assert len(fake_qt["windows"]) == 1


def test_passed_objects_reach_the_window(cfg_dir, fake_qt):
    """The CLI hands over its loaded config/state (`memanga --gui`); the
    window must get those, not reload a repaired state file."""
    from memanga.config import Config
    from memanga.gui import launch_gui
    from memanga.state import State
    (cfg_dir / "state.json").write_text("{bad", encoding="utf-8")
    config = Config(cfg_dir, tolerate_errors=True)
    state = State(cfg_dir)
    with pytest.raises(SystemExit) as exc:
        launch_gui(config=config, state=state)
    assert exc.value.code == 0
    assert fake_qt["windows"] == [(config, state)]
    assert fake_qt["warning"] == [state.recovery_notice]


def test_window_keeps_passed_config_and_state(qapp, theme, isolated_home):
    from memanga.config import Config
    from memanga.gui.app import MeMangaApp
    from memanga.state import State
    config = Config(tolerate_errors=True)
    state = State()
    w = MeMangaApp(config=config, app_state=state)
    try:
        assert w.config is config
        assert w.app_state is state
    finally:
        try:
            w.worker.shutdown()
        except Exception:
            pass
        w.close()


def test_startup_problem_none_for_healthy_objects():
    from memanga.gui import _startup_problem
    ok = types.SimpleNamespace(load_error=None, config_path="c")
    assert _startup_problem(ok, types.SimpleNamespace(load_error=None)) is None


def test_locked_config_dir_shows_error_and_loads_nothing(cfg_dir, fake_qt,
                                                          lock_holder):
    """Issue #244: another process (a check, another window) holds the
    config directory; the GUI must not load and later overwrite it."""
    (cfg_dir / "state.json").write_text("{bad", encoding="utf-8")
    lock_holder.hold(cfg_dir)
    assert _launch() == 1
    assert "already running" in fake_qt["critical"][0]
    assert str(cfg_dir) in fake_qt["critical"][0]
    assert fake_qt["windows"] == []
    # Not even loaded: a damaged file would have been copied aside.
    assert (cfg_dir / "state.json").read_text(encoding="utf-8") == "{bad"


def test_window_holds_the_config_dir_lock(cfg_dir, fake_qt, lock_holder):
    assert _launch() == 0
    assert len(fake_qt["windows"]) == 1
    assert not lock_holder.can_lock(cfg_dir)


def test_direct_launch_uses_the_cli_default_folder(isolated_home, fake_qt,
                                                   monkeypatch):
    """Issue #249: started on its own, the GUI picks (and moves to) the
    same platform folder the CLI uses by default."""
    from memanga import config as config_mod
    legacy = isolated_home / ".config" / "memanga"
    native = isolated_home / "platform" / "memanga"
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    (legacy / "config.yaml").write_text(
        "manga:\n- title: Blue Lock\n  url: https://example.org/b\n",
        encoding="utf-8")
    assert _launch() == 0
    config, state = fake_qt["windows"][0]
    assert config.config_dir == state.config_dir == native
    assert config.get("manga")[0]["title"] == "Blue Lock"
    assert config_mod.default_config_dir() == native
    assert (legacy / config_mod.MOVED_NOTE).exists()


def test_direct_launch_uses_env_config_dir(isolated_home, fake_qt,
                                           monkeypatch, tmp_path, lock_holder):
    """Issue #249: started on its own, the GUI selects like the CLI:
    $MEMANGA_CONFIG_DIR before the platform folder, and an explicit
    directory never moves the legacy folder."""
    from memanga import config as config_mod
    legacy = isolated_home / ".config" / "memanga"
    native = isolated_home / "platform" / "memanga"
    monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
    (legacy / "state.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "from-env"
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
    assert _launch() == 0
    config, state = fake_qt["windows"][0]
    assert config.config_dir == state.config_dir == root
    assert fake_qt["explicit"] == [root]
    assert not lock_holder.can_lock(root)
    assert (legacy / "state.json").exists()
    assert not native.exists()


def test_explicit_argument_wins_over_env(isolated_home, fake_qt, monkeypatch,
                                         tmp_path):
    from memanga.gui import launch_gui
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "from-env"))
    root = tmp_path / "chosen"
    with pytest.raises(SystemExit) as exc:
        launch_gui(explicit_config_dir=root)
    assert exc.value.code == 0
    config, state = fake_qt["windows"][0]
    assert config.config_dir == state.config_dir == root
    assert fake_qt["explicit"] == [root]
    assert not (tmp_path / "from-env").exists()


def test_cli_explicit_dir_reaches_the_window(cfg_dir, fake_qt, tmp_path):
    """`memanga --config-dir DIR --gui`: the loaded objects and the
    explicit choice both reach the window."""
    from memanga.config import Config
    from memanga.gui import launch_gui
    from memanga.state import State
    root = tmp_path / "portable"
    config = Config(root, tolerate_errors=True)
    state = State(root)
    with pytest.raises(SystemExit) as exc:
        launch_gui(config=config, state=state, explicit_config_dir=root)
    assert exc.value.code == 0
    assert fake_qt["windows"] == [(config, state)]
    assert fake_qt["explicit"] == [root]


class TestMoveRaceWithDirectGui:
    """Issue #249, direct GUI launch: the window picks the legacy folder
    while another process holds its migration lock, which then renames it
    before the GUI takes its lock. The GUI must never load or save in the
    recreated, orphaned legacy folder. Counterpart of
    tests/unit/test_config_dir.py::TestMoveRaceWithCommand."""

    @pytest.fixture
    def dirs(self, isolated_home, monkeypatch):
        from memanga import config as config_mod
        legacy = isolated_home / ".config" / "memanga"
        native = isolated_home / "platform" / "memanga"
        monkeypatch.setattr(config_mod, "platform_config_dir", lambda: native)
        (legacy / "config.yaml").write_text(
            "manga:\n- title: Blue Lock\n  url: https://example.org/b\n",
            encoding="utf-8")
        (legacy / "state.json").write_text("{}", encoding="utf-8")
        return legacy, native

    @staticmethod
    def _stale_selection(monkeypatch, legacy, native, after_move=None):
        """First default_config_dir() call returns legacy, then "the other
        process" finishes its move; later calls resolve normally."""
        import os
        from memanga import config as config_mod
        real = config_mod.default_config_dir
        calls = []

        def selected_then_moved():
            calls.append(1)
            if len(calls) == 1:
                # The mover creates the parent first (migrate_legacy_config_dir).
                native.parent.mkdir(parents=True, exist_ok=True)
                os.rename(legacy, native)
                legacy.mkdir()
                (legacy / config_mod.MOVED_NOTE).write_text("moved", encoding="utf-8")
                if after_move is not None:
                    after_move()
                return legacy
            return real()

        monkeypatch.setattr(config_mod, "default_config_dir", selected_then_moved)
        return calls

    def test_window_loads_and_locks_platform_folder(self, dirs, fake_qt,
                                                    monkeypatch, lock_holder):
        legacy, native = dirs
        calls = self._stale_selection(monkeypatch, legacy, native)

        assert _launch() == 0

        assert len(calls) == 2
        config, state = fake_qt["windows"][0]
        assert config.config_dir == state.config_dir == native
        assert config.get("manga")[0]["title"] == "Blue Lock"
        assert fake_qt["explicit"] == [None]
        assert not lock_holder.can_lock(native)
        # The legacy lock was let go and nothing was saved there.
        assert lock_holder.can_lock(legacy)
        config.set("delivery.output_format", "epub")
        config.save()
        assert "epub" in (native / "config.yaml").read_text(encoding="utf-8")
        assert not (legacy / "config.yaml").exists()
        assert not (legacy / "state.json").exists()

    def test_runtime_log_and_lock_follow_the_window(self, dirs, fake_qt,
                                                    monkeypatch, lock_holder):
        """Issue #226: the windowed entry locked the recreated legacy
        folder for runtime.log after the move. When the window switches
        to the platform folder, the log follows it there and the legacy
        lock is let go instead of being held for the whole session."""
        import os
        import sys
        from pathlib import Path

        import memanga
        from memanga import config as config_mod
        from memanga import gui

        legacy, native = dirs
        # The other process finished its move before the entry started.
        native.parent.mkdir(parents=True, exist_ok=True)
        os.rename(legacy, native)
        legacy.mkdir()
        (legacy / config_mod.MOVED_NOTE).write_text("moved", encoding="utf-8")
        (native / "runtime.log").write_text("earlier session\n", encoding="utf-8")

        src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
        entry: dict = {}
        exec(src.split("if getattr(sys")[0], entry)
        old_log = entry["_open_runtime_log"](legacy)
        old_log.write("entry\n")
        monkeypatch.setattr(sys, "stderr", old_log)
        dup2 = []
        monkeypatch.setattr(os, "dup2", lambda fd, target: dup2.append(target))
        monkeypatch.setattr(gui, "_runtime_log_mover", entry["_move_runtime_log"])
        real = config_mod.default_config_dir
        calls = []

        def stale_then_real():
            calls.append(1)
            return legacy if len(calls) == 1 else real()
        monkeypatch.setattr(config_mod, "default_config_dir", stale_then_real)

        try:
            assert _launch() == 0
            new_log = sys.stderr
            assert new_log is not old_log
            new_log.write("window\n")
            new_log.flush()
        finally:
            old_log.close()

        config, _ = fake_qt["windows"][0]
        assert config.config_dir == native
        assert lock_holder.can_lock(legacy)
        assert not lock_holder.can_lock(native)
        assert dup2 == [2]
        assert (legacy / "runtime.log").read_text(encoding="utf-8") == "entry\n"
        assert (native / "runtime.log").read_text(encoding="utf-8") == "window\n"
        # The platform folder's previous session was rotated, not lost.
        assert (native / "runtime.log.1").read_text(
            encoding="utf-8") == "earlier session\n"
        lock = entry["_runtime_log_lock"]
        assert lock.acquired and lock.config_dir == native
        new_log.close()
        lock.release()

    def test_busy_platform_folder_shows_error_and_loads_nothing(
            self, dirs, fake_qt, monkeypatch, lock_holder):
        """The mover still holds the platform folder: the window is not
        opened and nothing is written anywhere."""
        legacy, native = dirs
        before = (legacy / "config.yaml").read_text(encoding="utf-8")
        self._stale_selection(monkeypatch, legacy, native,
                              after_move=lambda: lock_holder.hold(native))

        assert _launch() == 1

        assert "already running" in fake_qt["critical"][0]
        assert fake_qt["windows"] == []
        assert (native / "config.yaml").read_text(encoding="utf-8") == before
        assert not (legacy / "config.yaml").exists()
        assert not (legacy / "state.json").exists()

    def test_explicit_legacy_path_is_kept(self, dirs, fake_qt, monkeypatch):
        """$MEMANGA_CONFIG_DIR naming the old folder is a choice, not a
        stale default: it is used even though the platform folder has
        data."""
        import os
        legacy, native = dirs
        native.parent.mkdir(parents=True, exist_ok=True)
        os.rename(legacy, native)
        legacy.mkdir()
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(legacy))

        assert _launch() == 0

        config, state = fake_qt["windows"][0]
        assert config.config_dir == state.config_dir == legacy
        assert fake_qt["explicit"] == [legacy]
