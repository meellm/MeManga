"""Issue #259: the GUI keeps config, state, covers and scheduled checks
in the root it was launched with."""

import shlex
import subprocess

import pytest


@pytest.fixture
def portable_window(qapp, theme, isolated_home, tmp_path):
    from memanga.gui.app import MeMangaApp
    # Spaces exercise quoting in the scheduled-check commands.
    root = tmp_path / "Portable Root"
    w = MeMangaApp(root)
    yield w, root
    try:
        w.worker.shutdown()
    except Exception:
        pass
    w.close()


def test_gui_paths_follow_selected_root(portable_window, isolated_home,
                                        monkeypatch):
    from memanga.gui.pages import settings as settings_mod

    w, root = portable_window
    assert w.selected_config_dir == root
    assert w.config.config_path == root / "config.yaml"
    assert w.app_state.state_path == root / "state.json"
    assert w.cover_cache._disk_dir == root / "covers"
    w.reload_data()
    assert w.config.config_dir == w.app_state.config_dir == root

    submitted = {}

    def _fake_run(cmd, input=None, **kwargs):
        if cmd == ["crontab", "-"]:
            submitted["crontab"] = input
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "no crontab for tester\n")

    monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
    w._pages["settings"]._install_cron_unix("06", "30")
    line, = [l for l in submitted["crontab"].splitlines() if l]
    command = shlex.split(line.split("* * * ", 1)[1], comments=True)
    i = command.index("memanga")
    assert command[i + 1:i + 4] == ["--config-dir", str(root), "check"]
    assert command[-3:] == [">>", str(root / "memanga.log"), "2>&1"]
    assert not (isolated_home / ".config" / "memanga" / "config.yaml").exists()


def test_windows_task_keeps_quoted_root(portable_window, monkeypatch):
    """#259: the Task Scheduler /TR command pins the selected root,
    quoted for CommandLineToArgvW since the path has spaces."""
    import sys

    from memanga.cron import build_task_command
    from memanga.gui.pages import settings as settings_mod

    w, root = portable_window
    python = r"C:\Program Files\Python312\python.exe"
    monkeypatch.setattr(sys, "executable", python)
    monkeypatch.setattr(settings_mod, "source_checkout_root", lambda: None)
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
    w._pages["settings"]._install_cron_windows("06:30")

    create, = [c for c in calls if c[1] == "/Create"]
    command = create[create.index("/TR") + 1]
    assert command == build_task_command(python, root)
    assert command == (f'"{python}" -m memanga --config-dir "{root}" '
                       "check --auto --quiet")
    assert w.config.get("cron.enabled") is True


@pytest.fixture
def default_window(qapp, theme, isolated_home, monkeypatch):
    from memanga.gui.app import MeMangaApp
    monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
    w = MeMangaApp()
    yield w, isolated_home / ".config" / "memanga"
    try:
        w.worker.shutdown()
    except Exception:
        pass
    w.close()


def _root_used_by(pinned_args, env_root, monkeypatch):
    """Root a later run with the scheduled ``--config-dir`` args picks
    once $MEMANGA_CONFIG_DIR points elsewhere."""
    from memanga.config import resolve_config_dir

    flag, value = pinned_args
    assert flag == "--config-dir"
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(env_root))
    return resolve_config_dir(value)


def test_default_root_cron_pins_config_dir(default_window, monkeypatch,
                                           tmp_path):
    """#259: a window on the default root still writes it into the
    crontab line, so a later $MEMANGA_CONFIG_DIR cannot redirect it."""
    from memanga.gui.pages import settings as settings_mod

    w, default_root = default_window
    assert w.selected_config_dir == default_root
    submitted = {}

    def _fake_run(cmd, input=None, **kwargs):
        if cmd == ["crontab", "-"]:
            submitted["crontab"] = input
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "no crontab for tester\n")

    monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
    w._pages["settings"]._install_cron_unix("06", "30")
    line, = [l for l in submitted["crontab"].splitlines() if l]
    command = shlex.split(line.split("* * * ", 1)[1], comments=True)
    i = command.index("memanga")
    assert command[i + 1:i + 4] == ["--config-dir", str(default_root), "check"]
    assert command[-3:] == [">>", str(default_root / "memanga.log"), "2>&1"]
    assert _root_used_by(command[i + 1:i + 3], tmp_path / "later-env",
                         monkeypatch) == default_root


def test_default_root_windows_task_pins_config_dir(default_window,
                                                   monkeypatch, tmp_path):
    import sys

    from memanga.cron import build_task_command
    from memanga.gui.pages import settings as settings_mod

    w, default_root = default_window
    python = r"C:\Program Files\Python312\python.exe"
    monkeypatch.setattr(sys, "executable", python)
    monkeypatch.setattr(settings_mod, "source_checkout_root", lambda: None)
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(settings_mod.subprocess, "run", _fake_run)
    w._pages["settings"]._install_cron_windows("06:30")

    create, = [c for c in calls if c[1] == "/Create"]
    command = create[create.index("/TR") + 1]
    assert command == build_task_command(python, default_root)
    assert command == (f'"{python}" -m memanga --config-dir '
                       f'"{default_root}" check --auto --quiet')
    assert _root_used_by(["--config-dir", str(default_root)],
                         tmp_path / "later-env", monkeypatch) == default_root


def test_launch_gui_passes_resolved_default_root(isolated_home, monkeypatch):
    """#259: launch_gui() hands MeMangaApp the default as a real path."""
    import memanga.gui as gui
    import memanga.gui.app as app_mod

    monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
    seen = []

    class _Stop(Exception):
        pass

    def _fake_app(config_dir=None):
        seen.append(config_dir)
        raise _Stop

    import PySide6.QtWidgets as qtwidgets
    from memanga.gui import theme

    class _FakeQApp:
        # pytest-qt looks up the running app through this class.
        instance = staticmethod(qtwidgets.QApplication.instance)

        def __init__(self, argv):
            pass

        def setStyle(self, style):
            pass

        def setWindowIcon(self, icon):
            pass

    monkeypatch.setattr(qtwidgets, "QApplication", _FakeQApp)
    monkeypatch.setattr(theme, "apply", lambda qapp: None)
    monkeypatch.setattr(app_mod, "MeMangaApp", _fake_app)
    monkeypatch.setattr(gui, "_ensure_browsers", lambda: None)
    with pytest.raises(_Stop):
        gui.launch_gui()
    assert seen == [isolated_home / ".config" / "memanga"]


def test_launch_gui_rejects_unusable_env_dir(isolated_home, monkeypatch,
                                             capsys, tmp_path):
    """The standalone GUI reads $MEMANGA_CONFIG_DIR and fails clearly
    before any window is created."""
    from memanga.gui import launch_gui

    target = tmp_path / "not-a-dir"
    target.write_text("")
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(target))
    with pytest.raises(SystemExit) as exc:
        launch_gui()
    assert exc.value.code == 1
    assert "not a directory" in capsys.readouterr().err
