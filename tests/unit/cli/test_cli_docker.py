"""Tests for MEMANGA_CLI_ONLY=1 -- Docker image hides and rejects --gui.

The env variable is set in the Dockerfile ENV block so it is present in
every container process.  The three behaviours under test:

  1. --help output omits --gui flag and the epilog example line.
  2. Passing --gui exits 1 and writes a clear message to stderr.
  3. Normal installs (env unset) are unaffected: --gui is visible in help.
"""
from __future__ import annotations

import sys
import types
import pytest


@pytest.fixture
def invoke(monkeypatch, isolated_home):
    """Call cli.main() with patched argv; return exit code."""
    def _call(*argv):
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        monkeypatch.setattr(sys, "argv", ["memanga"] + list(argv))
        try:
            cli.main()
            return 0
        except SystemExit as exc:
            return exc.code
    return _call


class TestCliOnlyEnvVar:
    def test_help_hides_gui_flag(self, monkeypatch, isolated_home, capsys):
        monkeypatch.setenv("MEMANGA_CLI_ONLY", "1")
        monkeypatch.setattr(sys, "argv", ["memanga", "--help"])
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--gui" not in out
        assert "graphical" not in out.lower()

    def test_help_hides_epilog_gui_line(self, monkeypatch, isolated_home, capsys):
        monkeypatch.setenv("MEMANGA_CLI_ONLY", "1")
        monkeypatch.setattr(sys, "argv", ["memanga", "--help"])
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "memanga --gui" not in out

    def test_gui_flag_rejected_exit_1(self, monkeypatch, isolated_home, capsys):
        monkeypatch.setenv("MEMANGA_CLI_ONLY", "1")
        monkeypatch.setattr(sys, "argv", ["memanga", "--gui"])
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--gui" in err
        assert "not available" in err

    def test_gui_flag_visible_in_normal_mode(self, monkeypatch, isolated_home, capsys):
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
        monkeypatch.setattr(sys, "argv", ["memanga", "--help"])
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--gui" in out
        assert "memanga --gui" in out

    def test_gui_flag_launches_gui_in_normal_mode(self, monkeypatch, isolated_home):
        """Without MEMANGA_CLI_ONLY the --gui path reaches launch_gui(), not the error."""
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
        monkeypatch.setattr(sys, "argv", ["memanga", "--gui"])
        import memanga.cli as cli
        from memanga.config import Config
        cli.config = Config()
        launched = []
        fake_gui = types.SimpleNamespace(launch_gui=lambda: launched.append(True))
        monkeypatch.setitem(sys.modules, "memanga.gui", fake_gui)
        cli.main()
        assert launched == [True]
