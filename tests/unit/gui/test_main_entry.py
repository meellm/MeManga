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


def test_log_dir_follows_config_dir_env(isolated_home, monkeypatch, tmp_path):
    """#259: runtime.log and crash.log land in the selected root."""
    root = tmp_path / "portable"
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
    assert _entry_helpers()["_config_dir"]() == root


def test_log_dir_defaults_to_home_config(isolated_home):
    assert _entry_helpers()["_config_dir"]() == isolated_home / ".config" / "memanga"


def test_log_dir_is_none_when_env_is_unusable(isolated_home, monkeypatch,
                                              tmp_path):
    """A file in $MEMANGA_CONFIG_DIR must not redirect logs to the default."""
    target = tmp_path / "not-a-dir"
    target.write_text("")
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(target))
    assert _entry_helpers()["_config_dir"]() is None


def test_crash_logger_tolerates_uncreatable_root(isolated_home, monkeypatch,
                                                 tmp_path):
    """#259: an override beneath a regular file must not break startup."""
    import sys

    blocker = tmp_path / "blocker"
    blocker.write_text("")
    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(blocker / "memanga"))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    # The logger sits below the frozen-only block: exec it on its own.
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    body = "def _install_crash_logger" + src.split(
        "def _install_crash_logger", 1)[1].split('if __name__ == "__main__"', 1)[0]
    ns = _entry_helpers()
    exec(body, ns)
    ns["_install_crash_logger"]()
    sys.excepthook(ValueError, ValueError("boom"), None)
    assert not (isolated_home / ".config" / "memanga" / "crash.log").exists()


@pytest.mark.parametrize("beneath_file", [True, False])
def test_standalone_gui_reports_unusable_root(tmp_path, beneath_file):
    """#259: `python -m memanga.gui` with a bad $MEMANGA_CONFIG_DIR exits 1
    with one line, no traceback, and creates no default root."""
    import subprocess
    import sys

    home = tmp_path / "home"
    home.mkdir()
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    target = blocker / "memanga" if beneath_file else blocker
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
               MEMANGA_CONFIG_DIR=str(target), QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "memanga.gui"],
        cwd=Path(memanga.__file__).resolve().parent.parent,
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr
    expected = ("cannot use config directory" if beneath_file
                else "is not a directory")
    assert proc.stderr.startswith("error: ") and expected in proc.stderr
    assert not (home / ".config" / "memanga").exists()
