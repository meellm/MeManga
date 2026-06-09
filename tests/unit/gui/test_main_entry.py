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

import memanga


def _entry_helpers() -> dict:
    src = (Path(memanga.__file__).parent / "gui" / "__main__.py").read_text()
    header = src.split("if getattr(sys")[0]
    ns: dict = {}
    exec(header, ns)
    return ns


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
