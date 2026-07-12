"""Tests for memanga.downloader — chapter checking, file output paths,
sanitization, format conversion, fallback delay logic."""

from __future__ import annotations

import types
import sys
import time
import shutil
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────
# _sanitize_filename — pure function, easy to exercise
# ─────────────────────────────────────────────────────────────────────────


class TestSanitizeFilename:
    def test_strips_path_separators(self):
        from memanga.downloader import _sanitize_filename
        assert "/" not in _sanitize_filename("a/b/c")
        assert "\\" not in _sanitize_filename("a\\b\\c")

    def test_strips_reserved_chars(self):
        from memanga.downloader import _sanitize_filename
        out = _sanitize_filename('a<b>c:d"e|f?g*h')
        for ch in '<>:"|?*':
            assert ch not in out

    def test_preserves_safe_text(self):
        from memanga.downloader import _sanitize_filename
        assert _sanitize_filename("Chainsaw Man") == "Chainsaw Man"


class TestFormatChapterNumber:
    def test_integer_passes_through(self):
        from memanga.downloader import _format_chapter_number
        # Plain integers are kept as-is (sorting uses float, not strings).
        assert _format_chapter_number("5") == "5"
        assert _format_chapter_number("10") == "10"

    def test_part_chapters_zero_padded(self):
        from memanga.downloader import _format_chapter_number
        # "2 Part 1" → "2.01" so it sorts between "2" and "2.5".
        assert _format_chapter_number("2 Part 1") == "2.01"
        assert _format_chapter_number("2 Part 2") == "2.02"
        # Lexicographic ordering of part-formatted strings is consistent
        assert _format_chapter_number("2 Part 1") < _format_chapter_number("2 Part 2")

    def test_decimal_chapters_passed_through(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("2.5") == "2.5"


# ─────────────────────────────────────────────────────────────────────────
# check_for_updates — uses mock scraper
# ─────────────────────────────────────────────────────────────────────────


class TestCheckForUpdates:
    def test_returns_chapters_above_last_chapter(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        state.set_last_chapter("Mock", "3")
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new, all_ = check_for_updates(manga, state, return_all=True)
        # Mock returns chapters 1..5, last_chapter=3, so new should be 4 + 5
        nums = [c.number for c in new]
        assert "4" in nums and "5" in nums
        assert "3" not in nums

    def test_returns_all_when_no_last_chapter(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        manga = {"title": "Fresh", "url": "https://mock.test/m",
                 "source": "mock.test"}
        new, all_ = check_for_updates(manga, state, return_all=True)
        assert len(new) >= 5

    def test_from_chapter_override(self, state, patch_get_scraper):
        from memanga.downloader import check_for_updates
        manga = {"title": "Mock", "url": "https://mock.test/m",
                 "source": "mock.test"}
        # from_chapter=3 should include chapters 3+
        # Without return_all=True, the function returns just the list.
        new = check_for_updates(manga, state, from_chapter=3)
        assert all(float(c.number) >= 3 for c in new)


# ─────────────────────────────────────────────────────────────────────────
# download_chapter — issue #23: every format under <dir>/<title>/
# ─────────────────────────────────────────────────────────────────────────


class TestDownloadChapterPath:
    """Verify the issue #23 fix — every format ends up in
    <output_dir>/<manga_title>/*."""

    @pytest.fixture
    def fake_state(self):
        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass
        return S()

    @pytest.mark.parametrize("fmt", ["pdf", "epub", "cbz", "zip", "jpg"])
    def test_output_path_is_under_manga_subfolder(self, fmt, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state):
        from memanga.downloader import download_chapter
        out = tmp_path / "downloads"
        manga = {"title": "Bleach", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="5", title="", url="https://mock.test/c/5",
            source="mock.test", source_url="https://mock.test/c/5",
            is_backup=False,
        )
        path = download_chapter(manga, chapter, out, fmt, fake_state)
        rel = Path(path).relative_to(out)
        assert rel.parts[0] == "Bleach", (
            f"format {fmt!r} produced {rel} — not under Bleach/"
        )


class TestNamingTemplate:
    def test_template_variables_substituted(self, tmp_path,
                                             patch_get_scraper):
        from memanga.downloader import download_chapter

        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass

        manga = {"title": "MyManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://mock.test/c/1",
            source="mock.test", source_url="https://mock.test/c/1",
            is_backup=False,
        )
        path = download_chapter(
            manga, chapter, tmp_path, "pdf", S(),
            naming_template="{title}__ch{chapter}",
        )
        assert "MyManga__ch1" in Path(path).stem


# ─────────────────────────────────────────────────────────────────────────
# download_chapter — issue #89: optional post-processing hook
# ─────────────────────────────────────────────────────────────────────────


class TestPostProcessing:
    """Verify the configurable post-download command hook."""

    @pytest.fixture
    def fake_state(self):
        class S:
            def add_downloaded_chapter(self, *a, **k): pass
            def is_chapter_downloaded(self, *a, **k): return False
            def get_pending_backup(self, *a, **k): return None
            def set_pending_backup(self, *a, **k): pass
            def clear_pending_backup(self, *a, **k): pass
        return S()

    def _manga_and_chapter(self):
        manga = {"title": "PPManga", "url": "https://mock.test/m",
                 "source": "mock.test"}
        chapter = types.SimpleNamespace(
            number="3", title="", url="https://mock.test/c/3",
            source="mock.test", source_url="https://mock.test/c/3",
            is_backup=False,
        )
        return manga, chapter

    def test_disabled_by_default_does_not_run(self, tmp_path,
                                              patch_get_scraper, fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "ran.txt"
        pp = {"enabled": False, "command": f'touch "{marker}"',
              "fail_on_error": False}
        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)
        assert not marker.exists()

    def test_none_config_is_noop(self, tmp_path, patch_get_scraper, fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        # Simply must not raise when no config is passed.
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=None)
        assert path is not None

    def test_successful_command_runs(self, tmp_path, patch_get_scraper,
                                     fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "ran.txt"
        pp = {
            "enabled": True,
            "command": (
                f'"{sys.executable}" -c '
                f'"from pathlib import Path; Path({str(marker)!r}).touch()"'
            ),
            "fail_on_error": True,
        }
        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)
        assert marker.exists()

    def test_placeholders_and_env_vars(self, tmp_path, patch_get_scraper,
                                       fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        out_marker = tmp_path / "placeholders.txt"
        env_marker = tmp_path / "env.txt"
        script = tmp_path / "record_post_processing.py"
        script.write_text(
            "import os, sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text('|'.join(sys.argv[3:]))\n"
            "Path(sys.argv[2]).write_text('|'.join([\n"
            "    os.environ['MEMANGA_MANGA_TITLE'],\n"
            "    os.environ['MEMANGA_CHAPTER'],\n"
            "    os.environ['MEMANGA_OUTPUT_FORMAT'],\n"
            "    os.environ['MEMANGA_IS_DIR'],\n"
            "]))\n"
            "assert Path(os.environ['MEMANGA_OUTPUT_PATH']).exists()\n"
        )
        command = (
            f'"{sys.executable}" "{script}" "{out_marker}" "{env_marker}" '
            "{title} {chapter} {source} {format} {is_dir}"
        )
        pp = {"enabled": True, "command": command, "fail_on_error": True}
        download_chapter(manga, chapter, tmp_path, "cbz", fake_state,
                         post_processing=pp)
        assert out_marker.read_text().strip() == "PPManga|3|mock.test|cbz|0"
        assert env_marker.read_text().strip() == "PPManga|3|cbz|0"

    def test_image_folder_output_is_dir_flag(self, tmp_path, patch_get_scraper,
                                             fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "isdir.txt"
        script = tmp_path / "check_dir.py"
        script.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['MEMANGA_OUTPUT_PATH']).is_dir() or exit(1)\n"
            f"Path({str(marker)!r}).write_text(os.environ['MEMANGA_IS_DIR'])\n"
        )
        # For an image folder, is_dir should be "1" and the path a directory.
        command = f'"{sys.executable}" "{script}"'
        pp = {"enabled": True, "command": command, "fail_on_error": True}
        path = download_chapter(manga, chapter, tmp_path, "jpg", fake_state,
                                post_processing=pp)
        assert Path(path).is_dir()
        assert marker.read_text().strip() == "1"

    def test_fail_on_error_false_only_warns(self, tmp_path, patch_get_scraper,
                                            fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
            "fail_on_error": False,
        }
        # Should NOT raise — download stays successful.
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=pp)
        assert path is not None and Path(path).exists()

    def test_fail_on_error_true_raises(self, tmp_path, patch_get_scraper,
                                       fake_state):
        from memanga.downloader import download_chapter, DownloaderError
        manga, chapter = self._manga_and_chapter()
        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" -c "import sys; sys.exit(3)"',
            "fail_on_error": True,
        }
        with pytest.raises(DownloaderError):
            download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                             post_processing=pp)

    def test_empty_command_is_noop(self, tmp_path, patch_get_scraper,
                                   fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        pp = {"enabled": True, "command": "   ", "fail_on_error": True}
        path = download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                                post_processing=pp)
        assert path is not None

    def test_placeholder_values_are_not_shell_evaluated(self, tmp_path,
                                                        patch_get_scraper,
                                                        fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "placeholder.txt"
        injected = tmp_path / "injected.txt"
        manga["title"] = f"PPManga; touch {injected}"
        script = tmp_path / "write_arg.py"
        script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(sys.argv[2])\n"
        )

        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" "{script}" "{marker}" {{title}}',
            "fail_on_error": True,
        }

        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)

        assert marker.read_text() == manga["title"]
        assert not injected.exists()

    def test_placeholder_values_are_not_reexpanded(self, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state):
        from memanga.downloader import download_chapter
        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "placeholder.txt"
        script = tmp_path / "write_arg.py"
        script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(sys.argv[2])\n"
        )
        manga["title"] = "Title {source}"

        pp = {
            "enabled": True,
            "command": f'"{sys.executable}" "{script}" "{marker}" {{title}}',
            "fail_on_error": True,
        }

        download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                         post_processing=pp)

        assert marker.read_text() == "Title {source}"

    def test_timeout_stops_explicit_shell_children(self, tmp_path,
                                                   patch_get_scraper,
                                                   fake_state,
                                                   monkeypatch):
        sh = shutil.which("sh")
        if not sh:
            pytest.skip("requires POSIX sh")

        import memanga.downloader as dl
        from memanga.downloader import download_chapter, DownloaderError

        manga, chapter = self._manga_and_chapter()
        marker = tmp_path / "late.txt"
        monkeypatch.setattr(dl, "POST_PROCESSING_TIMEOUT", 1)

        pp = {
            "enabled": True,
            "command": f'"{sh}" -c "sleep 3; touch {marker}"',
            "fail_on_error": True,
        }

        with pytest.raises(DownloaderError, match="timed out"):
            download_chapter(manga, chapter, tmp_path, "pdf", fake_state,
                             post_processing=pp)

        time.sleep(3.5)
        assert not marker.exists()


class TestPostProcessingCommandSplit:
    def test_windows_paths_keep_backslashes(self, monkeypatch):
        import memanga.downloader as dl

        monkeypatch.setattr(dl.os, "name", "nt")

        assert dl._split_post_processing_command(
            r'python C:\Tools\after_download.py {output_path}'
        ) == ["python", r"C:\Tools\after_download.py", "{output_path}"]
        assert dl._split_post_processing_command(
            r'"C:\Program Files\Tool\hook.exe" "{output_path}"'
        ) == [r"C:\Program Files\Tool\hook.exe", "{output_path}"]
        assert dl._split_post_processing_command(
            r'python --input="C:\Program Files\x" --out="{output_path}"'
        ) == ["python", r"--input=C:\Program Files\x", "--out={output_path}"]


class TestPostProcessingDrainAfterTimeout:
    """The timeout cleanup must stay bounded even if draining keeps blocking."""

    class _FakeStream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _WedgedProcess:
        """A process whose pipes never reach EOF, mimicking a stuck grandchild."""

        def __init__(self):
            import subprocess as sp
            self._sp = sp
            self.communicate_calls = 0
            self.kill_calls = 0
            self.stdout = TestPostProcessingDrainAfterTimeout._FakeStream()
            self.stderr = TestPostProcessingDrainAfterTimeout._FakeStream()

        def communicate(self, timeout=None):
            self.communicate_calls += 1
            raise self._sp.TimeoutExpired(cmd="hook", timeout=timeout)

        def kill(self):
            self.kill_calls += 1

    def test_gives_up_and_closes_pipes_instead_of_hanging(self):
        import memanga.downloader as dl

        proc = self._WedgedProcess()
        stdout, stderr = dl._drain_after_timeout(proc, drain_timeout=0)

        assert (stdout, stderr) == (None, None)
        assert proc.kill_calls == 1
        assert proc.communicate_calls == 2
        assert proc.stdout.closed and proc.stderr.closed

    def test_returns_output_when_drain_succeeds(self):
        import memanga.downloader as dl

        class _CleanProcess:
            def communicate(self, timeout=None):
                return "out", "err"

            def kill(self):  # pragma: no cover - should not be called
                raise AssertionError("kill should not run on a clean drain")

        stdout, stderr = dl._drain_after_timeout(_CleanProcess(), drain_timeout=5)
        assert (stdout, stderr) == ("out", "err")


# ─────────────────────────────────────────────────────────────────────────
# get_supported_sources — registry exposed to the GUI
# ─────────────────────────────────────────────────────────────────────────


class TestGetSupportedSources:
    def test_returns_nonempty_list(self):
        from memanga.downloader import get_supported_sources
        srcs = get_supported_sources()
        assert isinstance(srcs, (list, set))
        assert len(list(srcs)) > 0

    def test_contains_known_sources(self):
        from memanga.downloader import get_supported_sources
        srcs = set(get_supported_sources())
        # MangaDex + MangaFire are baseline scrapers in this repo.
        assert "mangadex.org" in srcs
        assert "mangafire.to" in srcs
