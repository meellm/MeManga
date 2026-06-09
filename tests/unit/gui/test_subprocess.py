"""Tests for memanga.gui._subprocess.

open_in_file_manager is the cross-platform "reveal this folder" helper
behind the Downloads/Settings folder buttons (issue #39). The Windows
path must use os.startfile rather than launching Explorer with the
console-hiding flags, which suppressed Explorer's window.
"""

from __future__ import annotations

import os
import sys

import memanga.gui._subprocess as sp
from memanga.gui._subprocess import open_in_file_manager


class TestOpenInFileManager:
    def test_opens_existing_dir_linux(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(sp.sys, "platform", "linux")
        monkeypatch.setattr(sp.subprocess, "run",
                            lambda *a, **k: calls.append(a[0]))
        assert open_in_file_manager(tmp_path) is True
        assert calls == [["xdg-open", str(tmp_path)]]

    def test_opens_dir_macos(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(sp.sys, "platform", "darwin")
        monkeypatch.setattr(sp.subprocess, "run",
                            lambda *a, **k: calls.append(a[0]))
        assert open_in_file_manager(tmp_path) is True
        assert calls == [["open", str(tmp_path)]]

    def test_windows_uses_startfile_not_explorer_subprocess(self, tmp_path,
                                                             monkeypatch):
        seen = []
        monkeypatch.setattr(sp.sys, "platform", "win32")
        monkeypatch.setattr(os, "startfile", lambda p: seen.append(p),
                            raising=False)
        # Any subprocess launch on the Windows path would be the bug.
        def _no_subprocess(*a, **k):
            raise AssertionError("must not spawn a subprocess on Windows")
        monkeypatch.setattr(sp.subprocess, "run", _no_subprocess)
        assert open_in_file_manager(tmp_path) is True
        assert seen == [str(tmp_path)]

    def test_creates_missing_directory(self, tmp_path, monkeypatch):
        target = tmp_path / "downloads" / "MeManga"
        monkeypatch.setattr(sp.sys, "platform", "linux")
        monkeypatch.setattr(sp.subprocess, "run", lambda *a, **k: None)
        assert open_in_file_manager(target) is True
        assert target.is_dir()

    def test_returns_false_when_opener_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sp.sys, "platform", "linux")

        def _boom(*a, **k):
            raise OSError("no file manager")

        monkeypatch.setattr(sp.subprocess, "run", _boom)
        assert open_in_file_manager(tmp_path) is False
