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
    @pytest.fixture(autouse=True)
    def no_network(self, monkeypatch):
        from memanga import cli
        monkeypatch.setattr(cli, "get_scraper", lambda source: types.SimpleNamespace(
            get_cover_url=lambda url: None))

    @pytest.mark.parametrize("title", ["One Piece", "oNe PiEcE"])
    @pytest.mark.parametrize("flags", [(), ("--force",), ("--yes",), ("-f",), ("-y",)])
    @pytest.mark.parametrize("url", [
        "https://mangadex.org/title/original/x",
        "https://mangadex.org/title/different/x",
    ])
    def test_duplicate_exits_1_without_writing(self, run_cli, isolated_home,
                                              config, capsys, title, flags, url):
        assert run_cli("add", "--title", "One Piece", "--url",
                       "https://mangadex.org/title/original/x") == 0
        path = isolated_home / ".config" / "memanga" / "config.yaml"
        before = path.read_bytes()
        capsys.readouterr()

        rc = run_cli("add", "--title", title, "--url", url, *flags)

        assert rc == 1
        assert "already exists" in capsys.readouterr().err
        assert path.read_bytes() == before
        assert [m["title"] for m in config.get("manga")] == ["One Piece"]

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
# `add --status/--mode/--kindle` — per-manga policy fields (#347)
# ─────────────────────────────────────────────────────────────────────────


class TestAddPolicyFields:
    @pytest.fixture(autouse=True)
    def no_network(self, monkeypatch):
        from memanga import cli
        monkeypatch.setattr(cli, "get_scraper", lambda source: types.SimpleNamespace(
            get_cover_url=lambda url: None))

    def _add(self, run_cli, *flags):
        return run_cli("add", "--title", "Policy Test",
                       "--url", "https://mangadex.org/title/a/x", *flags)

    def test_no_flags_keeps_legacy_entry_shape(self, run_cli, config):
        assert self._add(run_cli) == 0
        [entry] = config.get("manga", [])
        assert entry == {"title": "Policy Test", "source": "mangadex.org",
                         "url": "https://mangadex.org/title/a/x"}

    @pytest.mark.parametrize("status", ["reading", "on-hold", "dropped", "completed"])
    def test_status_is_saved(self, run_cli, config, status):
        assert self._add(run_cli, "--status", status) == 0
        [entry] = config.get("manga", [])
        assert entry["status"] == status

    @pytest.mark.parametrize("mode", ["auto", "manual"])
    def test_mode_is_saved(self, run_cli, config, mode):
        assert self._add(run_cli, "--mode", mode) == 0
        [entry] = config.get("manga", [])
        assert entry["mode"] == mode

    @pytest.mark.parametrize(("flag", "expected"), [
        ("--kindle", True), ("--no-kindle", False),
    ])
    def test_kindle_is_saved(self, run_cli, config, flag, expected):
        assert self._add(run_cli, flag) == 0
        [entry] = config.get("manga", [])
        assert entry["send_to_kindle"] is expected

    def test_all_fields_with_backup(self, run_cli, config):
        assert self._add(run_cli, "--backup", "https://mangapill.com/manga/1/x",
                         "--status", "on-hold", "--mode", "manual",
                         "--no-kindle") == 0
        [entry] = config.get("manga", [])
        assert entry == {
            "title": "Policy Test",
            "fallback_delay_days": 2,
            "sources": [
                {"url": "https://mangadex.org/title/a/x"},
                {"url": "https://mangapill.com/manga/1/x"},
            ],
            "status": "on-hold",
            "mode": "manual",
            "send_to_kindle": False,
        }

    def test_fields_show_in_list_json(self, run_cli, config, capsys):
        assert self._add(run_cli, "--status", "completed", "--mode", "manual",
                         "--no-kindle") == 0
        capsys.readouterr()
        assert run_cli("list", "--json") == 0
        [item] = json.loads(capsys.readouterr().out)["manga"]
        assert (item["status"], item["mode"], item["send_to_kindle"]) == (
            "completed", "manual", False)

    @pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
    @pytest.mark.parametrize(("flags", "message"), [
        (("--status", "plan"), "--status"),
        (("--status", "Reading"), "--status"),
        (("--mode", "automatic"), "--mode"),
        (("--kindle", "--no-kindle"), "not allowed with"),
        (("--no-kindle", "--kindle"), "not allowed with"),
    ])
    def test_invalid_flags_do_not_write_config(self, run_cli, isolated_home,
                                               capsys, flags, message, existing):
        path = isolated_home / ".config" / "memanga" / "config.yaml"
        before = b"# Keep this formatting\nmanga:\n  - title: Existing Manga\n"
        if existing:
            path.write_bytes(before)

        assert self._add(run_cli, "--force", *flags) == 2
        assert message in capsys.readouterr().err
        if existing:
            assert path.read_bytes() == before
        else:
            assert not path.exists()

    def test_flags_do_not_bypass_duplicate(self, run_cli, isolated_home, capsys):
        assert self._add(run_cli) == 0
        path = isolated_home / ".config" / "memanga" / "config.yaml"
        before = path.read_bytes()
        assert self._add(run_cli, "--status", "dropped", "--no-kindle",
                         "--force") == 1
        assert "already exists" in capsys.readouterr().err
        assert path.read_bytes() == before


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


PRIMARY = "https://mangadex.org/title/a/x"
BACKUP = "https://mangapill.com/manga/1/x"
BACKUP2 = "https://weebcentral.com/series/2/x"
LEGACY = {"title": "Legacy", "source": "mangadex.org", "url": PRIMARY}
MULTI = {"title": "Multi", "fallback_delay_days": 3,
         "sources": [{"url": PRIMARY}, {"url": BACKUP}]}


class TestUpdatePolicyFields:
    """Issue #350: `update` / `edit` covers every editable per-manga field."""

    @pytest.fixture
    def seed(self, config, isolated_home):
        def _seed(*entries):
            config.set("manga", [dict(e) for e in entries])
            config.save()
            return isolated_home / ".config" / "memanga" / "config.yaml"
        return _seed

    def _entry(self, config, title):
        return next(m for m in config.get("manga", []) if m["title"] == title)

    @pytest.mark.parametrize("status", ["on-hold", "dropped", "completed"])
    def test_status(self, run_cli, config, seed, status):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "--status", status) == 0
        assert self._entry(config, "Legacy")["status"] == status

    def test_mode(self, run_cli, config, seed):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "--mode", "manual") == 0
        assert self._entry(config, "Legacy")["mode"] == "manual"
        assert run_cli("update", "Legacy", "--mode", "auto") == 0
        assert self._entry(config, "Legacy")["mode"] == "auto"

    @pytest.mark.parametrize(("start", "flag", "expected"), [
        (None, "--no-kindle", False), (False, "--kindle", True),
    ])
    def test_kindle(self, run_cli, config, seed, start, flag, expected):
        entry = dict(LEGACY)
        if start is not None:
            entry["send_to_kindle"] = start
        seed(entry)
        assert run_cli("update", "Legacy", flag) == 0
        assert self._entry(config, "Legacy")["send_to_kindle"] is expected

    @pytest.mark.parametrize("days", [0, 7])
    def test_fallback_days_with_existing_backup(self, run_cli, config, seed, days):
        seed(MULTI)
        assert run_cli("update", "Multi", "--fallback-days", str(days)) == 0
        entry = self._entry(config, "Multi")
        assert entry["fallback_delay_days"] == days
        assert entry["sources"] == MULTI["sources"]

    def test_backup_and_fallback_days_on_legacy_entry(self, run_cli, config, seed):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "--backup", BACKUP, "--fallback-days", "5") == 0
        entry = self._entry(config, "Legacy")
        assert entry == {
            "title": "Legacy",
            "fallback_delay_days": 5,
            "sources": [{"url": PRIMARY, "source": "mangadex.org"},
                        {"url": BACKUP, "source": "mangapill.com"}],
        }

    def test_backup_alone_keeps_legacy_default_delay(self, run_cli, config, seed):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "-b", BACKUP) == 0
        assert self._entry(config, "Legacy")["fallback_delay_days"] == 2

    def test_backup_appends_to_single_entry_sources(self, run_cli, config, seed):
        seed({"title": "One", "sources": [{"url": PRIMARY}]})
        assert run_cli("update", "One", "--backup", BACKUP) == 0
        assert self._entry(config, "One")["sources"] == [
            {"url": PRIMARY}, {"url": BACKUP, "source": "mangapill.com"}]

    def test_no_backup_removes_backup_and_delay(self, run_cli, config, seed, capsys):
        seed(dict(MULTI, status="on-hold", mode="manual", send_to_kindle=False))
        assert run_cli("update", "Multi", "--no-backup") == 0
        assert "Backup removed" in capsys.readouterr().out
        assert self._entry(config, "Multi") == {
            "title": "Multi", "sources": [{"url": PRIMARY}],
            "status": "on-hold", "mode": "manual", "send_to_kindle": False,
        }

    def test_no_backup_removes_every_backup(self, run_cli, config, seed):
        seed(dict(MULTI, sources=[{"url": PRIMARY}, {"url": BACKUP}, BACKUP2]))
        assert run_cli("update", "Multi", "--no-backup") == 0
        assert self._entry(config, "Multi")["sources"] == [{"url": PRIMARY}]

    def test_no_backup_clears_stale_delay_on_primary_only_entry(self, run_cli, config,
                                                                 seed, capsys):
        seed(dict(LEGACY, fallback_delay_days=4), {"title": "One", "fallback_delay_days": 1,
                                                   "sources": [{"url": BACKUP}]})
        assert run_cli("update", "Legacy", "--no-backup") == 0
        assert "Stale fallback delay removed" in capsys.readouterr().out
        assert self._entry(config, "Legacy") == LEGACY
        assert run_cli("update", "One", "--no-backup") == 0
        assert self._entry(config, "One") == {"title": "One", "sources": [{"url": BACKUP}]}

    @pytest.mark.parametrize("url", [
        "http://mangadex.org/title/a/x",
        "https://www.mangadex.org:8443/title/a/x?x=1#y",
        "https://user:pw@mangadex.org/title/a/x",
        "http://localhost:8080/manga",
        "http://127.0.0.1/manga",
        "http://[::1]:8080/manga",
        "https://mangadex.org./title/a/x",
    ])
    def test_valid_url_forms_are_accepted(self, run_cli, config, seed, url):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "--url", url) == 0
        assert self._entry(config, "Legacy")["url"] == url

    def test_no_backup_then_list_json(self, run_cli, config, seed, capsys):
        seed(MULTI)
        assert run_cli("update", "Multi", "--no-backup") == 0
        capsys.readouterr()
        assert run_cli("list", "--json") == 0
        [item] = json.loads(capsys.readouterr().out)["manga"]
        assert (item["url"], item["backup_count"]) == (PRIMARY, 0)

    def test_string_sources_are_supported(self, run_cli, config, seed):
        seed({"title": "Strings", "fallback_delay_days": 1, "sources": [PRIMARY, BACKUP]})
        assert run_cli("update", "Strings", "--url", "https://mangadex.org/title/b/y",
                       "--no-backup") == 0
        assert self._entry(config, "Strings") == {
            "title": "Strings",
            "sources": [{"url": "https://mangadex.org/title/b/y", "source": "mangadex.org"}],
        }

    def test_combined_edit_via_edit_alias(self, run_cli, config, seed, cli_state):
        seed(MULTI, LEGACY)
        cli_state.add_downloaded_chapter("Multi", "4")
        cli_state.save()
        assert run_cli("edit", "#1", "--url", "https://www.mangadex.org/title/c/z",
                       "--backup", BACKUP2, "--fallback-days", "1",
                       "--title", "Renamed", "--status", "completed",
                       "--mode", "manual", "--no-kindle") == 0
        assert self._entry(config, "Renamed") == {
            "title": "Renamed",
            "fallback_delay_days": 1,
            "sources": [
                {"url": "https://www.mangadex.org/title/c/z", "source": "mangadex.org"},
                {"url": BACKUP2, "source": "weebcentral.com"},
            ],
            "status": "completed", "mode": "manual", "send_to_kindle": False,
        }
        assert self._entry(config, "Legacy") == LEGACY
        from memanga.state import State
        reloaded = State(config_dir=cli_state.state_path.parent)
        assert reloaded.get_downloaded_chapters("Renamed") == ["4"]
        assert reloaded.get_downloaded_chapters("Multi") == []

    def test_title_case_only_rename(self, run_cli, config, seed):
        seed(LEGACY)
        assert run_cli("update", "Legacy", "--title", "LEGACY") == 0
        assert [m["title"] for m in config.get("manga", [])] == ["LEGACY"]

    @pytest.mark.parametrize("flags", [
        ("--status", "reading"),
        ("--mode", "auto"),
        ("--kindle",),
        ("--no-backup",),
        ("--url", PRIMARY, "--title", "Legacy"),
    ])
    def test_matching_values_write_nothing(self, run_cli, seed, capsys, flags):
        path = seed(LEGACY)
        before = path.read_bytes()
        assert run_cli("update", "Legacy", *flags) == 0
        assert "No changes" in capsys.readouterr().out
        assert path.read_bytes() == before

    def test_matching_backup_and_delay_write_nothing(self, run_cli, seed):
        path = seed(MULTI)
        before = path.read_bytes()
        assert run_cli("update", "Multi", "-b", BACKUP, "--fallback-days", "3") == 0
        assert path.read_bytes() == before

    @pytest.mark.parametrize(("target", "flags", "code", "message"), [
        ("Multi", ("--backup", BACKUP2, "--no-backup"), 2, "not allowed with"),
        ("Multi", ("--kindle", "--no-kindle"), 2, "not allowed with"),
        ("Multi", ("--mode", "automatic"), 2, "--mode"),
        ("Multi", ("--status", "plan"), 2, "--status"),
        ("Multi", ("--fallback-days", "-1"), 2, "--fallback-days"),
        ("Multi", ("--fallback-days", "1.5"), 2, "--fallback-days"),
        ("Multi", ("--no-backup", "--fallback-days", "1"), 1, "cannot be combined"),
        ("Legacy", ("--fallback-days", "1"), 1, "no backup source"),
        ("Legacy", ("--mode", "manual", "--fallback-days", "1"), 1, "no backup source"),
        ("Multi", ("--backup", ""), 1, "--no-backup"),
        ("Multi", ("--backup", "mangapill.com/x"), 1, "http(s) URL"),
        ("Multi", ("--url", ""), 1, "http(s) URL"),
        ("Multi", ("--url", "ftp://mangadex.org/x", "--status", "dropped"), 1, "http(s) URL"),
        ("Multi", ("--url", "http://["), 1, "http(s) URL"),
        ("Multi", ("--backup", "https://[::1"), 1, "http(s) URL"),
        ("Multi", ("--url", "http://[not-an-ip]/x"), 1, "http(s) URL"),
        ("Multi", ("--url", "https://:443/x"), 1, "http(s) URL"),
        ("Multi", ("--url", "https://user@/x"), 1, "http(s) URL"),
        ("Multi", ("--url", "https://mangadex.org:abc/x"), 1, "http(s) URL"),
        ("Multi", ("--backup", "https://bad host.com/x"), 1, "http(s) URL"),
        ("Multi", ("--backup", "https://-bad.com/x"), 1, "http(s) URL"),
        ("Multi", ("--backup", "https://a..b/x"), 1, "http(s) URL"),
        ("Multi", ("--title", "  "), 1, "cannot be empty"),
        ("Multi", ("--title", "legacy", "--no-kindle"), 1, "already exists"),
    ])
    def test_invalid_input_writes_nothing(self, run_cli, seed, capsys,
                                          target, flags, code, message):
        path = seed(MULTI, LEGACY)
        before = path.read_bytes()
        assert run_cli("update", target, *flags) == code
        assert message in capsys.readouterr().err
        assert path.read_bytes() == before

    def test_backup_without_primary_is_refused(self, run_cli, seed, capsys):
        path = seed({"title": "Empty", "sources": []})
        before = path.read_bytes()
        assert run_cli("update", "Empty", "--backup", BACKUP) == 1
        assert "no primary source" in capsys.readouterr().err
        assert path.read_bytes() == before

    def test_url_on_empty_sources_list(self, run_cli, config, seed):
        seed({"title": "Empty", "sources": []})
        assert run_cli("update", "Empty", "--url", PRIMARY) == 0
        assert self._entry(config, "Empty")["sources"] == [
            {"url": PRIMARY, "source": "mangadex.org"}]

    @pytest.mark.parametrize("url", [
        "https://user:pw@mangadex.org/title/a/x",
        "https://mangadex.org:8443/title/a/x",
        "https://MangaDex.org./title/a/x",
        "https://www.mangadex.org/title/a/x",
    ])
    @pytest.mark.parametrize("flag", ["--url", "--backup"])
    def test_url_forms_store_canonical_scraper_source(self, run_cli, config, seed,
                                                      capsys, flag, url):
        from memanga.downloader import _get_sources_from_manga
        from memanga.scrapers import get_scraper
        from memanga.scrapers.mangadex import MangaDexScraper

        seed({"title": "One", "sources": [{"url": BACKUP, "source": "mangapill.com"}]})
        assert run_cli("update", "One", flag, url) == 0
        assert "pw" not in capsys.readouterr().out
        sources = self._entry(config, "One")["sources"]
        saved = sources[0] if flag == "--url" else sources[1]
        assert saved == {"url": url, "source": "mangadex.org"}
        resolved = _get_sources_from_manga(self._entry(config, "One"))
        assert isinstance(get_scraper(resolved[sources.index(saved)]["source"]),
                          MangaDexScraper)

    def test_legacy_url_stores_canonical_scraper_source(self, run_cli, config, seed):
        url = "https://user:pw@mangadex.org:8443/title/a/x"
        seed(dict(LEGACY, url=BACKUP, source="mangapill.com"))
        assert run_cli("update", "Legacy", "--url", url) == 0
        entry = self._entry(config, "Legacy")
        assert (entry["url"], entry["source"]) == (url, "mangadex.org")

    def test_help_documents_global_format(self, run_cli, capsys):
        assert run_cli("update", "--help") == 0
        out = " ".join(capsys.readouterr().out.split())
        for flag in ("--no-backup", "--fallback-days", "--status", "--mode",
                     "--kindle", "--no-kindle"):
            assert flag in out
        assert "no per-manga format" in out


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

    def test_check_success_records_download_history(
            self, run_cli, config, monkeypatch, tmp_path):
        """CLI downloads must feed download_history so the suspicion guard
        can learn a manga's typical batch size."""
        from memanga import cli

        config.set("manga", [{
            "title": "Vinland Saga",
            "status": "reading",
            "sources": [{"source": "primary.test", "url": "https://primary.test/vs"}],
        }])
        config.save()

        primary_ch = types.SimpleNamespace(
            number="71", title="", url="https://primary.test/c/71",
            source="primary.test", is_backup=False)
        pdf_path = tmp_path / "vinland-71.pdf"
        pdf_path.write_bytes(b"x" * 1024)

        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [primary_ch])
        monkeypatch.setattr(cli, "download_chapter",
                            lambda *a, **k: pdf_path)

        rc = run_cli("check", "--auto", "--quiet")

        assert rc == 0
        history = cli.state.get_download_history()
        assert [(h["title"], h["chapter"]) for h in history] == [("Vinland Saga", "71")]
        assert history[0]["path"] == str(pdf_path)

    def test_backup_complete_save_records_download_history(
            self, run_cli, config, monkeypatch, tmp_path):
        """A complete save from the backup source is a successful download
        and must be recorded too, with the backup file's path."""
        from memanga import cli
        from memanga.downloader import DownloaderError

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
        backup_path = tmp_path / "backup-71.pdf"
        backup_path.write_bytes(b"x" * 2048)

        monkeypatch.setattr(cli, "check_for_updates",
                            lambda *a, **k: [primary_ch])
        monkeypatch.setattr(cli, "_find_chapter_on_backup",
                            lambda *a, **k: backup_ch)

        def fake_download(manga, chapter, *args, **kwargs):
            if getattr(chapter, "is_backup", False):
                return backup_path
            raise DownloaderError("primary failed")

        monkeypatch.setattr(cli, "download_chapter", fake_download)

        rc = run_cli("check", "--auto", "--quiet")

        assert rc == 0
        history = cli.state.get_download_history()
        assert [(h["title"], h["chapter"]) for h in history] == [("Vinland Saga", "71")]
        assert history[0]["path"] == str(backup_path)

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

    def test_cron_install_default_dir_omits_config_dir(self, isolated_home,
                                                       monkeypatch):
        """#221: with no flag or $MEMANGA_CONFIG_DIR the scheduled check
        keeps the pre-#221 line, so it follows the default root."""
        from memanga import cli

        submitted = _capture_crontab(monkeypatch)
        monkeypatch.setattr(sys, "argv",
                            ["memanga", "cron", "install", "--time", "06:00"])
        cli.main()

        assert _expected_cron_line() in submitted["crontab"].splitlines()
        assert "--config-dir" not in submitted["crontab"]

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
        monkeypatch.setattr(sys, "argv",
                            ["memanga", "cron", "install", "--time", "06:00"])
        cli.main()

        create, = [c for c in calls if c[1] == "/create"]
        command = create[create.index("/tr") + 1]
        assert command == (f'cmd /d /c "cd /d "{checkout}" && "{python}" '
                           '-m memanga check --auto --quiet"')


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
            "mode": "auto", "send_to_kindle": True, "backup_count": 0,
        }
        assert multi["status"] == "on-hold"
        assert multi["source"] == "mangapill.com"
        assert multi["source_display"] == "mangapill.com (+1)"
        assert len(multi["sources"]) == 2
        assert multi["last_chapter"] == "2"
        assert multi["downloaded_count"] == 2
        assert multi["backup_count"] == 1


class TestListFilterSort:
    """Issue #346: list --status / --sort / --reverse and richer fields."""

    @pytest.fixture
    def library(self, config, cli_state, capsys):
        config.set("manga", [
            {"title": "beta", "status": "completed", "mode": "manual",
             "send_to_kindle": False, "sources": [
                 {"source": "mangadex.org", "url": "https://mangadex.org/t/b"},
                 {"source": "mangapill.com", "url": "https://mangapill.com/m/b"},
                 {"url": "https://comick.io/comic/b"},
             ]},
            {"title": "Alpha", "source": "mangadex.org",
             "url": "https://mangadex.org/t/a"},
            {"title": "gamma", "status": "on-hold",
             "sources": [{"url": "https://mangadex.org/t/g"}]},
            {"title": "Delta", "status": "reading",
             "sources": [{"url": "https://mangadex.org/t/d"}]},
        ])
        config.save()
        for ch in ("1", "2", "10"):
            cli_state.add_downloaded_chapter("beta", ch)
        cli_state.add_downloaded_chapter("Delta", "9.5")
        cli_state.save()
        capsys.readouterr()

    def _titles(self, run_cli, capsys, *flags):
        assert run_cli("list", "--json", *flags) == 0
        payload = _stdout_json(capsys)
        assert payload["count"] == len(payload["manga"])
        return [m["title"] for m in payload["manga"]]

    def test_default_is_list_order(self, run_cli, library, capsys):
        assert self._titles(run_cli, capsys) == ["beta", "Alpha", "gamma", "Delta"]
        assert self._titles(run_cli, capsys, "--sort", "list") == [
            "beta", "Alpha", "gamma", "Delta"]

    def test_richer_fields(self, run_cli, library, capsys):
        assert run_cli("list", "--json") == 0
        beta, alpha, gamma, _ = _stdout_json(capsys)["manga"]
        assert (beta["mode"], beta["send_to_kindle"], beta["backup_count"]) == (
            "manual", False, 2)
        # Legacy single-source record: defaults, no backups.
        assert (alpha["mode"], alpha["send_to_kindle"], alpha["backup_count"]) == (
            "auto", True, 0)
        assert alpha["status"] == "reading"
        assert gamma["backup_count"] == 0

    def test_status_filter_keeps_list_numbers(self, run_cli, library, capsys):
        assert run_cli("list", "--json", "--status", "reading") == 0
        payload = _stdout_json(capsys)
        assert payload["count"] == 2
        assert [(m["n"], m["title"]) for m in payload["manga"]] == [
            (2, "Alpha"), (4, "Delta")]

    def test_status_filter_repeatable(self, run_cli, library, capsys):
        assert self._titles(run_cli, capsys, "--status", "completed",
                            "--status", "on-hold") == ["beta", "gamma"]

    def test_status_filter_no_match(self, run_cli, library, capsys):
        assert run_cli("list", "--json", "--status", "dropped") == 0
        assert _stdout_json(capsys) == {"schema_version": 1, "count": 0, "manga": []}

    def test_invalid_status_is_usage_error(self, run_cli, library, capsys):
        assert run_cli("list", "--status", "paused") == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_invalid_sort_is_usage_error(self, run_cli, library, capsys):
        assert run_cli("list", "--sort", "rating") == 2
        assert "invalid choice" in capsys.readouterr().err

    @pytest.mark.parametrize("key,expected", [
        ("title", ["Alpha", "beta", "Delta", "gamma"]),
        # reading < on-hold < dropped < completed; ties keep list order.
        ("status", ["Alpha", "Delta", "gamma", "beta"]),
        # Numeric, not string, order (10 > 9.5); no chapter goes last.
        ("last-chapter", ["Delta", "beta", "Alpha", "gamma"]),
        ("downloaded", ["Alpha", "gamma", "Delta", "beta"]),
    ])
    def test_sort_keys(self, run_cli, library, capsys, key, expected):
        assert self._titles(run_cli, capsys, "--sort", key) == expected

    @pytest.mark.parametrize("key,expected", [
        ("list", ["Delta", "gamma", "Alpha", "beta"]),
        ("title", ["gamma", "Delta", "beta", "Alpha"]),
        ("last-chapter", ["beta", "Delta", "Alpha", "gamma"]),
        # Ties (Alpha, gamma = 0) stay in list order when reversed.
        ("downloaded", ["beta", "Delta", "Alpha", "gamma"]),
    ])
    def test_reverse(self, run_cli, library, capsys, key, expected):
        assert self._titles(run_cli, capsys, "--sort", key, "--reverse") == expected

    @pytest.mark.parametrize("flags,expected", [
        ((), ["Delta", "gamma", "beta", "Alpha"]),
        (("--reverse",), ["beta", "gamma", "Delta", "Alpha"]),
    ])
    def test_sort_status_unknown_goes_last(self, run_cli, library, config,
                                           capsys, flags, expected):
        # A hand-edited status outside VALID_STATUSES has no rank.
        manga = config.get("manga")
        manga[1]["status"] = "paused"
        config.set("manga", manga)
        config.save()
        assert self._titles(run_cli, capsys, "--sort", "status", *flags) == expected

    @pytest.mark.parametrize("flags,expected", [
        ((), ["Delta", "beta", "Alpha", "gamma"]),
        (("--reverse",), ["beta", "Delta", "Alpha", "gamma"]),
    ])
    def test_sort_last_chapter_nonnumeric_goes_last(self, run_cli, library,
                                                     cli_state, capsys,
                                                     flags, expected):
        cli_state.set_last_chapter("gamma", "Extra")
        cli_state.save()
        assert run_cli("list", "--json", "--sort", "last-chapter", *flags) == 0
        manga = _stdout_json(capsys)["manga"]
        assert [m["title"] for m in manga] == expected
        assert manga[-1]["last_chapter"] == "Extra"

    def test_filter_and_sort_combine(self, run_cli, library, capsys):
        assert self._titles(run_cli, capsys, "--status", "reading",
                            "--sort", "title", "--reverse") == ["Delta", "Alpha"]

    def test_table_shows_new_columns_and_list_numbers(self, run_cli, library, capsys):
        assert run_cli("list", "--sort", "title", "--status", "completed",
                       "--status", "reading") == 0
        out = capsys.readouterr().out
        for header in ("Status", "Mode", "Kindle"):
            assert header in out
        lines = out.splitlines()
        # Mode and Kindle are stacked in one column: mode, then on/off below.
        i = next(i for i, line in enumerate(lines) if "beta" in line)
        assert "completed" in lines[i] and "manual" in lines[i]
        assert lines[i].split("│")[1].strip() == "1"
        assert "off" in lines[i + 1]
        assert "(+2)" in out  # backup count, in the Source column
        i = next(i for i, line in enumerate(lines) if "Alpha" in line)
        assert "auto" in lines[i] and " on " in lines[i + 1]
        assert lines[i].split("│")[1].strip() == "2"
        assert out.index("Alpha") < out.index("beta") < out.index("Delta")
        assert "gamma" not in out

    def test_table_filter_no_match(self, run_cli, library, capsys):
        assert run_cli("list", "--status", "dropped") == 0
        assert "No manga with status dropped" in capsys.readouterr().out


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
    """Issue #221: the config root is chosen per run, after parsing."""

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

    def test_rejected_with_gui(self, isolated_home, monkeypatch, tmp_path):
        from memanga import cli
        monkeypatch.delenv("MEMANGA_CLI_ONLY", raising=False)
        monkeypatch.setattr(sys, "argv", ["memanga", "--config-dir",
                                          str(tmp_path / "x"), "--gui"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 2

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

    def test_failed_record_wins_over_partial(self, run_cli, cli_state, capsys):
        # A partial that later failed on retry is listed once, as failed.
        cli_state.add_partial_chapter("Berserk", "1", source="mangapill.com",
                                      failed_pages=[2], total_pages=20)
        cli_state.add_failed_chapter("Berserk", "1", "mangadex.org", "timeout")

        assert run_cli("failed", "--json") == 0
        payload = _stdout_json(capsys)
        assert payload["count"] == 1
        entry, = payload["chapters"]
        assert (entry["status"], entry["source"], entry["error"]) == (
            "failed", "mangadex.org", "timeout")
        assert entry["total_pages"] is None

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


def _disk_state():
    """State as `run_cli` left it on disk (seed objects don't reload)."""
    from pathlib import Path
    from memanga.state import State
    return State(config_dir=Path.home() / ".config" / "memanga")


class TestFailedSubcommands:
    """Issue #352: `failed list|retry|clear [TARGET]`, targets resolved
    like `check -t`, retry through the shared chapter pipeline."""

    @pytest.fixture(autouse=True)
    def wide_console(self, monkeypatch):
        # Wide enough that table cells and status lines don't wrap the
        # asserted strings.
        from rich.console import Console
        from memanga import cli
        monkeypatch.setattr(cli, "console", Console(width=250))
        monkeypatch.setattr(cli, "err_console", Console(width=250, stderr=True))

    @pytest.fixture
    def tracked(self, config):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(("Berserk", "Vinland Saga"))
        ])
        config.save()

    @pytest.fixture
    def records(self, cli_state, tracked):
        cli_state.add_failed_chapter("Berserk", "1", "mangadex.org", "timeout")
        cli_state.add_failed_chapter("Vinland Saga", "10", "mangadex.org", "HTTP 503")
        cli_state.add_partial_chapter("Vinland Saga", "9", source="mangadex.org",
                                      failed_pages=[7], total_pages=40)
        cli_state.save()

    @pytest.fixture
    def downloads(self, monkeypatch, tmp_path):
        """Primary scraper lists every chapter; downloads of chapters in
        `fail` raise. Returns (calls, fail)."""
        from memanga import cli
        from memanga.downloader import DownloaderError
        from memanga.scrapers.base import Chapter

        calls, fail = [], set()

        class FakeScraper:
            def get_chapters(self, url):
                return [Chapter(number=n) for n in ("1", "9", "10")]

        def _download(manga, ch, *a, **k):
            calls.append((manga["title"], ch.number))
            if ch.number in fail:
                raise DownloaderError(f"chapter {ch.number} broke")
            path = tmp_path / f"{manga['title']}-{ch.number}.pdf"
            path.write_bytes(b"pdf")
            return path

        monkeypatch.setattr(cli, "get_scraper", lambda source: FakeScraper())
        monkeypatch.setattr(cli, "download_chapter", _download)
        monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: None)
        return calls, fail

    def test_bare_failed_and_list_both_list(self, run_cli, records, capsys):
        capsys.readouterr()
        assert run_cli("failed") == 0
        bare = capsys.readouterr().out
        assert run_cli("failed", "list") == 0
        listed = capsys.readouterr().out
        for out in (bare, listed):
            assert "Berserk" in out and "Vinland Saga" in out
        assert _disk_state().get_failed_chapters("Berserk")

    def test_list_json_same_payload_as_legacy(self, run_cli, records, capsys):
        capsys.readouterr()
        assert run_cli("failed", "--json") == 0
        legacy = _stdout_json(capsys)
        assert run_cli("failed", "list", "--json") == 0
        assert _stdout_json(capsys) == legacy
        assert legacy["count"] == 3

    def test_list_target(self, run_cli, records, capsys):
        capsys.readouterr()
        assert run_cli("failed", "list", "vinland", "--json") == 0
        payload = _stdout_json(capsys)
        assert payload["title_filter"] == "vinland"
        assert {c["title"] for c in payload["chapters"]} == {"Vinland Saga"}

    def test_list_target_by_list_index(self, run_cli, records, capsys):
        capsys.readouterr()
        assert run_cli("failed", "list", "#1", "--json") == 0
        payload = _stdout_json(capsys)
        assert [c["title"] for c in payload["chapters"]] == ["Berserk"]

    def test_untracked_records_stay_reachable(self, run_cli, cli_state,
                                              tracked, capsys):
        cli_state.add_failed_chapter("Gone Manga", "3", "mangadex.org", "x")
        cli_state.save()
        capsys.readouterr()
        assert run_cli("failed", "list", "gone", "--json") == 0
        payload = _stdout_json(capsys)
        assert [c["title"] for c in payload["chapters"]] == ["Gone Manga"]

    @pytest.mark.parametrize("action", ["list", "retry", "clear"])
    def test_unknown_target_exits_1_and_changes_nothing(
            self, run_cli, records, downloads, capsys, action):
        calls, _ = downloads
        capsys.readouterr()
        assert run_cli("failed", action, "Nope") == 1
        captured = capsys.readouterr()
        assert "Not found" in captured.err
        assert calls == []
        assert _disk_state().get_failed_chapters("Berserk")
        assert _disk_state().get_failed_chapters("Vinland Saga")

    def test_ambiguous_target_exits_1(self, run_cli, config, cli_state, capsys):
        config.set("manga", [
            {"title": t, "source": "mangadex.org", "url": "https://mangadex.org/title/a/x"}
            for t in ("Alpha One", "Alpha Two")
        ])
        config.save()
        cli_state.add_failed_chapter("Alpha One", "1", "mangadex.org", "x")
        cli_state.add_failed_chapter("Alpha Two", "1", "mangadex.org", "x")
        cli_state.save()
        capsys.readouterr()
        assert run_cli("failed", "clear", "alpha") == 1
        assert "Ambiguous" in capsys.readouterr().err
        assert _disk_state().get_failed_chapters("Alpha One")
        assert _disk_state().get_failed_chapters("Alpha Two")

    def test_clear_target_only_clears_that_manga(self, run_cli, records, capsys):
        assert run_cli("failed", "clear", "vinland") == 0
        assert "Cleared failure and partial records for Vinland Saga" in capsys.readouterr().out
        assert _disk_state().get_failed_chapters("Vinland Saga") == {}
        assert _disk_state().get_partial_chapter("Vinland Saga", "9") is None
        assert _disk_state().get_failed_chapters("Berserk")

    def test_clear_without_target_clears_all(self, run_cli, records, capsys):
        assert run_cli("failed", "clear") == 0
        assert "Cleared all failure and partial records" in capsys.readouterr().out
        assert _disk_state().get_failed_chapters("Berserk") == {}
        assert _disk_state().get_failed_chapters("Vinland Saga") == {}
        assert _disk_state().get_partial_chapter("Vinland Saga", "9") is None

    def test_legacy_clear_alias_with_title(self, run_cli, records):
        assert run_cli("failed", "--clear", "-t", "berserk") == 0
        assert _disk_state().get_failed_chapters("Berserk") == {}
        assert _disk_state().get_failed_chapters("Vinland Saga")

    def test_retry_target_only_retries_that_manga(self, run_cli, records,
                                                  downloads, capsys):
        calls, _ = downloads
        capsys.readouterr()
        assert run_cli("failed", "retry", "Berserk") == 0
        assert calls == [("Berserk", "1")]
        assert "1/1 chapters recovered" in capsys.readouterr().out
        assert _disk_state().get_failed_chapters("Berserk") == {}
        assert _disk_state().is_chapter_downloaded("Berserk", "1")
        assert _disk_state().get_failed_chapters("Vinland Saga")

    def test_title_option_before_action(self, run_cli, records, downloads):
        calls, _ = downloads
        assert run_cli("failed", "-t", "berserk", "retry") == 0
        assert calls == [("Berserk", "1")]

    def test_retry_still_failing_exits_3(self, run_cli, records, downloads,
                                         capsys):
        calls, fail = downloads
        fail.add("10")
        capsys.readouterr()
        assert run_cli("failed", "retry", "vinland") == 3
        captured = capsys.readouterr()
        assert sorted(calls) == [("Vinland Saga", "10"), ("Vinland Saga", "9")]
        assert "1/2 chapters recovered" in captured.out
        assert "Failed: chapter 10 broke" in captured.err
        assert _disk_state().get_failed_chapters("Vinland Saga")["10"]["attempts"] == 2
        assert _disk_state().get_partial_chapter("Vinland Saga", "9") is None

    def test_retry_uses_check_pipeline_for_backup_and_email(
            self, run_cli, config, cli_state, monkeypatch, tmp_path, capsys):
        """A backup save is emailed, like in `check`; the old retry loop
        skipped delivery for backup saves."""
        from memanga import cli
        from memanga.downloader import DownloaderError
        from memanga.scrapers.base import Chapter

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
        cli_state.add_failed_chapter("Vinland Saga", "71", "primary.test", "timeout")
        cli_state.save()
        backup_ch = types.SimpleNamespace(
            number="71", title="", url="https://backup.test/c/71",
            source="backup.test", is_backup=True)
        backup_path = tmp_path / "backup.pdf"
        backup_path.write_bytes(b"pdf")
        sent = []

        class FakeScraper:
            def get_chapters(self, url):
                return [Chapter(number="71", url="https://primary.test/c/71")]

        def fake_download(manga, chapter, *a, **k):
            if getattr(chapter, "is_backup", False):
                return backup_path
            raise DownloaderError("primary broke")

        monkeypatch.setattr(cli, "get_scraper", lambda source: FakeScraper())
        monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: backup_ch)
        monkeypatch.setattr(cli, "download_chapter", fake_download)
        monkeypatch.setattr(cli, "send_to_kindle",
                            lambda **kwargs: sent.append(kwargs["pdf_path"]))
        monkeypatch.setattr(cli, "get_app_password", lambda cfg: "pw")

        assert run_cli("failed", "retry") == 0
        assert sent == [backup_path]
        assert _disk_state().is_chapter_downloaded("Vinland Saga", "71")
        assert _disk_state().get_failed_chapters("Vinland Saga") == {}

    def test_retry_saved_as_partial_again_is_not_recovered(
            self, run_cli, config, cli_state, monkeypatch, tmp_path, capsys):
        from memanga import cli
        from memanga.scrapers.base import Chapter

        config.set("partial_chapters.enabled", True)
        config.set("partial_chapters.threshold_percent", 10)
        config.set("manga", [{"title": "Berserk", "source": "mangadex.org",
                              "url": "https://mangadex.org/title/b/x"}])
        config.save()
        cli_state.add_partial_chapter("Berserk", "5", source="mangadex.org",
                                      failed_pages=[2], total_pages=40)
        cli_state.save()
        path = tmp_path / "partial.pdf"
        path.write_bytes(b"pdf")

        class FakeScraper:
            def get_chapters(self, url):
                return [Chapter(number="5")]

        def fake_download(manga, chapter, *a, **k):
            k["on_partial"]([3], 40)
            return path

        monkeypatch.setattr(cli, "get_scraper", lambda source: FakeScraper())
        monkeypatch.setattr(cli, "download_chapter", fake_download)
        capsys.readouterr()

        assert run_cli("failed", "retry") == 3
        assert "0/1 chapters recovered" in capsys.readouterr().out
        assert _disk_state().get_partial_chapter("Berserk", "5")["failed_pages"] == [3]

    @pytest.mark.parametrize("argv", [
        ("failed", "--json", "retry"),
        ("failed", "--json", "clear"),
        ("failed", "--json", "--clear"),
    ])
    def test_json_rejected_with_retry_and_clear(self, run_cli, records,
                                                capsys, argv):
        capsys.readouterr()
        assert run_cli(*argv) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--json cannot be combined" in captured.err
        assert _disk_state().get_failed_chapters("Berserk")

    @pytest.mark.parametrize("argv", [
        ("failed", "retry", "--json"),
        ("failed", "clear", "--json"),
        ("failed", "--retry", "clear"),
        ("failed", "--clear", "list"),
        ("failed", "-t", "berserk", "clear", "vinland"),
    ])
    def test_usage_errors_change_nothing(self, run_cli, records, capsys, argv):
        capsys.readouterr()
        assert run_cli(*argv) == 2
        assert capsys.readouterr().out == ""
        assert _disk_state().get_failed_chapters("Berserk")
        assert _disk_state().get_failed_chapters("Vinland Saga")

    def test_help_describes_actions(self, run_cli, capsys):
        assert run_cli("failed", "--help") == 0
        out = capsys.readouterr().out
        for text in ("failed retry [TARGET]", "failed clear [TARGET]",
                     "aliases", "Exit codes"):
            assert text in out


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

    def test_interactive_does_not_dump_source_list(self, run_cli, config,
                                                   monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", _TtyInput(
            "Blue Lock\nhttps://mangadex.org/title/a/x\nn\n"))
        assert run_cli("add", "--interactive") == 0
        out = capsys.readouterr().out
        assert "memanga sources" in out
        assert "weebcentral.com" not in out

    def test_unsupported_source_warning_does_not_dump_source_list(
            self, run_cli, config, capsys):
        assert run_cli("add", "--title", "Unsafe", "--force",
                       "--url", "https://unsupported.example/manga") == 0
        err = capsys.readouterr().err
        assert "memanga sources" in err
        assert "weebcentral.com" not in err

    def test_interactive_applies_policy_flags_without_extra_prompts(
            self, run_cli, config, monkeypatch):
        # Only title, url and "no backup" are answered; any extra prompt
        # would hit EOF and fail the command.
        monkeypatch.setattr(sys, "stdin", _TtyInput(
            "Blue Lock\nhttps://mangadex.org/title/a/x\nn\n"))
        assert run_cli("add", "--interactive", "--status", "on-hold",
                       "--mode", "manual", "--no-kindle") == 0
        [entry] = config.get("manga", [])
        assert (entry["status"], entry["mode"], entry["send_to_kindle"]) == (
            "on-hold", "manual", False)

    def test_flag_add_with_policy_on_tty_does_not_prompt(self, run_cli, config,
                                                         monkeypatch):
        stdin = _TtyInput("y\n")
        monkeypatch.setattr(sys, "stdin", stdin)
        assert run_cli("add", "--title", "Blue Lock",
                       "--url", "https://mangadex.org/title/a/x",
                       "--status", "completed", "--mode", "auto",
                       "--kindle") == 0
        assert stdin.read() == "y\n"
        [entry] = config.get("manga", [])
        assert (entry["status"], entry["mode"], entry["send_to_kindle"]) == (
            "completed", "auto", True)

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
        assert "Failed: chapter 7 broke" in captured.err

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


class TestCheckModes:
    """Check-only, download and ask modes of `check` (#351)."""

    DOWNLOAD_FLAGS = [
        ["--download"], ["-a"], ["--auto"], ["-y"], ["--yes"],
        ["--auto", "--yes"], ["--download", "--auto"], ["--auto", "--quiet"],
    ]

    @pytest.fixture
    def seeded(self, config, tmp_path):
        config.set("manga", [
            {"title": t, "source": "mangadex.org",
             "url": f"https://mangadex.org/title/{i}/x", "status": "reading"}
            for i, t in enumerate(("Alpha", "Beta"))
        ])
        config.set("delivery.mode", "email")
        config.set("delivery.download_dir", str(tmp_path / "dl"))
        config.set("email.kindle_email", "kindle@example.invalid")
        config.set("email.sender_email", "me@example.invalid")
        config.save()

    @pytest.fixture
    def calls(self, monkeypatch, tmp_path):
        """Stub the check and every side-effecting step; record calls."""
        from memanga import cli
        from memanga.scrapers.base import Chapter

        rec = {"download": [], "email": [], "prompt": [], "restart": 0,
               "check_kwargs": []}

        def _check(manga, state, **k):
            rec["check_kwargs"].append(k)
            return [Chapter(number="5"), Chapter(number="6")]

        def _download(manga, ch, *a, **k):
            rec["download"].append((manga["title"], ch.number))
            path = tmp_path / f"{manga['title']}-{ch.number}.pdf"
            path.write_bytes(b"pdf")
            return path

        def _prompt(*a, **k):
            rec["prompt"].append(a)
            return True

        def _restart():
            rec["restart"] += 1

        monkeypatch.setattr(cli, "check_for_updates", _check)
        monkeypatch.setattr(cli, "download_chapter", _download)
        monkeypatch.setattr(cli, "send_to_kindle",
                            lambda **k: rec["email"].append(k["pdf_path"]))
        monkeypatch.setattr(cli, "get_app_password", lambda cfg: "x")
        monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: None)
        monkeypatch.setattr(cli, "restart_browsers", _restart)
        monkeypatch.setattr(cli.Confirm, "ask", _prompt)
        return rec

    @staticmethod
    def _stdin(monkeypatch, tty):
        monkeypatch.setattr(sys, "stdin", _TtyInput("") if tty else io.StringIO(""))

    @pytest.fixture
    def bound_cli(self, isolated_home, monkeypatch):
        """memanga.cli bound to the isolated config dir, globals restored."""
        from memanga import cli
        for name in ("_context", "config", "state"):
            monkeypatch.setattr(cli, name, getattr(cli, name))
        cli.use_context(cli.build_context(isolated_home / ".config" / "memanga"))
        return cli

    @pytest.mark.parametrize("tty", [False, True])
    @pytest.mark.parametrize("flags", DOWNLOAD_FLAGS)
    def test_download_flags_download_without_prompting(
            self, run_cli, seeded, calls, monkeypatch, capsys, flags, tty):
        self._stdin(monkeypatch, tty)
        capsys.readouterr()
        assert run_cli("check", *flags) == 0
        assert sorted(calls["download"]) == [
            ("Alpha", "5"), ("Alpha", "6"), ("Beta", "5"), ("Beta", "6")]
        assert len(calls["email"]) == 4
        assert calls["prompt"] == []
        captured = capsys.readouterr()
        assert "4/4 chapters downloaded" in captured.out
        assert captured.err == ""

    @pytest.mark.parametrize("tty", [False, True])
    @pytest.mark.parametrize("flags", [
        ["--dry-run"], ["-n"], ["--dry-run", "--auto"], ["-n", "--download"],
        ["-n", "--yes", "--quiet"], ["-n", "-a", "--all", "--safe"],
        ["-n", "--download", "--from", "1", "--format", "cbz", "--retries", "0"],
        ["-n", "--force-suspicious"],
    ])
    def test_dry_run_wins_and_has_no_side_effects(
            self, run_cli, seeded, calls, cli_state, isolated_home,
            monkeypatch, capsys, flags, tty):
        from memanga.state import State

        cli_state.add_downloaded_chapter("Alpha", "4")
        cli_state.save()
        state_path = isolated_home / ".config" / "memanga" / "state.json"
        on_disk = state_path.read_bytes()
        self._stdin(monkeypatch, tty)
        capsys.readouterr()

        assert run_cli("check", *flags) == 0

        assert calls["download"] == calls["email"] == calls["prompt"] == []
        assert calls["restart"] == 0
        assert all(k.get("dry_run") is True for k in calls["check_kwargs"])
        captured = capsys.readouterr()
        assert captured.out.count("[DRY RUN]") == 4
        assert "Dry run: 4 chapter(s) available for download" in captured.out
        assert captured.err == ""
        # No check is recorded: last_check, history and every other field
        # are byte-for-byte unchanged.
        assert state_path.read_bytes() == on_disk
        reloaded = State(isolated_home / ".config" / "memanga")
        assert reloaded.get("last_check") is None
        assert reloaded.get("check_history", []) == []

    def test_download_run_records_history(self, run_cli, seeded, calls,
                                          isolated_home, monkeypatch):
        from memanga.state import State

        self._stdin(monkeypatch, False)
        assert run_cli("check", "--download") == 0
        assert all("dry_run" not in k for k in calls["check_kwargs"])
        reloaded = State(isolated_home / ".config" / "memanga")
        assert reloaded.get("last_check") is not None
        assert reloaded.get_check_history()[-1]["downloaded"] == 4
        assert reloaded.get_check_history()[-1]["new_chapters"] == 4

    def test_default_on_terminal_still_prompts(self, run_cli, seeded, calls,
                                               monkeypatch):
        self._stdin(monkeypatch, True)
        assert run_cli("check", "-t", "Alpha") == 0
        assert len(calls["prompt"]) == 2
        assert calls["download"] == [("Alpha", "5"), ("Alpha", "6")]

    @pytest.mark.parametrize("tty,flags", [
        (False, []), (False, ["--quiet"]), (True, ["--quiet"]),
        (True, ["-q", "--all"]), (False, ["--from", "1"]),
    ])
    def test_unconfirmed_never_downloads_and_exits_1(
            self, run_cli, seeded, calls, isolated_home, monkeypatch, capsys,
            tty, flags):
        from memanga.state import State

        self._stdin(monkeypatch, tty)
        capsys.readouterr()
        assert run_cli("check", *flags) == 1
        assert calls["download"] == calls["email"] == calls["prompt"] == []
        err = capsys.readouterr().err
        assert "skipped 4 chapter(s) that need confirmation" in err
        for flag in ("--download", "--auto", "--yes", "--dry-run"):
            assert flag in err
        # Unchanged: an unconfirmed run is still a recorded check.
        history = State(isolated_home / ".config" / "memanga").get_check_history()
        assert history[-1] == {**history[-1], "new_chapters": 4, "downloaded": 0}

    def test_unconfirmed_wins_over_partial_failure(self, run_cli, config,
                                                   calls, monkeypatch, capsys):
        """Documented precedence: needing confirmation exits 1, not 3."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        config.set("manga", [
            {"title": "Alpha", "source": "mangadex.org", "url": "u/a"},
            {"title": "Beta", "source": "mangadex.org", "url": "u/b"},
        ])
        config.save()

        def _check(manga, state, **k):
            if manga["title"] == "Beta":
                raise DownloaderError("HTTP 503")
            from memanga.scrapers.base import Chapter
            return [Chapter(number="5")]
        monkeypatch.setattr(cli, "check_for_updates", _check)
        self._stdin(monkeypatch, False)
        assert run_cli("check") == 1

    def test_tui_namespace_still_works(self, seeded, calls, bound_cli,
                                       monkeypatch):
        """`cmd_tui` passes the pre-#351 attribute names."""
        import argparse
        cli = bound_cli

        self._stdin(monkeypatch, False)

        def _tui_args(auto):
            return argparse.Namespace(
                title="Alpha", auto=auto, yes=False, quiet=False,
                from_chapter=None, safe=False, dry_run=False, format=None,
                retries=3,
            )

        assert cli.cmd_check(_tui_args(auto=True)) is None
        assert calls["download"] == [("Alpha", "5"), ("Alpha", "6")]
        assert cli.cmd_check(_tui_args(auto=False)) == 1
        assert len(calls["download"]) == 2

    def test_namespace_without_mode_attributes(self, seeded, calls,
                                               bound_cli, monkeypatch):
        import argparse
        cli = bound_cli

        self._stdin(monkeypatch, False)
        assert cli.cmd_check(argparse.Namespace(title="Alpha")) == 1
        assert calls["download"] == []

    def test_help_describes_modes(self, run_cli, capsys):
        assert run_cli("check", "--help") == 0
        out = " ".join(capsys.readouterr().out.split())
        assert "--download, -a, --auto, -y, --yes" in out
        assert "--auto and --yes are aliases" in out
        assert "check only" in out.lower()
        assert "wins over --download" in out
        assert "Never prompt" in out
        assert "Minimal output" not in out
        assert "Exit codes: 0 no new chapters" in out
        assert "suspicious batch withheld" in out

    def test_top_level_example_uses_download(self, run_cli, capsys):
        run_cli("--help")
        out = capsys.readouterr().out
        assert "memanga check --download" in out
        assert "memanga check --dry-run" in out


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


# ─────────────────────────────────────────────────────────────────────────
# Issue #349 — explicit history and file choices for `remove`
# ─────────────────────────────────────────────────────────────────────────


class TestRemoveHistoryAndFiles:
    @pytest.fixture(autouse=True)
    def no_tty(self, monkeypatch):
        # Any unexpected prompt dies with EOFError on a closed pipe.
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    @pytest.fixture
    def downloads(self, config, tmp_path):
        root = tmp_path / "downloads"
        root.mkdir()
        config.set("delivery.download_dir", str(root))
        config.set("manga", [
            {"title": "Goner", "source": "mangadex.org", "url": "u1", "status": "reading"},
            {"title": "Keeper", "source": "mangadex.org", "url": "u2", "status": "reading"},
        ])
        config.save()
        goner = root / "Goner"
        (goner / "Chapter 2").mkdir(parents=True)
        (goner / "Goner - Chapter 1.cbz").write_text("a")
        (goner / "Chapter 2" / "001.jpg").write_text("img")
        (root / "Keeper").mkdir()
        (root / "Keeper" / "Keeper - Chapter 1.cbz").write_text("k")
        # Pre-#21 layout: a root-level file is never touched.
        (root / "Goner - Chapter 0.cbz").write_text("legacy")
        return root

    @pytest.fixture
    def history(self, cli_state):
        cli_state.add_downloaded_chapter("Goner", "1")
        cli_state.save()
        return cli_state

    def _titles(self, config):
        return [m["title"] for m in config.get("manga", [])]

    def _history(self, cli_state):
        from memanga.state import State
        return State(config_dir=cli_state.state_path.parent).get_downloaded_chapters("Goner")

    def _untouched(self, root):
        assert (root / "Keeper" / "Keeper - Chapter 1.cbz").read_text() == "k"
        assert (root / "Goner - Chapter 0.cbz").read_text() == "legacy"

    @pytest.mark.parametrize("flags, history_kept, files_kept", [
        ((), True, True),
        (("--keep-files",), True, True),
        (("--purge-history",), False, True),
        (("--purge",), False, True),
        (("--purge-history", "--keep-files"), False, True),
        (("--delete-files",), True, False),
        (("--purge-history", "--delete-files"), False, False),
        (("--purge", "--delete-files"), False, False),
    ])
    def test_yes_combinations(self, run_cli, config, downloads, history,
                              flags, history_kept, files_kept):
        assert run_cli("rm", "Goner", "--yes", *flags) == 0
        assert self._titles(config) == ["Keeper"]
        assert (self._history(history) == ["1"]) is history_kept
        assert (downloads / "Goner").exists() is files_kept
        self._untouched(downloads)

    def test_keep_and_delete_files_conflict_changes_nothing(
            self, run_cli, config, downloads, history):
        assert run_cli("rm", "Goner", "--yes", "--purge-history",
                       "--keep-files", "--delete-files") == 2
        assert self._titles(config) == ["Goner", "Keeper"]
        assert self._history(history) == ["1"]
        assert (downloads / "Goner" / "Goner - Chapter 1.cbz").exists()

    def test_conflict_rejected_for_direct_namespace(self, config, downloads,
                                                    monkeypatch):
        import argparse
        from memanga import cli
        from memanga.config import Config
        monkeypatch.setattr(cli, "config", Config())
        args = argparse.Namespace(target="Goner", yes=True, purge_history=False,
                                  keep_files=True, delete_files=True)
        assert cli.cmd_remove(args) == 1
        assert self._titles(config) == ["Goner", "Keeper"]
        assert (downloads / "Goner").exists()

    def test_delete_files_without_yes_refuses_off_tty(
            self, run_cli, config, downloads, capsys):
        assert run_cli("rm", "Goner", "--delete-files") == 1
        assert "--yes" in capsys.readouterr().err
        assert self._titles(config) == ["Goner", "Keeper"]
        assert (downloads / "Goner").exists()

    def test_delete_files_with_no_folder(self, run_cli, config, downloads, capsys):
        import shutil
        shutil.rmtree(downloads / "Goner")
        capsys.readouterr()
        assert run_cli("rm", "Goner", "--yes", "--delete-files") == 0
        assert "No downloaded files" in capsys.readouterr().out
        assert self._titles(config) == ["Keeper"]
        self._untouched(downloads)

    def test_delete_files_with_no_download_root(self, run_cli, config, tmp_path):
        config.set("delivery.download_dir", str(tmp_path / "missing"))
        config.set("manga", [{"title": "Goner", "source": "mangadex.org", "url": "u"}])
        config.save()
        assert run_cli("rm", "Goner", "--yes", "--delete-files") == 0
        assert self._titles(config) == []
        assert not (tmp_path / "missing").exists()

    def test_symlinked_folder_is_refused_before_any_change(
            self, run_cli, config, downloads, history, tmp_path, capsys):
        import shutil
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("p")
        shutil.rmtree(downloads / "Goner")
        (downloads / "Goner").symlink_to(outside, target_is_directory=True)
        assert run_cli("rm", "Goner", "--yes", "--purge-history",
                       "--delete-files") == 1
        assert "symlink" in capsys.readouterr().err
        assert self._titles(config) == ["Goner", "Keeper"]
        assert self._history(history) == ["1"]
        assert (outside / "precious.txt").read_text() == "p"
        assert (downloads / "Goner").is_symlink()

    def test_symlink_inside_folder_is_not_followed(
            self, run_cli, config, downloads, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("p")
        (downloads / "Goner" / "link").symlink_to(outside, target_is_directory=True)
        assert run_cli("rm", "Goner", "--yes", "--delete-files") == 0
        assert not (downloads / "Goner").exists()
        assert (outside / "precious.txt").read_text() == "p"

    def test_file_in_place_of_folder_is_refused(self, run_cli, config, downloads):
        import shutil
        shutil.rmtree(downloads / "Goner")
        (downloads / "Goner").write_text("not a dir")
        assert run_cli("rm", "Goner", "--yes", "--delete-files") == 1
        assert self._titles(config) == ["Goner", "Keeper"]
        assert (downloads / "Goner").read_text() == "not a dir"

    def test_shared_folder_is_refused(self, run_cli, config, downloads, capsys):
        # "Goner:" sanitizes to the same folder as "Goner".
        config.set("manga", config.get("manga") + [
            {"title": "Goner:", "source": "mangadex.org", "url": "u3"}])
        config.save()
        assert run_cli("rm", "Goner", "--yes", "--delete-files") == 1
        assert "same download folder" in capsys.readouterr().err
        assert self._titles(config) == ["Goner", "Keeper", "Goner:"]
        assert (downloads / "Goner").exists()

    # Interactive: prompts are remove → history → files, all default no.

    def test_tty_defaults_keep_history_and_files(
            self, run_cli, config, downloads, history, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\n\n\n"))
        assert run_cli("rm", "Goner") == 0
        assert self._titles(config) == ["Keeper"]
        assert self._history(history) == ["1"]
        assert (downloads / "Goner").exists()

    def test_tty_can_opt_in_to_both(self, run_cli, config, downloads, history,
                                    monkeypatch):
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\ny\ny\n"))
        assert run_cli("rm", "Goner") == 0
        assert self._history(history) == []
        assert not (downloads / "Goner").exists()
        self._untouched(downloads)

    def test_tty_keep_files_skips_file_prompt(self, run_cli, config, downloads,
                                              monkeypatch):
        # A third prompt would hit EOF and fail the command.
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\nn\n"))
        assert run_cli("rm", "Goner", "--keep-files") == 0
        assert (downloads / "Goner").exists()

    def test_tty_delete_files_and_purge_skip_their_prompts(
            self, run_cli, config, downloads, history, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\n"))
        assert run_cli("rm", "Goner", "--purge-history", "--delete-files") == 0
        assert self._history(history) == []
        assert not (downloads / "Goner").exists()

    def test_tty_declined_removal_changes_nothing(
            self, run_cli, config, downloads, history, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _TtyInput("n\n"))
        assert run_cli("rm", "Goner", "--purge-history", "--delete-files") == 0
        assert self._titles(config) == ["Goner", "Keeper"]
        assert self._history(history) == ["1"]
        assert (downloads / "Goner").exists()

    def test_tui_namespace_keeps_files_by_default(self, config, downloads,
                                                  monkeypatch):
        import argparse
        from memanga import cli
        from memanga.config import Config
        monkeypatch.setattr(cli, "config", Config())
        monkeypatch.setattr(sys, "stdin", _TtyInput("y\nn\nn\n"))
        cli.cmd_remove(argparse.Namespace(target="Goner", yes=False, purge=False))
        assert self._titles(config) == ["Keeper"]
        assert (downloads / "Goner").exists()

    def test_help_lists_explicit_flags(self, run_cli, capsys):
        run_cli("rm", "--help")
        out = capsys.readouterr().out
        for flag in ("--purge-history", "--keep-files", "--delete-files"):
            assert flag in out
