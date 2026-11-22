"""Tests for `memanga watch`, the container-native scheduler (#327).

The scheduling loop itself is covered in tests/unit/test_watch.py; these
drive cli.main() with run_watch replaced, so nothing is started.
"""
from __future__ import annotations

import signal
import sys

import pytest


@pytest.fixture
def invoke(monkeypatch, isolated_home):
    """Call cli.main() with patched argv; return the exit code."""
    def _call(*argv):
        from memanga import cli
        # Left over from earlier tests; the watcher itself loads none.
        monkeypatch.setattr(cli, "state", None)
        monkeypatch.setattr(sys, "argv", ["memanga"] + list(argv))
        try:
            cli.main()
            return 0
        except SystemExit as exc:
            # sys.exit(None), how watch dispatch ends, is exit status 0.
            return 0 if exc.code is None else exc.code
    return _call


class _Calls(list):
    pass


@pytest.fixture
def runs(monkeypatch):
    from memanga import watch
    calls = _Calls()
    calls.hook = None

    def fake_run_watch(argv, every, jitter=0, **kwargs):
        calls.append({"argv": argv, "every": every, "jitter": jitter, **kwargs})
        if calls.hook is not None:
            calls.hook()
    monkeypatch.setattr(watch, "run_watch", fake_run_watch)
    return calls


class TestWatchCommand:
    def test_defaults_run_check_auto_quiet_every_6h(self, invoke, runs, capsys):
        assert invoke("watch") == 0
        [call] = runs
        assert call["every"] == 6 * 3600
        assert call["jitter"] == 0
        assert call["argv"] == [sys.executable, "-m", "memanga",
                                "check", "--auto", "--quiet"]
        assert "Checking every 6h" in capsys.readouterr().out

    def test_interval_jitter_and_global_options(self, invoke, runs, tmp_path,
                                                capsys):
        cfg = tmp_path / "cfg"
        assert invoke("--config-dir", str(cfg), "-v", "--plain",
                      "watch", "--every", "12h", "--jitter", "30m") == 0
        [call] = runs
        assert call["every"] == 12 * 3600
        assert call["jitter"] == 30 * 60
        assert call["argv"][3:] == ["--config-dir", str(cfg), "-v", "--plain",
                                    "check", "--auto", "--quiet"]
        assert "plus up to 30m" in capsys.readouterr().out

    def test_relative_config_dir_is_made_absolute(self, invoke, runs, tmp_path,
                                                  monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert invoke("--config-dir", "rel", "watch") == 0
        argv = runs[0]["argv"]
        assert argv[argv.index("--config-dir") + 1] == str(tmp_path / "rel")

    def test_config_dir_from_environment_is_passed_on(self, invoke, runs,
                                                      tmp_path, monkeypatch):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "env"))
        assert invoke("watch") == 0
        argv = runs[0]["argv"]
        assert argv[argv.index("--config-dir") + 1] == str(tmp_path / "env")

    def test_watcher_holds_no_lock_and_loads_nothing(self, invoke, runs,
                                                     tmp_path):
        from memanga import cli, process_lock
        cfg = tmp_path / "cfg"
        seen = {}

        def inside():
            seen["lock"] = cli._config_lock
            seen["held"] = dict(process_lock._held)
            seen["sigterm"] = signal.getsignal(signal.SIGTERM)
        runs.hook = inside
        assert invoke("--config-dir", str(cfg), "watch") == 0
        assert seen["lock"] is None
        assert seen["held"] == {}
        assert not cfg.exists()
        if hasattr(signal, "SIGTERM"):
            assert seen["sigterm"] is cli._raise_termination

    def test_sigterm_exits_143(self, invoke, runs, capsys):
        from memanga import cli

        def terminated():
            raise cli.TerminationRequested(signal.SIGTERM)
        runs.hook = terminated
        assert invoke("watch") == 143
        assert "Terminated" in capsys.readouterr().err

    def test_ctrl_c_exits_130(self, invoke, runs):
        def interrupted():
            raise KeyboardInterrupt
        runs.hook = interrupted
        assert invoke("watch") == 130

    @pytest.mark.parametrize("args, message", [
        (["--every", "10m"], "at least 15m"),
        (["--every", "6"], "invalid duration"),
        (["--jitter", "soon"], "invalid duration"),
    ])
    def test_invalid_durations_are_usage_errors(self, invoke, runs, capsys,
                                                args, message):
        assert invoke("watch", *args) == 2
        assert message in capsys.readouterr().err
        assert runs == []

    def test_frozen_build_is_refused(self, invoke, runs, monkeypatch, capsys):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert invoke("watch") == 1
        assert "command-line version" in capsys.readouterr().err
        assert runs == []

    def test_check_runs_from_source_checkout(self, invoke, runs):
        from pathlib import Path
        import memanga
        from memanga.cron import source_checkout_root
        assert invoke("watch") == 0
        expected = source_checkout_root(Path(memanga.__file__).resolve().parent)
        assert runs[0]["cwd"] == expected


class TestWatchReport:
    @pytest.fixture(autouse=True)
    def _console_output(self, monkeypatch):
        from memanga import cli
        monkeypatch.setattr(cli, "logging_configured", lambda: False)

    def test_finished_ok_goes_to_stdout(self, capsys):
        from memanga import cli
        cli._watch_report("finished", code=0, elapsed=75)
        out = capsys.readouterr().out
        assert "Check finished in 1m15s" in out

    def test_failed_check_warns_on_stderr(self, capsys):
        from memanga import cli
        cli._watch_report("finished", code=3, elapsed=10)
        captured = capsys.readouterr()
        assert "Check exited 3 after 10s; the schedule continues" in captured.err
        assert captured.out == ""

    def test_waiting_shows_next_time(self, capsys):
        from memanga import cli
        cli._watch_report("waiting", delay=6 * 3600)
        assert "(in 6h)" in capsys.readouterr().out


def test_watch_is_in_help(monkeypatch, isolated_home, capsys):
    from memanga import cli
    monkeypatch.setattr(sys, "argv", ["memanga", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "watch" in capsys.readouterr().out
