"""Real CLI tests — drive `memanga.cli.main()` with sys.argv patched.

Each subcommand is exercised at least once. Network-touching paths
(check / update) are stubbed.
"""

from __future__ import annotations

import io
import json
import os
import pytest
import shlex
import sys
import types
from unittest.mock import patch, MagicMock


@pytest.fixture
def run_cli(monkeypatch, isolated_home):
    """Helper: run `cli.main()` with synthetic argv.

    Every invocation passes `--config-dir` pointing into the isolated
    home, so main() builds a fresh Config/State from disk there and
    writes from earlier `run_cli` calls in the same test are visible.
    """
    config_dir = isolated_home / ".config" / "memanga"

    def _run(*argv):
        monkeypatch.setattr(
            sys, "argv",
            ["memanga", "--config-dir", str(config_dir)] + list(argv),
        )
        from memanga import cli
        try:
            cli.main()
        except SystemExit as exc:
            return exc.code
        return 0
    return _run


@pytest.fixture
def config(isolated_home, monkeypatch):
    """Override the shared `config` fixture for CLI tests so that calling
    `config.get(...)` after a CLI command reflects what the CLI wrote
    to disk. We return a thin wrapper that reloads before each read.
    """
    from memanga.config import Config

    class _ReloadingConfig:
        def __init__(self):
            self._inner = Config()

        def get(self, key, default=None):
            self._inner.reload()
            return self._inner.get(key, default)

        def set(self, key, value):
            return self._inner.set(key, value)

        def save(self):
            return self._inner.save()

    return _ReloadingConfig()


# ─────────────────────────────────────────────────────────────────────────
# Top-level: --help, unknown subcommand
# ─────────────────────────────────────────────────────────────────────────


class TestTopLevel:
    def test_help(self, run_cli, capsys):
        rc = run_cli("--help")
        assert rc == 0
        out = capsys.readouterr().out.lower()
        for sub in ("list", "add", "check", "config", "sources"):
            assert sub in out

    def test_unknown_subcommand_errors(self, run_cli):
        rc = run_cli("not-a-real-command")
        assert rc != 0


# ─────────────────────────────────────────────────────────────────────────
# `list` / `ls` — show the library
# ─────────────────────────────────────────────────────────────────────────


class TestListCommand:
    def test_empty_library(self, run_cli, config, capsys):
        rc = run_cli("list")
        assert rc == 0
        out = capsys.readouterr().out
        # Should mention "no manga" or similar empty-state copy.
        assert "no" in out.lower() or "empty" in out.lower() or out == ""

    def test_with_one_manga(self, run_cli, config, capsys):
        config.set("manga", [{
            "title": "Sample One",
            "url": "https://mangadex.org/x",
            "source": "mangadex.org",
            "status": "reading",
        }])
        config.save()
        # Clear capsys buffer so we only inspect the CLI's output.
        capsys.readouterr()
        rc = run_cli("list")
        assert rc == 0
        assert "Sample One" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────
# `add` — register a manga
# ─────────────────────────────────────────────────────────────────────────


class TestAddCommand:
    def test_add_basic(self, run_cli, config):
        rc = run_cli("add",
                      "--url", "https://mangadex.org/title/abc/x",
                      "--title", "Added One")
        assert rc == 0
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "Added One" in titles

    def test_add_dedupes(self, run_cli, config):
        run_cli("add", "--url", "https://mangadex.org/title/a/x",
                "--title", "Dup")
        run_cli("add", "--url", "https://mangadex.org/title/b/x",
                "--title", "Dup")
        titles = [m["title"] for m in config.get("manga", []) or []]
        # Same title shouldn't appear twice.
        assert titles.count("Dup") == 1


# ─────────────────────────────────────────────────────────────────────────
# `add --fallback-days` — validate before writing config (#420)
# ─────────────────────────────────────────────────────────────────────────


class TestAddFallbackDays:
    @pytest.fixture(autouse=True)
    def no_network(self, monkeypatch):
        from memanga import cli
        monkeypatch.setattr(cli, "get_scraper", lambda source: types.SimpleNamespace(
            get_cover_url=lambda url: None))

    @pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
    @pytest.mark.parametrize("flags", [
        ("--fallback-days", "-1"),
        ("--fallback-days=-7",),
        ("--fallback-days", "-1", "--force"),
        ("--fallback-days", "abc"),
        ("--fallback-days", "1.5"),
    ])
    def test_invalid_delay_does_not_write_config(self, run_cli, isolated_home,
                                                capsys, flags, existing):
        path = isolated_home / ".config" / "memanga" / "config.yaml"
        before = b"# Keep this formatting\nmanga:\n  - title: Existing Manga\n"
        if existing:
            path.write_bytes(before)

        rc = run_cli("add", "--title", "Delay Test",
                     "--url", "https://mangadex.org/title/a/x",
                     "--backup", "https://mangapill.com/manga/1/x", *flags)

        assert rc == 2
        err = capsys.readouterr().err
        assert "--fallback-days" in err
        assert "non-negative integer" in err
        if existing:
            assert path.read_bytes() == before
        else:
            assert not path.exists()

    @pytest.mark.parametrize(("flags", "expected"), [
        (("--fallback-days", "0"), 0),
        (("--fallback-days", "3"), 3),
        (("--fallback-days=7",), 7),
        ((), 2),
    ])
    def test_valid_delay_is_saved(self, run_cli, config, flags, expected):
        rc = run_cli("add", "--title", "Delay Test",
                     "--url", "https://mangadex.org/title/a/x",
                     "--backup", "https://mangapill.com/manga/1/x", *flags)

        assert rc == 0
        [entry] = config.get("manga", [])
        assert entry["fallback_delay_days"] == expected
        assert entry["sources"] == [
            {"url": "https://mangadex.org/title/a/x"},
            {"url": "https://mangapill.com/manga/1/x"},
        ]


# ─────────────────────────────────────────────────────────────────────────
# `remove` / `rm`
# ─────────────────────────────────────────────────────────────────────────


class TestRemoveCommand:
    def test_remove_by_title(self, run_cli, config):
        config.set("manga", [{"title": "Goner", "url": "u",
                              "source": "mangadex.org",
                              "status": "reading"}])
        config.save()
        rc = run_cli("remove", "Goner", "--yes")
        assert rc == 0
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "Goner" not in titles

    def test_remove_unknown_fails(self, run_cli, config, capsys):
        # Issue #239: not found is an error, reported on stderr.
        config.set("manga", [{"title": "Kept", "url": "u",
                              "source": "mangadex.org",
                              "status": "reading"}])
        config.save()
        rc = run_cli("remove", "never-added", "--yes")
        assert rc == 1
        assert "Not found" in capsys.readouterr().err


# ─────────────────────────────────────────────────────────────────────────
# `set` — change a manga's status
# ─────────────────────────────────────────────────────────────────────────


class TestSetStatusCommand:
    def test_set_status_round_trips(self, run_cli, config):
        config.set("manga", [{"title": "Stat", "url": "u",
                              "source": "mangadex.org",
                              "status": "reading"}])
        config.save()
        run_cli("set", "Stat", "completed")
        m = [m for m in config.get("manga", []) if m["title"] == "Stat"][0]
        assert m["status"] == "completed"


# ─────────────────────────────────────────────────────────────────────────
# `update` — change URL / backup / title
# ─────────────────────────────────────────────────────────────────────────


class TestUpdateCommand:
    def test_update_title(self, run_cli, config):
        config.set("manga", [{"title": "Old Title", "url": "u",
                              "source": "mangadex.org",
                              "status": "reading"}])
        config.save()
        rc = run_cli("update", "Old Title", "--title", "New Title")
        assert rc == 0
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "New Title" in titles


# ─────────────────────────────────────────────────────────────────────────
# `check` — find new chapters (mocked)
# ─────────────────────────────────────────────────────────────────────────


class TestCheckCommand:
    def test_check_with_no_manga(self, run_cli, config):
        rc = run_cli("check")
        assert rc == 0  # nothing to do — should exit cleanly

    def test_partial_flags_are_accepted(self, run_cli, config):
        # Issue #86: the partial-tolerance override flags must parse.
        # With no manga, check exits cleanly regardless.
        rc = run_cli("check", "--allow-partial", "--partial-threshold", "10")
        assert rc == 0

    def test_check_out_of_range_threshold_rejected(self, run_cli, config):
        # Issue #86: out-of-range threshold is rejected consistently with
        # `config` (argparse type error).
        rc = run_cli("check", "--partial-threshold", "150")
        assert rc != 0

    def test_allow_and_no_partial_are_mutually_exclusive(self, run_cli, config):
        rc = run_cli("check", "--allow-partial", "--no-partial")
        assert rc != 0  # argparse rejects the conflicting pair

    def test_partial_flags_listed_in_help(self, run_cli, capsys):
        run_cli("check", "--help")
        out = capsys.readouterr().out.lower()
        assert "--allow-partial" in out
        assert "--partial-threshold" in out

    def test_check_with_one_manga(self, run_cli, config, patch_get_scraper,
                                    monkeypatch):
        config.set("manga", [{
            "title": "Mock", "source": "mock.test",
            "url": "https://mock.test/m", "status": "reading", "mode": "manual"
        }])
        config.save()
        # Patch input() so any prompt auto-answers "no".
        monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
        rc = run_cli("check")
        # Either returns 0 (success) or a small int — should not crash.
        assert rc in (0, 1)

    def test_backup_success_in_email_mode_sends_before_marking_downloaded(
            self, run_cli, config, monkeypatch, tmp_path):
        """Issue #86 regression: backup recovery must still run Kindle
        delivery before the chapter is marked downloaded."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        config.set("delivery.mode", "email")
        config.set("email.kindle_email", "reader@example.com")
        config.set("email.sender_email", "sender@example.com")
        config.set("manga", [{
            "title": "Vinland Saga",
            "status": "reading",
            "sources": [
                {"source": "primary.test", "url": "https://primary.test/vs"},
                {"source": "backup.test", "url": "https://backup.test/vs"},
            ],
        }])
        config.save()

        primary_ch = types.SimpleNamespace(
            number="71", title="", url="https://primary.test/c/71",
            source="primary.test", is_backup=False)
        backup_ch = types.SimpleNamespace(
            number="71", title="", url="https://backup.test/c/71",
            source="backup.test", is_backup=True)
        backup_path = tmp_path / "backup.pdf"
        sent = []

        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [primary_ch])
        monkeypatch.setattr(cli, "_find_chapter_on_backup",
                            lambda *a, **k: backup_ch)

        def fake_download(manga, chapter, *args, **kwargs):
            if getattr(chapter, "is_backup", False):
                return backup_path
            raise DownloaderError("primary incomplete",
                                  failed_pages=[13], total_pages=40)

        def fake_send_to_kindle(**kwargs):
            sent.append(kwargs["pdf_path"])
            assert not cli.state.is_chapter_downloaded("Vinland Saga", "71")

        monkeypatch.setattr(cli, "download_chapter", fake_download)
        monkeypatch.setattr(cli, "send_to_kindle", fake_send_to_kindle)
        monkeypatch.setattr(cli, "get_app_password", lambda cfg: "pw")

        rc = run_cli("check", "--auto", "--quiet")

        assert rc == 0
        assert sent == [backup_path]
        assert cli.state.is_chapter_downloaded("Vinland Saga", "71")

    def test_backup_partial_in_email_mode_sends_and_warns(
            self, run_cli, config, monkeypatch, tmp_path):
        """When both sources fail complete downloads, an accepted backup
        partial must be delivered and logged before state is advanced."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        config.set("delivery.mode", "email")
        config.set("email.kindle_email", "reader@example.com")
        config.set("email.sender_email", "sender@example.com")
        config.set("partial_chapters.enabled", True)
        config.set("partial_chapters.threshold_percent", 10)
        config.set("manga", [{
            "title": "Vinland Saga",
            "status": "reading",
            "sources": [
                {"source": "primary.test", "url": "https://primary.test/vs"},
                {"source": "backup.test", "url": "https://backup.test/vs"},
            ],
        }])
        config.save()

        primary_ch = types.SimpleNamespace(
            number="71", title="", url="https://primary.test/c/71",
            source="primary.test", is_backup=False)
        backup_ch = types.SimpleNamespace(
            number="71", title="", url="https://backup.test/c/71",
            source="backup.test", is_backup=True)
        partial_path = tmp_path / "backup-partial.pdf"
        sent = []

        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [primary_ch])
        monkeypatch.setattr(cli, "_find_chapter_on_backup",
                            lambda *a, **k: backup_ch)

        def fake_download(manga, chapter, *args, **kwargs):
            if not getattr(chapter, "is_backup", False):
                raise DownloaderError("primary incomplete",
                                      failed_pages=[13], total_pages=40)
            if not kwargs.get("allow_partial", False):
                raise DownloaderError("backup incomplete",
                                      failed_pages=[7], total_pages=40)
            kwargs["on_partial"]([7], 40)
            return partial_path

        def fake_send_to_kindle(**kwargs):
            sent.append(kwargs["pdf_path"])
            assert not cli.state.is_chapter_downloaded("Vinland Saga", "71")

        monkeypatch.setattr(cli, "download_chapter", fake_download)
        monkeypatch.setattr(cli, "send_to_kindle", fake_send_to_kindle)
        monkeypatch.setattr(cli, "get_app_password", lambda cfg: "pw")

        rc = run_cli("check", "--auto", "--quiet")

        assert rc == 0
        assert sent == [partial_path]
        assert cli.state.is_chapter_downloaded("Vinland Saga", "71")
        assert cli.state.get_partial_chapter("Vinland Saga", "71")["failed_pages"] == [7]
        notifications = cli.state.get("notifications", [])
        assert any("saved as partial" in n["message"] for n in notifications)

    def test_over_threshold_backup_failure_records_failure_not_downloaded(
            self, run_cli, config, monkeypatch):
        """If neither complete nor partial recovery is acceptable, the
        chapter stays failed and is not marked downloaded."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        config.set("partial_chapters.enabled", True)
        config.set("partial_chapters.threshold_percent", 1)
        config.set("manga", [{
            "title": "Vinland Saga",
            "status": "reading",
            "sources": [
                {"source": "primary.test", "url": "https://primary.test/vs"},
                {"source": "backup.test", "url": "https://backup.test/vs"},
            ],
        }])
        config.save()

        primary_ch = types.SimpleNamespace(
            number="71", title="", url="https://primary.test/c/71",
            source="primary.test", is_backup=False)
        backup_ch = types.SimpleNamespace(
            number="71", title="", url="https://backup.test/c/71",
            source="backup.test", is_backup=True)

        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [primary_ch])
        monkeypatch.setattr(cli, "_find_chapter_on_backup",
                            lambda *a, **k: backup_ch)
        monkeypatch.setattr(
            cli, "download_chapter",
            lambda *a, **k: (_ for _ in ()).throw(
                DownloaderError("incomplete", failed_pages=[1], total_pages=10)
            ),
        )

        rc = run_cli("check", "--auto", "--quiet")

        assert rc == cli.EXIT_PARTIAL
        assert not cli.state.is_chapter_downloaded("Vinland Saga", "71")
        failed = cli.state.get_failed_chapters("Vinland Saga")
        assert "71" in failed

    def test_failed_retry_includes_accepted_partials(
            self, run_cli, config, state, monkeypatch, tmp_path):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        config.set("manga", [{
            "title": "Vinland Saga",
            "status": "reading",
            "source": "primary.test",
            "url": "https://primary.test/vs",
        }])
        config.save()

        state.add_downloaded_chapter("Vinland Saga", "71")
        state.add_partial_chapter(
            "Vinland Saga",
            "71",
            source="primary.test",
            failed_pages=[7],
            total_pages=40,
        )
        state.save()
        fixed_path = tmp_path / "fixed.pdf"
        fixed_path.write_bytes(b"%PDF")

        primary_ch = Chapter(
            number="71", title="", url="https://primary.test/c/71", date=None,
        )

        class FakeScraper:
            def get_chapters(self, url):
                return [primary_ch]

        monkeypatch.setattr(cli, "get_scraper", lambda source: FakeScraper())
        monkeypatch.setattr(cli, "download_chapter", lambda *a, **k: fixed_path)

        rc = run_cli("failed", "--retry")

        assert rc == 0
        assert cli.state.is_chapter_downloaded("Vinland Saga", "71")
        assert cli.state.get_partial_chapter("Vinland Saga", "71") is None


# ─────────────────────────────────────────────────────────────────────────
# `status` — show overall config + library counts
# ─────────────────────────────────────────────────────────────────────────


class TestStatusCommand:
    def test_status_outputs(self, run_cli, config, capsys):
        rc = run_cli("status")
        assert rc == 0
        out = capsys.readouterr().out
        # The status command typically shows version + library + delivery.
        assert len(out) > 0


# ─────────────────────────────────────────────────────────────────────────
# `config` — get / set / list
# ─────────────────────────────────────────────────────────────────────────


class TestConfigCommand:
    def test_config_list_runs(self, run_cli, config):
        rc = run_cli("config", "list")
        # Should not raise
        assert rc in (0, 1, 2)

    def test_config_set_and_get(self, run_cli, config):
        rc = run_cli("config", "set", "delivery.output_format", "epub")
        if rc == 0:
            # Reload config from disk
            from memanga.config import Config
            assert Config().get("delivery.output_format") == "epub"

    # ── Non-interactive partial-chapter tolerance (issue #86) ──

    def test_config_partial_on_persists(self, run_cli, config):
        rc = run_cli("config", "--partial", "on", "--partial-threshold", "5")
        assert rc == 0
        assert config.get("partial_chapters.enabled") is True
        assert float(config.get("partial_chapters.threshold_percent")) == 5.0

    def test_config_partial_off_persists(self, run_cli, config):
        run_cli("config", "--partial", "on")
        rc = run_cli("config", "--partial", "off")
        assert rc == 0
        assert config.get("partial_chapters.enabled") is False

    def test_config_threshold_only_keeps_enabled_state(self, run_cli, config):
        # Turn tolerance on, then change only the threshold — enabled
        # state must be preserved.
        run_cli("config", "--partial", "on", "--partial-threshold", "5")
        rc = run_cli("config", "--partial-threshold", "10")
        assert rc == 0
        assert config.get("partial_chapters.enabled") is True
        assert float(config.get("partial_chapters.threshold_percent")) == 10.0

    def test_config_out_of_range_threshold_rejected(self, run_cli, config):
        rc = run_cli("config", "--partial-threshold", "150")
        assert rc != 0  # argparse rejects it, nothing persisted
        assert config.get("partial_chapters.threshold_percent") != 150

    def test_config_non_numeric_threshold_rejected(self, run_cli, config):
        rc = run_cli("config", "--partial-threshold", "lots")
        assert rc != 0

    def test_config_show_does_not_prompt(self, run_cli, config, monkeypatch):
        # --show must return without touching stdin.
        def _boom(*a, **k):
            raise AssertionError("config --show should not prompt")
        monkeypatch.setattr("builtins.input", _boom)
        rc = run_cli("config", "--show")
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────
# `sources` — list registered scrapers
# ─────────────────────────────────────────────────────────────────────────


class TestSourcesCommand:
    def test_lists_sources(self, run_cli, capsys):
        rc = run_cli("sources")
        assert rc == 0
        out = capsys.readouterr().out
        # Should mention at least a couple known sources.
        assert "mangadex.org" in out or "mangafire.to" in out


# ─────────────────────────────────────────────────────────────────────────
# `export` / `import` — backup + restore
# ─────────────────────────────────────────────────────────────────────────


class TestExportImport:
    def test_export_writes_json(self, run_cli, config, tmp_path):
        config.set("manga", [{"title": "Exp", "url": "u",
                              "source": "mangadex.org", "status": "reading"}])
        config.save()
        out = tmp_path / "backup.json"
        rc = run_cli("export", str(out))
        if rc == 0:
            assert out.exists()
            data = json.loads(out.read_text())
            # Export schema should include manga list somewhere.
            assert "manga" in str(data) or "Exp" in str(data)

    def test_export_stamps_schema_version(self, run_cli, config, tmp_path):
        from memanga.backup import EXPORT_VERSION
        out = tmp_path / "backup.json"
        rc = run_cli("export", str(out))
        assert rc == 0
        assert json.loads(out.read_text())["version"] == EXPORT_VERSION

    def test_import_merge(self, run_cli, config, tmp_path):
        # First export
        backup = tmp_path / "x.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "FromImport", "url": "u",
                       "source": "mangadex.org", "status": "reading"}]
        }))
        rc = run_cli("import", str(backup))
        if rc == 0:
            titles = [m["title"] for m in config.get("manga", []) or []]
            assert "FromImport" in titles

    def test_import_merge_preserves_existing_manga_state(
            self, run_cli, config, isolated_home, tmp_path):
        from memanga import cli
        from memanga.state import State

        config.set("manga", [{"title": "Stateful", "url": "local",
                              "source": "mangadex.org",
                              "status": "reading"}])
        config.save()
        state = State(config_dir=isolated_home / ".config" / "memanga")
        state.set("manga", {
            "Stateful": {
                "downloaded": ["1"],
                "read_chapters": ["1"],
                "failed_chapters": {
                    "4": {"error": "local", "attempts": 2},
                },
                "reading_progress": {
                    "last_chapter": "1",
                    "last_read": "2026-07-17T09:00:00",
                },
            }
        })
        backup = tmp_path / "state.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "stateful", "url": "imported",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {
                "stateful": {
                    "downloaded": ["2"],
                    "read_chapters": ["2"],
                    "external_chapters": ["3"],
                    "failed_chapters": {
                        "4": {"error": "imported", "attempts": 1},
                        "5": {"error": "backup", "attempts": 1},
                    },
                    "reading_progress": {
                        "last_chapter": "2",
                        "last_read": "2026-07-17T10:00:00",
                    },
                }
            },
        }))

        assert run_cli("import", str(backup)) == 0

        titles = [m["title"] for m in config.get("manga", []) or []]
        assert titles == ["Stateful"]
        manga_state = cli.state.get("manga", {})
        assert list(manga_state) == ["Stateful"]
        assert "stateful" not in manga_state
        merged = manga_state["Stateful"]
        assert merged["downloaded"] == ["1", "2"]
        assert merged["read_chapters"] == ["1", "2"]
        assert merged["external_chapters"] == ["3"]
        assert merged["failed_chapters"]["4"]["error"] == "local"
        assert merged["failed_chapters"]["5"]["error"] == "backup"
        assert merged["reading_progress"]["last_chapter"] == "2"

    def test_import_merge_keeps_added_title_state_apart_from_orphan(
            self, run_cli, config, isolated_home, tmp_path):
        from memanga import cli
        from memanga.state import State

        config.set("manga", [])
        config.save()
        state = State(config_dir=isolated_home / ".config" / "memanga")
        state.set("manga", {
            "Stateful": {
                "downloaded": ["1"],
                "failed_chapters": {
                    "4": {"error": "local", "attempts": 2},
                },
            }
        })
        backup = tmp_path / "orphan-state.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "stateful", "url": "imported",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {
                "stateful": {
                    "downloaded": ["2"],
                    "failed_chapters": {
                        "5": {"error": "backup", "attempts": 1},
                    },
                }
            },
        }))

        assert run_cli("import", str(backup)) == 0

        titles = [m["title"] for m in config.get("manga", []) or []]
        assert titles == ["stateful"]
        manga_state = cli.state.get("manga", {})
        assert manga_state["Stateful"]["downloaded"] == ["1"]
        assert manga_state["stateful"]["downloaded"] == ["2"]
        assert manga_state["stateful"]["failed_chapters"]["5"]["error"] == "backup"

    def test_import_roundtrip(self, run_cli, config, tmp_path):
        """An export produced by the CLI must import cleanly (issue #42)."""
        config.set("manga", [{"title": "RoundTrip", "url": "u",
                              "source": "mangadex.org", "status": "reading"}])
        config.save()
        backup = tmp_path / "rt.json"
        assert run_cli("export", str(backup)) == 0
        config.set("manga", [])
        config.save()
        assert run_cli("import", str(backup)) == 0
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "RoundTrip" in titles

    def test_import_merge_unions_downloaded_state(self, run_cli, config,
                                                  isolated_home, tmp_path):
        from memanga.state import State

        config.set("manga", [{"title": "Existing", "url": "u",
                              "source": "mangadex.org", "status": "reading"}])
        config.save()
        state = State(config_dir=isolated_home / ".config" / "memanga")
        state.add_downloaded_chapter("Existing", "1")
        state.save()

        backup = tmp_path / "merge-state.json"
        backup.write_text(json.dumps({
            "version": 1,
            "manga": [{"title": "Existing", "url": "u",
                       "source": "mangadex.org", "status": "reading"}],
            "state": {"Existing": {"downloaded": ["2", "10"]}},
        }))

        assert run_cli("import", str(backup)) == 0

        reloaded = State(config_dir=isolated_home / ".config" / "memanga")
        assert reloaded.get_downloaded_chapters("Existing") == ["1", "2", "10"]

    def test_import_missing_version_rejected(self, run_cli, config, tmp_path,
                                             capsys):
        """Issue #42: a file without the export's `version` stamp is not
        a MeManga backup and must not be imported blindly."""
        backup = tmp_path / "noversion.json"
        backup.write_text(json.dumps({
            "manga": [{"title": "Sneaky", "url": "u",
                       "source": "mangadex.org", "status": "reading"}]
        }))
        capsys.readouterr()
        rc = run_cli("import", str(backup))
        assert rc == 1
        assert "version" in capsys.readouterr().err.lower()
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "Sneaky" not in titles

    def test_import_newer_version_rejected(self, run_cli, config, tmp_path,
                                           capsys):
        backup = tmp_path / "future.json"
        backup.write_text(json.dumps({"version": 99, "manga": []}))
        capsys.readouterr()
        rc = run_cli("import", str(backup))
        assert rc == 1
        assert "newer" in capsys.readouterr().err.lower()

    def test_import_malformed_version_rejected(self, run_cli, config,
                                               tmp_path, capsys):
        backup = tmp_path / "bad.json"
        backup.write_text(json.dumps({"version": "one", "manga": []}))
        capsys.readouterr()
        rc = run_cli("import", str(backup))
        assert rc == 1
        assert "version" in capsys.readouterr().err.lower()


# ─────────────────────────────────────────────────────────────────────────
# `search` — live multi-source search (scrapers mocked, no network)
# ─────────────────────────────────────────────────────────────────────────


class _FakeSearchScraper:
    def __init__(self, results=None, chapters=3, search_error=None):
        self._results = results
        self._chapters = chapters
        self._search_error = search_error
        self.get_chapters_calls = []

    def search(self, query):
        if self._search_error:
            raise self._search_error
        if self._results is not None:
            return self._results
        from memanga.scrapers import Manga
        return [Manga(title="Blue Lock", url="https://fake.test/blue-lock",
                      cover_url="https://fake.test/cover.jpg")]

    def get_chapters(self, url):
        self.get_chapters_calls.append(url)
        return [object()] * self._chapters


@pytest.fixture
def fake_search_scraper(monkeypatch):
    """Route every scraper lookup (CLI validation + engine sweep) to one
    fake. Tests pass `--source fake.test` so the sweep stays single-source
    and never consults the real registry."""
    scraper = _FakeSearchScraper()

    def _install(s):
        monkeypatch.setattr("memanga.cli.get_scraper", lambda d: s)
        monkeypatch.setattr("memanga.search.get_scraper", lambda d: s)
        return s

    _install(scraper)
    scraper.reinstall = _install
    return scraper


class TestSearchCommand:
    def test_table_output(self, run_cli, fake_search_scraper, capsys):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test")
        assert rc == 0
        out = capsys.readouterr().out
        assert "Blue Lock" in out
        assert "fake.test" in out
        assert "3" in out            # chapter-count chip
        assert "1 / 1 sources done" in out

    def test_json_output(self, run_cli, fake_search_scraper, capsys):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test", "--json")
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["query"] == "Blue Lock"
        assert payload["sources_searched"] == 1
        assert payload["failed"] == []
        (result,) = payload["results"]
        assert result["title"] == "Blue Lock"
        assert result["source"] == "fake.test"
        assert result["url"] == "https://fake.test/blue-lock"
        assert result["chapters"] == 3

    def test_no_chips_skips_chapter_probe(self, run_cli, fake_search_scraper,
                                          capsys):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--no-chips", "--json")
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["results"][0]["chapters"] is None
        assert fake_search_scraper.get_chapters_calls == []

    def test_limit_caps_per_source_results(self, run_cli, fake_search_scraper,
                                           capsys):
        from memanga.scrapers import Manga
        many = [Manga(title=f"Blue Lock {i}", url=f"https://fake.test/{i}")
                for i in range(8)]
        fake_search_scraper.reinstall(_FakeSearchScraper(results=many))
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--limit", "2", "--no-chips", "--json")
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["results"]) == 2

    def test_add_directly_with_status(self, run_cli, fake_search_scraper,
                                      config):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--add", "1", "--status", "on-hold", "--no-chips")
        assert rc == 0
        (manga,) = config.get("manga", [])
        assert manga["title"] == "Blue Lock"
        assert manga["source"] == "fake.test"
        assert manga["url"] == "https://fake.test/blue-lock"
        assert manga["cover_url"] == "https://fake.test/cover.jpg"
        assert manga["status"] == "on-hold"

    def test_add_duplicate_rejected(self, run_cli, fake_search_scraper,
                                    config):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--add", "1", "--no-chips")
        assert rc == 0
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--add", "1", "--no-chips")
        assert rc == 1
        assert len(config.get("manga", [])) == 1

    def test_add_out_of_range(self, run_cli, fake_search_scraper, config):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--add", "99", "--no-chips")
        assert rc == 1
        assert config.get("manga", []) == []

    def test_json_add_out_of_range_exits_nonzero(self, run_cli,
                                                 fake_search_scraper,
                                                 capsys):
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--add", "99", "--no-chips", "--json")
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["added"]["ok"] is False

    def test_no_results(self, run_cli, fake_search_scraper, capsys):
        fake_search_scraper.reinstall(_FakeSearchScraper(results=[]))
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--no-chips")
        assert rc == 1
        assert "No results" in capsys.readouterr().err

    def test_source_failure_reported(self, run_cli, fake_search_scraper,
                                     capsys):
        fake_search_scraper.reinstall(
            _FakeSearchScraper(search_error=RuntimeError("HTTP 502")))
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--no-chips")
        assert rc == 1
        err = capsys.readouterr().err
        assert "1 failed" in err
        assert "HTTP 502" in err

    def test_unknown_source_errors(self, run_cli, isolated_home, capsys):
        rc = run_cli("search", "Blue Lock",
                     "--source", "not-a-real-source.example")
        assert rc == 1
        assert "Unknown source" in capsys.readouterr().err

    def test_irrelevant_results_filtered(self, run_cli, fake_search_scraper,
                                         capsys):
        from memanga.scrapers import Manga
        fake_search_scraper.reinstall(_FakeSearchScraper(results=[
            Manga(title="Blue Lock", url="https://fake.test/bl"),
            Manga(title="Beastars", url="https://fake.test/beastars"),
        ]))
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--no-chips", "--json")
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert [r["title"] for r in payload["results"]] == ["Blue Lock"]

    def test_default_source_selection_used(self, run_cli, monkeypatch,
                                           fake_search_scraper, capsys):
        """Without --source the command sweeps compute_search_sources()."""
        monkeypatch.setattr("memanga.cli.compute_search_sources",
                            lambda cfg: ["fake.test", "other.test"])
        rc = run_cli("search", "Blue Lock", "--no-chips", "--json")
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["sources_searched"] == 2


# ─────────────────────────────────────────────────────────────────────────
# `cron` — install / status / remove scheduled task
# ─────────────────────────────────────────────────────────────────────────


def _capture_crontab(monkeypatch, existing=None):
    """Fake a crontab on Linux (empty, or ``existing`` text); return the
    dict that receives the text `cron install` submits under
    ``"crontab"`` and records a `crontab -r` under ``"removed"``."""
    from memanga import cli

    submitted = {}

    def _run(argv, *a, **k):
        if argv == ["crontab", "-r"]:
            submitted["removed"] = True
        if existing is None:
            return types.SimpleNamespace(returncode=1, stdout="",
                                         stderr="no crontab for tester\n")
        return types.SimpleNamespace(returncode=0, stdout=existing, stderr="")

    class _FakePopen:
        returncode = 0

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, input=None):
            submitted["crontab"] = input
            return ("", "")

    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli.subprocess, "run", _run)
    monkeypatch.setattr(cli.subprocess, "Popen", _FakePopen)
    return submitted


_THIS_CHECKOUT = object()


def _expected_cron_line(config_dir=None, runtime_dir=None,
                        source_root=_THIS_CHECKOUT):
    """The managed line: sys.executable logging to the config root (#232),
    run from the source checkout this test suite imports memanga from."""
    from pathlib import Path

    from memanga import cli
    from memanga.cron import build_cron_line, source_checkout_root

    if runtime_dir is None:
        runtime_dir = config_dir or Path.home() / ".config" / "memanga"
    if source_root is _THIS_CHECKOUT:
        source_root = source_checkout_root(Path(cli.__file__).resolve().parent)
    return build_cron_line(0, 6, runtime_dir, sys.executable,
                           config_dir=config_dir, source_root=source_root)


def _fake_package_install(monkeypatch, tmp_path):
    """Point cli.__file__ into a read-only, spaced site-packages dir that
    has a checkout-style venv next to it, which must never be used."""
    from memanga import cli

    site = tmp_path / "pipx venvs" / "lib" / "site-packages"
    (site / "memanga").mkdir(parents=True)
    for venv_python in (site / "venv" / "bin" / "python3",
                        site / "venv" / "Scripts" / "python.exe"):
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("")
    monkeypatch.setattr(cli, "__file__", str(site / "memanga" / "cli.py"))
    site.chmod(0o555)
    return site


def _root_used_by(monkeypatch, capsys, pinned_args, env_root):
    """Root a run with the scheduled command's ``--config-dir`` args
    uses once $MEMANGA_CONFIG_DIR points at ``env_root`` (#259)."""
    from memanga import cli

    monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(env_root))
    monkeypatch.setattr(sys, "argv",
                        ["memanga", *pinned_args, "status", "--json"])
    capsys.readouterr()
    cli.main()
    assert not env_root.exists()
    return _stdout_json(capsys)["paths"]["config_dir"]


class TestCronCommand:
    def test_cron_status_safe(self, run_cli):
        # Status should never write anything system-wide
        rc = run_cli("cron", "status")
        assert rc in (0, 1, 2)

    def test_cron_install_submits_quoted_line(self, run_cli, monkeypatch,
                                              isolated_home):
        """#109: `cron install` must submit the shell-safe crontab line
        from build_cron_line() so paths with spaces survive. run_cli
        selects a config dir, which the line keeps (#221)."""
        submitted = _capture_crontab(monkeypatch)

        rc = run_cli("cron", "install", "--time", "06:00")
        assert rc == 0

        expected = _expected_cron_line(isolated_home / ".config" / "memanga")
        assert expected in submitted["crontab"].splitlines()

    def test_cron_install_default_dir_pins_config_dir(self, isolated_home,
                                                      monkeypatch, capsys,
                                                      tmp_path):
        """#259: with no flag or $MEMANGA_CONFIG_DIR the scheduled check
        still pins the default root, so a variable set later cannot
        redirect it away from the root that holds its log."""
        from memanga import cli

        default_root = isolated_home / ".config" / "memanga"
        submitted = _capture_crontab(monkeypatch)
        monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
        monkeypatch.setattr(sys, "argv",
                            ["memanga", "cron", "install", "--time", "06:00"])
        cli.main()

        line, = [l for l in submitted["crontab"].splitlines() if l]
        assert line == _expected_cron_line(default_root)
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        i = command.index("memanga")
        assert command[i + 1:i + 4] == ["--config-dir", str(default_root),
                                        "check"]
        assert command[-3:] == [">>", str(default_root / "memanga.log"), "2>&1"]
        assert _root_used_by(monkeypatch, capsys, command[i + 1:i + 3],
                             tmp_path / "later-env") == str(default_root)

    def test_cron_install_outside_source_checkout(self, isolated_home,
                                                  monkeypatch, tmp_path):
        """#232: a pip/pipx-style install runs sys.executable from the
        config root and logs there, never into the package directory."""
        from memanga import cli

        site = _fake_package_install(monkeypatch, tmp_path)
        try:
            root = tmp_path / "My Manga config"
            python = "/opt/pipx venvs/memanga/bin/python"
            monkeypatch.setattr(sys, "executable", python)
            submitted = _capture_crontab(monkeypatch)
            monkeypatch.setattr(sys, "argv", [
                "memanga", "--config-dir", str(root),
                "cron", "install", "--time", "06:00"])
            cli.main()
        finally:
            site.chmod(0o755)

        line, = [l for l in submitted["crontab"].splitlines() if l]
        assert line == _expected_cron_line(root, source_root=None)
        assert str(site) not in line
        assert str(site / "venv") not in line
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        assert command[:2] == ["cd", str(root)]
        assert command[3:9] == [python, "-m", "memanga",
                                "--config-dir", str(root), "check"]
        assert command[-3:] == [">>", str(root / "memanga.log"), "2>&1"]

    def test_cron_install_windows_uses_running_interpreter(
            self, isolated_home, monkeypatch, tmp_path):
        """#232: the scheduled task runs sys.executable, not a
        checkout-local venv/Scripts/python.exe."""
        from memanga import cli
        from memanga.cron import build_task_command

        site = _fake_package_install(monkeypatch, tmp_path)
        root = tmp_path / "My Manga config"
        python = r"C:\Program Files\Python312\python.exe"
        monkeypatch.setattr(sys, "executable", python)
        calls = []

        def _run(argv, *a, **k):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
        monkeypatch.setattr(cli.subprocess, "run", _run)
        monkeypatch.setattr(sys, "argv", [
            "memanga", "--config-dir", str(root),
            "cron", "install", "--time", "06:00"])
        try:
            cli.main()
        finally:
            site.chmod(0o755)

        create, = [c for c in calls if c[1] == "/create"]
        command = create[create.index("/tr") + 1]
        assert command == build_task_command(python, root)
        assert command == (f'"{python}" -m memanga --config-dir "{root}" '
                           "check --auto --quiet")

    def test_cron_install_source_checkout_runs_from_checkout(
            self, isolated_home, monkeypatch, tmp_path):
        """#232: a requirements-only checkout venv can only import memanga
        from the checkout, so the job cd's there but logs to the config
        root."""
        from memanga import cli

        checkout = tmp_path / "My Checkout"
        (checkout / "memanga").mkdir(parents=True)
        monkeypatch.setattr(cli, "__file__",
                            str(checkout / "memanga" / "cli.py"))
        root = tmp_path / "My Manga config"
        python = str(checkout / "venv" / "bin" / "python3")
        monkeypatch.setattr(sys, "executable", python)
        submitted = _capture_crontab(monkeypatch)
        monkeypatch.setattr(sys, "argv", [
            "memanga", "--config-dir", str(root),
            "cron", "install", "--time", "06:00"])
        cli.main()

        line, = [l for l in submitted["crontab"].splitlines() if l]
        assert line == _expected_cron_line(root, source_root=checkout)
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        assert command[:3] == ["cd", str(checkout), "&&"]
        assert command[3:9] == [python, "-m", "memanga",
                                "--config-dir", str(root), "check"]
        assert command[-3:] == [">>", str(root / "memanga.log"), "2>&1"]

    def test_cron_install_windows_source_checkout_changes_dir(
            self, isolated_home, monkeypatch, tmp_path):
        """#232: Task Scheduler has no working dir, so a checkout task
        cd's into the checkout before running -m memanga."""
        from memanga import cli

        checkout = tmp_path / "My Checkout"
        (checkout / "memanga").mkdir(parents=True)
        monkeypatch.setattr(cli, "__file__",
                            str(checkout / "memanga" / "cli.py"))
        python = r"C:\My Checkout\venv\Scripts\python.exe"
        monkeypatch.setattr(sys, "executable", python)
        calls = []

        def _run(argv, *a, **k):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
        monkeypatch.setattr(cli.subprocess, "run", _run)
        monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
        monkeypatch.setattr(sys, "argv",
                            ["memanga", "cron", "install", "--time", "06:00"])
        cli.main()

        # #259: the default root is pinned like any other.
        default_root = isolated_home / ".config" / "memanga"
        create, = [c for c in calls if c[1] == "/create"]
        command = create[create.index("/tr") + 1]
        assert command == (f'cmd /d /c "cd /d "{checkout}" && "{python}" '
                           f'-m memanga --config-dir "{default_root}" '
                           'check --auto --quiet"')

    def test_cron_install_windows_default_dir_pins_config_dir(
            self, isolated_home, monkeypatch, capsys, tmp_path):
        """#259: the Task Scheduler command pins the default root, so a
        later $MEMANGA_CONFIG_DIR cannot redirect the scheduled run."""
        from memanga import cli
        from memanga.cron import build_task_command

        site = _fake_package_install(monkeypatch, tmp_path)
        python = r"C:\Program Files\Python312\python.exe"
        monkeypatch.setattr(sys, "executable", python)
        calls = []

        def _run(argv, *a, **k):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
        monkeypatch.setattr(cli.subprocess, "run", _run)
        monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
        monkeypatch.setattr(sys, "argv",
                            ["memanga", "cron", "install", "--time", "06:00"])
        try:
            cli.main()
        finally:
            site.chmod(0o755)

        default_root = isolated_home / ".config" / "memanga"
        create, = [c for c in calls if c[1] == "/create"]
        command = create[create.index("/tr") + 1]
        assert command == build_task_command(python, default_root)
        assert command == (f'"{python}" -m memanga --config-dir '
                           f'"{default_root}" check --auto --quiet')
        assert _root_used_by(monkeypatch, capsys,
                             ["--config-dir", str(default_root)],
                             tmp_path / "later-env") == str(default_root)


# Issue #231: install/remove/status only touch the marked line.
_LEGACY_CRON = ("0 6 * * * cd /opt/memanga && /usr/bin/python3 -m memanga "
                "check --auto --quiet >> /opt/memanga/memanga.log 2>&1")
_DOCKER_CRON = ("0 5 * * * /usr/bin/flock -n /tmp/memanga.lock docker compose "
                "-f /srv/memanga/compose.yaml run --rm memanga check")
_USER_CRONTAB = (
    "# my jobs, including memanga ones\n"
    "MAILTO=me@example.com\n"
    "\n"
    "30 2 * * *  /usr/local/bin/backup.sh   # nightly\n"
    f"{_LEGACY_CRON}\n"
    "\n"
    f"{_DOCKER_CRON}\n"
)


class TestCronOwnership:
    def _managed(self, minute=0, hour=6):
        from memanga.cron import build_cron_line
        return build_cron_line(minute, hour, "/opt/memanga", "/usr/bin/python3")

    def test_install_keeps_unrelated_lines(self, run_cli, monkeypatch,
                                           isolated_home, capsys):
        submitted = _capture_crontab(monkeypatch, _USER_CRONTAB)
        assert run_cli("cron", "install", "--time", "06:00") == 0

        expected = _expected_cron_line(isolated_home / ".config" / "memanga")
        assert submitted["crontab"] == f"{_USER_CRONTAB}{expected}\n"
        out = capsys.readouterr().out
        assert "not managed" in out
        assert "/srv/memanga/compose.yaml" in out

    def test_install_replaces_only_managed_line(self, run_cli, monkeypatch,
                                                isolated_home):
        existing = f"{self._managed(15, 3)}\n{_USER_CRONTAB}"
        submitted = _capture_crontab(monkeypatch, existing)
        assert run_cli("cron", "install", "--time", "06:00") == 0

        expected = _expected_cron_line(isolated_home / ".config" / "memanga")
        assert submitted["crontab"] == f"{_USER_CRONTAB}{expected}\n"

    def test_remove_drops_only_managed_line(self, run_cli, monkeypatch):
        existing = _USER_CRONTAB.replace(
            "\n\n", f"\n{self._managed()}\n\n", 1)
        submitted = _capture_crontab(monkeypatch, existing)
        assert run_cli("cron", "remove") == 0

        assert submitted["crontab"] == _USER_CRONTAB
        assert "removed" not in submitted

    def test_remove_without_managed_line_leaves_crontab(self, run_cli,
                                                        monkeypatch, capsys):
        """Blank lines and unmarked MeManga lines must not count as a
        managed job, so nothing is rewritten or deleted."""
        submitted = _capture_crontab(monkeypatch, _USER_CRONTAB)
        assert run_cli("cron", "remove") == 0

        assert submitted == {}
        assert "No MeManga cron job found" in capsys.readouterr().out

    def test_remove_last_managed_line_deletes_crontab(self, run_cli,
                                                      monkeypatch):
        submitted = _capture_crontab(monkeypatch, f"\n{self._managed()}\n")
        assert run_cli("cron", "remove") == 0
        assert submitted == {"removed": True}

    def test_status_ignores_unmarked_lines(self, run_cli, monkeypatch, capsys):
        _capture_crontab(monkeypatch, _USER_CRONTAB)
        run_cli("cron", "status")
        out = capsys.readouterr().out
        assert "No cron job found" in out
        assert "Cron job is installed" not in out
        assert "not managed" in out

    def test_install_refuses_unreadable_crontab(self, run_cli, monkeypatch,
                                                config, capsys):
        """A `crontab -l` failure other than "no crontab" must not lead to
        overwriting the user's crontab."""
        from memanga import cli

        submitted = _capture_crontab(monkeypatch)
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            returncode=1, stdout="", stderr="crontab: Permission denied\n"))
        assert run_cli("cron", "install", "--time", "06:00") == 1

        assert submitted == {}
        assert not config.get("cron.enabled")
        assert "Could not read" in capsys.readouterr().err

    def test_remove_write_failure_keeps_config(self, run_cli, monkeypatch,
                                               config):
        from memanga import cli

        config.set("cron.enabled", True)
        config.save()
        submitted = _capture_crontab(monkeypatch, f"{_USER_CRONTAB}{self._managed()}\n")

        class _FailingPopen:
            returncode = 1

            def __init__(self, *args, **kwargs):
                pass

            def communicate(self, input=None):
                submitted["crontab"] = input
                return ("", "")

        monkeypatch.setattr(cli.subprocess, "Popen", _FailingPopen)
        assert run_cli("cron", "remove") == 1
        assert config.get("cron.enabled") is True

    def test_status_reports_managed_line(self, run_cli, monkeypatch, capsys):
        _capture_crontab(monkeypatch, f"{_USER_CRONTAB}{self._managed()}\n")
        run_cli("cron", "status")
        assert "Cron job is installed" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────
# `tui` — interactive mode — we don't drive it; just import-check
# ─────────────────────────────────────────────────────────────────────────


class TestTuiCommand:
    def test_tui_subcommand_registered(self, monkeypatch, isolated_home,
                                         capsys):
        """The `tui` subparser should at least exist and parse."""
        monkeypatch.setattr(sys, "argv", ["memanga", "tui", "--help"])
        from memanga import cli
        try:
            cli.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out.lower()
        assert "tui" in out or "interactive" in out


# ─────────────────────────────────────────────────────────────────────────
# `--json` status output and `doctor` (#250)
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def cli_state(isolated_home):
    """State in the config dir `run_cli` selects. main() loads it from
    disk, so seed with persisting mutators or call save()."""
    from memanga.state import State
    return State(config_dir=isolated_home / ".config" / "memanga")


def _stdout_json(capsys):
    # json.loads on the whole stdout proves nothing else was printed.
    return json.loads(capsys.readouterr().out)


class TestListJson:
    def test_empty_library(self, run_cli, cli_state, capsys):
        assert run_cli("list", "--json") == 0
        assert _stdout_json(capsys) == {"schema_version": 1, "count": 0, "manga": []}

    def test_entries(self, run_cli, config, cli_state, capsys):
        config.set("manga", [
            {"title": "Legacy", "source": "mangadex.org", "url": "https://mangadex.org/t/1"},
            {"title": "Multi", "status": "on-hold", "sources": [
                {"source": "mangapill.com", "url": "https://mangapill.com/m/2"},
                {"source": "mangadex.org", "url": "https://mangadex.org/t/2"},
            ]},
        ])
        config.save()
        cli_state.add_downloaded_chapter("Multi", "1")
        cli_state.add_downloaded_chapter("Multi", "2")
        cli_state.save()
        capsys.readouterr()

        assert run_cli("list", "--json") == 0
        payload = _stdout_json(capsys)
        assert payload["count"] == 2
        legacy, multi = payload["manga"]
        assert legacy == {
            "n": 1, "title": "Legacy", "status": "reading",
            "source": "mangadex.org", "source_display": "mangadex.org",
            "url": "https://mangadex.org/t/1",
            "sources": [{"source": "mangadex.org", "url": "https://mangadex.org/t/1"}],
            "last_chapter": None, "downloaded_count": 0,
        }
        assert multi["status"] == "on-hold"
        assert multi["source"] == "mangapill.com"
        assert multi["source_display"] == "mangapill.com (+1)"
        assert len(multi["sources"]) == 2
        assert multi["last_chapter"] == "2"
        assert multi["downloaded_count"] == 2


class TestStatusJson:
    def test_payload_has_no_secrets(self, run_cli, config, cli_state, capsys):
        config.set("delivery.mode", "email")
        config.set("email.kindle_email", "me@kindle.com")
        config.set("email.app_password", "secret-pw")
        config.set("cron.enabled", True)
        config.set("cron.time", "07:30")
        config.save()
        capsys.readouterr()

        assert run_cli("status", "--json") == 0
        out = capsys.readouterr().out
        assert "secret-pw" not in out
        payload = json.loads(out)
        assert payload["schema_version"] == 1
        assert payload["manga_count"] == 0
        assert payload["delivery"]["mode"] == "email"
        assert payload["email"]["kindle_email"] == "me@kindle.com"
        assert payload["email"]["sender_email"] is None
        assert payload["cron"] == {"enabled": True, "time": "07:30"}
        assert payload["post_processing"]["enabled"] is False
        assert payload["last_check"] is None
        assert payload["paths"]["state"] == str(cli_state.state_path)


class TestConfigDir:
    """Issues #221/#259: the config root is chosen per run, after
    parsing: `--config-dir`, then $MEMANGA_CONFIG_DIR, then the default."""

    @staticmethod
    def _status_paths(monkeypatch, capsys, *argv):
        from memanga import cli
        monkeypatch.setattr(sys, "argv", ["memanga", *argv, "status", "--json"])
        capsys.readouterr()
        cli.main()
        return _stdout_json(capsys)["paths"]

    def test_import_does_not_create_config_dir(self, tmp_path):
        import subprocess
        from pathlib import Path
        import memanga

        home = tmp_path / "fresh-home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items()
               if k != "MEMANGA_CONFIG_DIR"}
        env.update(HOME=str(home), USERPROFILE=str(home))
        subprocess.run(
            [sys.executable, "-c", "import memanga.cli"],
            cwd=Path(memanga.__file__).resolve().parent.parent,
            env=env, check=True, timeout=120,
        )
        assert not (home / ".config" / "memanga").exists()

    def test_flag_selects_config_and_state(self, isolated_home, monkeypatch,
                                           capsys, tmp_path):
        from memanga import cli
        root = tmp_path / "portable"
        paths = self._status_paths(monkeypatch, capsys, "--config-dir", str(root))
        assert paths == {
            "config_dir": str(root),
            "config": str(root / "config.yaml"),
            "state": str(root / "state.json"),
        }
        assert cli.config.config_dir == cli.state.config_dir == root

        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(root),
                                          "config", "--partial", "on"])
        cli.main()
        assert (root / "config.yaml").exists()
        assert not (isolated_home / ".config" / "memanga" / "config.yaml").exists()

    def test_env_var_selects_config_dir(self, isolated_home, monkeypatch,
                                        capsys, tmp_path):
        root = tmp_path / "from-env"
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
        paths = self._status_paths(monkeypatch, capsys)
        assert paths["config"] == str(root / "config.yaml")
        assert paths["state"] == str(root / "state.json")

    def test_flag_overrides_env_var(self, isolated_home, monkeypatch, capsys,
                                    tmp_path):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "from-env"))
        root = tmp_path / "from-flag"
        paths = self._status_paths(monkeypatch, capsys, "--config-dir", str(root))
        assert paths["config_dir"] == str(root)
        assert not (tmp_path / "from-env").exists()

    def test_default_is_home_config(self, isolated_home, monkeypatch, capsys):
        paths = self._status_paths(monkeypatch, capsys)
        assert paths["config_dir"] == str(isolated_home / ".config" / "memanga")

    @staticmethod
    def _gui_launches(monkeypatch, *argv):
        """Run `memanga ... --gui` with launch_gui faked; return its args."""
        import memanga.gui
        from memanga import cli
        calls = []
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
        monkeypatch.setattr(memanga.gui, "launch_gui",
                            lambda *a, **k: calls.append(a))
        monkeypatch.setattr(sys, "argv", ["memanga", *argv, "--gui"])
        cli.main()
        return calls

    def test_gui_uses_flag_dir(self, isolated_home, monkeypatch, tmp_path):
        """#259: --gui runs on the same resolved root as the CLI."""
        root = tmp_path / "portable"
        assert self._gui_launches(monkeypatch, "--config-dir", str(root)) == [(root,)]

    def test_gui_uses_env_dir(self, isolated_home, monkeypatch, tmp_path):
        root = tmp_path / "from-env"
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(root))
        assert self._gui_launches(monkeypatch) == [(root,)]

    def test_gui_default_dir(self, isolated_home, monkeypatch):
        """#259: the default root is passed on as an explicit path."""
        monkeypatch.delenv("MEMANGA_CONFIG_DIR", raising=False)
        assert self._gui_launches(monkeypatch) == [
            (isolated_home / ".config" / "memanga",)]

    def test_flag_after_command_is_rejected(self, isolated_home, monkeypatch,
                                            capsys, tmp_path):
        """#259: --config-dir is global and goes before the command; after
        it the run fails instead of silently using another root."""
        from memanga import cli
        root = tmp_path / "late"
        monkeypatch.setattr(sys, "argv", ["memanga", "status", "--config-dir",
                                          str(root)])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert "--config-dir" in capsys.readouterr().err
        assert not root.exists()

    def test_empty_flag_is_a_usage_error(self, isolated_home, monkeypatch,
                                         capsys, tmp_path):
        from memanga import cli
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(tmp_path / "from-env"))
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", "", "status"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2
        assert "--config-dir needs a directory path" in capsys.readouterr().err
        assert not (tmp_path / "from-env").exists()

    def test_empty_env_var_uses_default(self, isolated_home, monkeypatch, capsys):
        monkeypatch.setenv("MEMANGA_CONFIG_DIR", "")
        paths = self._status_paths(monkeypatch, capsys)
        assert paths["config_dir"] == str(isolated_home / ".config" / "memanga")

    @pytest.mark.parametrize("via_env", [False, True])
    def test_file_instead_of_dir_is_an_error(self, isolated_home, monkeypatch,
                                             capsys, tmp_path, via_env):
        from memanga import cli
        target = tmp_path / "not-a-dir"
        target.write_text("")
        argv = ["memanga", "status"]
        if via_env:
            monkeypatch.setenv("MEMANGA_CONFIG_DIR", str(target))
        else:
            argv[1:1] = ["--config-dir", str(target)]
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        source = "MEMANGA_CONFIG_DIR" if via_env else "--config-dir"
        assert err == f"error: {source}: {target} is not a directory\n"

    def test_uncreatable_dir_is_an_error(self, isolated_home, monkeypatch,
                                         capsys, tmp_path):
        """A parent that is a file makes mkdir fail; report it cleanly."""
        from memanga import cli
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        root = blocker / "memanga"
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(root),
                                          "status"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert err.startswith(f"error: cannot use config directory {root}: ")
        assert "Traceback" not in err

    @staticmethod
    def _run_in(monkeypatch, root, *argv):
        from memanga import cli
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(root),
                                          *argv])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        return exc.value.code

    def test_unwritable_root_is_refused_before_the_command(
            self, isolated_home, monkeypatch, capsys, tmp_path,
            refuse_writes_in):
        """#259: an existing root that cannot be written fails up front
        with one line instead of a PermissionError from config.save()."""
        root = tmp_path / "ro"
        root.mkdir()
        refuse_writes_in(root)
        assert self._run_in(monkeypatch, root, "config", "--partial", "on") == 1
        assert capsys.readouterr().err == (
            f"error: cannot use config directory {root}: Permission denied\n")
        assert list(root.iterdir()) == []

    def test_read_only_root_is_refused(self, isolated_home, monkeypatch,
                                       capsys, read_only_dir):
        """Same check against a real 0500 directory (skipped as root)."""
        assert self._run_in(monkeypatch, read_only_dir,
                            "config", "--partial", "on") == 1
        err = capsys.readouterr().err
        assert err.startswith(f"error: cannot use config directory {read_only_dir}: ")
        assert "Traceback" not in err
        assert list(read_only_dir.iterdir()) == []

    def test_doctor_still_reports_unwritable_root(
            self, isolated_home, monkeypatch, capsys, tmp_path,
            refuse_writes_in):
        """doctor is exempt so it can diagnose the root itself."""
        root = tmp_path / "ro"
        root.mkdir()
        refuse_writes_in(root)
        code = self._run_in(monkeypatch, root, "doctor", "--json",
                            "--check", "config")
        assert code == 1
        out = capsys.readouterr().out
        assert "Permission denied" in out

    def test_export_import_follow_selected_dirs(self, isolated_home,
                                                monkeypatch, tmp_path):
        """#259: export reads from one root and import writes to another;
        the default root is never touched."""
        from memanga import cli
        from memanga.config import Config
        from memanga.state import State
        src, dst = tmp_path / "src", tmp_path / "dst"
        seeded = Config(src)
        seeded.set("manga", [{"title": "Berserk",
                              "sources": [{"url": "https://mangadex.org/title/x"}]}])
        seeded.save()
        seeded_state = State(src)
        seeded_state.add_downloaded_chapter("Berserk", "1")
        seeded_state.flush()
        default_root = isolated_home / ".config" / "memanga"
        backup = tmp_path / "backup.json"

        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(src),
                                          "export", str(backup)])
        assert cli.main() is None
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(dst),
                                          "import", str(backup), "--replace"])
        assert cli.main() is None

        assert [m["title"] for m in Config(dst).get("manga")] == ["Berserk"]
        assert State(dst).get_downloaded_chapters("Berserk") == ["1"]
        assert not (default_root / "config.yaml").exists()
        assert not (default_root / "state.json").exists()

    def test_cron_install_keeps_config_dir(self, isolated_home, monkeypatch,
                                           tmp_path):
        from memanga import cli
        root = tmp_path / "portable"
        submitted = _capture_crontab(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir", str(root),
                                          "cron", "install", "--time", "06:00"])
        cli.main()
        line, = [l for l in submitted["crontab"].splitlines() if l]
        command = shlex.split(line.split("* * * ", 1)[1])
        i = command.index("memanga")
        assert command[i + 1:i + 4] == ["--config-dir", str(root), "check"]


class TestFailedJson:
    def test_empty(self, run_cli, cli_state, capsys):
        assert run_cli("failed", "--json") == 0
        assert _stdout_json(capsys) == {
            "schema_version": 1, "title_filter": None, "count": 0, "chapters": [],
        }

    def test_failed_and_partial_entries(self, run_cli, cli_state, capsys):
        cli_state.add_failed_chapter("Vinland Saga", "10", "mangadex.org", "HTTP 503", failed_pages=[3])
        cli_state.add_failed_chapter("Vinland Saga", "10", "mangadex.org", "HTTP 503", failed_pages=[3])
        cli_state.add_partial_chapter("Vinland Saga", "9", source="mangapill.com",
                                      failed_pages=[7], total_pages=40)
        cli_state.add_failed_chapter("Berserk", "1", "mangadex.org", "timeout")

        assert run_cli("failed", "--json") == 0
        payload = _stdout_json(capsys)
        assert payload["count"] == 3
        assert [(c["title"], c["chapter"], c["status"]) for c in payload["chapters"]] == [
            ("Berserk", "1", "failed"),
            ("Vinland Saga", "9", "partial"),
            ("Vinland Saga", "10", "failed"),
        ]
        partial, failed = payload["chapters"][1:]
        assert partial["failed_pages"] == [7]
        assert partial["total_pages"] == 40
        assert partial["attempts"] is None
        assert partial["error"] is None
        assert failed["attempts"] == 2
        assert failed["error"] == "HTTP 503"
        assert failed["source"] == "mangadex.org"
        assert failed["recorded_at"]

    def test_title_filter(self, run_cli, cli_state, capsys):
        cli_state.add_failed_chapter("Vinland Saga", "10", "mangadex.org", "x")
        cli_state.add_failed_chapter("Berserk", "1", "mangadex.org", "y")
        assert run_cli("failed", "--json", "-t", "vinland") == 0
        payload = _stdout_json(capsys)
        assert payload["title_filter"] == "vinland"
        assert [c["title"] for c in payload["chapters"]] == ["Vinland Saga"]

    @pytest.mark.parametrize("flag", ["--retry", "--clear"])
    def test_json_rejects_mutating_flags(self, run_cli, cli_state, capsys, flag):
        cli_state.add_failed_chapter("Berserk", "1", "mangadex.org", "y")
        assert run_cli("failed", "--json", flag) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--json cannot be combined" in captured.err
        assert cli_state.get_failed_chapters("Berserk")


class TestDoctorCommand:
    def test_json_report(self, run_cli, cli_state, capsys):
        assert run_cli("doctor", "--json", "--check", "config", "--check", "state") == 0
        payload = _stdout_json(capsys)
        assert payload["schema_version"] == 1
        assert payload["status"] == "ok"
        assert [c["name"] for c in payload["checks"]] == ["config", "state"]
        for check in payload["checks"]:
            assert set(check) == {"name", "status", "message", "details"}

    def test_json_runtime_check(self, run_cli, cli_state, monkeypatch, capsys):
        # Stub the probe: the real result depends on how memanga is installed.
        from memanga import doctor
        monkeypatch.setattr(doctor, "check_runtime", lambda c=None, s=None: doctor.CheckResult(
            "runtime", doctor.OK, "stub", {"install_mode": "source"}))
        assert run_cli("doctor", "--json", "--check", "runtime") == 0
        payload = _stdout_json(capsys)
        assert payload["status"] == "ok"
        assert [c["name"] for c in payload["checks"]] == ["runtime"]
        assert payload["checks"][0]["status"] == "ok"
        assert payload["checks"][0]["details"]["install_mode"] == "source"

    def test_failed_check_exits_1(self, run_cli, cli_state, capsys):
        cli_state.state_path.write_text("{broken", encoding="utf-8")
        assert run_cli("doctor", "--json", "--check", "state") == 1
        payload = _stdout_json(capsys)
        assert payload["status"] == "fail"
        assert payload["checks"][0]["status"] == "fail"

    def test_warning_exits_0_unless_strict(self, run_cli, config, cli_state, capsys):
        config.set("email.app_password", "secret-pw")
        config.save()
        assert run_cli("doctor", "--json", "--check", "keyring") == 0
        assert "secret-pw" not in capsys.readouterr().out
        assert run_cli("doctor", "--json", "--check", "keyring", "--strict") == 1

    def test_flags_reach_opt_in_checks(self, run_cli, cli_state, monkeypatch, capsys):
        from memanga import doctor
        seen = dict()

        def fake_smtp(c, s, live=False):
            seen["smtp"] = live
            return doctor.CheckResult("smtp", doctor.SKIP, "stub")

        def fake_browsers(c, s, launch=False):
            seen["launch"] = launch
            return doctor.CheckResult("browsers", doctor.OK, "stub")

        monkeypatch.setattr(doctor, "check_smtp", fake_smtp)
        monkeypatch.setattr(doctor, "check_browsers", fake_browsers)
        assert run_cli("doctor", "--json", "--check", "smtp", "--check", "browsers") == 0
        assert seen == dict(smtp=False, launch=False)
        assert run_cli("doctor", "--json", "--check", "smtp", "--check", "browsers",
                       "--smtp", "--launch-browsers") == 0
        assert seen == dict(smtp=True, launch=True)

    def test_human_output(self, run_cli, cli_state, capsys):
        assert run_cli("doctor", "--check", "config", "--check", "smtp") == 0
        out = capsys.readouterr().out
        assert "config" in out
        assert "smtp" in out
        assert "All checks passed" in out

    def test_unknown_check_is_usage_error(self, run_cli):
        assert run_cli("doctor", "--check", "nope") == 2


class TestInvalidConfigFile:
    """A broken config.yaml must not crash `import memanga.cli`: doctor
    reports it, every other command refuses to run (issue #250)."""

    BROKEN = "manga: [unclosed\n"

    def _write_broken(self, home):
        path = home / ".config" / "memanga" / "config.yaml"
        path.write_text(self.BROKEN, encoding="utf-8")
        return path

    def test_doctor_json_in_real_process(self, isolated_home):
        import os
        import subprocess
        self._write_broken(isolated_home)
        proc = subprocess.run(
            [sys.executable, "-m", "memanga", "doctor", "--json", "--check", "config"],
            capture_output=True, text=True, env=dict(os.environ), timeout=120,
        )
        assert proc.returncode == 1, proc.stderr
        assert "Traceback" not in proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["status"] == "fail"
        assert payload["checks"][0]["name"] == "config"
        assert payload["checks"][0]["status"] == "fail"

    def test_doctor_human_output(self, run_cli, isolated_home, capsys):
        self._write_broken(isolated_home)
        assert run_cli("doctor", "--check", "config") == 1
        out = capsys.readouterr().out
        assert "not valid YAML" in out
        assert "Problems found" in out

    def test_other_commands_refuse_and_keep_file(self, run_cli, isolated_home, capsys):
        path = self._write_broken(isolated_home)
        assert run_cli("list") == 1
        err = capsys.readouterr().err
        assert "cannot load config file" in err
        assert "memanga doctor" in err
        assert path.read_text(encoding="utf-8") == self.BROKEN


# ─────────────────────────────────────────────────────────────────────────
# Issue #375 — bracketed data must render literally, not as Rich markup
# ─────────────────────────────────────────────────────────────────────────


class TestRichMarkupEscaping:
    CLOSING = "Mushoku Tensei [/Official]"  # unmatched close tag → MarkupError
    STYLED = "Re:Zero [bold]"               # valid style tag → text vanished

    @pytest.fixture(autouse=True)
    def wide_console(self, monkeypatch):
        # Wide enough that table cells don't wrap the asserted strings.
        from rich.console import Console
        from memanga import cli
        monkeypatch.setattr(cli, "console", Console(width=250))
        monkeypatch.setattr(cli, "err_console", Console(width=250, stderr=True))

    def _seed(self, config, *entries):
        config.set("manga", [
            {"title": title, "source": "mangadex.org",
             "url": f"https://mangadex.org/t/{i}", "status": status}
            for i, (title, status) in enumerate(entries)
        ])
        config.save()

    def test_list_renders_bracketed_titles(self, run_cli, config, capsys):
        self._seed(config, (self.CLOSING, "reading"), (self.STYLED, "on-hold"))
        capsys.readouterr()

        assert run_cli("list") == 0
        out = capsys.readouterr().out
        assert self.CLOSING in out
        assert self.STYLED in out
        assert "on-hold" in out

    def test_check_dry_run_renders_titles_status_and_chapter_titles(
            self, run_cli, config, monkeypatch, capsys):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        self._seed(config, (self.CLOSING, "reading"), (self.STYLED, "on-hold"))
        monkeypatch.setattr(cli, "check_for_updates", lambda *a, **k: [
            Chapter(number="5", title="[/Extra] Side [bold]Story"),
        ])
        capsys.readouterr()

        assert run_cli("check", "--dry-run") == 0
        out = capsys.readouterr().out
        assert f"Checking: {self.CLOSING}..." in out
        assert f"Skipping: {self.STYLED} [on-hold]" in out
        assert "[DRY RUN] Chapter 5: [/Extra] Side [bold]Story" in out

    def test_check_renders_exception_text(self, run_cli, config, monkeypatch,
                                          capsys):
        from memanga import cli
        from memanga.downloader import DownloaderError

        self._seed(config, (self.CLOSING, "reading"))

        def _boom(*a, **k):
            raise DownloaderError("HTTP 403 [/forbidden] at [red]edge")

        monkeypatch.setattr(cli, "check_for_updates", _boom)
        capsys.readouterr()

        # The only manga errored, so nothing was checked (#239).
        assert run_cli("check", "--dry-run") == 1
        err = capsys.readouterr().err
        assert "Error: HTTP 403 [/forbidden] at [red]edge" in err

    def test_failed_renders_bracketed_title_and_error(self, run_cli, config,
                                                     cli_state, capsys):
        self._seed(config, (self.CLOSING, "reading"))
        cli_state.add_failed_chapter(
            self.CLOSING, "12", "mangadex.org", "Timeout [/retry] [bold]x",
        )
        cli_state.save()
        capsys.readouterr()

        assert run_cli("failed") == 0
        out = capsys.readouterr().out
        assert self.CLOSING in out
        assert "Timeout [/retry] [bold]x" in out


# ─────────────────────────────────────────────────────────────────────────
# Issue #258 — commands must never prompt when stdin is not a terminal
# ─────────────────────────────────────────────────────────────────────────


class _TtyInput(io.StringIO):
    """Scripted stdin that claims to be a terminal."""

    def isatty(self):
        return True


class TestNonInteractive:
    @pytest.fixture(autouse=True)
    def no_tty(self, monkeypatch):
        # A closed pipe: isatty() is False and any input() raises EOFError.
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    def _seed(self, config, *titles):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(titles)
        ])
        config.save()

    def _titles(self, config):
        return [m["title"] for m in config.get("manga", []) or []]

    def test_add_unsupported_source_fails_without_force(self, run_cli, config,
                                                        capsys):
        rc = run_cli("add", "--title", "Unsafe",
                     "--url", "https://unsupported.example/manga")
        assert rc == 1
        assert "--force" in capsys.readouterr().err
        assert "Unsafe" not in self._titles(config)

    def test_add_unsupported_source_with_force(self, run_cli, config):
        rc = run_cli("add", "--title", "Unsafe", "--force",
                     "--url", "https://unsupported.example/manga")
        assert rc == 0
        assert "Unsafe" in self._titles(config)

    def test_add_unsupported_source_with_yes(self, run_cli, config):
        rc = run_cli("add", "--title", "Unsafe", "--yes",
                     "--url", "https://unsupported.example/manga")
        assert rc == 0
        assert "Unsafe" in self._titles(config)

    def test_add_similar_title_fails_without_yes(self, run_cli, config, capsys):
        self._seed(config, "One Piece")
        rc = run_cli("add", "--title", "One Piece Color",
                     "--url", "https://mangadex.org/title/z/x")
        assert rc == 1
        assert "similar manga" in capsys.readouterr().err
        assert self._titles(config) == ["One Piece"]

    def test_add_similar_title_with_yes(self, run_cli, config):
        self._seed(config, "One Piece")
        rc = run_cli("add", "--title", "One Piece Color", "--yes",
                     "--url", "https://mangadex.org/title/z/x")
        assert rc == 0
        assert "One Piece Color" in self._titles(config)

    def test_add_similar_title_with_force(self, run_cli, config):
        self._seed(config, "One Piece")
        rc = run_cli("add", "--title", "One Piece Color", "-f",
                     "--url", "https://mangadex.org/title/z/x")
        assert rc == 0
        assert "One Piece Color" in self._titles(config)

    def test_force_does_not_bypass_exact_duplicate(self, run_cli, config,
                                                   capsys):
        self._seed(config, "One Piece")
        run_cli("add", "--title", "one piece", "--force",
                "--url", "https://mangadex.org/title/z/x")
        assert self._titles(config) == ["One Piece"]
        assert "already exists" in capsys.readouterr().err

    def test_add_interactive_flag_fails(self, run_cli, capsys):
        assert run_cli("add", "--interactive") == 1
        assert "--title and --url" in capsys.readouterr().err

    def test_rm_fails_without_yes(self, run_cli, config, capsys):
        self._seed(config, "Goner")
        rc = run_cli("rm", "Goner")
        assert rc == 1
        assert "--yes" in capsys.readouterr().err
        assert self._titles(config) == ["Goner"]

    def test_rm_with_yes(self, run_cli, config):
        self._seed(config, "Goner")
        assert run_cli("rm", "Goner", "--yes") == 0
        assert self._titles(config) == []

    def test_cron_install_fails_without_time(self, run_cli, monkeypatch,
                                             capsys):
        submitted = _capture_crontab(monkeypatch)
        rc = run_cli("cron", "install")
        assert rc == 1
        assert "--time" in capsys.readouterr().err
        assert "crontab" not in submitted

    def test_cron_install_invalid_time_exits_nonzero(self, run_cli,
                                                     monkeypatch):
        _capture_crontab(monkeypatch)
        assert run_cli("cron", "install", "--time", "six") == 1

    def test_bare_memanga_fails_with_help(self, run_cli, capsys):
        rc = run_cli()
        assert rc == 1
        err = capsys.readouterr().err
        assert "usage:" in err
        assert "needs a terminal" in err

    def test_tui_subcommand_fails(self, run_cli, capsys):
        assert run_cli("tui") == 1
        assert "needs a terminal" in capsys.readouterr().err

    def test_interactive_config_fails(self, run_cli, capsys):
        assert run_cli("config") == 1
        assert "--show" in capsys.readouterr().err

    def test_check_skips_unconfirmed_chapters(self, run_cli, config,
                                              monkeypatch, capsys):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        self._seed(config, "Mock")
        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [Chapter(number="5")])
        downloads = []
        monkeypatch.setattr(cli, "download_chapter",
                            lambda *a, **k: downloads.append(a))
        rc = run_cli("check")
        assert rc == 1
        assert "--auto" in capsys.readouterr().err
        assert downloads == []

    def test_check_quiet_still_fails_on_unconfirmed(self, run_cli, config,
                                                    monkeypatch, capsys):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        self._seed(config, "Mock")
        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [Chapter(number="5")])
        downloads = []
        monkeypatch.setattr(cli, "download_chapter",
                            lambda *a, **k: downloads.append(a))
        rc = run_cli("check", "--quiet")
        assert rc == 1
        err = capsys.readouterr().err
        assert "--auto" in err and "--yes" in err
        assert downloads == []

    def test_real_process_never_reads_stdin(self, isolated_home):
        """The issue's repro: a subprocess with stdin from /dev/null."""
        import subprocess
        root = isolated_home / "cfg"
        cases = [
            [],
            ["add", "--title", "Unsafe", "--url", "https://unsupported.example/manga"],
            ["cron", "install"],
        ]
        for argv in cases:
            proc = subprocess.run(
                [sys.executable, "-m", "memanga", "--config-dir", str(root)] + argv,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                env=dict(os.environ), timeout=120,
            )
            assert proc.returncode == 1, (argv, proc.stderr)
            assert "Traceback" not in proc.stderr, argv
            assert "error:" in proc.stderr, argv


class TestInteractiveStillPrompts:
    """A real terminal keeps the confirmation flows (#258)."""

    def test_rm_confirms_on_tty(self, run_cli, config, monkeypatch):
        config.set("manga", [{"title": "Goner", "url": "u",
                              "source": "mangadex.org", "status": "reading"}])
        config.save()
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\nn\n"))
        assert run_cli("rm", "Goner") == 0
        assert config.get("manga", []) == []

    def test_cron_install_asks_time_on_tty(self, run_cli, monkeypatch):
        submitted = _capture_crontab(monkeypatch)
        monkeypatch.setattr(sys, "stdin", _TtyInput("\n"))
        assert run_cli("cron", "install") == 0
        assert "crontab" in submitted


class TestAddPrompts:
    """`add` prompts only with --interactive, even on a terminal (#238)."""

    @pytest.fixture(autouse=True)
    def no_network(self, monkeypatch):
        from memanga import cli

        def _no_scraper(source):
            raise RuntimeError("no network in tests")
        monkeypatch.setattr(cli, "get_scraper", _no_scraper)

    def _titles(self, config):
        return [m["title"] for m in config.get("manga", []) or []]

    def test_flag_add_on_tty_does_not_prompt(self, run_cli, config,
                                             monkeypatch, capsys):
        # "y" would be read if add still asked "Add anyway?".
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\n"))
        rc = run_cli("add", "--title", "Unsafe",
                     "--url", "https://unsupported.example/manga")
        assert rc == 1
        assert "--force" in capsys.readouterr().err
        assert "Unsafe" not in self._titles(config)

    def test_flag_add_similar_title_on_tty_does_not_prompt(self, run_cli, config,
                                                           monkeypatch, capsys):
        config.set("manga", [{"title": "One Piece", "source": "mangadex.org",
                              "url": "https://mangadex.org/title/a/x"}])
        config.save()
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\n"))
        rc = run_cli("add", "--title", "One Piece Color",
                     "--url", "https://mangadex.org/title/z/x")
        assert rc == 1
        assert "similar manga" in capsys.readouterr().err
        assert self._titles(config) == ["One Piece"]

    def test_interactive_unsupported_source_still_confirms(self, run_cli, config,
                                                           monkeypatch):
        # title, url, no backup, then "Add anyway?" -> yes
        monkeypatch.setattr(sys, "stdin", _TtyInput(
            "Unsafe\nhttps://unsupported.example/manga\nn\ny\n"))
        assert run_cli("add", "--interactive") == 0
        assert "Unsafe" in self._titles(config)

    def test_interactive_invalid_fallback_days_reprompts(self, run_cli, config,
                                                         monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", _TtyInput(
            "Blue Lock\n"
            "https://mangadex.org/title/a/x\n"
            "y\n"
            "https://mangapill.com/manga/1/x\n"
            "abc\n"
            "-1\n"
            "3\n"))
        assert run_cli("add", "--interactive") == 0
        out = capsys.readouterr().out
        assert "valid integer" in out
        assert "0 or more days" in out
        [entry] = config.get("manga", [])
        assert entry["title"] == "Blue Lock"
        assert entry["fallback_delay_days"] == 3


# ─────────────────────────────────────────────────────────────────────────
# Issue #239 — exit codes and stdout/stderr separation
# ─────────────────────────────────────────────────────────────────────────


class TestExitCodes:
    def _seed(self, config, *titles):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(titles)
        ])
        config.save()

    def _assert_error_on_stderr(self, capsys, text):
        captured = capsys.readouterr()
        assert text in captured.err
        assert text not in captured.out

    @pytest.mark.parametrize("argv", [
        ("remove", "missing-title", "--yes"),
        ("set", "missing-title", "completed"),
        ("update", "missing-title", "--title", "New"),
        ("check", "-t", "missing-title"),
    ])
    def test_not_found_exits_1_on_stderr(self, run_cli, config, capsys, argv):
        self._seed(config, "Tracked")
        capsys.readouterr()
        assert run_cli(*argv) == 1
        self._assert_error_on_stderr(capsys, "Not found")

    @pytest.mark.parametrize("argv", [
        ("remove", "missing-title", "--yes"),
        ("set", "missing-title", "completed"),
        ("update", "missing-title", "--title", "New"),
        ("check", "-t", "missing-title"),
    ])
    def test_not_found_on_empty_library_exits_1(self, run_cli, capsys, argv):
        assert run_cli(*argv) == 1
        captured = capsys.readouterr()
        assert captured.err
        assert captured.out == ""

    def test_update_without_changes_exits_1(self, run_cli, config, capsys):
        self._seed(config, "Tracked")
        capsys.readouterr()
        assert run_cli("update", "Tracked") == 1
        self._assert_error_on_stderr(capsys, "No changes specified")

    def test_add_missing_url_exits_1(self, run_cli, capsys):
        assert run_cli("add", "--title", "Only Title") == 1
        self._assert_error_on_stderr(capsys, "--title and --url required")

    def test_usage_error_keeps_argparse_exit_2(self, run_cli, config):
        self._seed(config, "Tracked")
        assert run_cli("set", "Tracked", "not-a-status") == 2

    def test_keyboard_interrupt_exits_130(self, run_cli, monkeypatch, capsys):
        from memanga import cli

        def _interrupt(args):
            raise KeyboardInterrupt
        monkeypatch.setattr(cli, "cmd_list", _interrupt)
        assert run_cli("list") == 130
        captured = capsys.readouterr()
        assert "Interrupted" in captured.err
        assert captured.out == ""

    def test_console_script_targets_wrapped_main(self):
        # Issue #234: the installed `memanga` script must enter through
        # main(), which owns the Ctrl-C handling, not _main().
        # Plain-text parse: tomllib is stdlib only on 3.11+ and we support 3.10.
        import re
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        section = re.search(r"^\[project\.scripts\]\n(.*?)(?=^\[|\Z)",
                            pyproject.read_text(), re.M | re.S)
        assert section is not None
        assert re.search(r'^memanga\s*=\s*"memanga\.cli:main"\s*$',
                         section.group(1), re.M)

    def test_python_m_memanga_interrupt_exits_130(self, monkeypatch, capsys):
        import runpy
        from memanga import cli

        def _interrupt():
            raise KeyboardInterrupt
        monkeypatch.setattr(cli, "_main", _interrupt)
        monkeypatch.setattr(cli, "state", None)
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("memanga", run_name="__main__")
        assert exc.value.code == 130
        captured = capsys.readouterr()
        assert "Interrupted" in captured.err
        assert "Traceback" not in captured.err
        assert captured.out == ""

    def test_search_json_error_keeps_stdout_clean(self, run_cli, capsys):
        rc = run_cli("search", "Blue Lock", "--json",
                     "--source", "not-a-real-source.example")
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Unknown source" in captured.err


class TestCheckExitCodes:
    @pytest.fixture
    def seeded(self, config):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(("Alpha", "Beta"))
        ])
        config.save()

    @pytest.fixture
    def fake_download(self, monkeypatch, tmp_path):
        """Patch downloads; chapters whose number is in `fail` raise."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        fail = set()

        def _download(manga, ch, *a, **k):
            if ch.number in fail:
                raise DownloaderError(f"chapter {ch.number} broke")
            path = tmp_path / f"{manga['title']}-{ch.number}.pdf"
            path.write_bytes(b"pdf")
            return path
        monkeypatch.setattr(cli, "download_chapter", _download)
        monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: None)
        return fail

    def _updates(self, monkeypatch, per_title):
        """`per_title` maps title -> chapter numbers, or an exception."""
        from memanga import cli
        from memanga.scrapers.base import Chapter

        def _check(manga, *a, **k):
            result = per_title[manga["title"]]
            if isinstance(result, Exception):
                raise result
            return [Chapter(number=n) for n in result]
        monkeypatch.setattr(cli, "check_for_updates", _check)

    def test_all_downloaded_exits_0(self, run_cli, seeded, fake_download,
                                    monkeypatch, capsys):
        self._updates(monkeypatch, {"Alpha": ["1"], "Beta": ["2"]})
        capsys.readouterr()
        assert run_cli("check", "--auto") == 0
        captured = capsys.readouterr()
        assert "2/2 chapters downloaded" in captured.out
        assert captured.err == ""

    def test_failed_chapter_exits_3(self, run_cli, seeded, fake_download,
                                    monkeypatch, capsys):
        from memanga import cli

        self._updates(monkeypatch, {"Alpha": ["1", "2"], "Beta": []})
        fake_download.add("2")
        capsys.readouterr()
        assert run_cli("check", "--auto") == cli.EXIT_PARTIAL == 3
        captured = capsys.readouterr()
        assert "1/2 chapters downloaded" in captured.out
        assert "chapter 2 broke" in captured.err
        assert "1 chapter(s) failed" in captured.err
        assert "broke" not in captured.out

    def test_one_source_error_exits_3(self, run_cli, seeded, fake_download,
                                      monkeypatch, capsys):
        from memanga.downloader import DownloaderError

        self._updates(monkeypatch, {"Alpha": DownloaderError("HTTP 503"),
                                    "Beta": ["1"]})
        capsys.readouterr()
        assert run_cli("check", "--auto") == 3
        captured = capsys.readouterr()
        assert "HTTP 503" in captured.err
        assert "1/2 manga could not be checked" in captured.err
        assert "HTTP 503" not in captured.out

    def test_all_sources_error_exits_1(self, run_cli, seeded, fake_download,
                                       monkeypatch, capsys):
        from memanga.downloader import DownloaderError

        self._updates(monkeypatch, {"Alpha": DownloaderError("HTTP 503"),
                                    "Beta": RuntimeError("boom")})
        capsys.readouterr()
        assert run_cli("check", "--auto") == 1
        err = capsys.readouterr().err
        assert "HTTP 503" in err and "boom" in err

    def test_failed_retry_still_failing_exits_3(self, run_cli, config,
                                                cli_state, fake_download,
                                                monkeypatch, capsys):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        config.set("manga", [{"title": "Alpha", "source": "mangadex.org",
                              "url": "https://mangadex.org/title/a/x"}])
        config.save()
        cli_state.add_failed_chapter("Alpha", "7", "mangadex.org", "timeout")
        cli_state.save()
        scraper = MagicMock()
        scraper.get_chapters.return_value = [Chapter(number="7")]
        monkeypatch.setattr(cli, "get_scraper", lambda source: scraper)
        fake_download.add("7")
        capsys.readouterr()

        assert run_cli("failed", "--retry") == 3
        captured = capsys.readouterr()
        assert "0/1 chapters recovered" in captured.out
        assert "Still failing" in captured.err

    def test_failed_retry_manga_missing_from_config_exits_3(
            self, run_cli, config, cli_state, fake_download, capsys):
        config.set("manga", [])
        config.save()
        cli_state.add_failed_chapter("Missing", "7", "mangadex.org", "timeout")
        cli_state.add_failed_chapter("Missing", "8", "mangadex.org", "timeout")
        cli_state.save()
        capsys.readouterr()

        assert run_cli("failed", "--retry") == 3
        captured = capsys.readouterr()
        assert "0/2 chapters recovered" in captured.out
        assert "Manga not found in config: Missing" in captured.err

    def test_failed_retry_manga_without_sources_exits_3(
            self, run_cli, config, cli_state, fake_download, capsys):
        config.set("manga", [{"title": "Alpha", "sources": []}])
        config.save()
        cli_state.add_failed_chapter("Alpha", "7", "mangadex.org", "timeout")
        cli_state.save()
        capsys.readouterr()

        assert run_cli("failed", "--retry") == 3
        captured = capsys.readouterr()
        assert "0/1 chapters recovered" in captured.out
        assert "No source to retry Chapter 7 of Alpha" in captured.err

    def _interrupt_on_beta(self, monkeypatch):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        def _check(manga, *a, **k):
            if manga["title"] == "Beta":
                raise KeyboardInterrupt
            return [Chapter(number="1")]
        monkeypatch.setattr(cli, "check_for_updates", _check)

    def test_interrupted_check_keeps_completed_chapters(
            self, run_cli, seeded, fake_download, isolated_home,
            monkeypatch, capsys):
        # Issue #234: Alpha's chapter is only marked dirty; Ctrl-C before
        # the end-of-check save must still persist it.
        from memanga.state import State

        self._interrupt_on_beta(monkeypatch)
        capsys.readouterr()
        assert run_cli("check", "--auto") == 130
        assert "Interrupted" in capsys.readouterr().err

        on_disk = State(isolated_home / ".config" / "memanga")
        assert on_disk.is_chapter_downloaded("Alpha", "1")
        assert on_disk.get("last_check") is None

    def test_interrupt_flush_failure_still_exits_130(
            self, run_cli, seeded, fake_download, monkeypatch, capsys):
        from memanga.state import State

        def _broken_flush(self):
            raise OSError("disk full")
        monkeypatch.setattr(State, "flush", _broken_flush)
        self._interrupt_on_beta(monkeypatch)
        capsys.readouterr()
        assert run_cli("check", "--auto") == 130
        err = capsys.readouterr().err
        assert "Could not save state: disk full" in err
        assert "Interrupted" in err


class TestTargetMatching:
    """Tracked-manga targets resolve to exactly one entry (#237)."""

    @pytest.fixture(autouse=True)
    def no_tty(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    def _seed(self, config, *titles):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(titles)
        ])
        config.save()

    def _titles(self, config):
        return [m["title"] for m in config.get("manga", []) or []]

    def _status(self, config, title):
        return [m for m in config.get("manga", [])
                if m["title"] == title][0]["status"]

    def test_ambiguous_substring_refuses_and_lists(self, run_cli, config,
                                                   capsys):
        self._seed(config, "One Piece", "One Punch-Man", "Berserk")
        capsys.readouterr()
        assert run_cli("rm", "one", "--yes") == 1
        captured = capsys.readouterr()
        assert "Ambiguous" in captured.err
        assert "One Piece" in captured.err
        assert "One Punch-Man" in captured.err
        assert "Berserk" not in captured.err
        assert captured.out == ""
        assert self._titles(config) == ["One Piece", "One Punch-Man", "Berserk"]

    @pytest.mark.parametrize("argv", [
        ("set", "one", "dropped"),
        ("update", "one", "--title", "New"),
        ("check", "-t", "one"),
    ])
    def test_ambiguous_target_fails_everywhere(self, run_cli, config, capsys,
                                               monkeypatch, argv):
        from memanga import cli

        monkeypatch.setattr(cli, "check_for_updates", lambda *a, **k: [])
        self._seed(config, "One Piece", "One Punch-Man")
        capsys.readouterr()
        assert run_cli(*argv) == 1
        captured = capsys.readouterr()
        assert "Ambiguous" in captured.err
        assert captured.out == ""
        assert self._titles(config) == ["One Piece", "One Punch-Man"]
        assert self._status(config, "One Piece") == "reading"

    def test_exact_match_wins_over_substring(self, run_cli, config):
        self._seed(config, "One Piece Colored", "One Piece")
        assert run_cli("set", "one piece", "dropped") == 0
        assert self._status(config, "One Piece") == "dropped"
        assert self._status(config, "One Piece Colored") == "reading"

    def test_unique_substring_still_matches(self, run_cli, config):
        self._seed(config, "One Piece", "Berserk")
        assert run_cli("set", "berse", "on-hold") == 0
        assert self._status(config, "Berserk") == "on-hold"

    def test_numeric_title_is_a_title(self, run_cli, config):
        # "1" used to mean the first entry; it is now a title lookup.
        self._seed(config, "Berserk", "86", "1")
        assert run_cli("set", "86", "completed") == 0
        assert self._status(config, "86") == "completed"
        assert run_cli("rm", "1", "--yes") == 0
        assert self._titles(config) == ["Berserk", "86"]

    def test_bare_number_is_not_an_index(self, run_cli, config, capsys):
        self._seed(config, "Berserk", "Vinland Saga")
        capsys.readouterr()
        assert run_cli("rm", "2", "--yes") == 1
        assert "Not found" in capsys.readouterr().err
        assert self._titles(config) == ["Berserk", "Vinland Saga"]

    def test_bare_number_never_substring_matches(self, run_cli, config,
                                                 capsys):
        # "1" is a substring of only "Mob Psycho 100"; it must not hit it.
        self._seed(config, "One Piece", "Mob Psycho 100", "Berserk")
        capsys.readouterr()
        assert run_cli("rm", "1", "--yes") == 1
        captured = capsys.readouterr()
        assert "Not found" in captured.err
        assert "#1" in captured.err
        assert captured.out == ""
        assert self._titles(config) == ["One Piece", "Mob Psycho 100", "Berserk"]

    def test_bare_number_exact_title_beside_substring(self, run_cli, config):
        self._seed(config, "Mob Psycho 100", "1")
        assert run_cli("set", "1", "dropped") == 0
        assert self._status(config, "1") == "dropped"
        assert self._status(config, "Mob Psycho 100") == "reading"

    def test_hash_index_rejects_non_ascii_digits(self, run_cli, config,
                                                 capsys):
        # "²".isdigit() is True but int("²") raises; "١" is Arabic-Indic one.
        self._seed(config, "Berserk", "86")
        for target in ("#²", "#\u0661"):
            capsys.readouterr()
            assert run_cli("rm", target, "--yes") == 1
            assert "Not found" in capsys.readouterr().err
        assert self._titles(config) == ["Berserk", "86"]

    def test_hash_index_selects_entry(self, run_cli, config):
        self._seed(config, "Berserk", "86")
        assert run_cli("set", "#2", "dropped") == 0
        assert self._status(config, "86") == "dropped"
        assert run_cli("rm", "#1", "--yes") == 0
        assert self._titles(config) == ["86"]

    def test_hash_index_out_of_range(self, run_cli, config, capsys):
        self._seed(config, "Berserk")
        capsys.readouterr()
        assert run_cli("rm", "#5", "--yes") == 1
        assert "Not found" in capsys.readouterr().err
        assert self._titles(config) == ["Berserk"]

    def test_check_title_runs_only_the_exact_match(self, run_cli, config,
                                                   monkeypatch):
        from memanga import cli

        self._seed(config, "One Piece", "One Piece Colored")
        checked = []
        monkeypatch.setattr(cli, "check_for_updates",
                            lambda manga, *a, **k: checked.append(manga["title"]) or [])
        assert run_cli("check", "-t", "One Piece") == 0
        assert checked == ["One Piece"]

    def test_rm_yes_keeps_history(self, run_cli, config, cli_state):
        from memanga.state import State

        self._seed(config, "Goner")
        cli_state.add_downloaded_chapter("Goner", "1")
        cli_state.save()
        assert run_cli("rm", "Goner", "--yes") == 0
        assert self._titles(config) == []
        fresh = State(config_dir=cli_state.state_path.parent)
        assert fresh.get_downloaded_chapters("Goner") == ["1"]

    def test_rm_purge_removes_history(self, run_cli, config, cli_state):
        from memanga.state import State

        self._seed(config, "Goner")
        cli_state.add_downloaded_chapter("Goner", "1")
        cli_state.save()
        assert run_cli("rm", "Goner", "--yes", "--purge") == 0
        assert self._titles(config) == []
        fresh = State(config_dir=cli_state.state_path.parent)
        assert fresh.get_downloaded_chapters("Goner") == []
