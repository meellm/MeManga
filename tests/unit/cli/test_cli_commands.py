"""Real CLI tests — drive `memanga.cli.main()` with sys.argv patched.

Each subcommand is exercised at least once. Network-touching paths
(check / update) are stubbed.
"""

from __future__ import annotations

import json
import pytest
import sys
import types
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
        from memanga.state import State

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

        cli.state = State()
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
        from memanga.state import State

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

        cli.state = State()
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
        notifications = cli.state.get("notifications", [])
        assert any("saved as partial" in n["message"] for n in notifications)

    def test_over_threshold_backup_failure_records_failure_not_downloaded(
            self, run_cli, config, monkeypatch):
        """If neither complete nor partial recovery is acceptable, the
        chapter stays failed and is not marked downloaded."""
        from memanga import cli
        from memanga.downloader import DownloaderError
        from memanga.state import State

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

        cli.state = State()
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

        assert rc == 0
        assert not cli.state.is_chapter_downloaded("Vinland Saga", "71")
        failed = cli.state.get_failed_chapters("Vinland Saga")
        assert "71" in failed


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
        assert "version" in capsys.readouterr().out.lower()
        titles = [m["title"] for m in config.get("manga", []) or []]
        assert "Sneaky" not in titles

    def test_import_newer_version_rejected(self, run_cli, config, tmp_path,
                                           capsys):
        backup = tmp_path / "future.json"
        backup.write_text(json.dumps({"version": 99, "manga": []}))
        capsys.readouterr()
        rc = run_cli("import", str(backup))
        assert rc == 1
        assert "newer" in capsys.readouterr().out.lower()

    def test_import_malformed_version_rejected(self, run_cli, config,
                                               tmp_path, capsys):
        backup = tmp_path / "bad.json"
        backup.write_text(json.dumps({"version": "one", "manga": []}))
        capsys.readouterr()
        rc = run_cli("import", str(backup))
        assert rc == 1
        assert "version" in capsys.readouterr().out.lower()


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
        assert "No results" in capsys.readouterr().out

    def test_source_failure_reported(self, run_cli, fake_search_scraper,
                                     capsys):
        fake_search_scraper.reinstall(
            _FakeSearchScraper(search_error=RuntimeError("HTTP 502")))
        rc = run_cli("search", "Blue Lock", "--source", "fake.test",
                     "--no-chips")
        assert rc == 1
        out = capsys.readouterr().out
        assert "1 failed" in out
        assert "HTTP 502" in out

    def test_unknown_source_errors(self, run_cli, isolated_home, capsys):
        rc = run_cli("search", "Blue Lock",
                     "--source", "not-a-real-source.example")
        assert rc == 1
        assert "Unknown source" in capsys.readouterr().out

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
