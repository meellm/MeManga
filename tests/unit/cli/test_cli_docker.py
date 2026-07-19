"""Tests that --gui is unconditionally hidden and rejected on the CLI branch.

The CLI branch has no memanga.gui package.  These behaviours must hold
regardless of the MEMANGA_CLI_ONLY environment variable:

  1. --help output never shows --gui or the epilog example line.
  2. Passing --gui exits 1 with a clear message to stderr.

MEMANGA_CLI_ONLY is still set in Docker images; the same checks confirm
that Docker containers behave identically (the env var no longer changes
anything on this branch).
"""
from __future__ import annotations

import sys
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


class TestGuiAlwaysHidden:
    """--gui must be absent from help on all CLI installs (with or without Docker env)."""

    def test_help_hides_gui_flag(self, monkeypatch, isolated_home, capsys):
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
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
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
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
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
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


class TestDockerCliOnlyEnvVar:
    """MEMANGA_CLI_ONLY=1 (Docker) produces the same --gui behaviour as a plain CLI install."""

    def test_help_hides_gui_flag_docker(self, monkeypatch, isolated_home, capsys):
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
        assert "memanga --gui" not in out

    def test_gui_flag_rejected_exit_1_docker(self, monkeypatch, isolated_home, capsys):
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
