"""Tests for the frozen-entry helpers in memanga/gui/__main__.py.

The module body is gated on ``sys.frozen`` and imports the GUI at the
bottom, so the helper functions are exec'd from the file header instead
of imported.

Core regression (issue #28): ``PLAYWRIGHT_BROWSERS_PATH`` must be pinned
unconditionally. Playwright's driver transport forces the variable to
``"0"`` (browsers inside the application bundle) for frozen builds when
it is unset, and no browsers ship in the bundle — so the old "set it
only if the directory already exists" logic broke every Playwright
source for the entire first session on a fresh machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import memanga


def _entry_helpers() -> dict:
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    header = src.split("if getattr(sys")[0]
    ns: dict = {}
    exec(header, ns)
    return ns


def test_playwright_verifier_uses_absolute_required_browsers_import():
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    verifier = src.split("def _verify_playwright", 1)[1].split(
        "def main", 1,
    )[0]

    assert "from memanga.gui import _REQUIRED_BROWSERS" in verifier
    assert "from . import _REQUIRED_BROWSERS" not in verifier


class TestConfigurePlaywrightBrowsers:
    def test_env_pinned_even_when_dir_missing(self, monkeypatch, tmp_path):
        ns = _entry_helpers()
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        # Point every platform cache root at an empty location so the
        # computed browsers dir definitely does not exist yet (a fresh
        # machine before the first-launch install).
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "nope"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nope"))
        monkeypatch.setattr(
            ns["Path"], "home", classmethod(lambda cls: tmp_path / "home"),
        )

        result = ns["_configure_playwright_browsers"]()

        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(result)
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] != "0"
        assert result.name == "ms-playwright"
        # The whole point: pinned before the directory exists, so the
        # transport's frozen setdefault("0") can never engage.
        assert not result.exists()

    def test_explicit_user_value_is_honoured(self, monkeypatch, tmp_path):
        ns = _entry_helpers()
        custom = tmp_path / "my-browsers"
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(custom))

        result = ns["_configure_playwright_browsers"]()

        assert result == custom
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(custom)

    def test_bundle_sentinel_is_replaced(self, monkeypatch):
        # "0" means "inside the bundle" — never valid for this app, the
        # bundle ships no browsers. It must be replaced with a real dir.
        ns = _entry_helpers()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")

        result = ns["_configure_playwright_browsers"]()

        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] != "0"
        assert result.name == "ms-playwright"

    def test_browsers_dir_matches_playwright_default_layout(self):
        ns = _entry_helpers()
        d = ns["_playwright_browsers_dir"]()
        assert d.name == "ms-playwright"
        assert d.is_absolute()


class TestVerifyGui:
    """``--verify-gui`` is the release pipeline's frozen GUI smoke test
    (issue #381). Run it from source in a child process — it owns the
    QApplication and exits — headless via Qt's offscreen platform."""

    def _run(self, tmp_path):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   HOME=str(tmp_path), USERPROFILE=str(tmp_path),
                   APPDATA=str(tmp_path),
                   XDG_CONFIG_HOME=str(tmp_path / ".config"))
        return subprocess.run(
            [sys.executable, "-m", "memanga.gui", "--verify-gui"],
            capture_output=True, text=True, timeout=120, env=env,
            cwd=Path(memanga.__file__).resolve().parent.parent,
        )

    def test_brings_up_the_main_window_and_exits_cleanly(self, tmp_path):
        pytest.importorskip("PySide6")
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[VerifyGUI] PASS: main window 'MeManga v" in result.stdout
        assert "platform=offscreen" in result.stdout

    def test_never_touches_the_users_config(self, tmp_path):
        pytest.importorskip("PySide6")
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (tmp_path / ".config" / "memanga").exists()

    def test_runs_before_the_normal_gui_launch(self):
        src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
        gate = src.index('if "--verify-gui" in sys.argv:')
        assert gate < src.index("from memanga.gui import launch_gui")
        # No first-launch browser install dialog in the smoke test.
        body = src.split("def _verify_gui", 1)[1].split("\ndef ", 1)[0]
        assert "_ensure_browsers" not in body
