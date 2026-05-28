"""Unit tests for the first-run Firefox install flow.

These cover the parts that DON'T need a real Playwright install:
  - progress-line parsing (regex used to pull the percentage out of
    Playwright's stdout)
  - dialog construction + slot behaviour
  - the streaming subprocess runner's success / failure / cancel paths
  - the version-aware browser-presence check
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────
# Percentage parsing
# ─────────────────────────────────────────────────────────────────────


class TestParsePercent:
    @pytest.mark.parametrize("line,expected", [
        ("91 MiB [====================] 100% 0.0s", 100),
        ("45 MiB [==========          ] 50% 1.2s", 50),
        ("Downloading Firefox 134.0 - 12% complete", 12),
        ("3.5% downloaded", 3),
        ("Done.", None),
        ("Downloading Firefox 134.0 (playwright build v1466)", None),
        ("", None),
    ])
    def test_extracts_percent(self, line, expected):
        from memanga.gui.components.firefox_install_dialog import _parse_percent
        assert _parse_percent(line) == expected

    def test_clamps_above_100(self):
        from memanga.gui.components.firefox_install_dialog import _parse_percent
        # Synthetic noise where the regex would match something out of
        # range; the parser still produces a valid 0..100 value.
        assert _parse_percent("999%") == 100

    def test_clamps_negative_noise(self):
        from memanga.gui.components.firefox_install_dialog import _parse_percent
        # The regex doesn't match negative numbers, so it returns None.
        assert _parse_percent("-5%") == 5  # regex matches the "5"


# ─────────────────────────────────────────────────────────────────────
# Dialog construction
# ─────────────────────────────────────────────────────────────────────


class TestDialogConstruction:
    def test_constructs_without_starting_install(self, qapp):
        from memanga.gui.components.firefox_install_dialog import FirefoxInstallDialog
        dlg = FirefoxInstallDialog()
        # Bar starts indeterminate (range 0,0 = busy spinner).
        assert dlg._bar.maximum() == 0
        assert dlg._status_label.text() == "Connecting…"
        # Log is hidden until the user opts in or the install fails.
        # Use isHidden() rather than isVisible() — the dialog isn't
        # realized in tests so isVisible() always returns False.
        assert dlg._log.isHidden()
        dlg.deleteLater()

    def test_progress_signal_switches_bar_to_determinate(self, qapp):
        from memanga.gui.components.firefox_install_dialog import FirefoxInstallDialog
        dlg = FirefoxInstallDialog()
        dlg._signals.progress.emit(42)
        qapp.processEvents()
        assert dlg._bar.maximum() == 100
        assert dlg._bar.value() == 42
        dlg.deleteLater()

    def test_status_signal_updates_label(self, qapp):
        from memanga.gui.components.firefox_install_dialog import FirefoxInstallDialog
        dlg = FirefoxInstallDialog()
        dlg._signals.status.emit("Downloading Firefox…")
        qapp.processEvents()
        assert dlg._status_label.text() == "Downloading Firefox…"
        dlg.deleteLater()

    def test_finished_failure_reveals_log_and_swaps_button(self, qapp):
        from memanga.gui.components.firefox_install_dialog import FirefoxInstallDialog
        dlg = FirefoxInstallDialog()
        dlg._signals.finished.emit(False, "boom: network unreachable")
        qapp.processEvents()
        # `isHidden()` reflects an explicit hide() call; after a
        # failure the dialog has explicitly shown the log.
        assert not dlg._log.isHidden()
        assert "boom: network unreachable" in dlg._log.toPlainText()
        assert dlg._cancel_btn.text() == "Close"
        dlg.deleteLater()

    def test_toggle_log_shows_and_hides(self, qapp):
        from memanga.gui.components.firefox_install_dialog import FirefoxInstallDialog
        dlg = FirefoxInstallDialog()
        assert dlg._log.isHidden()
        dlg._toggle_log()
        qapp.processEvents()
        assert not dlg._log.isHidden()
        dlg._toggle_log()
        qapp.processEvents()
        assert dlg._log.isHidden()
        dlg.deleteLater()


# ─────────────────────────────────────────────────────────────────────
# Streaming installer
# ─────────────────────────────────────────────────────────────────────


class TestStreamingInstaller:
    """Cover the streaming runner without actually launching Playwright.

    We stub `_resolve_install_strategies` to return a synthetic argv
    pointing at a tiny Python one-liner, so the test owns exactly what
    the subprocess will print.
    """

    def _stub_strategies(self, monkeypatch, argvs):
        from memanga import gui as gui_pkg
        monkeypatch.setattr(
            gui_pkg, "_resolve_install_strategies",
            lambda: iter(argvs),
        )

    def test_success_path_calls_on_line_and_returns_ok(self, monkeypatch):
        from memanga.gui import _install_playwright_browsers_stream
        import sys
        argv = [
            sys.executable, "-c",
            "import sys; print('Downloading Firefox 134.0'); "
            "print('50 MiB [==========] 100% 0.0s'); "
            "print('Firefox 134.0 downloaded to /tmp/x'); sys.exit(0)",
        ]
        self._stub_strategies(monkeypatch, [("test", argv)])
        seen: list[str] = []
        ok, err = _install_playwright_browsers_stream(
            on_line=seen.append,
            cancelled=lambda: False,
        )
        assert ok is True
        assert err == ""
        joined = "".join(seen)
        assert "Downloading Firefox" in joined
        assert "100%" in joined
        assert "downloaded to" in joined

    def test_failure_returns_error_text_with_label(self, monkeypatch):
        from memanga.gui import _install_playwright_browsers_stream
        import sys
        argv = [
            sys.executable, "-c",
            "import sys; sys.stderr.write('connection refused\\n'); sys.exit(7)",
        ]
        self._stub_strategies(monkeypatch, [("only", argv)])
        ok, err = _install_playwright_browsers_stream(
            on_line=lambda _l: None,
            cancelled=lambda: False,
        )
        assert ok is False
        assert "only" in err
        assert "exit 7" in err
        assert "connection refused" in err

    def test_cancel_kills_subprocess_and_returns_cancelled(self, monkeypatch):
        from memanga.gui import _install_playwright_browsers_stream
        import sys
        # Loop that prints a line then sleeps, repeatedly. We cancel
        # after the first line is delivered.
        argv = [
            sys.executable, "-c",
            "import time, sys\n"
            "for i in range(100):\n"
            "    print(f'line {i}', flush=True)\n"
            "    time.sleep(0.1)\n",
        ]
        self._stub_strategies(monkeypatch, [("loop", argv)])

        state = {"n": 0}

        def on_line(line):
            state["n"] += 1

        def cancelled():
            return state["n"] >= 1

        ok, err = _install_playwright_browsers_stream(
            on_line=on_line, cancelled=cancelled,
        )
        assert ok is False
        assert err == "cancelled by user"

    def test_falls_through_to_next_strategy_on_failure(self, monkeypatch):
        from memanga.gui import _install_playwright_browsers_stream
        import sys
        bad = [sys.executable, "-c", "import sys; sys.exit(1)"]
        good = [sys.executable, "-c",
                "print('Firefox installed'); import sys; sys.exit(0)"]
        self._stub_strategies(monkeypatch, [("bad", bad), ("good", good)])
        ok, err = _install_playwright_browsers_stream(
            on_line=lambda _l: None,
            cancelled=lambda: False,
        )
        assert ok is True
        assert err == ""

    def test_returns_unknown_when_no_strategies(self, monkeypatch):
        from memanga.gui import _install_playwright_browsers_stream
        self._stub_strategies(monkeypatch, [])
        ok, err = _install_playwright_browsers_stream(
            on_line=lambda _l: None,
            cancelled=lambda: False,
        )
        assert ok is False
        assert "no install strategy available" in err


# ─────────────────────────────────────────────────────────────────────
# Version-aware browser presence check
# ─────────────────────────────────────────────────────────────────────


class TestCheckPlaywrightBrowsers:
    """Regression for the "MangaFire works but WeebCentral crashes"
    bug: the old check only looked for *any* `firefox-*` dir under
    `ms-playwright`. A user upgrading to a newer release exe whose
    bundled Playwright pins a different Firefox revision passed the
    check (their old build was still there) and then crashed at
    runtime with "Executable doesn't exist at .../firefox-<NEW>". The
    fix consults Playwright's own `executable_path` so the exact
    expected binary is what we look for.
    """

    def test_returns_false_when_expected_binary_missing(self, monkeypatch, tmp_path):
        from memanga import gui as gui_pkg

        missing = tmp_path / "firefox-9999" / "nope.exe"
        # Build a fake `sync_playwright()` context that hands back a
        # Playwright object whose firefox.executable_path points at a
        # path that doesn't exist.
        class _FakeFirefox:
            executable_path = str(missing)

        class _FakePW:
            firefox = _FakeFirefox()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        import playwright.sync_api as pwapi
        monkeypatch.setattr(pwapi, "sync_playwright", lambda: _FakePW())
        assert gui_pkg._check_playwright_browsers() is False

    def test_returns_true_when_expected_binary_exists(self, monkeypatch, tmp_path):
        from memanga import gui as gui_pkg

        fake_bin = tmp_path / "firefox-1234" / "firefox.exe"
        fake_bin.parent.mkdir(parents=True)
        fake_bin.write_bytes(b"\x00")

        class _FakeFirefox:
            executable_path = str(fake_bin)

        class _FakePW:
            firefox = _FakeFirefox()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        import playwright.sync_api as pwapi
        monkeypatch.setattr(pwapi, "sync_playwright", lambda: _FakePW())
        assert gui_pkg._check_playwright_browsers() is True

    def test_returns_false_when_playwright_import_fails(self, monkeypatch):
        """If `playwright` can't be imported at all (corrupt install,
        broken venv), we must treat that as "not installed" and trigger
        the install dialog rather than crash on startup."""
        from memanga import gui as gui_pkg

        import builtins
        real_import = builtins.__import__

        def boom(name, *a, **k):
            if name == "playwright.sync_api":
                raise ImportError("simulated")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", boom)
        assert gui_pkg._check_playwright_browsers() is False
