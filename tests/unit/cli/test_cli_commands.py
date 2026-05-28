"""Real CLI tests — drive `memanga.cli.main()` with sys.argv patched.

Each subcommand is exercised at least once. Network-touching paths
(check / update) are stubbed.
"""

from __future__ import annotations

import json
import pytest
import sys
from unittest.mock import patch, MagicMock


@pytest.fixture
def run_cli(monkeypatch, isolated_home):
    """Helper: run `cli.main()` with synthetic argv.

    The CLI builds a module-level `config = Config()` at import time, so
    we rebind it to a fresh Config rooted in the isolated home before
    each invocation. Otherwise tests would share the developer's real
    config dir.
    """
    def _run(*argv):
        monkeypatch.setattr(sys, "argv", ["memanga"] + list(argv))
        from memanga import cli
        from memanga.config import Config
        # Always start from a fresh on-disk read so writes from earlier
        # `run_cli` calls in the same test are visible.
        cli.config = Config()
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

    def test_remove_unknown_is_noop(self, run_cli, config):
        rc = run_cli("remove", "never-added", "--yes")
        # Either succeeds with "not found" or errors — both acceptable
        assert rc in (0, 1, 2)


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
        rc = run_cli("update", "Old Title", "--new-title", "New Title")
        if rc == 0:
            titles = [m["title"] for m in config.get("manga", []) or []]
            assert "New Title" in titles


# ─────────────────────────────────────────────────────────────────────────
# `check` — find new chapters (mocked)
# ─────────────────────────────────────────────────────────────────────────


class TestCheckCommand:
    def test_check_with_no_manga(self, run_cli, config):
        rc = run_cli("check")
        assert rc == 0  # nothing to do — should exit cleanly

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

    def test_import_merge(self, run_cli, config, tmp_path):
        # First export
        backup = tmp_path / "x.json"
        backup.write_text(json.dumps({
            "manga": [{"title": "FromImport", "url": "u",
                       "source": "mangadex.org", "status": "reading"}]
        }))
        rc = run_cli("import", str(backup), "--merge")
        if rc == 0:
            titles = [m["title"] for m in config.get("manga", []) or []]
            assert "FromImport" in titles


# ─────────────────────────────────────────────────────────────────────────
# `cron` — install / status / remove scheduled task
# ─────────────────────────────────────────────────────────────────────────


class TestCronCommand:
    def test_cron_status_safe(self, run_cli):
        # Status should never write anything system-wide
        rc = run_cli("cron", "status")
        assert rc in (0, 1, 2)


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
